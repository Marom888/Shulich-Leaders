"""Analytic checks for terrain derivatives on synthetic HGT tiles."""
import numpy as np
import pytest

from conftest import N, write_hgt
from lunarmatch.data import raster_loader as rl
from lunarmatch.features import terrain as tf

PIX = 1 / (N - 1)                      # 3 arc-seconds for a 1201 tile


def series_m_per_deg(lat):
    """Independent textbook series (not the WGS84 code under test)."""
    p = np.radians(lat)
    mlat = 111132.954 - 559.822 * np.cos(2 * p) + 1.175 * np.cos(4 * p)
    mlon = 111412.84 * np.cos(p) - 93.5 * np.cos(3 * p)
    return mlat, mlon


def load(tmp_path, z):
    return rl.load_raster(write_hgt(tmp_path / "S24W070.hgt", z.astype(np.int16)))


def interior(a):
    return a[1:-1, 1:-1]


# ---------------------------------------------------------------- core Horn
def test_horn_flat_is_zero():
    s = tf.horn_slope(np.full((10, 12), 500.0), 30.0, 30.0)
    assert np.all(interior(s) == 0)
    assert np.all(np.isnan(s[0])) and np.all(np.isnan(s[-1]))
    assert np.all(np.isnan(s[:, 0])) and np.all(np.isnan(s[:, -1]))


@pytest.mark.parametrize("gx,gy", [(0.1, 0), (0, 0.25), (0.3, -0.4), (1.0, 1.0)])
def test_horn_exact_on_float_plane(gx, gy):
    dx, dy = 28.0, 31.0
    r, c = np.mgrid[0:20, 0:25]
    z = gx * c * dx - gy * r * dy            # gy > 0 means rising northward
    s = tf.horn_slope(z, dx, dy)
    expected = np.degrees(np.arctan(np.hypot(gx, gy)))
    assert np.allclose(interior(s), expected, atol=1e-10)


def test_horn_uses_per_row_dx():
    dx = np.linspace(20, 40, 15)
    z = np.tile(np.arange(10) * 5.0, (15, 1))   # +5 m per column
    s = tf.horn_slope(z, dx, 30.0)
    expected = np.degrees(np.arctan(5.0 / dx))
    assert np.allclose(s[1:-1, 5], expected[1:-1])


def test_horn_rejects_nonpositive_spacing():
    with pytest.raises(ValueError):
        tf.horn_slope(np.zeros((5, 5)), 0, 30)


# ---------------------------------------------------------------- on rasters
def test_flat_tile_zero_slope(tmp_path):
    layer = tf.slope_deg(load(tmp_path, np.full((N, N), 1234)))
    assert layer.shape == (N, N)
    assert np.all(interior(layer.values) == 0)
    assert layer.invalid_mask.sum() == 4 * N - 4        # only the border


def test_east_gradient_matches_latitude_dependent_spacing(tmp_path):
    k = 10                                               # +10 m per column
    z = np.tile(np.arange(N) * k, (N, 1))              # max 12000 m, fits int16
    r = load(tmp_path, z)
    s = tf.slope_deg(r).values
    lats = r.lat_of_row(np.arange(N))
    _, mlon = series_m_per_deg(lats)
    expected = np.degrees(np.arctan(k / (mlon * PIX)))
    assert np.allclose(s[1:-1, 600], expected[1:-1], atol=1e-3)
    # hard number at the centre row (lat -23.5): dx = 102141/1200 = 85.12 m
    assert s[600, 600] == pytest.approx(np.degrees(np.arctan(10 / 85.1175)), abs=1e-3)
    # east-west spacing shrinks poleward, so slope is larger at -24 than at -23
    assert s[N - 2, 600] > s[1, 600]


def test_north_gradient(tmp_path):
    k = 15                                               # +15 m per row northward
    z = np.tile(((N - 1 - np.arange(N)) * k)[:, None], (1, N))
    r = load(tmp_path, z)
    s = tf.slope_deg(r).values
    mlat, _ = series_m_per_deg(-23.5)
    assert s[600, 300] == pytest.approx(np.degrees(np.arctan(k / (mlat * PIX))), abs=1e-3)
    assert np.allclose(interior(s), s[600, 300], atol=0.01)   # ~uniform N-S


