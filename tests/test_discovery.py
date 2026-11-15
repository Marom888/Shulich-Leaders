"""Discovery infrastructure: bodies, lunar regions, grid, descriptors, cache, engine."""
import json
import math

import numpy as np
import pytest

from conftest import N, write_hgt
from lunarmatch import bodies as B
from lunarmatch import geodesy
from lunarmatch.data import raster_loader as rl
from lunarmatch.discovery import descriptors as dsc
from lunarmatch.discovery.engine import (GOVERNANCE, Constraint, SearchRequest, apply_filters,
                                         coverage, run_search)
from lunarmatch.discovery.grid import GridError, Tile, in_dataset_coverage, tiles_in_bbox
from lunarmatch.discovery.sources import LocalSRTMSource, plan_downloads
from lunarmatch.discovery.store import (RESULT_SCHEMA, DescriptorCache, cache_key, read_result,
                                        write_result)
from lunarmatch.regions import LunarRegion, RegionError


# ---------------------------------------------------------------- bodies
def test_earth_body_delegates_to_unchanged_wgs84():
    assert B.metres_per_degree(B.EARTH, -23.5) == geodesy.metres_per_degree(-23.5)
    assert B.EARTH.mean_radius_m == pytest.approx(6_371_007.2, abs=1)   # WGS84 authalic


def test_moon_is_a_sphere_not_wgs84():
    mlat, mlon = B.metres_per_degree(B.MOON, 0)
    assert mlat == pytest.approx(1_737_400 * math.pi / 180) and mlon == pytest.approx(mlat)
    mlat85, mlon85 = B.metres_per_degree(B.MOON, -85)
    assert mlat85 == pytest.approx(mlat)
    assert mlon85 == pytest.approx(mlat * math.cos(math.radians(85)))
    assert mlat < geodesy.metres_per_degree(0)[0] / 3          # ~30.3 km vs ~110.6 km
    assert B.MOON.crs == "IAU_2015:30100"


def test_band_area_whole_body_and_antimeridian():
    assert B.band_area_m2(B.MOON, -180, -90, 180, 90) == pytest.approx(4 * math.pi * 1_737_400 ** 2)
    a = B.band_area_m2(B.EARTH, 170, 0, -170, 1)
    assert a == pytest.approx(B.band_area_m2(B.EARTH, 0, 0, 20, 1))


# ---------------------------------------------------------------- lunar regions
def test_lunar_region_point_and_bbox():
    r = LunarRegion.point(-85.0, 30.0, 10_000, name="any region")
    assert r.contains(-85.0, 30.0) and not r.contains(-80.0, 30.0)
    assert r.area_m2() == pytest.approx(math.pi * 10_000 ** 2, rel=1e-4)    # small cap ≈ disc
    b = LunarRegion.bbox(170, -10, -170, 10)                                 # crosses antimeridian
    assert b.contains(0, 179) and b.contains(0, -175) and not b.contains(0, 0)
    d = b.to_dict()
    assert d["crs"] == "IAU_2015:30100" and d["kind"] == "bbox" and d["area_km2"] > 0


@pytest.mark.parametrize("make", [
    lambda: LunarRegion.point(-91, 0, 1000),
    lambda: LunarRegion.point(0, 181, 1000),
    lambda: LunarRegion.point(0, 0, 0),
    lambda: LunarRegion.bbox(0, 10, 5, 5),
    lambda: LunarRegion.bbox(5, 0, 5, 1),
    lambda: LunarRegion("polygon", {}),
])
def test_lunar_region_validation(make):
    with pytest.raises(RegionError):
        make()


# ---------------------------------------------------------------- grid
def test_tile_ids_roundtrip_and_bounds():
    for tid in ("S24W070", "N00E000", "N59W180", "S56E179"):
        assert Tile.from_id(tid).id == tid
    t = Tile.from_id("S24W070")
    assert t.bounds == (-70, -24, -69, -23)
    mlat, mlon = geodesy.metres_per_degree(-23.5)                            # ellipsoidal check
    assert t.area_km2() == pytest.approx(mlat * mlon / 1e6, rel=0.003)       # ~11,312 km²
    with pytest.raises(GridError):
        Tile.from_id("X24W070")


def test_tiles_in_bbox_counts_and_antimeridian():
    assert [t.id for t in tiles_in_bbox(-70, -24, -69, -23)] == ["S24W070"]
    assert len(tiles_in_bbox(-71, -25, -68, -22)) == 9
    assert len(tiles_in_bbox(-70.5, -23.5, -69.5, -22.5)) == 4               # partial overlap
    wrap = {t.id for t in tiles_in_bbox(179, 0, -179, 1)}
    assert wrap == {"N00E179", "N00W180"}
    assert len(tiles_in_bbox(-180, -90, 180, 90)) == 360 * 180
    with pytest.raises(GridError):
        tiles_in_bbox(0, 5, 1, 5)


