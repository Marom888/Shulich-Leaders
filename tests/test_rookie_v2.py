"""Rookie 2.0: spec interface, mission contract, environment, catalogue, job, figures, server."""
import json
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request

import numpy as np
import pytest

from lunarmatch import analog_catalog as ac
from lunarmatch.discovery.job import OVERALL_WINNER, STAGES, run_job
from lunarmatch.discovery.requirements import DraftSpec
from lunarmatch.discovery.store import DescriptorCache
from lunarmatch.environment import PROFILES, assess
from lunarmatch.knowledge.algorithm_spec import SPEC_FILES, AlgorithmSpec, compare_specs
from lunarmatch.knowledge.workbook import WorkbookError
from lunarmatch.lunar_presets import PRESETS, preset
from lunarmatch.mission import MissionError, MissionInput
from lunarmatch.terrain.connectors import ConnectorRegistry, LocalSRTMConnector
from lunarmatch.terrain.mock import MockEarthConnector, MockMoonConnector

have_both = pytest.mark.skipif(not all(p.is_file() for p in SPEC_FILES.values()),
                               reason="algorithm workbooks not present")
have_swir = pytest.mark.skipif(not SPEC_FILES["swir"].is_file(), reason="SWIR workbook not present")


# ---------------------------------------------------------------- workbook interface
@have_both
def test_swir_workbook_is_additive_to_v1():
    a, b = AlgorithmSpec.load("v1.0"), AlgorithmSpec.load("swir")
    assert a.sha256 != b.sha256 and len(b.sha256) == 64
    d = compare_specs(a, b)
    assert all(not v["changed"] and not v["removed"] for v in d.values())
    added = {k: v["added"] for k, v in d.items() if v["added"]}
    assert added["Datasets"] == ["D_M3", "D_WORLDCOVER_SWIR"]
    assert added["Features"] == ["F_SWIR_BANDPASS"]
    assert set(added) == {"Datasets", "Features", "Moon_Earth_Pairs", "Pair_URLs", "Start_Here"}
    assert a.experiments() == b.experiments()                       # experiments/weights unchanged


@have_swir
def test_swir_is_research_only_and_unscored():
    sw = AlgorithmSpec.load("swir").swir()
    assert sw["present"] and sw["used_by_experiments"] == []
    assert sw["feature"]["Status"] == "OPTIONAL_NOT_SCORED"
    assert "0 scoring contribution" in sw["scoring_policy"]
    assert sw["moon_dataset"]["Integration_Status"] == "OPTIONAL_RESEARCH_NOT_INTEGRATED"
    assert AlgorithmSpec.load("v1.0").swir() == {"present": False} if SPEC_FILES["v1.0"].is_file() else True


@have_swir
def test_spec_experiment_views_flag_governance():
    spec = AlgorithmSpec.load("swir")
    exps = spec.experiments()
    assert [e["experiment_id"] for e in exps] == ["EXP_02", "EXP_04", "EXP_08", "EXP_10", "EXP_SHADOW", "EXP_PLUME"]
    for e in exps:
        assert "not approval" in e["approval_status"]
        assert "NOT authorized" in e["spec_threshold_pct"]["status"]
        for f in e["required_features"] + e["optional_features"]:
            assert "NOT authorized" in f["spec_weight_pct"]["status"]
    with pytest.raises(WorkbookError):
        spec.rows("Score_Demo")                                      # synthetic sheets never exposed


# ---------------------------------------------------------------- presets and mission
def test_presets_only_verified_coordinates():
    ridge = preset("shackleton_de_gerlache_ridge")
    assert ridge["point"] == {"lat": -89.684, "lon": pytest.approx(-163.261)}
    assert ridge["source"] == "https://lroc.im-ldi.com/images/1247"
    for pid in ("mons_mouton_plateau", "nobile_rim_2"):
        p = preset(pid)
        assert p["point"] is None and p["status"] == "coordinates_pending_validation"
    assert {p["id"] for p in PRESETS} == {"mons_mouton_plateau", "nobile_rim_2",
                                         "shackleton_de_gerlache_ridge", "custom"}


def base_mission(**over):
    m = {"target": {"preset_id": "custom", "lat": -10.0, "lon": 20.0, "radius_km": 5},
         "search_mode": "extraordinary", "earth": {"scope_bbox": [-70, -24, -69, -23]},
         "scale": {"lunar_footprint_m": 10000, "terrestrial_footprint_m": 20000},
         "environment": {"vacuum": "required"}, "experiments": ["EXP_02"],
         "moon_dataset": "MOCK_MOON_DEM", "earth_dataset": "MOCK_EARTH_DEM"}
    m.update(over)
    return m


