"""Unified terrain interface, mock connectors, draft gates, per-feature comparison."""
import json
import math

import numpy as np
import pytest

from conftest import N, write_hgt
from lunarmatch.bodies import EARTH, MOON
from lunarmatch.discovery import descriptors as dsc
from lunarmatch.discovery.compare import (GOVERNANCE, compare_window, spacing_check,
                                          w1_from_quantiles)
from lunarmatch.discovery.comparison_run import (COMPARISON_SCHEMA, ComparisonRequest,
                                                 lunar_reference, run_comparison)
from lunarmatch.discovery.engine import Constraint, SearchRequest, run_search
from lunarmatch.discovery.requirements import (DRAFT_LABEL, DraftSpec, evaluate_experiment,
                                               evaluate_gate, find_spec)
from lunarmatch.discovery.store import DescriptorCache
from lunarmatch.regions import LunarRegion
from lunarmatch.terrain.connectors import (ConnectorRegistry, CoverageUnit, LocalSRTMConnector,
                                           TerrainConnector)
from lunarmatch.terrain.mock import MockEarthConnector, MockMoonConnector
from lunarmatch.terrain.patch import (GeographicGrid, ProjectedGrid, Provenance, TerrainPatch,
                                      azimuthal_equidistant, coarsen)
from lunarmatch.terrain.registry import default_registry

PROV = Provenance("TEST", "test data")


# ---------------------------------------------------------------- grids and patches
def test_geographic_grid_uses_body_geodesy():
    lats, lons = np.array([-23.0, -23.5, -24.0]), np.array([0.0, 0.5, 1.0])
    dxe, dye = GeographicGrid(EARTH, lats, lons).spacing_m()
    dxm, dym = GeographicGrid(MOON, lats, lons).spacing_m()
    assert dye[1] == pytest.approx(110_751 * 0.5, rel=1e-3)                  # WGS84
    assert dym[1] == pytest.approx(1_737_400 * math.pi / 180 * 0.5, rel=1e-9)  # Moon sphere
    assert dxm[1] == pytest.approx(dym[1] * math.cos(math.radians(23.5)), rel=1e-9)
    with pytest.raises(ValueError):
        GeographicGrid(EARTH, lats[::-1], lons)                              # south-up rejected


def test_projected_grid_and_azimuthal_inverse():
    f = azimuthal_equidistant(MOON, -85.0, 30.0)
    lat, lon = f(np.array([0.0]), np.array([0.0]))
    assert lat[0] == pytest.approx(-85.0) and lon[0] == pytest.approx(30.0)
    lat, _ = f(np.array([0.0]), np.array([10_000.0]))                        # 10 km north
    assert lat[0] == pytest.approx(-85.0 + 10_000 / (1_737_400 * math.pi / 180), abs=1e-6)
    g = ProjectedGrid(MOON, np.arange(5) * 20.0, np.arange(4)[::-1] * 20.0, f)
    dx, dy = g.spacing_m()
    assert dx[0] == dy[0] == 20.0
    b = g.window_bounds(0, 4, 0, 5)
    assert b["bounds_xy_m"] == [-10.0, -10.0, 90.0, 70.0]


def test_coarsen_block_mean_and_nodata():
    z = np.arange(36, dtype=float).reshape(6, 6)
    z[0, 0] = np.nan
    g = GeographicGrid(EARTH, np.linspace(-23, -23.05, 6), np.linspace(10, 10.05, 6))
    c = coarsen(TerrainPatch("T", z, g, PROV), 3)
    assert c.shape == (2, 2) and np.isnan(c.elevation_m[0, 0])
    assert c.elevation_m[1, 1] == pytest.approx(z[3:6, 3:6].mean())
    assert c.provenance.processing == ("block-mean x3",)
    with pytest.raises(ValueError):
        coarsen(c, 0)


def test_patch_shape_must_match_grid():
    g = GeographicGrid(EARTH, np.array([1.0, 0.0]), np.array([0.0, 1.0]))
    with pytest.raises(ValueError):
        TerrainPatch("x", np.zeros((3, 2)), g, PROV)