def test_dataset_latitude_coverage():
    assert in_dataset_coverage(Tile(-56, 0), "SRTMGL1")
    assert in_dataset_coverage(Tile(59, 0), "SRTMGL1")
    assert not in_dataset_coverage(Tile(-57, 0), "SRTMGL1")
    assert not in_dataset_coverage(Tile(60, 0), "SRTMGL1")


# ---------------------------------------------------------------- descriptors
def _raster(tmp_path, z, name="S24W070.hgt"):
    return rl.load_raster(write_hgt(tmp_path / name, z.astype(np.int16)))


def test_partition_is_physical_and_complete(tmp_path):
    r = _raster(tmp_path, np.full((N, N), 1000))
    wins = dsc.partition(r, "S24W070", 10_000)
    rows = sorted({(w.row0, w.row1) for w in wins})
    cols = sorted({(w.col0, w.col1) for w in wins})
    assert rows[0][0] == 0 and rows[-1][1] == N and cols[-1][1] == N
    assert all(a[1] == b[0] for a, b in zip(rows, rows[1:]))                 # no gaps/overlap
    recs = dsc.describe(r, wins)
    for rec in recs:
        assert 8_000 < rec["size_m"]["east_west"] < 12_500
        assert 8_000 < rec["size_m"]["north_south"] < 12_500
    assert sum(x["n_samples"] for x in recs) == N * N
    assert len({x["window_id"] for x in recs}) == len(recs)


def test_flat_tile_descriptors_and_orientation(tmp_path):
    r_, c_ = np.mgrid[0:N, 0:N]
    z = 1000 + (N - 1 - r_) * 2                       # rises northward, flat east-west
    recs = dsc.describe(_raster(tmp_path, z), dsc.partition(_raster(tmp_path, z), "S24W070", 20_000))
    first = recs[0]                                   # r00c00 = north-west window
    assert first["bounds_wsen"][3] == pytest.approx(-23 + 0.5 / (N - 1), abs=1e-6)
    assert first["bounds_wsen"][0] == pytest.approx(-70 - 0.5 / (N - 1), abs=1e-6)
    last = recs[-1]
    assert first["elevation_m"]["p50"] > last["elevation_m"]["p50"]          # north higher
    flat = dsc.describe(_raster(tmp_path, np.full((N, N), 500), "S24W070.hgt"),
                        dsc.partition(_raster(tmp_path, np.full((N, N), 500)), "S24W070", 20_000))
    assert all(x["slope_deg"]["p90"] == 0 and x["roughness_m"]["p90"] == 0 for x in flat)
    assert all(x["elevation_m"]["range"] == 0 for x in flat)


def test_insufficient_data_has_no_numbers(tmp_path):
    z = np.full((N, N), 700)
    z[:300, :300] = -32768                            # north-west corner missing
    r = _raster(tmp_path, z)
    recs = dsc.describe(r, dsc.partition(r, "S24W070", 20_000), min_valid_fraction=0.9)
    bad = [x for x in recs if x["status"] == "insufficient_data"]
    assert bad and bad[0]["window_id"].endswith("r00c00")
    for x in bad:
        assert x["elevation_m"] is None and x["slope_deg"] is None and x["roughness_m"] is None
        assert x["valid_fraction"] < 0.9
    assert all(x["status"] == "ok" for x in recs if x not in bad)


# ---------------------------------------------------------------- constraints and filters
def test_constraint_parsing_and_missing_values():
    c = Constraint.parse("slope_deg.p90<=15")
    assert (c.field, c.op, c.value) == ("slope_deg.p90", "<=", 15.0)
    assert c.evaluate({"slope_deg": {"p90": 12}}) == "pass"
    assert c.evaluate({"slope_deg": {"p90": 16}}) == "fail"
    assert c.evaluate({"slope_deg": None}) == "not_evaluable"
    for bad in ("slope<=1", "slope_deg.p90 == 3", "score>=80"):
        with pytest.raises(ValueError):
            Constraint.parse(bad)


