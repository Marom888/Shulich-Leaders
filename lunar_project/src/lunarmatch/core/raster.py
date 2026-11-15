"""Raster containers, alignment checks and GeoTIFF I/O.

``Layer`` is a numpy array plus everything needed to interpret it:
geotransform, CRS, nodata, units, and an :class:`Evidence` label.
``LayerStack`` holds several layers that are guaranteed to share one grid.

Remote Cloud-Optimized GeoTIFFs (Sentinel-2, NAIP, WorldCover, 3DEP,
NASADEM-COG, SoilGrids VRT, ShadowCam COGs ...) are read with rasterio /
GDAL ``/vsicurl/`` which issues HTTP range requests for only the tiles that
intersect the window.  rasterio is imported lazily so the rest of the
package works without GDAL.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from .evidence import Evidence

GeoTransform = tuple[float, float, float, float, float, float]


@dataclass
class Layer:
    name: str
    data: np.ndarray                     # 2-D float array, NaN = no data
    transform: GeoTransform              # GDAL order (x0, dx, 0, y0, 0, dy)
    crs: str                             # PROJ string, WKT or "EPSG:xxxx"
    units: str
    evidence: Evidence
    dataset_id: str
    description: str = ""
    source_url: str = ""
    nodata_original: Optional[float] = None
    extra: dict = field(default_factory=dict)

    @property
    def shape(self):
        return self.data.shape

    @property
    def resolution(self) -> tuple[float, float]:
        return abs(self.transform[1]), abs(self.transform[5])

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        x0, dx, _, y0, _, dy = self.transform
        h, w = self.data.shape
        xs, ys = (x0, x0 + dx * w), (y0, y0 + dy * h)
        return (min(xs), min(ys), max(xs), max(ys))

    def pixel_centers(self) -> tuple[np.ndarray, np.ndarray]:
        """1-D arrays of pixel-centre x (columns) and y (rows) coordinates."""
        x0, dx, _, y0, _, dy = self.transform
        h, w = self.data.shape
        return x0 + dx * (np.arange(w) + 0.5), y0 + dy * (np.arange(h) + 0.5)

    def stats(self) -> dict:
        v = self.data[np.isfinite(self.data)]
        n = self.data.size
        if v.size == 0:
            return {"count": 0, "nodata_fraction": 1.0}
        return {
            "min": float(v.min()), "max": float(v.max()), "mean": float(v.mean()),
            "std": float(v.std()), "p50": float(np.percentile(v, 50)), "p90": float(np.percentile(v, 90)),
            "count": int(v.size), "nodata_fraction": float(1 - v.size / n),
        }

    def metadata(self) -> dict:
        return {
            "layer": self.name, "dataset_id": self.dataset_id, "units": self.units,
            "evidence": self.evidence.value, "crs": self.crs, "transform": list(self.transform),
            "shape": list(self.data.shape), "resolution": list(self.resolution), "bounds": list(self.bounds),
            "source_url": self.source_url, "description": self.description,
            "nodata_original": self.nodata_original, **self.extra,
        }


def same_grid(a: Layer, b: Layer, tol: float = 1e-6) -> bool:
    return (a.data.shape == b.data.shape and a.crs == b.crs
            and np.allclose(a.transform, b.transform, atol=tol))


class LayerStack(dict):
    """dict[name -> Layer] whose members are verified to share one grid."""

    def add(self, layer: Layer):
        if self:
            ref = next(iter(self.values()))
            if not same_grid(ref, layer):
                raise ValueError(
                    f"layer '{layer.name}' is not aligned with '{ref.name}' "
                    f"({layer.shape} {layer.transform} vs {ref.shape} {ref.transform}); resample first"
                )
        self[layer.name] = layer

    def to_xarray(self):
        """Return an ``xarray.Dataset`` (requires xarray)."""
        import xarray as xr  # lazy

        if not self:
            return xr.Dataset()
        ref = next(iter(self.values()))
        xs, ys = ref.pixel_centers()
        ds = xr.Dataset(coords={"y": ys, "x": xs})
        for name, lyr in self.items():
            ds[name] = (("y", "x"), lyr.data)
            ds[name].attrs.update({k: (json.dumps(v) if isinstance(v, (list, dict)) else v)
                                   for k, v in lyr.metadata().items() if v is not None})
        ds.attrs["crs"] = ref.crs
        return ds


# ---------------------------------------------------------------- writing
def write_geotiff(layer: Layer, path: os.PathLike, compress: bool = True) -> Path:
    """Write a float32 GeoTIFF (rasterio if available, else tifffile with GeoTIFF tags).

    ``compress=False`` writes an uncompressed file that :mod:`geotiff_lite` can
    read without GDAL (used for raw windows).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.asarray(layer.data, dtype="float32")
    try:
        import rasterio
        from rasterio.crs import CRS
        from rasterio.transform import Affine

        x0, dx, rx, y0, ry, dy = layer.transform
        with rasterio.open(
            path, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1,
            dtype="float32", crs=CRS.from_user_input(layer.crs), transform=Affine(dx, rx, x0, ry, dy, y0),
            nodata=np.nan, tiled=True, blockxsize=256, blockysize=256,
            **({"compress": "deflate"} if compress else {}),
        ) as dst:
            dst.write(arr, 1)
            dst.update_tags(units=layer.units, evidence=layer.evidence.value, dataset_id=layer.dataset_id)
        return path
    except ImportError:
        pass
    import tifffile

    x0, dx, _, y0, _, dy = layer.transform
    extratags = [
        (33550, "d", 3, (abs(dx), abs(dy), 0.0), False),
        (33922, "d", 6, (0.0, 0.0, 0.0, x0, y0, 0.0), False),
        # Minimal GeoKeyDirectory: user-defined projected CRS; the full CRS
        # string is stored in GDAL_METADATA and the .meta.json sidecar.
        (34735, "H", 16, (1, 1, 0, 3, 1024, 0, 1, 1, 1025, 0, 1, 1, 3072, 0, 1, 32767), False),
        (42112, "s", 0, f'<GDALMetadata><Item name="crs">{layer.crs}</Item>'
                        f'<Item name="units">{layer.units}</Item></GDALMetadata>', False),
        (42113, "s", 0, "nan", False),
    ]
    tifffile.imwrite(path, arr, extratags=extratags)
    return path


