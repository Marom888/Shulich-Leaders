"""Checks on the real Atacama SRTM tile. Skipped when the tile is not on disk."""
import numpy as np
import pytest

from lunarmatch.data import raster_loader as rl
from lunarmatch.data.earthdata_client import find_local_tile
from lunarmatch.visualization import terrain_plots as tp

TILE = find_local_tile("S24W070")
pytestmark = pytest.mark.skipif(TILE is None, reason="real S24W070 tile not present")


@pytest.fixture(scope="module")
def raster(tmp_path_factory):
    return rl.load_raster(TILE, tmp_path_factory.mktemp("extract"))


def test_metadata(raster):
    assert raster.shape == (3601, 3601)
    assert "4326" in raster.crs
    assert raster.sample_extent == pytest.approx((-70, -24, -69, -23), abs=1e-9)
    w, s, e, n = raster.footprint
    assert w < -70 < -69 < e and s < -24 < -23 < n


def test_rasterio_matches_independent_big_endian_read(raster):
    """rasterio's decode equals a raw numpy read of the HGT bytes."""
    raw = np.fromfile(raster.source, dtype=">i2").reshape(raster.shape)
    assert np.array_equal(raster.data, raw)


def test_plausible_atacama_elevations(raster):
    # Sanity bounds only (not a validation of NASA accuracy).
    assert 0 < raster.valid_min < raster.valid_max < 7000


def test_pipeline_consistency(raster):
    g = rl.downsample(raster, rl.choose_step(raster.shape, 361))
    assert g.step == 10 and g.shape == (361, 361)
    rl.verify_samples(raster, g, n=200)
    tp.check_figures(g, tp.heatmap_figure(g), tp.surface_figure(g))