def test_filters_never_pass_missing_data():
    ws = [{"window_id": "b", "status": "ok", "slope_deg": {"p90": 5}},
          {"window_id": "a", "status": "ok", "slope_deg": {"p90": 1}},
          {"window_id": "c", "status": "ok", "slope_deg": {"p90": 30}},
          {"window_id": "d", "status": "insufficient_data", "slope_deg": None},
          {"window_id": "e", "status": "ok", "slope_deg": None}]
    f = apply_filters(ws, [Constraint.parse("slope_deg.p90<=10")])
    assert f["passed"] == ["a", "b"]                   # sorted by ID, not by value
    assert f["failed_count"] == 1
    assert f["insufficient_data"] == ["d"] and f["not_evaluable"] == ["e"]


# ---------------------------------------------------------------- cache and serialization
def test_cache_hit_and_key_sensitivity(tmp_path):
    c = DescriptorCache(tmp_path)
    k1 = cache_key(tile="S24W070", sha="x", window_m=10_000, version="v1")
    assert c.get("SRTMGL1", "S24W070", k1) is None
    c.put("SRTMGL1", "S24W070", k1, [{"window_id": "w"}], {})
    assert c.get("SRTMGL1", "S24W070", k1) == [{"window_id": "w"}]
    for change in ({"sha": "y"}, {"window_m": 5000}, {"version": "v2"}):
        k2 = cache_key(**{**dict(tile="S24W070", sha="x", window_m=10_000, version="v1"), **change})
        assert k2 != k1 and c.get("SRTMGL1", "S24W070", k2) is None
    assert (c.hits, c.misses) == (1, 4)


def test_result_roundtrip_and_schema_guard(tmp_path):
    p = write_result({"schema": RESULT_SCHEMA, "x": 1}, tmp_path / "r.json")
    assert read_result(p)["x"] == 1
    with pytest.raises(ValueError):
        write_result({"schema": "other"}, tmp_path / "bad.json")
    (tmp_path / "old.json").write_text(json.dumps({"schema": "v0"}), encoding="utf-8")
    with pytest.raises(ValueError):
        read_result(tmp_path / "old.json")


# ---------------------------------------------------------------- sources
def test_local_source_index_prefers_zip_and_skips_venv(tmp_path):
    import zipfile
    write_hgt(tmp_path / "a" / "S24W070.hgt", np.zeros((N, N)))
    write_hgt(tmp_path / ".venv" / "S10W050.hgt", np.zeros((N, N)))
    z = tmp_path / "S24W070.SRTMGL1.hgt.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("S24W070.hgt", b"")
    src = LocalSRTMSource([tmp_path])
    assert src.locate(Tile.from_id("S24W070")) == z
    assert src.locate(Tile.from_id("S10W050")) is None


class _G:
    def __init__(self, name, mb):
        self._n, self._mb = name, mb

    def data_links(self):
        return [f"https://example.invalid/{self._n}"]

    def size(self):
        return self._mb


def test_plan_downloads_uses_catalogue_metadata_only():
    def fake_search(bbox):
        w, s = bbox[0], bbox[1]
        tid = Tile(math.floor(s), math.floor(w)).id
        return [] if tid == "S24W069" else [_G(f"{tid}.SRTMGL1.hgt.zip", 12.5)]
    plan = plan_downloads([Tile.from_id("S24W070"), Tile.from_id("S24W069")], search=fake_search)
    assert plan["available"] == [{"tile": "S24W070", "granule": "S24W070.SRTMGL1.hgt.zip",
                                  "size_mb": 12.5}]
    assert plan["not_in_catalogue"] == ["S24W069"] and plan["total_mb"] == 12.5


# ---------------------------------------------------------------- engine
def test_run_search_coverage_progress_and_no_scores(tmp_path):
    data = tmp_path / "data"
    write_hgt(data / "S24W070.hgt", np.full((N, N), 900))
    write_hgt(data / "S23W070.hgt", 900 + np.tile(np.arange(N) * 3, (N, 1)))
    events = []
    req = SearchRequest(bbox=(-70.5, -24, -68.5, -22), window_m=20_000,
                        constraints=[Constraint.parse("slope_deg.p90<=1")])
    res = run_search(req, LocalSRTMSource([data]), DescriptorCache(tmp_path / "cache"),
                     events.append, extract_dir=tmp_path / "ex")
    cov = res["coverage"]
    assert cov["tiles_requested"] == 6 and cov["tiles_processed"] == 2
    assert cov["tiles_no_local_data"] == 4
    assert 0.3 < cov["fraction_of_request_processed"] < 0.35
    assert "not a global search" in cov["statement"]
    # progress events reflect real work, in order
    assert events[0] == {"stage": "plan", "tiles_total": 6, "tiles_done": 0,
                         "body": "Earth", "dataset": "SRTMGL1"}
    assert [e["tiles_done"] for e in events if e["stage"] == "tiles"] == [1, 2, 3, 4, 5, 6]
    assert events[-1]["stage"] == "done" and events[-1]["windows"] == len(res["windows"])
    # filters: the flat tile passes slope<=1, the sloped one does not
    assert res["filters"]["passed"] and all(w.startswith("S24W070") for w in res["filters"]["passed"])
    # no similarity/score/rank anywhere
    blob = json.dumps(res)
    for k in ('"score"', '"rank"', '"similarity"', '"winner"'):
        assert k not in blob
    assert res["governance"] == GOVERNANCE and GOVERNANCE["similarity_computed"] is False
    assert len(res["sources"]) == 2 and all(len(s["sha256"]) == 64 for s in res["sources"])
    # second run hits the cache and gives identical windows
    res2 = run_search(req, LocalSRTMSource([data]), DescriptorCache(tmp_path / "cache"),
                      extract_dir=tmp_path / "ex")
    assert res2["cache"] == {"hits": 2, "misses": 0}
    assert res2["windows"] == res["windows"]