def test_diagonal_gradient(tmp_path):
    r_, c_ = np.mgrid[0:N, 0:N]
    z = c_ * 4 + (N - 1 - r_) * 6
    r = load(tmp_path, z)
    s = tf.slope_deg(r).values
    mlat, mlon = series_m_per_deg(-23.5)
    gx, gy = 4 / (mlon * PIX), 6 / (mlat * PIX)
    assert s[600, 600] == pytest.approx(np.degrees(np.arctan(np.hypot(gx, gy))), abs=1e-3)


def test_slope_nodata_propagates(tmp_path):
    z = np.full((N, N), 800)
    z[600, 600] = -32768
    layer = tf.slope_deg(load(tmp_path, z))
    s = layer.values
    assert np.all(np.isnan(s[599:602, 599:602]))         # whole 3x3 neighbourhood
    assert s[597, 600] == 0 and s[600, 603] == 0         # outside it: valid
    assert not np.any(s == -32768)


def test_slope_metadata_labels(tmp_path):
    layer = tf.slope_deg(load(tmp_path, np.full((N, N), 1)))
    assert "SRTMGL1" in layer.derived_from and "S24W070.hgt" in layer.derived_from
    assert "Horn" in layer.method and layer.units == "deg"
    assert layer.params["window_samples"] == 3
    assert "lander-leg" in layer.scale_note
    assert layer.summary()["derived from"] == layer.derived_from


# ---------------------------------------------------------------- roughness
def test_window_std_flat_and_borders():
    r = tf.window_std(np.full((9, 9), 3000.0), 3)
    assert np.all(interior(r) == 0)
    assert np.all(np.isnan(r[0])) and np.all(np.isnan(r[:, -1]))
    r5 = tf.window_std(np.full((9, 9), 3000.0), 5)
    assert np.all(np.isnan(r5[:2])) and np.all(r5[2:-2, 2:-2] == 0)


def test_window_std_matches_numpy_reference():
    rng = np.random.default_rng(1)
    z = 3000 + rng.normal(0, 5, (30, 30))
    r = tf.window_std(z, 5)
    for (i, j) in [(2, 2), (10, 17), (27, 27)]:
        assert r[i, j] == pytest.approx(np.std(z[i - 2:i + 3, j - 2:j + 3]), abs=1e-9)


def test_window_std_plane_and_checkerboard():
    k = 7.0
    plane = np.tile(np.arange(12) * k, (12, 1))
    assert np.allclose(interior(tf.window_std(plane, 3)), k * np.sqrt(2 / 3))
    stripes = np.tile((np.arange(12) % 2) * 10.0, (12, 1))  # columns 0,10,0,...
    assert np.allclose(interior(tf.window_std(stripes, 3)), 10 * np.sqrt(2 / 9))


def test_window_std_rejects_bad_window():
    for w in (1, 2, 4):
        with pytest.raises(ValueError):
            tf.window_std(np.zeros((5, 5)), w)


def test_roughness_on_tile(tmp_path):
    z = np.full((N, N), 2000)
    z[600, 600] = -32768
    layer = tf.roughness(load(tmp_path, z), window=5)
    v = layer.values
    assert layer.shape == (N, N) and layer.units == "m"
    assert np.all(np.isnan(v[598:603, 598:603]))            # 5x5 around NoData
    assert v[597, 600] == 0 and v[600, 603] == 0
    assert np.all(np.isnan(v[:2])) and np.all(np.isnan(v[:, -2:]))
    assert not np.any(v == -32768)
    assert "SRTMGL1" in layer.derived_from and "5x5" in layer.method
    p = layer.params
    assert p["window_samples"] == 5
    assert p["window_m_east_west_centre_row"] == pytest.approx(5 * 85.12, abs=0.2)
    assert p["window_m_north_south_centre_row"] == pytest.approx(5 * 92.29, abs=0.2)
