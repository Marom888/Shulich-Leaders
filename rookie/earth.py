"""Summary of the real Earth test tile, computed with the lunarmatch engine.

If the tile is not on disk, the summary says so and contains no numbers.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from lunarmatch.config import ATACAMA_TILE, OUTPUT_DIR
from lunarmatch.data import raster_loader as rl
from lunarmatch.data.earthdata_client import find_local_tile
from lunarmatch.features import terrain as tf

PLOTS = {
    "terrain_2d": ("Elevation map", "terrain_2d.html"),
    "slope_2d": ("Slope map", "slope_2d.html"),
    "terrain_3d": ("3D terrain", "terrain_3d.html"),
}


def _stats(values: np.ndarray) -> dict:
    v = values[np.isfinite(values)]
    if not v.size:
        return {"valid_cells": 0}
    p10, p50, p90 = np.percentile(v, [10, 50, 90])
    return {"valid_cells": int(v.size), "undefined_cells": int(values.size - v.size),
            "min": float(v.min()), "p10": float(p10), "median": float(p50),
            "p90": float(p90), "max": float(v.max())}


def earth_summary(tile_path: Path | None = None, output_dir: Path = OUTPUT_DIR) -> dict:
    tile = tile_path if tile_path is not None else find_local_tile(ATACAMA_TILE)
    plots = {k: {"title": t, "file": f, "available": (Path(output_dir) / f).is_file()}
             for k, (t, f) in PLOTS.items()}
    if tile is None or not Path(tile).exists():
        return {"available": False, "reason": "SRTM tile S24W070 not found locally.",
                "plots": plots}

    raster = rl.load_raster(tile)
    slope = tf.slope_deg(raster)
    rough = tf.roughness(raster, window=3)
    return {
        "available": True,
        "dataset": "NASA SRTMGL1 v003",
        "tile": raster.source.name,
        "crs": raster.crs,
        "shape": list(raster.shape),
        "sample_extent_wsen": [round(x, 6) for x in raster.sample_extent],
        "nodata_count": raster.nodata_count,
        "elevation_m": {"min": raster.valid_min, "max": raster.valid_max},
        "spacing_m": {"east_west": slope.params["dx_m_centre_row"],
                      "north_south": slope.params["dy_m_centre_row"]},
        "slope": {"label": slope.label, "params": slope.params, "stats": _stats(slope.values)},
        "roughness": {"label": rough.label, "params": rough.params,
                      "stats": _stats(rough.values)},
        "plots": plots,
    }