def test_mission_valid_and_scale_ratio():
    m = MissionInput.from_dict(base_mission())
    assert m.target.region().area_m2() == pytest.approx(np.pi * 5000 ** 2, rel=1e-4)
    d = m.to_dict()
    assert d["scale"]["geometric_ratio"] == 2.0 and "not establish" in d["scale"]["limitation"]
    assert "planning inputs" in d["earth"]["planning_only"]


@pytest.mark.parametrize("over,needle", [
    ({"target": {"preset_id": "mons_mouton_plateau", "radius_km": 5}}, "pending validation"),
    ({"target": {"preset_id": "custom", "lat": -95, "lon": 0, "radius_km": 5}}, "lunar region"),
    ({"target": {"preset_id": "custom", "lat": 0, "lon": 0, "radius_km": 0}}, "radius"),
    ({"search_mode": "global"}, "search_mode"),
    ({"earth": {"scope_bbox": [0, 5, 1, 5]}}, "scope"),
    ({"earth": {"scope_bbox": [-70, -24, -69, -23], "budget": 1000}}, "currency"),
    ({"earth": {"scope_bbox": [-70, -24, -69, -23], "budget": -1, "currency": "USD"}}, "negative"),
    ({"scale": {"lunar_footprint_m": 0, "terrestrial_footprint_m": 10}}, "footprint"),
    ({"environment": {"vacuum": "sometimes"}}, "vacuum"),
    ({"experiments": []}, "at least one"),
])
def test_mission_rejects_bad_input(over, needle):
    with pytest.raises(MissionError) as e:
        MissionInput.from_dict(base_mission(**over))
    assert any(needle in x for x in e.value.errors)


def test_mission_unknown_experiment_and_ridge_autofill():
    with pytest.raises(MissionError):
        MissionInput.from_dict(base_mission(experiments=["EXP_99"]), {"EXP_02"})
    m = MissionInput.from_dict(base_mission(target={"preset_id": "shackleton_de_gerlache_ridge", "radius_km": 7}))
    assert (m.target.lat, m.target.lon) == (-89.684, pytest.approx(-163.261))


# ---------------------------------------------------------------- environment and catalogue
@have_swir
def test_environment_profiles_cover_spec_experiments():
    ids = {e["experiment_id"] for e in AlgorithmSpec.load("swir").experiments()}
    assert ids == set(PROFILES)
    plume = assess("EXP_PLUME", {"vacuum": "not_required"})
    assert plume["vacuum_material"] == "yes" and plume["chamber_required"].startswith("yes")
    assert any("materially affects" in w for w in plume["warnings"])
    assert "Not established" in plume["two_stage"]["sufficiency"]
    trn = assess("EXP_10", {"vacuum": "required"})
    assert trn["vacuum_material"].startswith("no") and trn["warnings"]
    assert "needs engineering review" in plume["status"]


def test_analog_catalogue_rules(tmp_path):
    assert ac.load_catalog()["status"].startswith("empty")
    good = {"site_id": "S1", "name": "x", "lat": 1, "lon": 2, "radius_km": 3, "role": "reference",
            "source_citation": "c", "source_url": "u", "verified_by": "team", "verified_on": "2026-11-15"}
    ac.validate_entry(good)
    with pytest.raises(ac.CatalogError):
        ac.validate_entry({**good, "source_citation": ""})
    with pytest.raises(ac.CatalogError):
        ac.validate_entry({**good, "role": "NASA approved analog"})
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"schema": ac.SCHEMA, "sites": [good, good]}), encoding="utf-8")
    with pytest.raises(ac.CatalogError):
        ac.load_catalog(p)


# ---------------------------------------------------------------- discovery job
def registry(tmp_path=None, local_dirs=None):
    reg = ConnectorRegistry()
    reg.register(MockMoonConnector())
    reg.register(MockEarthConnector(arcsec=30))
    if local_dirs is not None:
        reg.register(LocalSRTMConnector(search_dirs=local_dirs, extract_dir=tmp_path / "ex"))
    return reg


def spec_and_draft():
    if not SPEC_FILES["swir"].is_file():
        return None, None
    s = AlgorithmSpec.load("swir")
    return s, DraftSpec.load(s.path)


