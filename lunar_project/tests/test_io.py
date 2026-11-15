import os

import numpy as np
import pytest

from helpers import write_pgda_like_tiff
from lunarmatch.core.geotiff_lite import file_reader, http_reader, read_info, read_window
from lunarmatch.core.http import HttpClient


@pytest.mark.parametrize("tile", [None, (64, 64)])
def test_geotiff_lite_reads_exact_windows(tmp_path, tile):
    rng = np.random.default_rng(0)
    data = rng.normal(size=(300, 260)).astype("float32")
    data[5, 7] = np.nan
    p = tmp_path / "t.tif"
    write_pgda_like_tiff(p, data, x0=-19000, y0=-4000, tile=tile)
    info = read_info(file_reader(p))
    assert (info.width, info.height) == (260, 300)
    assert info.tiled == bool(tile)
    assert info.geotransform == (-19000, 5.0, 0.0, -4000, 0.0, -5.0)
    assert np.isnan(info.nodata)
    assert info.geokeys[1025] == 1
    w = read_window(file_reader(p), info, 10, 77, 33, 200)
    np.testing.assert_array_equal(w, data[10:77, 33:200])
    w = read_window(file_reader(p), info, 0, 300, 0, 260)
    np.testing.assert_array_equal(np.isnan(w), np.isnan(data))


def test_window_over_http_uses_range_requests(range_server, tmp_path):
    base, www = range_server
    data = np.arange(400 * 400, dtype="float32").reshape(400, 400)
    write_pgda_like_tiff(www / "x.tif", data, 0, 0)
    from conftest import RangeHandler

    reader = http_reader(f"{base}/x.tif", HttpClient(retries=1))
    info = read_info(reader)
    RangeHandler.requests_seen.clear()
    w = read_window(reader, info, 100, 140, 50, 90)
    np.testing.assert_array_equal(w, data[100:140, 50:90])
    # contiguous strips -> one merged Range request, far smaller than the file
    assert len(RangeHandler.requests_seen) == 1
    rng = RangeHandler.requests_seen[0][1]
    a, b = map(int, rng.split("=")[1].split("-"))
    assert (b - a + 1) < 0.15 * os.path.getsize(www / "x.tif")


def test_download_resume_and_cache(range_server, tmp_path):
    base, www = range_server
    payload = os.urandom(300_000)
    (www / "big.bin").write_bytes(payload)
    dest = tmp_path / "dl" / "big.bin"
    dest.parent.mkdir()
    # simulate an interrupted earlier download
    (dest.parent / "big.bin.part").write_bytes(payload[:120_000])
    from conftest import RangeHandler

    RangeHandler.requests_seen.clear()
    c = HttpClient(retries=1)
    out = c.download(f"{base}/big.bin", dest, progress=False)
    assert out.read_bytes() == payload
    assert RangeHandler.requests_seen[0][1] == "bytes=120000-"  # resumed, not restarted
    RangeHandler.requests_seen.clear()
    c.download(f"{base}/big.bin", dest, progress=False, expected_size=len(payload))
    assert RangeHandler.requests_seen == []  # reused from disk


def test_http_errors_raise(range_server):
    import requests

    base, _ = range_server
    with pytest.raises(requests.HTTPError):
        HttpClient(retries=0).get(f"{base}/missing.tif")
