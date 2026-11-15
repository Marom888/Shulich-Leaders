"""LOLA provider end-to-end against a local server that mimics the PGDA file layout.

The served rasters are synthetic test fixtures (a tilted plane with known
slope and a known measurement-density pattern), so every number can be
checked analytically.  Real-data validation is done by examples/
shackleton_lola_demo.py against pgda.gsfc.nasa.gov.
"""
import numpy as np
import pytest

from helpers import write_pgda_like_tiff
from lunarmatch.core.aoi import AOI
from lunarmatch.core.bodies import Body
from lunarmatch.core.evidence import Evidence
from lunarmatch.core.http import HttpClient
from lunarmatch.providers.moon import lola


@pytest.fixture()
def fake_pgda(range_server, monkeypatch):
    base, www = range_server
    n = 400
    site = lola.PgdaSite("SiteT", -19000, -4000, n, 0, "2020-06-05", "test fixture")
    (www / "SiteT").mkdir()
    yy, xx = np.mgrid[0:n, 0:n]
    elev = 1000.0 + 0.1 * xx * 5.0          # dz/dx = 0.1 -> slope atan(0.1) = 5.71 deg
    dens = ((xx % 10) == 0).astype("float32")  # 10 % of pixels carry a LOLA shot
    layers = {"surf": elev, "slp": np.full((n, n), 5.71), "ldec": dens,
              "toterr": np.full((n, n), 0.3), "slperr": np.full((n, n), 1.5)}
    for suf, arr in layers.items():
        write_pgda_like_tiff(www / "SiteT" / f"SiteT_final_adj_5mpp_{suf}.tif", arr, site.x0, site.y0)
    monkeypatch.setattr(lola, "PGDA_BASE", base)
    monkeypatch.setattr(lola, "PGDA_SITES", (site,))
    return site, layers


def test_fetch_window(fake_pgda, store):
    site, layers = fake_pgda
    from lunarmatch.core.projections import polar_stereo_inverse

    bx0, by0, bx1, by1 = site.bounds
    lat, lon = polar_stereo_inverse((bx0 + bx1) / 2, (by0 + by1) / 2, south=True)
    aoi = AOI(Body.MOON, float(lat), float(lon), 500, 500)
    p = lola.LOLAProvider(store=store, client=HttpClient(retries=1))
    res = p.fetch(aoi, layers=["elevation", "slope", "measurement_density", "elevation_uncertainty",
                               "slope_derived", "roughness", "measured_mask"])
    e = res.layers["elevation"]
    assert e.shape == (101, 101) or e.shape == (100, 100) or e.shape[0] in (100, 101, 102)
    assert e.evidence is Evidence.MEASURED_DERIVED
    r0, r1 = res.metadata["window_rows"]
    c0, c1 = res.metadata["window_cols"]
    np.testing.assert_allclose(e.data, layers["surf"][r0:r1, c0:c1].astype("float32"))
    # transform corresponds to the window's upper-left pixel corner
    assert e.transform[0] == site.x0 + c0 * 5 and e.transform[3] == site.y0 - r0 * 5
    sd = res.layers["slope_derived"]
    assert sd.evidence is Evidence.DERIVED_HERE
    assert np.nanmedian(sd.data) == pytest.approx(np.degrees(np.arctan(0.1)), abs=1e-3)
    assert np.nanmax(res.layers["roughness"].data) < 1e-6  # a plane has zero detrended roughness
    assert res.metadata["fraction_pixels_with_lola_shot"] == pytest.approx(0.1, abs=0.02)
    assert any("interpolated" in w for w in res.warnings)
    # raw window + sidecar written, then reused without new remote requests
    raw = [f for f in res.files if "/raw/" in f]
    assert raw and all(store.has(f) for f in raw)
    from conftest import RangeHandler

    RangeHandler.requests_seen.clear()
    res2 = p.fetch(aoi, layers=["elevation"])
    assert RangeHandler.requests_seen == []
    np.testing.assert_array_equal(res2.layers["elevation"].data, e.data)


def test_unknown_layer_rejected(fake_pgda, store):
    p = lola.LOLAProvider(store=store)
    with pytest.raises(Exception):
        p.fetch(AOI(Body.MOON, -89.46, 222.5, 100, 100), layers=["albedo"])
