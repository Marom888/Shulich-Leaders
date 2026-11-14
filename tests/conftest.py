"""Shared pytest fixtures: synthetic SRTM HGT tiles (offline, no NASA auth)."""
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

N = 1201  # SRTM3 size: smallest square size GDAL's SRTMHGT driver accepts
NODATA_CELLS = [(5, 7), (600, 600), (1200, 0)]


def synthetic_elevation(n: int = N) -> np.ndarray:
    """North (row 0) is high, east (high col) is high; unique-ish values."""
    r = np.arange(n)[:, None]
    c = np.arange(n)[None, :]
    z = (n - 1 - r) * 20 + c          # 0 .. 25200 m, fits int16
    z = z.astype(np.int16)
    for rr, cc in NODATA_CELLS:
        z[rr, cc] = -32768
    return z


def write_hgt(path: Path, z: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    z.astype(">i2").tofile(path)        # HGT = big-endian signed 16-bit
    return path


@pytest.fixture
def elevation():
    return synthetic_elevation()


@pytest.fixture
def hgt_file(tmp_path, elevation):
    return write_hgt(tmp_path / "src" / "S24W070.hgt", elevation)


@pytest.fixture
def hgt_zip(tmp_path, hgt_file):
    zp = tmp_path / "S24W070.SRTMGL1.hgt.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(hgt_file, arcname="S24W070.hgt")
    return zp
