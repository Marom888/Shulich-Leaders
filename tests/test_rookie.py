"""Rookie product layer: provenance rules, governance, guidance, rendering, navigation."""
import copy
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from lunarmatch.experiments import schema as cat
from lunarmatch.knowledge import workbook as wbm
from rookie import content as C
from rookie import journey as J
from rookie.build import PLACEHOLDER, build, render_html

needs_wb = pytest.mark.skipif(not wbm.WORKBOOK_PATH.is_file(), reason="team workbook not present")

EARTH_OK = {   # structure of rookie.earth.earth_summary(); numbers are test fixtures
    "available": True, "dataset": "NASA SRTMGL1 v003", "tile": "S24W070.hgt",
    "crs": "EPSG:4326", "shape": [3601, 3601], "sample_extent_wsen": [-70, -24, -69, -23],
    "nodata_count": 0, "elevation_m": {"min": 600.0, "max": 3400.0},
    "spacing_m": {"east_west": 28.4, "north_south": 30.8},
    "slope": {"label": "slope (deg) fixture", "params": {},
              "stats": {"median": 3.0, "p90": 10.0, "p10": 1.0, "min": 0, "max": 60}},
    "roughness": {"label": "roughness (m) fixture", "params": {},
                  "stats": {"median": 1.5, "p90": 4.5, "p10": 0.5, "min": 0, "max": 40}},
    "plots": {"terrain_2d": {"title": "Elevation map", "file": "terrain_2d.html", "available": True}},
}
EARTH_NONE = {"available": False, "reason": "SRTM tile S24W070 not found locally.",
              "plots": {"terrain_2d": {"title": "Elevation map", "file": "terrain_2d.html",
                                       "available": False}}}


def P(pid):
    return {"id": pid, "lunar_source": "src", "lunar_status": "st", "earth_source": "esrc"}


# ---------------------------------------------------------------- availability rules
ALL_IDS = [f"TOP-0{i}" for i in range(1, 9)] + [f"GEO-0{i}" for i in range(1, 9)] + \
          [f"SOIL-{i:02d}" for i in range(1, 13)]


@pytest.mark.parametrize("pid", ALL_IDS)
def test_lunar_targets_never_claim_data(pid):
    a = J.availability(P(pid), "lunar_target")
    assert a["status"] in ("missing", "not_integrated", "control")
    assert a["status"] in C.STATUS and a["source"] and a["note"]


@pytest.mark.parametrize("pid", ALL_IDS)
def test_apollo_never_measured_until_extracted(pid):
    st = J.availability(P(pid), "apollo_16")["status"]
    assert st not in ("measured", "derived", "model_estimate")
    if pid in J.APOLLO_DOCUMENTED:
        assert st == "documented"


def test_soil_water_content_is_control_everywhere():
    for site in ("lunar_target", "apollo_16", "earth_test"):
        assert J.availability(P("SOIL-12"), site, EARTH_OK)["status"] == "control"


def test_earth_status_depends_on_real_tile():
    assert J.availability(P("TOP-01"), "earth_test", EARTH_OK)["status"] == "measured"
    assert J.availability(P("TOP-02"), "earth_test", EARTH_OK)["status"] == "derived"
    assert J.availability(P("TOP-03"), "earth_test", EARTH_OK)["status"] == "derived"
    assert "3.0°" in J.availability(P("TOP-02"), "earth_test", EARTH_OK)["note"]
    for pid in ("TOP-01", "TOP-02", "TOP-03"):
        a = J.availability(P(pid), "earth_test", EARTH_NONE)
        assert a["status"] == "not_integrated"
        assert not re.search(r"\d", a["note"])          # no numbers without data
    for pid in ("SOIL-01", "SOIL-02", "SOIL-11"):          # no field tests performed
        assert J.availability(P(pid), "earth_test", EARTH_OK)["status"] == "missing"
    assert J.availability(P("TOP-04"), "earth_test", EARTH_OK)["status"] == "not_integrated"


def test_unknown_site_rejected():
    with pytest.raises(ValueError):
        J.availability(P("TOP-01"), "mars")


