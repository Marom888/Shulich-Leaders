"""Terrain descriptors for physically sized windows (Earth or Moon).

A window is a block of samples sized to a target length in metres using the
patch's body-aware metric spacing, so windows are comparable in physical size
on either body and at any latitude. Descriptors are statistics of existing,
tested engine layers (elevation, Horn slope, 3x3 roughness). They describe
terrain; they are not similarity values.

Data quality: a window whose valid-elevation fraction is below the threshold
gets status "insufficient_data" and no statistics (missing is never zero).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from lunarmatch.features import terrain as tf
from lunarmatch.terrain.patch import Provenance, TerrainPatch

DESCRIPTOR_VERSION = "terrain-descriptors/2"
QUANTILE_LEVELS = list(range(0, 101, 5))        # 21 levels, for distribution comparison

LIMITATIONS = [
    "Descriptors describe terrain at the dataset's sample scale (~30 m for SRTM), "
    "not lander-leg scale.",
    "Roughness is the std of elevation in a 3x3 sample window (not detrended).",
    "Terrain descriptors say nothing about soil mechanics or material composition.",
]

METHODS = {
    "elevation_m": "dataset sample values",
    "slope_deg": "Horn 3x3 with body-aware metric spacing (derived)",
    "roughness_m": "std of elevation in 3x3 samples, not detrended (derived)",
}


@dataclass(frozen=True)
class Window:
    id: str
    tile: str          # coverage unit ID
    row0: int
    row1: int          # exclusive
    col0: int
    col1: int          # exclusive


def _edges(n: int, block: float) -> np.ndarray:
    k = max(1, int(round(n / block)))
    return np.linspace(0, n, k + 1).round().astype(int)


def partition_patch(patch: TerrainPatch, target_m: float, prefix: str | None = None) -> list[Window]:
    """Split a patch into near-equal blocks about ``target_m`` on a side."""
    if target_m <= 0:
        raise ValueError("target_m must be > 0")
    dx, dy = patch.grid.spacing_m()
    mid = len(dx) // 2
    rows = _edges(patch.shape[0], max(1.0, target_m / dy[mid]))
    cols = _edges(patch.shape[1], max(1.0, target_m / dx[mid]))
    km = f"{target_m / 1000:g}"
    pre = prefix or patch.id
    return [Window(f"{pre}-w{km}km-r{i:02d}c{j:02d}", patch.id,
                   int(rows[i]), int(rows[i + 1]), int(cols[j]), int(cols[j + 1]))
            for i in range(len(rows) - 1) for j in range(len(cols) - 1)]


def _pct(values: np.ndarray, qs) -> list[float] | None:
    v = values[np.isfinite(values)]
    if not v.size:
        return None
    return [round(float(x), 3) for x in np.percentile(v, qs)]


def layers(patch: TerrainPatch) -> tuple[np.ndarray, np.ndarray]:
    """Full-resolution slope (deg) and 3x3 roughness (m) for a patch."""
    dx, dy = patch.grid.spacing_m()
    return tf.horn_slope(patch.elevation_m, dx, dy), tf.window_std(patch.elevation_m, 3)


def summarize(z, slope, rough, mask=None) -> dict:
    """Statistics of one sample set (optionally masked to a region)."""
    if mask is not None:
        z, slope, rough = z[mask], slope[mask], rough[mask]
    e = _pct(z, [0, 50, 100])
    s = _pct(slope, QUANTILE_LEVELS)
    r = _pct(rough, QUANTILE_LEVELS)
    return {
        "elevation_m": None if e is None else
        {"min": e[0], "p50": e[1], "max": e[2], "range": round(e[2] - e[0], 3)},
        "slope_deg": None if s is None else
        {"p10": s[2], "p50": s[10], "p90": s[18], "q": s},
        "roughness_m": None if r is None else {"p50": r[10], "p90": r[18], "q": r},
    }


def describe_patch(patch: TerrainPatch, windows: list[Window],
                   min_valid_fraction: float = 0.9) -> list[dict]:
    """Descriptor record per window (deterministic for identical input)."""
    if not 0 < min_valid_fraction <= 1:
        raise ValueError("min_valid_fraction must be in (0, 1]")
    z = patch.elevation_m
    slope, rough = layers(patch)
    dx, dy = patch.grid.spacing_m()
    prov = patch.provenance
    out = []
    for w in windows:
        rs, cs = slice(w.row0, w.row1), slice(w.col0, w.col1)
        zz = z[rs, cs]
        n = zz.size
        valid = float(np.isfinite(zz).sum() / n)
        mid = (w.row0 + w.row1) // 2
        size_ew = float(dx[mid] * (w.col1 - w.col0))
        size_ns = float(dy[mid] * (w.row1 - w.row0))
        rec = {
            "window_id": w.id, "tile": w.tile, "body": patch.body.name,
            "dataset_id": prov.dataset_id, "is_mock": prov.is_mock,
            "rows": [w.row0, w.row1], "cols": [w.col0, w.col1],
            **patch.grid.window_bounds(w.row0, w.row1, w.col0, w.col1),
            "size_m": {"east_west": round(size_ew, 1), "north_south": round(size_ns, 1)},
            "spacing_m": {"east_west": round(float(dx[mid]), 3), "north_south": round(float(dy[mid]), 3)},
            "area_km2": round(size_ew * size_ns / 1e6, 3),
            "n_samples": n, "valid_fraction": round(valid, 4),
        }
        if valid < min_valid_fraction:
            rec.update(status="insufficient_data", elevation_m=None, slope_deg=None, roughness_m=None)
        else:
            rec.update(status="ok", **summarize(zz, slope[rs, cs], rough[rs, cs]))
        out.append(rec)
    return out


# ---------------------------------------------------------------- raster compatibility
def _patch(raster, tile_id: str) -> TerrainPatch:
    return TerrainPatch.from_raster(raster, tile_id, Provenance("SRTMGL1", "NASA SRTMGL1 v003"))


def partition(raster, tile_id: str, target_m: float) -> list[Window]:
    """Raster-based wrapper (Earth geographic) kept for existing callers."""
    return partition_patch(_patch(raster, tile_id), target_m)


def describe(raster, windows: list[Window], min_valid_fraction: float = 0.9) -> list[dict]:
    tile = windows[0].tile if windows else "TILE"
    return describe_patch(_patch(raster, tile), windows, min_valid_fraction)