# ---------------------------------------------------------------- connectors and registry
def test_connectors_satisfy_contract_and_registry():
    reg = default_registry(include_external=False)
    assert set(reg.ids()) == {"SRTMGL1", "MOCK_EARTH_DEM", "MOCK_MOON_DEM"}
    for cid in reg.ids():
        assert isinstance(reg.get(cid), TerrainConnector)
    assert [c.dataset_id for c in reg.for_body("Moon", include_mock=False)] == []
    with pytest.raises(ValueError):
        reg.register(MockMoonConnector())                                    # duplicate
    with pytest.raises(TypeError):
        ConnectorRegistry().register(object())
    with pytest.raises(KeyError):
        reg.get("LOLA")


class FakeExternalMoon:
    """Shape of a connector the data-integration developer would supply."""
    dataset_id, body, is_mock, nominal_spacing_m = "FAKE_LOLA", "Moon", False, 30.0

    def units_for(self, bbox):
        return [CoverageUnit("U1", tuple(bbox), 1.0)]

    def fingerprint(self, unit_id):
        return "f" * 64

    def fetch(self, unit_id):
        return MockMoonConnector().fetch(MockMoonConnector.unit_id((0, -1, 1, 0)))


def test_external_connector_plugs_in():
    reg = ConnectorRegistry()
    reg.register(FakeExternalMoon())
    assert reg.for_body("Moon", include_mock=False)[0].dataset_id == "FAKE_LOLA"


def test_mock_connectors_are_deterministic_and_labelled():
    m = MockMoonConnector()
    u = m.units_for((10, -5, 10.5, -4.5))[0]
    a, b = m.fetch(u.id), m.fetch(u.id)
    assert np.array_equal(a.elevation_m, b.elevation_m)
    assert a.provenance.is_mock and a.provenance.dataset_id.startswith("MOCK_")
    assert a.body is MOON and a.grid.kind == "projected"
    e = MockEarthConnector(arcsec=30)                                        # small for speed
    p = e.fetch("S24W070")
    assert p.body is EARTH and p.provenance.is_mock and p.shape == (121, 121)
    assert e.fingerprint("S24W070") != e.fingerprint("S23W070")


def test_local_srtm_connector_real_or_missing(tmp_path):
    write_hgt(tmp_path / "S24W070.hgt", np.full((N, N), 1000))
    c = LocalSRTMConnector(search_dirs=[tmp_path], extract_dir=tmp_path / "ex")
    assert c.fingerprint("S23W070") is None and c.fetch("S23W070") is None
    p = c.fetch("S24W070")
    assert p.provenance.is_mock is False and len(p.provenance.fingerprint) == 64
    assert np.nanmax(p.elevation_m) == 1000


# ---------------------------------------------------------------- engine on both bodies
def test_search_engine_runs_on_the_moon(tmp_path):
    res = run_search(SearchRequest(bbox=(10, -5, 10.4, -4.6), window_m=3000), MockMoonConnector(),
                     DescriptorCache(tmp_path))
    assert res["body"] == "Moon" and res["contains_mock_data"] is True
    assert res["coverage"]["body"] == "Moon" and "Moon's surface" in res["coverage"]["statement"]
    ws = res["windows"]
    assert ws and all(w["body"] == "Moon" and w["is_mock"] for w in ws)
    assert all(2400 < w["size_m"]["east_west"] < 3600 for w in ws)
    assert "bounds_xy_m" in ws[0]


def test_descriptors_include_quantiles(tmp_path):
    p = MockMoonConnector().fetch(MockMoonConnector.unit_id((0, -1, 0.3, -0.7)))
    rec = dsc.describe_patch(p, dsc.partition_patch(p, 5000))[0]
    q = rec["slope_deg"]["q"]
    assert len(q) == 21 and q == sorted(q)
    assert rec["slope_deg"]["p50"] == q[10] and rec["slope_deg"]["p90"] == q[18]


# ---------------------------------------------------------------- comparison maths
def test_w1_from_quantiles():
    a = [float(i) for i in range(21)]
    assert w1_from_quantiles(a, a) == 0
    assert w1_from_quantiles(a, [x + 2.5 for x in a]) == pytest.approx(2.5)  # pure shift
    with pytest.raises(ValueError):
        w1_from_quantiles([1, 2], [1, 2])