def test_job_complete_honest_and_unranked(tmp_path):
    spec, draft = spec_and_draft()
    events = []
    m = MissionInput.from_dict(base_mission(experiments=["EXP_02", "EXP_PLUME"]))
    r = run_job(m, registry(), spec, DescriptorCache(tmp_path), events.append, draft)
    assert r["status"] == "complete" and r["contains_mock_data"] is True
    done = [e["stage"] for e in events if e.get("state") == "done"]
    assert done == [s for s, _ in STAGES]
    ids = [c["id"] for c in r["candidates"]]
    assert ids and ids == sorted(ids)
    blob = json.dumps(r)
    for k in ('"score"', '"rank"', '"winner_site"', '"weight_used"'):
        assert k not in blob
    assert r["overall_winner"] == OVERALL_WINNER
    for pe in r["per_experiment"]:
        assert pe["top_three"] is None and "withheld" in pe["top_three_status"]
        if spec:
            assert pe["evaluation_status"] == "insufficient_data"
    if spec:
        sw = r["swir"]
        assert sw["present"] and not any(sw[b][k] for b in ("moon", "earth")
                                         for k in ("downloaded", "integrated", "validated"))
    c = r["candidates"][0]
    assert c["measurements"]["status"]["slope_deg"] == "derived"
    assert "lunar gravity" in " ".join(c["environment_limitations"])


def test_job_blocked_states(tmp_path):
    reg = registry(tmp_path, [tmp_path / "empty"])
    (tmp_path / "empty").mkdir()
    r = run_job(MissionInput.from_dict(base_mission(search_mode="ordinary")), reg, None, DescriptorCache(tmp_path))
    assert r["status"] == "blocked" and "catalogue has no entries" in r["blocker"]["reason"]
    r2 = run_job(MissionInput.from_dict(base_mission(earth_dataset="SRTMGL1")), reg, None, DescriptorCache(tmp_path))
    assert r2["status"] == "blocked" and "0 of 1 coverage units" in r2["blocker"]["reason"]
    small = base_mission(scale={"lunar_footprint_m": 1000, "terrestrial_footprint_m": 500})
    r3 = run_job(MissionInput.from_dict(small), reg, None, DescriptorCache(tmp_path))
    assert r3["status"] == "blocked" and "below the resolvable size" in r3["blocker"]["reason"]
    assert all("candidates" not in x for x in (r, r2, r3))


# ---------------------------------------------------------------- window figures
def test_window_figures_use_real_samples():
    from lunarmatch.visualization.window_figures import figures, window_grid
    p = MockEarthConnector(arcsec=30).fetch("S24W070")
    out = figures(p, (10, 60), (20, 80), title="w", max_side=25)
    assert set(out["figures"]) == {"elevation", "slope", "roughness", "terrain_3d"}
    g = window_grid(p.elevation_m, p, (10, 60), (20, 80), 25)
    zj = out["figures"]["elevation"]["data"][0]["z"]
    if isinstance(zj, dict):                                         # plotly typed-array encoding
        import base64
        zj = np.frombuffer(base64.b64decode(zj["bdata"]), dtype=zj["dtype"]).reshape(
            [int(s) for s in str(zj["shape"]).split(",")])
    z = np.asarray(zj, float)[::-1]                                  # back to north-up rows
    assert np.array_equal(z, p.elevation_m[np.ix_(g.rows, g.cols)])
    assert "MOCK" in out["figures"]["elevation"]["layout"]["title"]["text"]
    assert out["provenance"]["is_mock"] is True


# ---------------------------------------------------------------- local server
def test_server_api_end_to_end(tmp_path):
    from rookie.v2.server import Engine, serve
    spec, _ = spec_and_draft()
    eng = Engine(registry(), DescriptorCache(tmp_path), spec=spec)
    httpd = serve(0, eng, static_dir=tmp_path)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    def call(path, payload=None):
        req = urllib.request.Request(base + path, json.dumps(payload).encode() if payload is not None else None,
                                     {"Content-Type": "application/json"})
        try:
            r = urllib.request.urlopen(req, timeout=30)
            return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    try:
        assert call("/api/health") == (200, {"ok": True})
        code, cfg = call("/api/config")
        assert code == 200 and cfg["overall_winner"]["status"] == "pending_engineering_validation"
        assert cfg["cost"]["status"] == "unavailable"
        code, bad = call("/api/jobs", base_mission(experiments=[]))
        assert code == 400 and bad["errors"]
        code, ok = call("/api/jobs", base_mission(experiments=["EXP_02"] if spec else ["EXP_02"]))
        assert code == 202
        jid = ok["job_id"]
        for _ in range(200):
            code, j = call(f"/api/jobs/{jid}")
            if j["status"] not in ("queued", "running"):
                break
            time.sleep(0.1)
        assert j["status"] == "complete" and j["result"]["candidates"]
        wid = j["result"]["candidates"][0]["id"]
        code, figs = call(f"/api/jobs/{jid}/figures/{wid}")
        assert code == 200 and "terrain_3d" in figs["figures"]
        assert call(f"/api/jobs/{jid}/figures/nope")[0] == 404
        assert call("/api/jobs/unknown")[0] == 404
    finally:
        httpd.shutdown()


