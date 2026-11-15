import json

import numpy as np
import pytest

from lunarmatch.core.aoi import AOI
from lunarmatch.core.bodies import Body
from lunarmatch.core.evidence import Evidence
from lunarmatch.core.raster import Layer
from lunarmatch.core.resample import UpsamplingRefused, block_mean, to_gsd


def _layer(shape, px, crs="TEST", name="x", val=None):
    data = np.arange(np.prod(shape), dtype=float).reshape(shape) if val is None else np.full(shape, val, float)
    return Layer(name, data, (0.0, px, 0.0, 0.0, 0.0, -px), crs, "m", Evidence.MEASURED, "D_TEST")


def test_block_mean_and_nan_rule():
    a = np.arange(16, dtype=float).reshape(4, 4)
    np.testing.assert_allclose(block_mean(a, 2, 2), [[2.5, 4.5], [10.5, 12.5]])
    a[0, 0] = a[0, 1] = a[1, 0] = np.nan  # 3 of 4 missing -> NaN with min_valid=0.5
    assert np.isnan(block_mean(a, 2, 2)[0, 0])


def test_to_gsd_downsamples_and_refuses_upsampling():
    lyr = _layer((100, 100), 1.0)
    out = to_gsd(lyr, 10.0, (1.0, 1.0))
    assert out.shape == (10, 10) and out.transform[1] == 10.0 and out.evidence is Evidence.DERIVED_HERE
    assert out.extra["original_evidence"] == "MEASURED" and out.extra["block_factor"] == [10, 10]
    with pytest.raises(UpsamplingRefused):
        to_gsd(_layer((10, 10), 30.0), 10.0, (30.0, 30.0))


def test_bundle_orchestration_with_fallbacks(monkeypatch, store):
    """Providers are replaced by stubs: checks fallback order, common GSD and manifest – not data."""
    from lunarmatch.core.base import FetchResult, NotCovered
    from lunarmatch.experiments import exp10_trn

    class Stub:
        def __init__(self, did):
            self.did = did

        def fetch(self, aoi, **kw):
            if self.did in ("D_LROC_DTM",):
                raise NotCovered("no DTM here")
            res = FetchResult(self.did, aoi)
            if self.did == "D_LROC_NAC_MAP":
                res.layers.add(_layer((60, 60), 1.0, name="image"))
            elif self.did == "D_LOLA":
                res.layers.add(_layer((12, 12), 5.0, name="elevation"))
            elif self.did == "D_COPDEM":
                lyr = _layer((4, 4), 1 / 3600, crs="EPSG:4326", name="elevation")
                res.layers.add(lyr)
            elif self.did == "D_SENT2":
                res.layers.add(_layer((6, 6), 10.0, name="red"))
                res.metadata.update(sun_elevation_deg=12.0)
            return res

    monkeypatch.setattr(exp10_trn, "get_provider", lambda did, **kw: Stub(did))
    b = exp10_trn.collect_exp10_inputs(AOI(Body.MOON, -89.46, 222.5, 60, 60), AOI(Body.EARTH, -23.5, -69.5, 60, 60),
                                       run_name="t", store=store)
    assert b.status["moon_image"] == "OK"
    assert b.status["moon_dem"].startswith("OK via fallback D_LOLA")
    assert b.sources["earth_image"]["sun_elevation_deg"] == 12.0
    # coarsest native GSD is Copernicus 1 arc-second (~28-31 m)
    assert 25 < b.common_gsd_m < 32
    assert b.layers["moon_image"].shape[0] == 60 // round(b.common_gsd_m / 1.0)
    m = json.loads(open(b.files[-1]).read())
    assert m["note"].startswith("Data bundle only") and set(m["layers"]) == set(b.layers)
