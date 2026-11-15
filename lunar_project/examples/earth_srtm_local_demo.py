"""Earth side, fully offline: read the SRTM 1-arc-second tile already in this repository
(S24W070.SRTMGL1.hgt/S24W070.hgt, Atacama/Andes) for a 1 km x 1 km AOI, derive slope and
roughness, validate, and plot – the same code path NASADEM tiles use.

    python examples/earth_srtm_local_demo.py [lat lon]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lunarmatch import AOI, Body  # noqa: E402
from lunarmatch.core import terrain  # noqa: E402
from lunarmatch.core.evidence import Evidence  # noqa: E402
from lunarmatch.core.raster import Layer  # noqa: E402
from lunarmatch.providers.earth._stac_cog import layer_pixel_size_m  # noqa: E402
from lunarmatch.providers.earth.nasadem import read_hgt  # noqa: E402

HGT = ROOT.parent / "S24W070.SRTMGL1.hgt" / "S24W070.hgt"


def main(lat=-23.5, lon=-69.5):
    aoi = AOI(Body.EARTH, lat, lon, 1000, 1000, name="SRTM test AOI")
    dem = read_hgt(HGT, aoi, dataset_id="SRTMGL1 (local file)")
    dx, dy = layer_pixel_size_m(dem, lat)
    slope = Layer("slope_derived", terrain.slope_horn(dem.data, dx, dy), dem.transform, dem.crs, "deg",
                  Evidence.DERIVED_HERE, dem.dataset_id, "Horn slope")
    n = terrain.window_px_for(150, dx)
    rough = Layer("roughness", terrain.detrended_rms_roughness(dem.data, n, dx, dy), dem.transform, dem.crs,
                  "m RMS", Evidence.DERIVED_HERE, dem.dataset_id, f"{n}x{n} px window")

    w, s, e, nn = aoi.geographic_bbox()
    b = dem.bounds
    assert b[0] <= w and b[1] <= s and b[2] >= e and b[3] >= nn, "window does not cover AOI"
    st = dem.stats()
    print(f"AOI {lat}, {lon}: grid {dem.shape}, pixel {dx:.1f} x {dy:.1f} m (1 arc-second)")
    print(f"elevation [m] min {st['min']:.1f} max {st['max']:.1f} mean {st['mean']:.1f}; "
          f"slope p50 {np.nanpercentile(slope.data, 50):.2f}° p90 {np.nanpercentile(slope.data, 90):.2f}°")
    print("NOTE: ~30 m support – cannot resolve lander-leg geometry (workbook rule R07).")

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axs = plt.subplots(1, 3, figsize=(16, 4.6))
    for ax, lyr, cm in zip(axs, (dem, slope, rough), ("terrain", "magma", "viridis")):
        im = ax.imshow(lyr.data, extent=[b[0], b[2], b[1], b[3]], cmap=cm, interpolation="nearest")
        plt.colorbar(im, ax=ax, shrink=0.85).set_label(f"{lyr.name} [{lyr.units}]")
        ax.ticklabel_format(useOffset=False)
        ax.set_xlabel("longitude [°]")
        ax.set_ylabel("latitude [°]")
        ax.set_title(f"{lyr.dataset_id} · {lyr.name} ({lyr.evidence.value})", fontsize=9)
    assert np.isclose(axs[0].images[0].get_clim()[1], st["max"])
    fig.tight_layout()
    out = ROOT / "data" / "processed" / "earth" / "SRTMGL1"
    out.mkdir(parents=True, exist_ok=True)
    fig.savefig(out / "srtm_aoi_maps.png", dpi=130)
    print("saved", out / "srtm_aoi_maps.png")


if __name__ == "__main__":
    args = [float(a) for a in sys.argv[1:3]]
    main(*args)
