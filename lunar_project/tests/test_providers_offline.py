"""Offline tests: parsers fed with response structures recorded from the live
services on 2026-11-15, terrain math, ephemeris sanity, and the real SRTM
tile that is committed in this repository."""
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from lunarmatch import registry
from lunarmatch.core import terrain
from lunarmatch.core.aoi import AOI
from lunarmatch.core.bodies import Body
from lunarmatch.core.evidence import Evidence
from lunarmatch.core.ode import OdeClient

REPO = Path(__file__).resolve().parents[2]
HGT = REPO / "S24W070.SRTMGL1.hgt" / "S24W070.hgt"


def test_registry_covers_every_workbook_dataset():
    wb = {d["Dataset_ID"] for d in registry.workbook_datasets()}
    assert wb and wb == set(registry.list_datasets())
    for did in registry.list_datasets():
        d = registry.get_provider(did).describe()
        assert d["dataset_id"] == did and d["access"] and d["evidence"]


def test_slope_and_roughness_on_known_surfaces():
    yy, xx = np.mgrid[0:50, 0:60].astype(float)
    z = 0.2 * xx * 2.0 + 0.0 * yy  # dx=2 m, dz/dx = 0.2
    s = terrain.slope_horn(z, 2.0, 2.0)
    assert np.isnan(s[0, 0]) and np.nanmax(np.abs(s - np.degrees(np.arctan(0.2)))) < 1e-9
    assert np.nanmax(terrain.detrended_rms_roughness(z, 5, 2.0, 2.0)) < 1e-9
    bumpy = z + np.where((xx + yy) % 2 == 0, 0.5, -0.5)
    r = terrain.detrended_rms_roughness(bumpy, 5, 2.0, 2.0)
    assert np.nanmedian(r) == pytest.approx(0.5, abs=0.03)
    assert np.nanmax(terrain.local_relief(z, 3)) == pytest.approx(0.2 * 2 * 2, abs=1e-9)
    assert terrain.window_px_for(25, 5) == 5 and terrain.window_px_for(10, 5) == 3


@pytest.mark.skipif(not HGT.exists(), reason="repo SRTM tile not present")
def test_real_srtm_tile_from_repo():
    from lunarmatch.providers.earth.nasadem import read_hgt

    full = read_hgt(HGT, dataset_id="SRTMGL1")
    assert full.shape == (3601, 3601)
    assert full.transform[0] == pytest.approx(-70 - 0.5 / 3600)
    assert full.transform[3] == pytest.approx(-23 + 0.5 / 3600)
    st = full.stats()
    # Atacama / Andes tile: real elevations between sea level and ~6 km
    assert -50 < st["min"] < 3000 and 2000 < st["max"] < 7000
    aoi = AOI(Body.EARTH, -23.5, -69.5, 1000, 1000)
    sub = read_hgt(HGT, aoi)
    assert 30 <= sub.shape[0] <= 36 and 30 <= sub.shape[1] <= 40
    np.testing.assert_array_equal(sub.data, full.data[
        int(round((full.transform[3] - sub.transform[3]) * 3600)):][:sub.shape[0],
        int(round((sub.transform[0] - full.transform[0]) * 3600)):][:, :sub.shape[1]])


def test_ode_parser_on_recorded_structure():
    recorded = {  # trimmed from a live SDNDTM response (NAC_DTM_SHACKRDGE02)
        "pdsid": "sdp.nac_dtm.shackrdge02.nac_dtm_shackrdge02",
        "Product_files": {"Product_file": [
            {"Description": "DTM IN GEOTIFF FORMAT", "FileName": "NAC_DTM_SHACKRDGE02.TIF", "KBytes": "9838",
             "Type": "Product",
             "URL": "https://pds.mcp.nasa.gov/data/store/img/lunar_reconnaissance_orbiter/pds4/lroc/lro-l-lroc-5-rdr/"
                    "LROLRC_2001/DATA/SDP/NAC_DTM/SHACKRDGE02/NAC_DTM_SHACKRDGE02.TIF"},
            {"Description": "CONFIDENCE MAP", "FileName": "NAC_DTM_SHACKRDGE02_CONF.IMG", "KBytes": "2462",
             "Type": "Product", "URL": "https://example.invalid/conf.img"},
        ]},
    }
    ref = OdeClient.to_product_ref(recorded)
    fname, url, size = OdeClient.pick_file(ref, "DTM IN GEOTIFF", ".TIF")
    assert fname == "NAC_DTM_SHACKRDGE02.TIF" and size == 9838 * 1024 and url.endswith(".TIF")
    no_id = OdeClient.to_product_ref({"Product_files": {"Product_file": [
        {"Description": "COLOR SLOPE COG MAP", "FileName": "SHADOWCAM_DTM_X_COLOR-SLOPE_COG.TIF", "KBytes": "1",
         "URL": "https://pds.shadowcam.im-ldi.com/x.tif"}]}})
    assert no_id.product_id == "SHADOWCAM_DTM_X_COLOR-SLOPE_COG"


