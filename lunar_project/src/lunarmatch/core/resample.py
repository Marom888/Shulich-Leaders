"""Scale harmonisation (workbook CAP_04): bring layers to a common ground sample distance.

Rule from the workbook Pipeline step 05: "No upsample fake resolution;
compare only resolvable features".  Therefore only *down*-sampling by
integer block averaging is offered; asking for a finer GSD than the native
one raises an error.
"""
from __future__ import annotations

import numpy as np

from .evidence import Evidence
from .raster import Layer


class UpsamplingRefused(ValueError):
    pass


def block_mean(a: np.ndarray, fy: int, fx: int, min_valid: float = 0.5) -> np.ndarray:
    """Mean over non-overlapping fy x fx blocks; NaN where < min_valid of the block is valid."""
    h, w = (a.shape[0] // fy) * fy, (a.shape[1] // fx) * fx
    b = a[:h, :w].reshape(h // fy, fy, w // fx, fx)
    valid = np.isfinite(b)
    cnt = valid.sum(axis=(1, 3))
    s = np.where(valid, b, 0.0).sum(axis=(1, 3))
    out = np.full(cnt.shape, np.nan)
    ok = cnt >= max(1, int(np.ceil(min_valid * fy * fx)))
    out[ok] = s[ok] / cnt[ok]
    return out


def to_gsd(layer: Layer, target_gsd_m: float, pixel_size_m: tuple[float, float],
           categorical: bool = False) -> Layer:
    """Downsample ``layer`` (native pixel size ``pixel_size_m`` = (dx, dy) metres) to ~target GSD."""
    dx, dy = pixel_size_m
    if target_gsd_m < 0.999 * max(dx, dy):
        raise UpsamplingRefused(f"target {target_gsd_m} m is finer than native {dx:.2f}x{dy:.2f} m")
    fx, fy = max(1, int(round(target_gsd_m / dx))), max(1, int(round(target_gsd_m / dy)))
    if categorical:
        data = layer.data[: (layer.shape[0] // fy) * fy: fy, : (layer.shape[1] // fx) * fx: fx]
    else:
        data = block_mean(layer.data, fy, fx)
    x0, tdx, rx, y0, ry, tdy = layer.transform
    out = Layer(
        name=layer.name, data=data, transform=(x0, tdx * fx, rx, y0, ry, tdy * fy), crs=layer.crs, units=layer.units,
        evidence=layer.evidence if fx == fy == 1 else Evidence.DERIVED_HERE, dataset_id=layer.dataset_id,
        description=f"{layer.description} | block-mean {fy}x{fx} -> ~{dx * fx:.1f}x{dy * fy:.1f} m",
        source_url=layer.source_url, nodata_original=layer.nodata_original,
        extra={**layer.extra, "native_pixel_m": [dx, dy], "block_factor": [fy, fx],
               "effective_gsd_m": [dx * fx, dy * fy], "original_evidence": layer.evidence.value},
    )
    return out
