"""Shackleton Connecting Ridge – real LOLA 5 m data: download, validate, plot.

Run from the lunar_project folder:
    python examples/shackleton_lola_demo.py

What it does
1. Shows that the task's example point (-89.5°, 150°E) is NOT inside any PGDA
   5 m site and reports the nearest one.
2. Uses the centre of PGDA Site01 ("Connecting ridge") as the 1 km x 1 km
   test area (≈ 89.463°S, 222.51°E; polar-stereo x = -11 000 m, y = -12 000 m).
3. Fetches elevation, official slope, LOLA spot count and height uncertainty
   with HTTP range requests (~160 kB per layer) and derives roughness.
4. Validates georeferencing, values and an independent reference reading.
5. Saves 2-D elevation, slope, roughness and 3-D plots to data/processed/moon/D_LOLA/plots.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lunarmatch import AOI, Body  # noqa: E402
from lunarmatch.providers.moon.lola import PGDA_SITES, LOLAProvider  # noqa: E402

# Independent reference: Site01 rows 1500-1699, cols 1500-1699 (exactly 1 km x 1 km at the
# site centre) read on 2026-11-15 straight from pgda.gsfc.nasa.gov with a separate byte-level
# reader (browser JavaScript, HTTP Range).  Used to cross-check this pipeline.
REFERENCE_SITE01_CENTER = {
    "elevation": {"min": 1819.5286865234375, "max": 1958.4503173828125, "mean": 1929.5080634155274},
    "slope": {"min": 0.07401874661445618, "max": 30.742935180664062, "mean": 7.132415822202899},
    "measurement_density": {"min": 0.0, "max": 3.0, "mean": 0.102175},
    "elevation_uncertainty": {"min": 0.07368746399879456, "max": 1.765453815460205, "mean": 0.3653010838676244},
}


def main(show: bool = False):
    lola = LOLAProvider()

    print("=== 1. Coverage of the example point from the task description ===")
    example = AOI(Body.MOON, -89.5, 150.0, 1000, 1000)
    print(lola.check_coverage(example).detail)

    print("\n=== 2. Test area: centre of PGDA Site01 (Shackleton connecting ridge) ===")
    site = next(s for s in PGDA_SITES if s.name == "Site01")
    lat, lon = site.center_latlon()
    aoi = AOI(Body.MOON, lat, lon, 1000, 1000, name="Shackleton connecting ridge – Site01 centre")
    print(f"centre: {lat:.5f}°, {lon:.5f}°E   polar-stereo: {aoi.polar_stereo_center()}")

    print("\n=== 3. Fetch ===")
    res = lola.fetch(aoi, layers=["elevation", "slope", "measurement_density", "elevation_uncertainty",
                                  "slope_derived", "roughness"], roughness_window_m=25)
    for w in res.warnings:
        print("WARNING:", w)
    e = res.layers["elevation"]

    print("\n=== 4. Validation ===")
    # 4a georeferencing: window transform must sit on the site's 5 m grid and cover the AOI
    xmin, ymin, xmax, ymax = aoi.polar_stereo_box()
    bx0, by0, bx1, by1 = e.bounds
    assert bx0 <= xmin and by0 <= ymin and bx1 >= xmax and by1 >= ymax, "window does not cover AOI"
    assert (e.transform[0] - site.x0) % 5 == 0 and (site.y0 - e.transform[3]) % 5 == 0, "off-grid window"
    print(f"window bounds (m): x {bx0:.0f}..{bx1:.0f}, y {by0:.0f}..{by1:.0f}  covers AOI box: OK")
    print("AOI corners (lat, lon):", [(round(a, 5), round(b, 5)) for a, b in res.metadata["corners_latlon"]])
    # 4b independent reference reading
    r0, c0 = res.metadata["window_rows"][0], res.metadata["window_cols"][0]
    sl = (slice(1500 - r0, 1700 - r0), slice(1500 - c0, 1700 - c0))
    for name, ref in REFERENCE_SITE01_CENTER.items():
        sub = res.layers[name].data[sl]
        got = {"min": float(np.nanmin(sub)), "max": float(np.nanmax(sub)), "mean": float(np.nanmean(sub))}
        ok = all(abs(got[k] - ref[k]) <= 1e-4 * max(1.0, abs(ref[k])) for k in ref)
        print(f"{name:22s} min {got['min']:9.3f} max {got['max']:9.3f} mean {got['mean']:9.3f}  "
              f"vs reference: {'MATCH' if ok else 'MISMATCH'}")
        if not ok:
            raise SystemExit(f"value check failed for {name}: {got} != {ref}")
    # 4c derived vs official slope agreement (both at 5 m support)
    d = res.layers["slope_derived"].data - res.layers["slope"].data
    print(f"slope_derived - official slope: median {np.nanmedian(d):+.2f}°, "
          f"MAD {np.nanmedian(np.abs(d)):.2f}° (different stencils; expected small)")

    print("\n=== 5. Summary ===")
    st = e.stats()
    print(f"elevation [m] min {st['min']:.2f}  max {st['max']:.2f}  mean {st['mean']:.2f}")
    print(f"resolution {e.resolution[0]:g} m/px, grid {e.shape[1]}x{e.shape[0]} px "
          f"= {e.shape[1] * 5 / 1000:.3f} x {e.shape[0] * 5 / 1000:.3f} km")
    print(f"pixels containing ≥1 LOLA shot: {100 * res.metadata['fraction_pixels_with_lola_shot']:.1f}% "
          "(the rest is interpolated)")
    print(f"CRS: {e.crs}")

    print("\n=== 6. Plots ===")
    import matplotlib

    if not show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from lunarmatch.viz import plot_3d, plot_map

    out = lola.store.processed_dir("moon", "D_LOLA", "plots")
    fig, axs = plt.subplots(1, 3, figsize=(17, 5))
    plot_map(e, axs[0], cmap="terrain")
    plot_map(res.layers["slope"], axs[1], cmap="magma")
    plot_map(res.layers["roughness"], axs[2], cmap="viridis")
    # plotted values check: colour limits must equal the data limits
    assert np.isclose(axs[0].images[0].get_clim()[0], st["min"]) and np.isclose(axs[0].images[0].get_clim()[1], st["max"])
    fig.suptitle(f"{aoi.name}  ({lat:.4f}°, {lon:.4f}°E)", fontsize=11)
    fig.tight_layout()
    fig.savefig(out / "site01_maps.png", dpi=130)
    ax = plot_3d(e, vertical_exaggeration=1.0)
    ax.figure.savefig(out / "site01_3d.png", dpi=130)
    print("saved:", out / "site01_maps.png", "and", out / "site01_3d.png")
    if show:
        plt.show()
    return res


if __name__ == "__main__":
    main(show="--show" in sys.argv)
