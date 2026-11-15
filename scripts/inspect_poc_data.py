"""Open the stored LOLA and 3DEP subsets and print dimensions, resolution, coverage and elevation range.

    .venv\\Scripts\\python scripts\\inspect_poc_data.py

The foundation's load_raster() reads SRTM HGT only, so GeoTIFFs are read with rasterio
into the foundation's ElevationRaster container (values unchanged, NoData as a mask).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import rasterio  # noqa: E402
from pyproj import Transformer  # noqa: E402

from lunarmatch.config import DATA_DIR  # noqa: E402
from lunarmatch.data.raster_loader import ElevationRaster  # noqa: E402

FILES = {
    "moon": sorted((DATA_DIR / "moon" / "lola").glob("*.tif")),
    "earth": sorted((DATA_DIR / "earth" / "usgs_3dep").glob("*.tif")),
}
GEOG = {"moon": "+proj=longlat +R=1737400 +no_defs", "earth": "EPSG:4326"}


def load_geotiff(path: Path) -> ElevationRaster:
    with rasterio.open(path) as ds:
        data, nd, t, b = ds.read(1), ds.nodata, ds.transform, ds.bounds
        crs, aop = ds.crs.to_wkt(), ds.tags().get("AREA_OR_POINT")
    mask = ~np.isfinite(data.astype(float))
    if nd is not None and np.isfinite(nd):
        mask |= data == nd
    h, w = data.shape
    return ElevationRaster(data=data, nodata_mask=mask, nodata_value=nd, crs=crs, transform=t,
                           footprint=(b.left, b.bottom, b.right, b.top),
                           sample_extent=(t.c + t.a / 2, t.f + (h - 0.5) * t.e, t.c + (w - 0.5) * t.a, t.f + t.e / 2),
                           area_or_point=aop, source=path, driver="GTiff")


def main() -> int:
    ok = True
    for body, files in FILES.items():
        if not files:
            print(f"{body}: no files found")
            ok = False
        for p in files:
            r = load_geotiff(p)
            left, bottom, right, top = r.footprint
            tr = Transformer.from_crs(r.crs, GEOG[body], always_xy=True)
            corners = [tr.transform(x, y) for x, y in ((left, top), (right, top), (right, bottom), (left, bottom))]
            lats = [c[1] for c in corners]
            lons = [c[0] % 360 if body == "moon" else c[0] for c in corners]
            v = r.data[~r.nodata_mask]
            print(f"\n{p.relative_to(ROOT)}  ({p.stat().st_size / 1e6:.2f} MB)")
            print(f"  shape {r.shape}, dtype {r.data.dtype}, pixel {r.transform.a:g} x {-r.transform.e:g} (CRS units: m)")
            print(f"  extent {right - left:.0f} m x {top - bottom:.0f} m; CRS: {r.crs.split('[')[1].split(',')[0]}")
            print(f"  latitude {min(lats):.5f} .. {max(lats):.5f}; longitude {min(lons):.5f} .. {max(lons):.5f}")
            print(f"  values {r.valid_min:.2f} .. {r.valid_max:.2f}; NoData {r.nodata_count} of {r.data.size}")
            good = v.size > 0.99 * r.data.size and np.ptp(v) > 0 and abs(r.transform.a) > 0
            print("  CHECK:", "OK" if good else "FAILED")
            ok &= bool(good)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