# ---------------------------------------------------------------- payload (real workbook)
@pytest.fixture(scope="module")
def wb():
    if not wbm.WORKBOOK_PATH.is_file():
        pytest.skip("team workbook not present")
    return wbm.load_workbook()


def payload(wb, earth=EARTH_OK):
    return J.build_payload(wb, copy.deepcopy(earth))


@needs_wb
def test_experiment_parameter_mapping_and_origin(wb):
    exps = {e["key"]: e for e in payload(wb)["experiments"]}
    ids = lambda k: [r["id"] for r in exps[k]["parameters"]]
    assert ids("footpad_penetration") == ["SOIL-01", "SOIL-02", "SOIL-03", "SOIL-04", "SOIL-11",
                                          "TOP-02", "TOP-03"]
    assert ids("slope_stability") == ["TOP-02", "SOIL-03", "SOIL-02", "TOP-03"]
    assert ids("asymmetric_settlement") == ["SOIL-01", "SOIL-11", "TOP-02", "TOP-04"]
    origin = {r["id"]: r["origin"] for r in exps["footpad_penetration"]["parameters"]}
    assert origin["SOIL-01"] == "Workbook EXP-01"
    assert origin["TOP-02"] == C.BRIEF_ADDITION_NOTE
    assert {e["workbook"]["id"] for e in exps.values()} == {"EXP-01", "EXP-04", "EXP-05"}


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


@needs_wb
def test_no_scores_ranks_or_similarity_values(wb):
    p = payload(wb)
    forbidden = {"score", "scores", "rank", "ranking", "similarity_score", "winner", "cost"}
    assert not forbidden & set(_keys(p))
    assert p["matching"]["enabled"] is False
    for e in p["experiments"]:
        assert e["results"]["similarity"] == {"computed": False, "value": None,
                                              "reason": C.MATCHING["reason"]}


@needs_wb
def test_regions_are_candidates_not_confirmed(wb):
    p = payload(wb)
    assert [t["name"] for t in p["targets"]] == ["Mons Mouton Plateau", "Nobile Rim 2"]
    for t in p["targets"]:
        assert t["designation"].startswith("Candidate landing region")
        assert "Not a confirmed landing site" in t["status_note"]
        assert t["coordinates"] is None                  # not invented
        assert t["source"].startswith("https://www.nasa.gov/")
    assert p["reference"]["role"] == "Historical validation reference"
    assert p["earth_region"]["designation"] == "Not a matched analog candidate"


@needs_wb
def test_governance_catalog_untouched_and_reported(wb, tmp_path):
    before = hashlib.sha256(cat.DEFAULT_CATALOG.read_bytes()).hexdigest()
    p = payload(wb)
    assert hashlib.sha256(cat.DEFAULT_CATALOG.read_bytes()).hexdigest() == before
    n_approved = len(cat.approved_experiments(cat.load_catalog()))
    assert p["governance"]["approved_catalog_experiments"] == n_approved
    assert "not entries in the approved experiment catalog" in p["governance"]["note"]
    for e in p["experiments"]:                          # workbook planning status, not run
        assert e["workbook"]["status"] == "לא החל; מתוכנן"


@needs_wb
def test_guidance_is_deterministic_and_cautious(wb):
    a, b = payload(wb), payload(wb)
    assert a["journeys"] == b["journeys"]
    for key, g in a["journeys"].items():
        assert set(g) == {"region", "experiment", "parameters", "lunar", "earth", "results"}
        assert g["lunar"]["mood"] == "caution"
        assert g["results"]["mood"] == "caution"
        assert "not a confirmed landing site" in g["region"]["messages"][0]["text"]
        assert g["parameters"]["mood"] == "caution"     # all MVP experiments need soil data
        assert g["earth"]["mood"] == "celebrate"
    none = payload(wb, EARTH_NONE)
    for g in none["journeys"].values():
        assert g["earth"]["mood"] == "caution"
        assert not any("real slope data" in m["text"] for m in g["results"]["messages"])


@needs_wb
def test_no_numbers_without_earth_data(wb):
    p = payload(wb, EARTH_NONE)
    assert "slope" not in p["earth"] and "stats" not in set(_keys(p))
    for e in p["experiments"]:
        assert e["results"]["available_measurements"] == []
        assert e["results"]["location_wsen"] is None