# ---------------------------------------------------------------- COG reading
def _require_rasterio():
    try:
        import rasterio  # noqa: F401

        return rasterio
    except ImportError as exc:  # pragma: no cover - depends on env
        raise ImportError(
            "rasterio is required to read compressed/remote COG rasters. "
            "Install it with:  pip install rasterio"
        ) from exc


GDAL_HTTP_ENV = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.tiff,.TIF,.vrt,.jp2,.img,.IMG",
    "GDAL_HTTP_MULTIRANGE": "YES",
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "GDAL_HTTP_MAX_RETRY": "5",
    "GDAL_HTTP_RETRY_DELAY": "2",
    "VSI_CACHE": "TRUE",
}


def read_window_lonlat(href: str, bbox_lonlat: tuple[float, float, float, float], *, name: str,
                       units: str, evidence: Evidence, dataset_id: str, band: int = 1,
                       scale: float = 1.0, description: str = "", overview_level: Optional[int] = None) -> Layer:
    """Read the part of a (remote) raster covering a lon/lat bbox (Earth, WGS84).

    Only the intersecting COG tiles are transferred.  The returned layer is in
    the raster's native CRS (no resampling).
    """
    rasterio = _require_rasterio()
    from rasterio.warp import transform_bounds
    from rasterio.windows import from_bounds

    with rasterio.Env(**GDAL_HTTP_ENV):
        kw = {"overview_level": overview_level} if overview_level is not None else {}
        with rasterio.open(href, **kw) as src:
            left, bottom, right, top = transform_bounds("EPSG:4326", src.crs, *bbox_lonlat, densify_pts=21)
            win = from_bounds(left, bottom, right, top, transform=src.transform)
            win = win.round_offsets("floor").round_lengths("ceil")
            win = win.intersection(rasterio.windows.Window(0, 0, src.width, src.height))
            arr = src.read(band, window=win, masked=True).astype("float64")
            data = arr.filled(np.nan) * scale
            t = src.window_transform(win)
            crs = src.crs.to_string()
            nod = src.nodata
    return Layer(
        name=name, data=data, transform=(t.c, t.a, t.b, t.f, t.d, t.e), crs=crs, units=units,
        evidence=evidence, dataset_id=dataset_id, description=description, source_url=href,
        nodata_original=nod,
    )


def read_window_native(href: str, bounds_native: tuple[float, float, float, float], **kw) -> Layer:
    """Same as :func:`read_window_lonlat` but the bbox is already in the raster CRS."""
    rasterio = _require_rasterio()
    from rasterio.windows import from_bounds

    with rasterio.Env(**GDAL_HTTP_ENV):
        with rasterio.open(href) as src:
            win = from_bounds(*bounds_native, transform=src.transform)
            win = win.round_offsets("floor").round_lengths("ceil")
            win = win.intersection(rasterio.windows.Window(0, 0, src.width, src.height))
            arr = src.read(kw.pop("band", 1), window=win, masked=True).astype("float64")
            t = src.window_transform(win)
            scale = kw.pop("scale", 1.0)
            return Layer(data=arr.filled(np.nan) * scale, transform=(t.c, t.a, t.b, t.f, t.d, t.e),
                         crs=src.crs.to_string() if src.crs else "", source_url=href,
                         nodata_original=src.nodata, **kw)
