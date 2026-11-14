import zipfile

import numpy as np
import pytest

from conftest import N, NODATA_CELLS
from lunarmatch.data import raster_loader as rl
from lunarmatch.data.earthdata_client import find_local_tile


# ---------------------------------------------------------------- paths
def test_extract_from_zip(hgt_zip, tmp_path, elevation):
    out = rl.extract_hgt(hgt_zip, tmp_path / "ex")
    assert out.name == "S24W070.hgt"
    assert out.stat().st_size == N * N * 2
    # second call reuses the existing file
    mtime = out.stat().st_mtime_ns
    assert rl.extract_hgt(hgt_zip, tmp_path / "ex").stat().st_mtime_ns == mtime


def test_extract_ignores_paths_inside_archive(tmp_path, hgt_file):
    zp = tmp_path / "evil.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        zf.write(hgt_file, arcname="../../S24W070.hgt")
    out = rl.extract_hgt(zp, tmp_path / "ex")
    assert out.parent == tmp_path / "ex"


def test_bad_zip_and_missing(tmp_path):
    bad = tmp_path / "bad.hgt.zip"
    bad.write_bytes(b"not a zip")
    with pytest.raises(ValueError):
        rl.extract_hgt(bad, tmp_path)
    with pytest.raises(FileNotFoundError):
        rl.resolve_hgt(tmp_path / "nope.hgt")


def test_zip_and_bare_hgt_load_identically(hgt_zip, hgt_file, tmp_path):
    a = rl.load_raster(hgt_zip, tmp_path / "ex")
    b = rl.load_raster(hgt_file)
    assert np.array_equal(a.data, b.data)


def test_find_local_tile_prefers_zip(tmp_path, hgt_file, hgt_zip):
    assert find_local_tile("S24W070", [tmp_path]) == hgt_zip
    hgt_zip.unlink()
    assert find_local_tile("S24W070", [tmp_path]) == hgt_file
    assert find_local_tile("N00E000", [tmp_path]) is None


# ---------------------------------------------------------------- metadata
def test_dimensions_crs_and_extents(hgt_file):
    r = rl.load_raster(hgt_file)
    assert r.shape == (N, N)
    assert r.data.dtype == np.int16
    assert "4326" in r.crs
    half = 0.5 / (N - 1)
    assert r.sample_extent == pytest.approx((-70, -24, -69, -23), abs=1e-9)
    assert r.footprint == pytest.approx(
        (-70 - half, -24 - half, -69 + half, -23 + half), abs=1e-9)


def test_values_match_big_endian_source(hgt_file, elevation):
    r = rl.load_raster(hgt_file)
    assert np.array_equal(r.data, elevation)  # unmodified


# ---------------------------------------------------------------- nodata
def test_nodata_masked_not_zeroed(hgt_file, elevation):
    r = rl.load_raster(hgt_file)
    assert r.nodata_value == -32768
    assert r.nodata_count == len(NODATA_CELLS)
    f = r.as_float_nan()
    for rr, cc in NODATA_CELLS:
        assert r.nodata_mask[rr, cc]
        assert np.isnan(f[rr, cc])
    assert not np.any(f[~r.nodata_mask] == -32768)
    valid = elevation[elevation != -32768]
    assert r.valid_min == valid.min() and r.valid_max == valid.max()


# ---------------------------------------------------------------- orientation
def test_orientation_north_up_east_right(hgt_file):
    r = rl.load_raster(hgt_file)
    lats = r.lat_of_row(np.arange(N))
    lons = r.lon_of_col(np.arange(N))
    assert np.all(np.diff(lats) < 0)          # row 0 is north
    assert np.all(np.diff(lons) > 0)          # col 0 is west
    assert lats[0] == pytest.approx(-23) and lons[0] == pytest.approx(-70)
    # synthetic surface is higher in the north and in the east
    assert r.data[1, 600] > r.data[1199, 600]
    assert r.data[600, 1199] > r.data[600, 1]


# ---------------------------------------------------------------- downsampling
@pytest.mark.parametrize("step", [1, 7, 10, 100, 1200, 5000])
def test_stride_downsample_is_exact_subset(hgt_file, step):
    r = rl.load_raster(hgt_file)
    g = rl.downsample(r, step)
    assert g.rows[0] == 0 and g.rows[-1] == N - 1
    assert g.cols[0] == 0 and g.cols[-1] == N - 1
    sub = r.data[np.ix_(g.rows, g.cols)]
    m = r.nodata_mask[np.ix_(g.rows, g.cols)]
    assert np.array_equal(g.values[~m], sub[~m].astype(float))
    assert np.all(np.isnan(g.values[m]))
    assert np.allclose(g.lats, r.lat_of_row(g.rows))
    assert np.allclose(g.lons, r.lon_of_col(g.cols))
    rl.verify_samples(r, g, n=50)


def test_downsample_keeps_nodata_cell(hgt_file):
    g = rl.downsample(rl.load_raster(hgt_file), 600)   # rows/cols 0,600,1200
    assert np.isnan(g.values[1, 1])                     # (600, 600)
    assert np.isnan(g.values[2, 0])                     # (1200, 0)


def test_choose_step():
    assert rl.choose_step((3601, 3601), 361) == 10
    assert rl.choose_step((100, 100), 500) == 1
    assert rl.stride_indices(3601, 10)[-1] == 3600


def test_verify_samples_detects_tampering(hgt_file):
    r = rl.load_raster(hgt_file)
    g = rl.downsample(r, 10)
    g.values[0, 0] += 1
    with pytest.raises(AssertionError):
        rl.verify_samples(r, g)
