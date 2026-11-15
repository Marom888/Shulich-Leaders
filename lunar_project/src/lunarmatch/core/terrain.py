"""Terrain derivatives computed *here* from a DEM.

Everything returned from this module is labelled ``Evidence.DERIVED_HERE``
by the callers, so it is never confused with official products such as
the PGDA slope map.

Conventions: ``z`` is a 2-D array on a regular grid with spacing
``dx`` (columns) and ``dy`` (rows) in metres.  NaN marks no data and
propagates (no gap filling is done).
"""
from __future__ import annotations

import numpy as np


def _pad_nan(z: np.ndarray, n: int = 1) -> np.ndarray:
    return np.pad(z.astype("float64"), n, mode="constant", constant_values=np.nan)


def slope_horn(z: np.ndarray, dx: float, dy: float) -> np.ndarray:
    """Slope in degrees using Horn's (1981) 3x3 finite differences.

    Edge pixels (no full 3x3 neighbourhood) are NaN.
    """
    p = _pad_nan(z)
    a, b, c = p[:-2, :-2], p[:-2, 1:-1], p[:-2, 2:]
    d, f = p[1:-1, :-2], p[1:-1, 2:]
    g, h, i = p[2:, :-2], p[2:, 1:-1], p[2:, 2:]
    dzdx = ((c + 2 * f + i) - (a + 2 * d + g)) / (8.0 * dx)
    dzdy = ((g + 2 * h + i) - (a + 2 * b + c)) / (8.0 * dy)
    return np.degrees(np.arctan(np.hypot(dzdx, dzdy)))


def _windows(z: np.ndarray, size: int):
    if size < 3 or size % 2 == 0:
        raise ValueError("window size must be an odd integer >= 3")
    from numpy.lib.stride_tricks import sliding_window_view

    r = size // 2
    p = _pad_nan(z, r)
    return sliding_window_view(p, (size, size))


def local_relief(z: np.ndarray, window_px: int) -> np.ndarray:
    """max - min elevation inside a square window (metres).  NaN if any cell is NaN."""
    w = _windows(z, window_px)
    out = w.max(axis=(-1, -2)) - w.min(axis=(-1, -2))
    return out


def detrended_rms_roughness(z: np.ndarray, window_px: int, dx: float, dy: float) -> np.ndarray:
    """RMS of height residuals after removing a best-fit plane in each window (metres).

    Implements the workbook recipe for F_ROUGH ("RMS of local height residual
    after planar detrending, fixed physical window in metres").
    Windows containing NaN return NaN.
    """
    w = _windows(z, window_px)  # (H, W, n, n)
    n = window_px
    yy, xx = np.mgrid[0:n, 0:n].astype("float64")
    xx = (xx - xx.mean()) * dx
    yy = (yy - yy.mean()) * dy
    A = np.stack([xx.ravel(), yy.ravel(), np.ones(n * n)], axis=1)  # (n*n, 3)
    pinv = np.linalg.pinv(A)  # (3, n*n)
    flat = w.reshape(w.shape[0], w.shape[1], n * n)
    coef = flat @ pinv.T  # (H, W, 3)
    fit = coef @ A.T  # (H, W, n*n)
    resid = flat - fit
    return np.sqrt(np.mean(resid ** 2, axis=-1))


def window_px_for(length_m: float, pixel_m: float) -> int:
    """Smallest odd window (>=3 px) covering ``length_m`` metres."""
    n = int(np.ceil(length_m / pixel_m))
    n = max(3, n)
    return n if n % 2 == 1 else n + 1
