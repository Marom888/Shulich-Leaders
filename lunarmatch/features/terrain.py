"""Deterministic terrain derivatives computed from an elevation raster.

These are *derived products*, not scores. Every output has the same shape as
the input raster, keeps NaN wherever the result is undefined (NoData in the
window, or a raster edge where the window is incomplete), and records its
method and parameters.

Scale limitation
----------------
SRTMGL1 posts are 1 arc-second apart, which is about 30 m north-south and
about 28 m east-west at 23.5 S. A 3x3 Horn slope therefore describes terrain
over roughly 60-90 m. A roughness window of N samples spans roughly N x 30 m.
These values do **not** describe terrain at lander-leg or footpad scale
(metres or less). Boulders, small craters and decimetre relief cannot be
resolved, and SRTM radar measurements also smooth over the fine relief
inside each sample.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from lunarmatch.data.raster_loader import ElevationRaster
from lunarmatch.geodesy import row_spacing_m

DEFAULT_DATASET = "SRTMGL1 v003"

SCALE_NOTE = ("SRTM ~30 m sampling: describes terrain at >=30-90 m scale, "
              "not lander-leg (metre) scale")


@dataclass
class DerivedLayer:
    """A per-sample derived product aligned with its source raster."""

    values: np.ndarray            # float64, same shape as source; NaN = undefined
    name: str                     # e.g. "slope"
    units: str                    # e.g. "deg"
    method: str                   # human-readable method description
    params: dict = field(default_factory=dict)
    derived_from: str = ""        # e.g. "SRTMGL1 v003 (S24W070.hgt)"
    scale_note: str = SCALE_NOTE

    @property
    def shape(self) -> tuple[int, int]:
        return self.values.shape

    @property
    def invalid_mask(self) -> np.ndarray:
        return ~np.isfinite(self.values)

    @property
    def label(self) -> str:
        return f"{self.name} ({self.units}), {self.method}, derived from {self.derived_from}"

    def summary(self) -> dict:
        v = self.values[np.isfinite(self.values)]
        return {
            "layer": self.name,
            "units": self.units,
            "derived from": self.derived_from,
            "method": self.method,
            "params": self.params,
            "shape": self.shape,
            "undefined (NaN) cells": int(self.invalid_mask.sum()),
            "min": float(v.min()) if v.size else None,
            "median": float(np.median(v)) if v.size else None,
            "max": float(v.max()) if v.size else None,
            "scale note": self.scale_note,
        }


def _derived_from(raster: ElevationRaster, dataset: str) -> str:
    return f"{dataset} ({raster.source.name})"


def _spacing(raster: ElevationRaster):
    """Per-row metric spacing (dx east-west, dy north-south) in metres."""
    rows = np.arange(raster.shape[0])
    lats = raster.lat_of_row(rows)
    return row_spacing_m(lats, raster.transform.e, raster.transform.a)


# --------------------------------------------------------------------------
# Slope
# --------------------------------------------------------------------------
def horn_slope(z: np.ndarray, dx, dy) -> np.ndarray:
    """Slope in degrees using Horn (1981) 3x3 finite differences.

    For a window::

        a b c
        d e f
        g h i

    dz/dx = ((c + 2f + i) - (a + 2d + g)) / (8 dx)
    dz/dy = ((g + 2h + i) - (a + 2b + c)) / (8 dy)
    slope = atan(sqrt(dz/dx^2 + dz/dy^2))

    ``dx`` and ``dy`` are metric spacings, either scalars or one value per
    row. The centre row's spacing is used for its whole window (the change
    across three rows is about 1e-5 relative). The result is NaN on the
    1-cell border, wherever any of the 9 cells is NaN, and where the centre
    cell is NaN.
    """
    z = np.asarray(z, dtype=np.float64)
    nr, nc = z.shape
    dx = np.broadcast_to(np.asarray(dx, dtype=np.float64), (nr,))[:, None]
    dy = np.broadcast_to(np.asarray(dy, dtype=np.float64), (nr,))[:, None]
    if np.any(dx <= 0) or np.any(dy <= 0):
        raise ValueError("spacing must be positive metres")

    p = np.pad(z, 1, mode="constant", constant_values=np.nan)
    a, b, c = p[:-2, :-2], p[:-2, 1:-1], p[:-2, 2:]
    d, f = p[1:-1, :-2], p[1:-1, 2:]
    g, h, i = p[2:, :-2], p[2:, 1:-1], p[2:, 2:]

    gx = ((c + 2 * f + i) - (a + 2 * d + g)) / (8 * dx)
    gy = ((g + 2 * h + i) - (a + 2 * b + c)) / (8 * dy)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    slope[np.isnan(z)] = np.nan
    return slope


def slope_deg(raster: ElevationRaster, dataset: str = DEFAULT_DATASET) -> DerivedLayer:
    """Slope (degrees) of an elevation raster, Horn 3x3, true metric spacing.

    The east-west spacing for each row is the WGS84 prime-vertical scale at
    that row's latitude times the longitude step. The north-south spacing
    uses the meridional radius. At 23.5 S on SRTMGL1 this is about
    28.4 m x 30.8 m, so each 3x3 window spans about 85 m x 92 m. See the
    module docstring for the scale limitation.
    """
    dx, dy = _spacing(raster)
    vals = horn_slope(raster.as_float_nan(), dx, dy)
    mid = raster.shape[0] // 2
    return DerivedLayer(
        values=vals, name="slope", units="deg",
        method="Horn 3x3, WGS84 per-row metric spacing",
        params={"window_samples": 3,
                "dx_m_centre_row": round(float(dx[mid]), 3),
                "dy_m_centre_row": round(float(dy[mid]), 3),
                "edge_cells": "NaN", "nodata": "NaN-propagating"},
        derived_from=_derived_from(raster, dataset),
    )


# --------------------------------------------------------------------------
# Roughness
# --------------------------------------------------------------------------
def window_std(z: np.ndarray, window: int = 3) -> np.ndarray:
    """Population standard deviation (ddof=0) of ``z`` in a centred window.

    ``window`` must be an odd integer >= 3 (samples per side). The result
    is NaN where the window is incomplete (border of width window//2) or
    contains any NaN. It is computed from deviations relative to the centre
    sample, which avoids numerical cancellation at high elevations.
    """
    if window < 3 or window % 2 == 0:
        raise ValueError("window must be an odd integer >= 3")
    z = np.asarray(z, dtype=np.float64)
    h = window // 2
    p = np.pad(z, h, mode="constant", constant_values=np.nan)
    nr, nc = z.shape
    s = np.zeros_like(z)
    s2 = np.zeros_like(z)
    for dr in range(window):
        for dc in range(window):
            d = p[dr:dr + nr, dc:dc + nc] - z
            s += d
            s2 += d * d
    n = window * window
    var = s2 / n - (s / n) ** 2
    np.maximum(var, 0, out=var, where=np.isfinite(var))
    return np.sqrt(var)


def roughness(raster: ElevationRaster, window: int = 3,
              dataset: str = DEFAULT_DATASET) -> DerivedLayer:
    """Roughness = standard deviation of elevation (m) in a window x window window.

    Definition: the population std (ddof=0) of the raw elevation samples in a
    centred ``window`` x ``window`` neighbourhood. The values are **not
    detrended**, so a uniform slope contributes too. On a plane rising k
    metres per sample along one axis, a 3x3 window gives k*sqrt(2/3).

    Window size: ``window`` samples per side. On SRTMGL1 at 23.5 S that is
    about ``window`` x 28.4 m (east-west) by ``window`` x 30.8 m
    (north-south): 3 samples is about 85 m x 92 m, 5 samples about 142 m x
    154 m. The exact metres for the tile's centre row are stored in
    ``params``. See the module docstring: this is not lander-leg-scale
    roughness.
    """
    dx, dy = _spacing(raster)
    mid = raster.shape[0] // 2
    vals = window_std(raster.as_float_nan(), window)
    return DerivedLayer(
        values=vals, name="roughness", units="m",
        method=f"std of elevation in {window}x{window} window (not detrended)",
        params={"window_samples": window,
                "window_m_east_west_centre_row": round(float(window * dx[mid]), 1),
                "window_m_north_south_centre_row": round(float(window * dy[mid]), 1),
                "ddof": 0, "edge_cells": "NaN", "nodata": "NaN-propagating"},
        derived_from=_derived_from(raster, dataset),
    )