def _rec(p50, spacing=30.0, status="ok", wid="E1"):
    q = [p50 + (i - 10) * 0.5 for i in range(21)]
    s = {"p10": q[2], "p50": q[10], "p90": q[18], "q": q}
    return {"window_id": wid, "status": status, "spacing_m": {"east_west": spacing, "north_south": spacing},
            "slope_deg": s if status == "ok" else None,
            "roughness_m": {"p50": 1.0, "p90": 2.0, "q": [1.0] * 21} if status == "ok" else None}


def test_compare_window_deltas_and_no_score():
    c = compare_window(_rec(5.0), _rec(7.0), passes_filters=True)
    f = c["features"]["slope_deg"]
    assert f["status"] == "computed" and f["delta"]["p50"] == pytest.approx(2.0)
    assert f["w1"] == pytest.approx(2.0) and f["unit"] == "deg"
    blob = json.dumps(c)
    for k in ('"score"', '"rank"', '"weight"', '"pass"', '"winner"'):
        assert k not in blob


def test_compare_refuses_scale_mismatch_and_missing():
    assert spacing_check(_rec(5, 30), _rec(5, 90))["comparable"] is False
    c = compare_window(_rec(5, 30), _rec(5, 90))
    assert all(v["status"] == "scale_mismatch" and "delta" not in v for v in c["features"].values())
    c2 = compare_window(_rec(5), _rec(5, status="insufficient_data"))
    assert all(v["status"] == "insufficient_data" for v in c2["features"].values())
    moon = _rec(5)
    moon["roughness_m"] = None
    assert compare_window(moon, _rec(5))["features"]["roughness_m"]["status"] == "missing"


# ---------------------------------------------------------------- draft gates
def test_gate_evaluation_rules():
    sp = {"earth": 30.0, "moon": 30.0}
    assert evaluate_gate("High-res DEM <= leg-spacing/3 required", sp, {})["result"] == "unverified"
    assert evaluate_gate("High-res DEM <= leg-spacing/3 required", sp, {"leg_spacing_m": 4})["result"] == "unverified"
    assert evaluate_gate("High-res DEM <= leg-spacing/3 required", {"earth": 1.0, "moon": 1.0},
                         {"leg_spacing_m": 4})["result"] == "pass"
    assert evaluate_gate("Use same spatial support / physical meters", sp, {})["result"] == "pass"
    assert evaluate_gate("Use same spatial support", {"earth": 30, "moon": 90}, {})["result"] == "fail"
    assert evaluate_gate("Exact vehicle footprint needed", sp, {})["result"] == "manual_review"


needs_spec = pytest.mark.skipif(find_spec() is None, reason="algorithm spec workbook not present")


@needs_spec
def test_draft_spec_loads_without_weights_or_thresholds():
    spec = DraftSpec.load()
    assert set(spec.experiments) == {"EXP_02", "EXP_04", "EXP_08", "EXP_10", "EXP_SHADOW", "EXP_PLUME"}
    for rows in spec.features.values():
        for r in rows:
            assert set(r) == {"feature_id", "requirement", "gate"}           # no weights read
    for e in spec.experiments.values():
        assert "threshold" not in json.dumps(e).lower()


@needs_spec
def test_all_spec_experiments_currently_insufficient_data():
    spec = DraftSpec.load()
    for eid in spec.experiments:
        d = evaluate_experiment(spec, eid, {"earth": 30.0, "moon": 30.0})
        assert d["label"] == DRAFT_LABEL
        assert d["status"] == "insufficient_data" and d["missing_required"]
    d2 = evaluate_experiment(spec, "EXP_02", {"earth": 30.0, "moon": 30.0})
    assert d2["missing_required"] == ["F_RELIEF"]
    slope = next(f for f in d2["features"] if f["feature_id"] == "F_SLOPE")
    assert slope["computable"] and slope["gate"]["result"] == "manual_review"


# ---------------------------------------------------------------- full run
def test_lunar_reference_respects_region_mask():
    region = LunarRegion.point(-10.0, 20.0, 5_000)
    ref = lunar_reference(region, MockMoonConnector(), target_spacing_m=None)
    assert ref["status"] == "ok" and ref["is_mock"]
    expected = math.pi * 5_000 ** 2 / 30.0 ** 2                             # disc / pixel area
    assert ref["n_samples"] == pytest.approx(expected, rel=0.05)
    coarse = lunar_reference(region, MockMoonConnector(), target_spacing_m=90.0)
    assert coarse["spacing_m"]["east_west"] == pytest.approx(90.0)
    assert coarse["provenance"][0]["processing"] == ["block-mean x3"]