def test_soilgrids_parser_on_recorded_response():
    from lunarmatch.providers.earth.soilgrids import parse_rest_response

    recorded = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [35.0, 31.0]},
                "properties": {"layers": [{"name": "bdod", "unit_measure": {
                    "d_factor": 100, "mapped_units": "cg/cm³", "target_units": "kg/dm³", "uncertainty_unit": ""},
                    "depths": [{"range": {"top_depth": 0, "bottom_depth": 5, "unit_depth": "cm"},
                                "label": "0-5cm", "values": {"mean": 141}}]}]}}
    rows = parse_rest_response(recorded)
    assert rows == [{"property": "bdod", "depth": "0-5cm", "top_cm": 0, "bottom_cm": 5, "units": "kg/dm³",
                     "mapped_units": "cg/cm³", "d_factor": 100, "evidence": "MODELED", "mean": 1.41}]


def test_earth_sun_position_sanity():
    from lunarmatch.providers.common.ephemeris import earth_sun_position, find_earth_times

    # June solstice at the North Pole: elevation ~ obliquity (23.44 deg) all day
    p = earth_sun_position(90.0, 0.0, datetime(2026, 6, 21, 12, tzinfo=timezone.utc))
    assert p["elevation_deg"] == pytest.approx(23.44, abs=0.05)
    # March equinox, solar noon at the equator on the Greenwich meridian -> sun near zenith
    p = earth_sun_position(0.0, 0.0, datetime(2026, 3, 20, 12, 7, tzinfo=timezone.utc))
    assert p["elevation_deg"] > 89.0
    # Low sun search returns only matching times
    hits = find_earth_times(31.0, 35.0, 5.0, None, datetime(2026, 11, 15, tzinfo=timezone.utc),
                            datetime(2026, 11, 16, tzinfo=timezone.utc), step_min=5, elev_tol=0.5)
    assert hits and all(abs(h["elevation_deg"] - 5.0) <= 0.5 for h in hits)
    with pytest.raises(ValueError):
        earth_sun_position(0, 0, datetime(2026, 1, 1))  # naive datetime refused


def test_user_inputs_validation_and_pressure(store):
    from lunarmatch.providers.common.user_inputs import LanderSpec, UserInputProvider

    spec = LanderSpec("demo_lander", mass_kg=1000, n_legs=4, footpad_diameter_m=0.5, leg_span_m=4.0,
                      cg_height_m=1.5, landing_time_utc="2027-01-01T00:00:00Z")
    assert spec.validate() == []
    q_moon = spec.static_pad_pressure_pa(Body.MOON)
    assert q_moon == pytest.approx(1000 * 1.62 / (4 * np.pi * 0.25 ** 2))
    assert spec.static_pad_pressure_pa(Body.EARTH) / q_moon == pytest.approx(9.80665 / 1.62)
    res = UserInputProvider(store=store).fetch(spec=spec)
    assert res.tables["derived"][0]["required_dem_resolution_m"] == pytest.approx(4 / 3)
    bad = LanderSpec("x", 1000, 2, 0.5, 4, 1.5)
    assert any("n_legs" in e for e in bad.validate())


def test_reference_only_and_soil_never_invent_values(store):
    from lunarmatch.core.base import NotAvailable
    from lunarmatch.providers.moon.lunar_soil import LunarSoilProvider
    from lunarmatch.providers.reference_only import SCALPSSProvider

    with pytest.raises(NotAvailable):
        SCALPSSProvider(store=store).fetch()
    res = LunarSoilProvider(store=store).fetch()
    assert res.tables["observations"] == []
    assert len(res.tables["references"]) == 4
    assert all(not (r.get("Numerical_Value") or "").strip() for r in res.tables["references"])