def _browser():
    from test_rookie import _browser as b
    return b()


@pytest.mark.skipif(_browser() is None, reason="no headless browser")
def test_v2_static_bundle_renders_offline(tmp_path):
    from rookie.v2.build import build
    out = build(tmp_path / "rookie2", registry())
    dom = subprocess.run([_browser(), "--headless=new", "--disable-gpu", f"--user-data-dir={tmp_path / 'p'}",
                          "--virtual-time-budget=8000", "--dump-dom", out.as_uri()],
                         capture_output=True, text=True, encoding="utf-8", timeout=90).stdout
    assert "Where on the Moon?" in dom
    assert "Verified point" in dom and "Mons Mouton Plateau" in dom
    assert "Engine offline" in dom                                   # file:// -> no fake engine
    assert (tmp_path / "rookie2" / "plotly.min.js").stat().st_size > 1_000_000
    assert "cdn." not in (tmp_path / "rookie2" / "index.html").read_text(encoding="utf-8")


# ================================================================ decision-first results
from lunarmatch import field_measurements as fm  # noqa: E402
from lunarmatch.discovery.candidates import PREVIEW_RULE, ring, spread_select  # noqa: E402
from lunarmatch.discovery.plain_language import FEATURES, coverage_blocker  # noqa: E402
from lunarmatch.geo_naming import NominatimGeocoder, NullGeocoder  # noqa: E402


def _w(i, lat, lon):
    return {"window_id": f"W{i:02d}", "centre_lat_lon": [lat, lon]}


def test_spread_select_is_deterministic_geographic_not_quality():
    ws = [_w(0, 0, 0), _w(1, 0, 0.01), _w(2, 0, 6), _w(3, 5, 0), _w(4, 0.01, 0)]
    a = [w["window_id"] for w in spread_select(ws)]
    assert a == ["W00", "W02", "W03"]                               # lowest ID, then farthest points
    tie = [_w(0, 0, 0), _w(2, 0, 5), _w(3, 5, 0)]                  # equal distances: higher ID wins (documented)
    assert [w["window_id"] for w in spread_select(tie)][1] == "W03"
    assert a == [w["window_id"] for w in spread_select(list(reversed(ws)))]
    assert spread_select([]) == [] and len(spread_select(ws[:2])) == 2
    assert "not ranked" in PREVIEW_RULE


def test_ring_is_closed_geojson_ccw():
    r = ring([-70, -24, -69, -23])
    assert r[0] == r[-1] and len(r) == 5
    area2 = sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(r, r[1:]))
    assert area2 > 0                                                # counter-clockwise exterior


@have_swir
def test_plain_language_covers_every_required_feature():
    spec = AlgorithmSpec.load("swir")
    for e in spec.experiments():
        for f in e["required_features"]:
            assert f["feature_id"] in FEATURES, f["feature_id"]
    assert coverage_blocker({"tiles_requested": 9, "tiles_processed": 1}).startswith("Rookie had terrain data for 1 of 9")
    assert coverage_blocker({"tiles_requested": 2, "tiles_processed": 2}) is None