def test_outside_coverage_and_failed_tiles_are_reported(tmp_path):
    bad = tmp_path / "data" / "S24W070.hgt"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"not a raster")
    res = run_search(SearchRequest(bbox=(-70, -24, -69, -23)), LocalSRTMSource([tmp_path / "data"]),
                     DescriptorCache(tmp_path / "c"), extract_dir=tmp_path / "ex")
    assert res["tiles"][0]["status"] == "failed" and "error" in res["tiles"][0]
    assert res["coverage"]["tiles_failed"] == 1 and res["windows"] == []
    polar = run_search(SearchRequest(bbox=(0, 70, 1, 71)), LocalSRTMSource([tmp_path / "data"]),
                       DescriptorCache(tmp_path / "c"))
    assert polar["tiles"][0]["status"] == "outside_dataset_coverage"


def test_coverage_math():
    c = coverage([{"status": "processed", "area_km2": 100.0},
                  {"status": "no_local_data", "area_km2": 300.0}])
    assert c["fraction_of_request_processed"] == 0.25 and c["area_processed_km2"] == 100.0


def test_real_tile_discovery_if_present(tmp_path):
    src = LocalSRTMSource()
    if src.locate(Tile.from_id("S24W070")) is None:
        pytest.skip("real tile not present")
    res = run_search(SearchRequest(bbox=(-70, -24, -69, -23), window_m=10_000), src,
                     DescriptorCache(tmp_path / "cache"), extract_dir=tmp_path / "ex")
    assert res["coverage"]["tiles_processed"] == 1
    ok = [w for w in res["windows"] if w["status"] == "ok"]
    assert len(ok) == len(res["windows"]) > 50
    for w in ok:
        assert 618 <= w["elevation_m"]["min"] <= w["elevation_m"]["max"] <= 3389
        assert -70.001 <= w["bounds_wsen"][0] < w["bounds_wsen"][2] <= -68.999


# ---------------------------------------------------------------- Rookie integration
from lunarmatch.knowledge.workbook import WORKBOOK_PATH  # noqa: E402


@pytest.mark.skipif(not WORKBOOK_PATH.is_file(), reason="team workbook not present")
def test_rookie_shows_real_coverage_only(tmp_path):
    import copy
    import re as _re
    from rookie.build import build, discovery_summary
    from test_rookie import EARTH_OK

    assert discovery_summary(tmp_path / "missing.json") is None
    data = tmp_path / "data"
    write_hgt(data / "S24W070.hgt", np.full((N, N), 900))
    res = run_search(SearchRequest(bbox=(-71, -24, -69, -23), window_m=20_000),
                     LocalSRTMSource([data]), DescriptorCache(tmp_path / "c"),
                     extract_dir=tmp_path / "ex")
    p = write_result(res, tmp_path / "latest.json")
    s = discovery_summary(p)
    assert s["coverage"]["tiles_processed"] == 1 and s["coverage"]["tiles_requested"] == 2
    assert "windows" in s and isinstance(s["windows"], int)          # counts only, no per-window data
    out = build(output_dir=tmp_path / "o", earth=copy.deepcopy(EARTH_OK), search_gif=None,
                discovery_path=p)
    html = out.read_text(encoding="utf-8")
    d = json.loads(_re.search(r'id="rookie-data">(.*?)</script>', html, _re.S).group(1))
    assert d["discovery"]["coverage"]["statement"].endswith("This is not a global search.")
    assert "function coverageCard" in html
