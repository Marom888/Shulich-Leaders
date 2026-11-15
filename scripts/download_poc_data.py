"""Download two small real elevation subsets into nasa_data/ (proof of concept).

    .venv\\Scripts\\python scripts\\download_poc_data.py

Moon : NASA PGDA LOLA product 78, Site01 "Connecting ridge" (5 m/px). 2 km x 2 km window
       (aligned with the product's south polar stereographic grid) centred on
       89.46485 S, 222.10767 E. Layers: surf (elevation), slp (slope), toterr (RMS height error).
Earth: USGS 3DEP 1 m DEM (lidar, bare earth), tile located with the official TNM Access API.
       1.5 km x 1.5 km window centred on Meteor Crater, Arizona (35.0275 N, 111.0225 W).

Only the needed pixels are read (HTTP range requests); no full source file is stored.
Pixel values, CRS, transform and NoData are copied unchanged into GeoTIFFs.
"""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import lunarmatch.gdal_env  # noqa: E402,F401  (HTTPS CA-bundle fix for non-ASCII project paths)
import rasterio  # noqa: E402
import requests  # noqa: E402
from pyproj import Transformer  # noqa: E402
from rasterio.windows import Window  # noqa: E402
from rasterio.windows import transform as wtransform  # noqa: E402

from lunarmatch.config import DATA_DIR  # noqa: E402

LOLA = "https://pgda.gsfc.nasa.gov/data/LOLA_5mpp/Site01/Site01_final_adj_5mpp_{}.tif"
MOON = (-89.46485, 222.10767)
EARTH = (35.0275, -111.0225)
TNM = "https://tnmaccess.nationalmap.gov/api/v1/products"


def save_window(src_url, center_xy, half_m, dst, attempts=3):
    if dst.is_file():
        print(f"exists, reusing {dst.relative_to(ROOT)}")
        return
    for k in range(attempts):
        try:
            return _save_window(src_url, center_xy, half_m, dst)
        except rasterio.errors.RasterioIOError as e:
            print(f"  read failed ({e}); retry {k + 1}/{attempts}")
    raise RuntimeError(f"could not read {src_url} after {attempts} attempts")


def _save_window(src_url, center_xy, half_m, dst):
    with rasterio.open("/vsicurl/" + src_url) as ds:
        T = ds.transform
        c0 = math.floor((center_xy[0] - half_m - T.c) / T.a)
        r0 = math.floor((T.f - (center_xy[1] + half_m)) / -T.e)
        n = round(2 * half_m / T.a)
        if c0 < 0 or r0 < 0 or c0 + n > ds.width or r0 + n > ds.height:
            raise RuntimeError(f"window outside {src_url}")
        win = Window(c0, r0, n, n)
        data = ds.read(1, window=win)
        prof = dict(driver="GTiff", width=n, height=n, count=1, dtype=data.dtype.name, crs=ds.crs,
                    transform=wtransform(win, T), nodata=ds.nodata, compress="deflate",
                    predictor=3 if data.dtype.kind == "f" else 2, tiled=True)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(dst, "w", **prof) as out:
        out.write(data, 1)
        out.update_tags(SOURCE_URL=src_url, SOURCE_WINDOW_ROW_COL_SIZE=f"{r0},{c0},{n}")
    print(f"saved {dst.relative_to(ROOT)} ({dst.stat().st_size / 1e6:.2f} MB)")


def moon():
    crs = rasterio.open("/vsicurl/" + LOLA.format("surf")).crs
    x, y = Transformer.from_crs("+proj=longlat +R=1737400 +no_defs", crs, always_xy=True).transform(MOON[1], MOON[0])
    for layer in ("surf", "slp", "toterr"):
        save_window(LOLA.format(layer), (x, y), 1000.0, DATA_DIR / "moon" / "lola" / f"LOLA_Site01_ConnectingRidge_2km_{layer}.tif")


def earth():
    lat, lon = EARTH
    d = 0.001
    items = requests.get(TNM, params={"datasets": "Digital Elevation Model (DEM) 1 meter",
                                      "bbox": f"{lon - d},{lat - d},{lon + d},{lat + d}", "outputFormat": "JSON"},
                         timeout=60).json()["items"]
    items = [i for i in items if i["downloadURL"].lower().endswith(".tif")]
    item = sorted(items, key=lambda i: i.get("publicationDate", ""), reverse=True)[0]
    url = item["downloadURL"]
    print("3DEP product:", item["title"], item.get("publicationDate"), url)
    crs = rasterio.open("/vsicurl/" + url).crs
    x, y = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform(lon, lat)
    save_window(url, (x, y), 750.0, DATA_DIR / "earth" / "usgs_3dep" / "USGS3DEP_1m_MeteorCrater_AZ_1p5km.tif")


if __name__ == "__main__":
    moon()
    earth()