def test_run_comparison_mock_end_to_end(tmp_path):
    req = ComparisonRequest(LunarRegion.bbox(10, -5, 10.3, -4.7), (-70, -24, -69, -23), 20_000,
                            [Constraint.parse("slope_deg.p90<=30")], {"leg_spacing_m": 4.0})
    spec = DraftSpec.load() if find_spec() else None
    events = []
    res = run_comparison(req, MockMoonConnector(), MockEarthConnector(arcsec=10),
                         DescriptorCache(tmp_path), events.append, spec)
    assert res["schema"] == COMPARISON_SCHEMA and res["contains_mock_data"] is True
    assert res["governance"] == GOVERNANCE
    assert res["moon"]["status"] == "ok"
    assert res["moon"]["spacing_m"]["east_west"] == pytest.approx(300.0, rel=0.05)   # 30 m x10
    ids = [c["window_id"] for c in res["comparisons"]]
    assert ids == sorted(ids) and len(ids) == len(res["earth"]["windows"])
    assert any(c["features"]["slope_deg"]["status"] == "computed" for c in res["comparisons"])
    assert {e["stage"] for e in events} >= {"moon", "plan", "tiles", "done"}
    if spec:
        assert len(res["experiments_draft"]) == 6
    with pytest.raises(ValueError):
        run_comparison(req, MockEarthConnector(), MockMoonConnector())


# ---------------------------------------------------------------- Rookie integration
from lunarmatch.knowledge.workbook import WORKBOOK_PATH  # noqa: E402


@pytest.mark.skipif(not WORKBOOK_PATH.is_file(), reason="team workbook not present")
def test_rookie_comparison_summary_and_mock_banner(tmp_path):
    import copy
    import re
    import subprocess
    from lunarmatch.discovery.store import write_json
    from rookie.build import build, comparison_summary
    from test_rookie import EARTH_OK, _browser

    assert comparison_summary(tmp_path / "none.json") is None
    data = tmp_path / "data"
    write_hgt(data / "S24W070.hgt", 900 + np.tile(np.arange(N) * 2, (N, 1)))
    req = ComparisonRequest(LunarRegion.point(-10, 20, 5_000), (-70, -24, -69, -23), 30_000)
    res = run_comparison(req, MockMoonConnector(),
                         LocalSRTMConnector(search_dirs=[data], extract_dir=tmp_path / "ex"),
                         DescriptorCache(tmp_path / "c"))
    p = write_json(res, tmp_path / "cmp.json")
    s = comparison_summary(p)
    assert s["contains_mock_data"] and s["moon"]["is_mock"] and not s["earth"]["is_mock"]
    assert all(r["earth_mock"] is False for r in s["rows"])         # real Earth rows not mislabelled
    assert [r["id"] for r in s["rows"]] == sorted(r["id"] for r in s["rows"])
    assert "q" not in json.dumps(s["moon"]["slope_deg"])
    out = build(output_dir=tmp_path / "o", earth=copy.deepcopy(EARTH_OK), search_gif=None,
                comparison_path=p)
    html = out.read_text(encoding="utf-8")
    d = json.loads(re.search(r'id="rookie-data">(.*?)</script>', html, re.S).group(1))
    assert d["comparison"]["governance"]["ranking_computed"] is False
    if _browser():
        dom = subprocess.run([_browser(), "--headless=new", "--disable-gpu",
                              f"--user-data-dir={tmp_path / 'prof'}", "--virtual-time-budget=3000",
                              "--dump-dom", out.as_uri() + "#target=nobile_rim_2&exp=slope_stability&step=6"],
                             capture_output=True, text=True, encoding="utf-8", timeout=60).stdout
        assert "MOCK DATA — not real terrain" in dom
        assert "Per-feature distances to the lunar reference" in dom
        ids = re.findall(r"<td>(S24W070-w30km-r\d\dc\d\d)", dom)
        assert ids and ids == sorted(ids)                               # engine order = window ID
