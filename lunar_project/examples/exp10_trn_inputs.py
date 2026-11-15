"""EXP_10 (terrain-relative navigation) – collect the Moon and Earth inputs on one common GSD.

    python examples/exp10_trn_inputs.py                 # Shackleton ridge vs. Atacama (global datasets)
    python examples/exp10_trn_inputs.py --usa 36.10 -112.10   # Earth site in the USA -> 3DEP + NAIP

Output: data/processed/experiments/EXP_10/<run>/  {moon_image,moon_dem,earth_image,earth_dem}.tif,
manifest.json and a side-by-side PNG.  No navigation score is computed – this prepares the inputs.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lunarmatch import AOI, Body  # noqa: E402
from lunarmatch.experiments.exp10_trn import collect_exp10_inputs  # noqa: E402

MOON = AOI(Body.MOON, -89.46311, 222.51, 3000, 3000, name="Shackleton connecting ridge (PGDA Site01 centre)")


def main():
    usa = "--usa" in sys.argv
    nums = [float(a) for a in sys.argv[1:] if a.lstrip("-").replace(".", "").isdigit()]
    lat, lon = nums[:2] if len(nums) >= 2 else (-23.5, -69.5)  # Atacama tile already in the repo
    earth = AOI(Body.EARTH, lat, lon, 3000, 3000, name=f"Earth candidate {lat},{lon}")
    b = collect_exp10_inputs(MOON, earth, run_name=f"site01_vs_{lat}_{lon}", earth_in_usa=usa)

    print(f"common GSD: {b.common_gsd_m}")
    for k in ("moon_image", "moon_dem", "earth_image", "earth_dem"):
        print(f"{k:12s} {b.status.get(k)}")
        if k in b.layers:
            st = b.layers[k].stats()
            print(f"             native px {b.native[k]}  -> {b.layers[k].shape}  "
                  f"min {st.get('min')} max {st.get('max')}  nodata {st.get('nodata_fraction'):.2%}")
    for w in b.warnings:
        print("WARNING:", w)
    if b.files:
        print("manifest:", b.files[-1])

    if b.layers:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        keys = [k for k in ("moon_image", "earth_image", "moon_dem", "earth_dem") if k in b.layers]
        fig, axs = plt.subplots(1, len(keys), figsize=(4.5 * len(keys), 4.3))
        for ax, k in zip(np.atleast_1d(axs), keys):
            lyr = b.layers[k]
            ax.imshow(lyr.data, cmap="gray" if "image" in k else "terrain", interpolation="nearest")
            ax.set_title(f"{k}\n{lyr.dataset_id} @ {b.common_gsd_m:.1f} m", fontsize=9)
            ax.axis("off")
        fig.tight_layout()
        out = Path(b.files[-1]).with_name("overview.png")
        fig.savefig(out, dpi=120)
        print("figure:", out)


if __name__ == "__main__":
    main()