@have_swir
def test_experiment_results_are_honest_location_cards(tmp_path):
    spec, draft = spec_and_draft()
    m = MissionInput.from_dict(base_mission(experiments=["EXP_02", "EXP_04", "EXP_PLUME"],
                                            constraints=["slope_deg.p90<=30"],
                                            earth={"scope_bbox": [-70, -24, -69, -23],
                                                   "start_location": {"lat": 32.0, "lon": 34.8}},
                                            scale={"lunar_footprint_m": 10000, "terrestrial_footprint_m": 20000,
                                                   "characteristic_lengths_m": {"leg_spacing": 4}}))
    r = run_job(m, registry(), spec, DescriptorCache(tmp_path), None, draft)
    er = {e["experiment_id"]: e for e in r["experiment_results"]}
    blob = json.dumps(r["experiment_results"])
    for k in ('"score"', '"rank"', '"Top 3"', '"best_site_id"'):
        assert k not in blob
    for e in er.values():
        assert e["best_site"]["status"] == "not_determined" and e["best_site"]["reason"]
        assert e["preview_label"] == "DISCOVERED CANDIDATES — NOT YET RANKED"
    assert er["EXP_04"]["candidates"] == [] and "cannot yet measure" in er["EXP_04"]["no_candidates_reason"]
    c = er["EXP_02"]["candidates"][0]
    assert c["label"] == "A" and c["point_type"].startswith("candidate-area centroid")
    assert c["place"]["status"] == "not_determined" and c["place"]["label"] is None      # never invented
    w, s, e_, n = c["bounds_wsen"]
    assert w < c["centroid"]["lon"] < e_ and s < c["centroid"]["lat"] < n
    assert c["boundary"][0] == [w, s] and c["area_km2"] > 0
    assert c["distance_from_start_km"] > 10000                     # Israel -> Chile, straight line
    assert any("MOCK lunar reference" in x for x in c["why"])
    assert any("too coarse" in x and "1.3 m" in x for x in c["missing"])
    assert c["next_actions"] and "vacuum" in er["EXP_PLUME"]["candidates"][0]["validation"]["vacuum_sentence"]
    assert len(er["EXP_02"]["candidates"]) <= 3
    ids = [x["id"] for x in er["EXP_02"]["alternatives"]]
    assert c["window_id"] not in ids


# ---------------------------------------------------------------- place names
def test_null_geocoder_never_names():
    p = NullGeocoder().place(-23.5, -69.5)
    assert p["label"] is None and p["status"] == "not_determined" and "23.5000" in p["coordinates"]


def test_nominatim_geocoder_caches_and_fails_safe(tmp_path):
    calls = []

    def fake(url):
        calls.append(url)
        return {"address": {"country": "Chile", "state": "Antofagasta"}}
    g = NominatimGeocoder(tmp_path / "geo.json", fetch=fake, min_interval_s=0)
    a = g.place(-23.5, -69.5)
    assert a["label"] == "Antofagasta, Chile" and "OpenStreetMap" in a["source"]
    assert g.place(-23.5, -69.5) == a and len(calls) == 1         # cached
    assert NominatimGeocoder(tmp_path / "geo.json", fetch=fake).place(-23.5, -69.5) == a   # persisted
    none = NominatimGeocoder(tmp_path / "g2.json", fetch=lambda u: {"address": {}}, min_interval_s=0).place(0, -150)
    assert none["label"] is None and none["status"] == "no_name_found"

    def boom(url):
        raise OSError("offline")
    off = NominatimGeocoder(tmp_path / "g3.json", fetch=boom, min_interval_s=0).place(1, 1)
    assert off["label"] is None


# ---------------------------------------------------------------- field measurements (Rookie Scout)
def _meas(**kw):
    d = dict(site_id="EXP_02-A", lat=-23.05, lon=-69.95, experiment_id="EXP_04",
             measurement_type="penetration_resistance", instrument="hand cone penetrometer",
             calibration="cal cert 2026-10", measured_on="2026-11-20", value=1.8, units="MPa",
             uncertainty=0.2, provenance="field team", sampling_depth_m=0.1)
    d.update(kw)
    return fm.FieldMeasurement(**d)


def test_field_measurement_roundtrip_and_validation(tmp_path):
    store = tmp_path / "m.jsonl"
    fm.append(_meas(), store)
    fm.append(_meas(site_id="X", measurement_type="dry_bulk_density", units="kg/m3", value=1500, uncertainty=50), store)
    assert [m.site_id for m in fm.load(store)] == ["EXP_02-A", "X"]
    assert len(fm.load(store, "X")) == 1
    for bad in (dict(units="kPa"), dict(measurement_type="vibes"), dict(uncertainty=-1), dict(lat=95),
                dict(calibration=""), dict(value=float("nan")), dict(sampling_depth_m=-0.5)):
        with pytest.raises(fm.MeasurementError):
            _meas(**bad).validate()
    assert fm.load(tmp_path / "none.jsonl") == []


def test_config_exposes_real_coverage_extent():
    from rookie.v2.config import coverage_extent
    assert coverage_extent(["S24W070"]) == [-70, -24, -69, -23]
    assert coverage_extent(["S24W070", "S23W069"]) == [-70, -24, -68, -22]
    assert coverage_extent([]) is None and coverage_extent(["junk"]) is None
