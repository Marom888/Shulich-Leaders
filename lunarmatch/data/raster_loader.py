"""Load SRTM HGT elevation rasters and derive geographic coordinates.

Conventions
-----------
* Row 0 is the northernmost sample row; column 0 is the westernmost.
* HGT samples are *points* (pixel-is-point). GDAL expresses them with an
  area-style transform whose cell edges sit half a cell outside the sample
  posts, so we report two extents:
    - ``footprint``: the rasterio bounds (cell edges), e.g. -70.000139 ...
    - ``sample_extent``: first/last sample centres, e.g. exactly -70 ... -69
* NoData (-32768 for SRTM) is kept as a boolean mask. Elevation values are
  never altered; the original int16 array is preserved as read.
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from lunarmatch.config import EXTRACT_DIR

SRTM_NODATA = -32768


# --------------------------------------------------------------------------
# Locating / extracting
# --------------------------------------------------------------------------
def extract_hgt(zip_path: Path, dest: Path = EXTRACT_DIR) -> Path:
    """Extract the single ``.hgt`` member of an SRTM ``.hgt.zip`` archive.

    Only the member's base name is used (no paths from the archive are
    trusted). Re-extraction is skipped if an identical-size file exists.
    """
    zip_path = Path(zip_path)
    if not zip_path.is_file():
        raise FileNotFoundError(f"Archive not found: {zip_path}")
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as e:
        raise ValueError(f"Not a valid zip archive: {zip_path}") from e

    with zf:
        members = [m for m in zf.infolist()
                   if not m.is_dir() and m.filename.lower().endswith(".hgt")]
        if len(members) != 1:
            raise ValueError(
                f"Expected exactly one .hgt in {zip_path.name}, found {len(members)}")
        member = members[0]
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        out = dest / Path(member.filename).name
        if out.is_file() and out.stat().st_size == member.file_size:
            return out
        with zf.open(member) as src, open(out, "wb") as dst:
            while chunk := src.read(1 << 20):
                dst.write(chunk)
    return out


def resolve_hgt(path: Path, extract_dir: Path = EXTRACT_DIR) -> Path:
    """Return a readable ``.hgt`` path from either a ``.hgt.zip`` or ``.hgt``."""
    path = Path(path)
    if path.suffix.lower() == ".zip":
        return extract_hgt(path, extract_dir)
    if path.suffix.lower() == ".hgt" and path.is_file():
        return path
    raise FileNotFoundError(f"No .hgt or .hgt.zip at: {path}")


# --------------------------------------------------------------------------
# Raster container
# --------------------------------------------------------------------------
@dataclass
class ElevationRaster:
    """An elevation raster exactly as stored in the source file."""

    data: np.ndarray                 # original values, dtype as stored (int16)
    nodata_mask: np.ndarray          # True where the sample is missing
    nodata_value: float | None
    crs: str
    transform: object                # affine.Affine (cell-edge convention)
    footprint: tuple[float, float, float, float]      # W, S, E, N (cell edges)
    sample_extent: tuple[float, float, float, float]  # W, S, E, N (centres)
    area_or_point: str | None
    source: Path
    driver: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def shape(self) -> tuple[int, int]:
        return self.data.shape

    @property
    def nodata_count(self) -> int:
        return int(self.nodata_mask.sum())

    @property
    def valid_min(self) -> float | None:
        v = self.data[~self.nodata_mask]
        return float(v.min()) if v.size else None

    @property
    def valid_max(self) -> float | None:
        v = self.data[~self.nodata_mask]
        return float(v.max()) if v.size else None

    def lon_of_col(self, cols) -> np.ndarray:
        """Longitude of sample centres for column index/indices."""
        cols = np.asarray(cols, dtype=float)
        return self.transform.c + (cols + 0.5) * self.transform.a

    def lat_of_row(self, rows) -> np.ndarray:
        """Latitude of sample centres for row index/indices (decreasing)."""
        rows = np.asarray(rows, dtype=float)
        return self.transform.f + (rows + 0.5) * self.transform.e

    def as_float_nan(self) -> np.ndarray:
        """Float copy with NoData as NaN (never zero)."""
        out = self.data.astype(np.float64)
        out[self.nodata_mask] = np.nan
        return out

    def summary(self) -> dict:
        return {
            "source": str(self.source),
            "driver": self.driver,
            "crs": self.crs,
            "shape (rows, cols)": self.shape,
            "dtype": str(self.data.dtype),
            "AREA_OR_POINT": self.area_or_point,
            "pixel size (deg)": (self.transform.a, -self.transform.e),
            "footprint W,S,E,N (cell edges)": self.footprint,
            "sample-centre extent W,S,E,N": self.sample_extent,
            "nodata value": self.nodata_value,
            "nodata count": self.nodata_count,
            "valid min (m)": self.valid_min,
            "valid max (m)": self.valid_max,
        }


def load_raster(path: Path, extract_dir: Path = EXTRACT_DIR) -> ElevationRaster:
    """Open a ``.hgt`` / ``.hgt.zip`` with rasterio and return its contents."""
    import rasterio

    hgt = resolve_hgt(path, extract_dir)
    with rasterio.open(hgt) as ds:
        if ds.count < 1:
            raise ValueError(f"{hgt} contains no bands")
        data = ds.read(1)
        nodata = ds.nodata
        crs = ds.crs.to_string() if ds.crs else "UNKNOWN"
        transform = ds.transform
        b = ds.bounds
        aop = ds.tags().get("AREA_OR_POINT")
        driver = ds.driver

    if transform.b != 0 or transform.d != 0:
        raise ValueError("Rotated rasters are not supported")
    if transform.a <= 0 or transform.e >= 0:
        raise ValueError("Expected north-up raster (positive x step, negative y step)")

    nd = SRTM_NODATA if nodata is None else nodata
    mask = data == nd

    rows, cols = data.shape
    r = ElevationRaster(
        data=data,
        nodata_mask=mask,
        nodata_value=nd,
        crs=crs,
        transform=transform,
        footprint=(b.left, b.bottom, b.right, b.top),
        sample_extent=(0.0, 0.0, 0.0, 0.0),
        area_or_point=aop,
        source=hgt,
        driver=driver,
    )
    w, e = r.lon_of_col([0, cols - 1])
    n, s = r.lat_of_row([0, rows - 1])
    r.sample_extent = (float(w), float(s), float(e), float(n))
    return r


# --------------------------------------------------------------------------
# Downsampling (stride decimation: every output value is an original sample)
# --------------------------------------------------------------------------
@dataclass
class SampledGrid:
    """A strided subset of an :class:`ElevationRaster`.

    ``values[i, j] == raster.data[rows[i], cols[j]]`` for every valid cell;
    NoData cells are NaN. No interpolation or smoothing is applied.
    """

    values: np.ndarray        # float64, NaN for NoData
    rows: np.ndarray          # original row indices
    cols: np.ndarray          # original column indices
    lats: np.ndarray          # sample-centre latitude per sampled row
    lons: np.ndarray          # sample-centre longitude per sampled column
    step: int
    source_shape: tuple[int, int]

    @property
    def shape(self) -> tuple[int, int]:
        return self.values.shape


def stride_indices(n: int, step: int) -> np.ndarray:
    """0, step, 2*step, ... always including the last index n-1."""
    idx = np.arange(0, n, step)
    if idx[-1] != n - 1:
        idx = np.append(idx, n - 1)
    return idx


def choose_step(shape: tuple[int, int], max_side: int) -> int:
    """Smallest integer stride keeping both sides at or below ``max_side``."""
    return max(1, int(np.ceil((max(shape) - 1) / max(max_side - 1, 1))))


def downsample(raster: ElevationRaster, step: int) -> SampledGrid:
    """Decimate by taking every ``step``-th original sample (plus the last)."""
    if step < 1:
        raise ValueError("step must be >= 1")
    nrows, ncols = raster.shape
    rows = stride_indices(nrows, step)
    cols = stride_indices(ncols, step)
    sub = raster.data[np.ix_(rows, cols)].astype(np.float64)
    sub[raster.nodata_mask[np.ix_(rows, cols)]] = np.nan
    return SampledGrid(
        values=sub,
        rows=rows,
        cols=cols,
        lats=raster.lat_of_row(rows),
        lons=raster.lon_of_col(cols),
        step=step,
        source_shape=raster.shape,
    )


def sample_layer(values: np.ndarray, like: SampledGrid) -> SampledGrid:
    """Stride-sample a full-resolution array on the same rows/cols as ``like``.

    Used to display a derived layer (for example slope) that was computed at
    full resolution. Values are taken as-is; nothing is recomputed on the
    decimated grid.
    """
    values = np.asarray(values)
    if values.shape != like.source_shape:
        raise ValueError(f"shape {values.shape} != source {like.source_shape}")
    return SampledGrid(
        values=values[np.ix_(like.rows, like.cols)].astype(np.float64),
        rows=like.rows, cols=like.cols, lats=like.lats, lons=like.lons,
        step=like.step, source_shape=like.source_shape,
    )


def verify_samples(raster: ElevationRaster, grid: SampledGrid,
                   n: int = 20, seed: int = 0) -> list[dict]:
    """Compare random sampled cells against the original raster.

    Returns a list of check records; raises AssertionError on any mismatch.
    This verifies processing consistency only, not NASA measurement accuracy.
    """
    rng = np.random.default_rng(seed)
    ii = rng.integers(0, grid.shape[0], n)
    jj = rng.integers(0, grid.shape[1], n)
    # Always include the four corners.
    ii = np.concatenate([[0, 0, -1, -1], ii]) % grid.shape[0]
    jj = np.concatenate([[0, -1, 0, -1], jj]) % grid.shape[1]
    out = []
    for i, j in zip(ii, jj):
        r, c = int(grid.rows[i]), int(grid.cols[j])
        orig = raster.data[r, c]
        plotted = grid.values[i, j]
        missing = bool(raster.nodata_mask[r, c])
        ok = np.isnan(plotted) if missing else float(orig) == plotted
        if not ok:
            raise AssertionError(f"Mismatch at row {r}, col {c}: {orig} vs {plotted}")
        out.append({"row": r, "col": c, "lat": float(grid.lats[i]),
                    "lon": float(grid.lons[j]), "original": int(orig),
                    "plotted": None if missing else plotted, "nodata": missing})
    return out
