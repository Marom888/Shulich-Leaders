"""Load the Atacama SRTM tile, print metadata, verify, and write 2D/3D HTML.

Usage:
    python visualize_terrain.py [--path FILE] [--max-side 361] [--vex 3]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402

from lunarmatch.config import ATACAMA_TILE, OUTPUT_DIR  # noqa: E402
from lunarmatch.features import terrain as tf  # noqa: E402
from lunarmatch.data import raster_loader as rl  # noqa: E402
from lunarmatch.data.earthdata_client import find_local_tile  # noqa: E402
from lunarmatch.visualization import terrain_plots as tp  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--path", type=Path, help=".hgt or .hgt.zip (default: find Atacama tile)")
    ap.add_argument("--max-side", type=int, default=361, help="max samples per side to plot")
    ap.add_argument("--vex", type=float, default=3.0, help="3D vertical exaggeration")
    ap.add_argument("--rough-window", type=int, default=3, help="roughness window (odd samples)")
    ap.add_argument("--out", type=Path, default=OUTPUT_DIR)
    args = ap.parse_args()

    src = args.path or find_local_tile(ATACAMA_TILE)
    if src is None:
        print("No local Atacama tile found. Run: python download_nasa.py", file=sys.stderr)
        return 1

    raster = rl.load_raster(src)
    print("=== Raster metadata ===")
    for k, v in raster.summary().items():
        print(f"  {k:32s} {v}")

    step = rl.choose_step(raster.shape, args.max_side)
    grid = rl.downsample(raster, step)
    print(f"\n=== Sampling ===\n  stride decimation factor {step} -> {grid.shape} "
          f"(original {raster.shape}); values are unmodified original samples")
    print(f"  plotted lat range {grid.lats.min():.6f} .. {grid.lats.max():.6f}")
    print(f"  plotted lon range {grid.lons.min():.6f} .. {grid.lons.max():.6f}")

    checks = rl.verify_samples(raster, grid, n=8)
    print("\n=== Spot checks: sampled grid vs original raster ===")
    print(f"  {'row':>5} {'col':>5} {'lat':>11} {'lon':>11} {'original':>9} {'plotted':>8}")
    for c in checks:
        print(f"  {c['row']:5d} {c['col']:5d} {c['lat']:11.6f} {c['lon']:11.6f} "
              f"{c['original']:9d} {str(c['plotted']):>8}")

    title = f"{raster.source.stem} (Atacama, Chile)"
    f2 = tp.heatmap_figure(grid, title)
    f3 = tp.surface_figure(grid, args.vex, title)
    tp.check_figures(grid, f2, f3)
    print("\n  OK: both figures contain exactly the sampled grid values and indices")

    # Derived products (computed at full resolution, then stride-sampled).
    slope = tf.slope_deg(raster)
    rough = tf.roughness(raster, window=args.rough_window)
    for layer in (slope, rough):
        print(f"\n=== Derived: {layer.name} ===")
        for k, v in layer.summary().items():
            print(f"  {k:24s} {v}")
    slope_grid = rl.sample_layer(slope.values, grid)
    fs = tp.layer_heatmap_figure(slope_grid, slope, title)
    if not np.array_equal(np.asarray(fs.data[0].z, float), slope_grid.values[::-1],
                          equal_nan=True):
        raise AssertionError("slope figure differs from sampled slope layer")
    print("\n  OK: slope figure contains exactly the full-resolution slope at sampled cells")

    p2 = tp.save_html(f2, args.out / "terrain_2d.html")
    p3 = tp.save_html(f3, args.out / "terrain_3d.html")
    ps = tp.save_html(fs, args.out / "slope_2d.html")
    print(f"\nSaved:\n  {p2}\n  {p3}\n  {ps}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