@needs_wb
def test_unresolved_tokens_surface(wb):
    for e in payload(wb)["experiments"]:
        assert e["unresolved"] == []                    # MVP experiments resolve fully


# ---------------------------------------------------------------- rendering
def test_render_escapes_script_breakout(tmp_path):
    t = tmp_path / "t.html"
    t.write_text(f'<script type="application/json" id="d">{PLACEHOLDER}</script>', encoding="utf-8")
    html = render_html({"x": "</script><script>alert(1)</script>"}, t)
    assert html.count("</script>") == 1
    data = re.search(r'id="d">(.*)</script>', html, re.S).group(1)
    assert json.loads(data)["x"] == "</script><script>alert(1)</script>"


@needs_wb
def test_build_writes_self_contained_app(tmp_path):
    out = build(output_dir=tmp_path, earth=copy.deepcopy(EARTH_OK))
    html = out.read_text(encoding="utf-8")
    assert out == tmp_path / "rookie" / "index.html"
    data = json.loads(re.search(r'id="rookie-data">(.*?)</script>', html, re.S).group(1))
    assert data["product"]["name"] == "Rookie" and data["product"]["engine"] == "LunarMatch"
    assert "Placeholder mascot" in html
    assert "prefers-reduced-motion: reduce" in html
    assert not re.search(r'<script[^>]+src=', html)          # no external scripts
    assert not re.search(r'<link[^>]+href=["\']https?:', html)
    assert data["provenance"]["workbook_sha256"] == hashlib.sha256(
        wbm.WORKBOOK_PATH.read_bytes()).hexdigest()


# ---------------------------------------------------------------- real Earth summary
def test_earth_summary_matches_engine():
    from lunarmatch.data import raster_loader as rl
    from lunarmatch.data.earthdata_client import find_local_tile
    from lunarmatch.features import terrain as tf
    from rookie.earth import earth_summary

    tile = find_local_tile("S24W070")
    if tile is None:
        pytest.skip("real tile not present")
    s = earth_summary(tile)
    slope = tf.slope_deg(rl.load_raster(tile)).values
    assert s["slope"]["stats"]["median"] == pytest.approx(float(np.nanmedian(slope)))
    assert s["slope"]["stats"]["undefined_cells"] == int(np.isnan(slope).sum())
    assert "derived from SRTMGL1" in s["slope"]["label"]
    assert s["sample_extent_wsen"] == [-70.0, -24.0, -69.0, -23.0]


def test_earth_summary_without_tile(tmp_path):
    from rookie.earth import earth_summary
    s = earth_summary(tmp_path / "missing.hgt", tmp_path)
    assert s["available"] is False and "slope" not in s
    assert all(not p["available"] for p in s["plots"].values())


# ---------------------------------------------------------------- navigation (headless browser)
def _browser():
    for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe"):
        if Path(p).is_file():
            return p
    return shutil.which("chromium") or shutil.which("google-chrome")


@needs_wb
@pytest.mark.skipif(_browser() is None, reason="no headless Chromium-based browser")
def test_deep_link_navigation_renders_each_step(tmp_path):
    out = build(output_dir=tmp_path, earth=copy.deepcopy(EARTH_OK))
    base = out.as_uri()

    def dom(fragment):
        r = subprocess.run([_browser(), "--headless=new", "--disable-gpu",
                            f"--user-data-dir={tmp_path / 'profile'}",
                            "--virtual-time-budget=3000", "--dump-dom", base + fragment],
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
        return r.stdout

    q = "#target=mons_mouton_plateau&exp=footpad_penetration&step="
    expected = {1: "Choose a lunar target region", 2: "Choose an engineering experiment",
                3: "Static lander footpad penetration: required parameters",
                4: "Lunar terrain: Mons Mouton Plateau",
                5: "Earth terrain: Atacama Desert test tile",
                6: "Results for Static lander footpad penetration"}
    for step, heading in expected.items():
        assert heading in dom(q + str(step)), step
    # Steps that need a selection cannot be entered by deep link without it.
    assert "Choose a lunar target region" in dom("#step=4")
    assert "Choose an engineering experiment" in dom("#target=nobile_rim_2&step=3")
