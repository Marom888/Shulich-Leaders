import numpy as np
import pytest

from conftest import N
from lunarmatch.data import raster_loader as rl
from lunarmatch.visualization import terrain_plots as tp


@pytest.fixture
def grid(hgt_file):
    raster = rl.load_raster(hgt_file)
    return raster, rl.downsample(raster, 100)   # rows/cols 0,100,...,1200


def test_metres_per_degree_reference_values():
    mlat, mlon = tp.metres_per_degree(0.0)
    assert mlat == pytest.approx(110574, abs=2)      # WGS84 equator
    assert mlon == pytest.approx(111320, abs=2)
    mlat, mlon = tp.metres_per_degree(-23.5)
    # series: 111132.954 - 559.822 cos2p + 1.175 cos4p ; 111412.84 cos p - 93.5 cos3p
    assert mlat == pytest.approx(110751, abs=2)
    assert mlon == pytest.approx(102141, abs=2)


def test_both_figures_use_same_values(grid):
    raster, g = grid
    f2, f3 = tp.heatmap_figure(g), tp.surface_figure(g)
    tp.check_figures(g, f2, f3)
    assert np.array_equal(np.asarray(f2.data[0].z, float),
                          np.asarray(f3.data[0].z, float), equal_nan=True)


def test_plotted_values_are_original_samples(grid):
    raster, g = grid
    z = np.asarray(tp.heatmap_figure(g).data[0].z, float)[::-1]   # back to row order
    cd = np.asarray(tp.heatmap_figure(g).data[0].customdata)[::-1]
    for i in range(g.shape[0]):
        for j in range(g.shape[1]):
            r, c = cd[i, j]
            if raster.nodata_mask[r, c]:
                assert np.isnan(z[i, j])
            else:
                assert z[i, j] == raster.data[r, c]


def test_nodata_is_nan_never_zero(grid):
    raster, g = grid
    z = np.asarray(tp.surface_figure(g).data[0].z, float)
    # NoData at (1200, 0) is sampled -> last grid row, first col -> first plotted row
    assert np.isnan(z[0, 0])
    assert not np.any(z == 0) or raster.data[raster.data == 0].size > 0
    assert not np.any(z == -32768)


def test_heatmap_north_up_east_right(grid):
    _, g = grid
    tr = tp.heatmap_figure(g).data[0]
    y, x = np.asarray(tr.y), np.asarray(tr.x)
    assert np.all(np.diff(y) > 0) and np.all(np.diff(x) > 0)
    assert y[-1] == pytest.approx(-23)          # top of plot = north edge
    cd = np.asarray(tr.customdata)
    assert cd[-1, 0, 0] == 0                    # top plotted row = raster row 0
    z = np.asarray(tr.z, float)
    assert z[-1, 6] > z[0, 6]                 # synthetic: north is higher
    assert z[5, -1] > z[5, 1]                   # synthetic: east is higher


def test_surface_is_metric_and_oriented(grid):
    _, g = grid
    tr = tp.surface_figure(g).data[0]
    x, y = np.asarray(tr.x), np.asarray(tr.y)
    assert np.all(np.diff(x) > 0) and np.all(np.diff(y) > 0)
    assert x[-1] - x[0] == pytest.approx(102.141, abs=0.01)    # km, 1 deg lon
    assert y[-1] - y[0] == pytest.approx(110.751, abs=0.01)    # km, 1 deg lat
    assert x[0] == pytest.approx(-x[-1]) and y[0] == pytest.approx(-y[-1])


@pytest.mark.parametrize("vex", [1, 2.5, 10])
def test_vertical_exaggeration_shown_and_applied(grid, vex):
    _, g = grid
    f = tp.surface_figure(g, vex)
    assert f"×{vex:g}" in f.layout.title.text
    a = f.layout.scene.aspectratio
    x_km, y_km, *_ = tp.local_km(g)
    base = max(np.ptp(x_km), np.ptp(y_km))
    zr_km = (np.nanmax(g.values) - np.nanmin(g.values)) / 1000
    assert a.z == pytest.approx(zr_km * vex / base)
    assert a.y / a.x == pytest.approx(np.ptp(y_km) / np.ptp(x_km))


def test_invalid_exaggeration(grid):
    with pytest.raises(ValueError):
        tp.surface_figure(grid[1], 0)


def test_titles_disclose_sampling(grid):
    _, g = grid
    for f in (tp.heatmap_figure(g), tp.surface_figure(g)):
        t = f.layout.title.text
        assert "every 100 sample" in t and f"{N}x{N}" in t and "not interpolated" in t


def test_check_figures_detects_mismatch(grid):
    _, g = grid
    f2, f3 = tp.heatmap_figure(g), tp.surface_figure(g)
    z = np.asarray(f3.data[0].z, float).copy()
    z[3, 3] += 1
    f3.data[0].z = z
    with pytest.raises(AssertionError):
        tp.check_figures(g, f2, f3)


def test_save_html(grid, tmp_path):
    p = tp.save_html(tp.heatmap_figure(grid[1]), tmp_path / "out" / "t.html")
    text = p.read_text(encoding="utf-8")
    assert p.is_file() and "plotly" in text.lower() and "<html" in text.lower()
