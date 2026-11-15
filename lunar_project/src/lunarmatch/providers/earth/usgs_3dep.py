"""D_EARTH_3DEP – USGS 3D Elevation Program.

Two verified access paths (2026-11-15):
* 1 m lidar DEM tiles – USGS TNM Access API
  ``https://tnmaccess.nationalmap.gov/api/v1/products?datasets=Digital Elevation Model (DEM) 1 meter&bbox=W,S,E,N``
  returns items with ``downloadURL`` (GeoTIFF on prd-tnm S3, UTM CRS).
  The AOI window is read remotely with rasterio range requests.
* 1/3 arc-second (~10 m) seamless DEM – Planetary Computer STAC
  collection ``3dep-seamless`` (COG, anonymous SAS).  Fallback when no 1 m
  tile exists.

1 m availability varies by project; footpad-scale geometry still needs a
local survey (workbook D_EARTH_3DEP Known_Limits).
"""
from __future__ import annotations

from ...core import terrain
from ...core.aoi import AOI
from ...core.base import CoverageReport, DataProvider, DatasetInfo, FetchResult, NotCovered, ProductRef
from ...core.bodies import Body
from ...core.evidence import AccessMode, Evidence
from ...core.raster import Layer, read_window_lonlat, write_geotiff
from ...core.stac import PLANETARY_COMPUTER, PlanetaryComputerSigner
from ...core.storage import utc_now_iso
from ._stac_cog import bbox_contains, choose_item, layer_pixel_size_m, read_assets, stac_items

TNM_API = "https://tnmaccess.nationalmap.gov/api/v1/products"
DATASET_1M = "Digital Elevation Model (DEM) 1 meter"


class USGS3DEPProvider(DataProvider):
    info = DatasetInfo(
        dataset_id="D_EARTH_3DEP", name="USGS 3DEP", body="Earth", provider="USGS",
        resolution="1 m lidar where available; 1/3 arc-sec (~10 m) seamless", evidence=Evidence.MEASURED_DERIVED,
        access=AccessMode.AUTOMATED,
        access_notes="TNM Access API for 1 m tiles; Planetary Computer 3dep-seamless COG for 10 m.",
        endpoints=(TNM_API, PLANETARY_COMPUTER + "/collections/3dep-seamless"),
        workbook_source_url="https://www.usgs.gov/3d-elevation-program/about-3dep-products-services",
        known_limits="United States only; 1 m coverage varies; footpad scale needs survey.",
    )

    def search(self, aoi: AOI, max_items: int = 50, **kw) -> list[ProductRef]:
        self.check_body(aoi, (Body.EARTH,))
        w, s, e, n = aoi.geographic_bbox()
        j = self.http.get_json(TNM_API, params={"datasets": DATASET_1M, "bbox": f"{w},{s},{e},{n}",
                                                "max": max_items, "prodFormats": "GeoTIFF"})
        out = []
        for it in j.get("items", []):
            bb = it.get("boundingBox") or {}
            bbox = (bb.get("minX"), bb.get("minY"), bb.get("maxX"), bb.get("maxY")) if bb else None
            out.append(ProductRef(product_id=it.get("sourceId") or it.get("title"), title=it.get("title", ""),
                                  urls={"dem": it.get("downloadURL")}, sizes={"dem": it.get("sizeInBytes") or 0},
                                  bbox=bbox, datetime=it.get("publicationDate"),
                                  properties={k: it.get(k) for k in ("lastUpdated", "dateCreated", "metaUrl")}))
        return out

    def check_coverage(self, aoi: AOI) -> CoverageReport:
        refs = self.search(aoi)
        if refs:
            return CoverageReport(self.info.dataset_id, True, f"{len(refs)} 1 m DEM tile(s)", [r.product_id for r in refs])
        items = stac_items(self, PLANETARY_COMPUTER, "3dep-seamless", aoi, max_items=5)
        return CoverageReport(self.info.dataset_id, bool(items) or None,
                              "no 1 m tile; 10 m seamless available" if items else "no 3DEP coverage found")

    def fetch(self, aoi: AOI, prefer_1m: bool = True, derive: bool = True, **kw) -> FetchResult:
        self.check_body(aoi, (Body.EARTH,))
        res = FetchResult(self.info.dataset_id, aoi)
        box = aoi.geographic_bbox()
        refs = self.search(aoi) if prefer_1m else []
        refs = [r for r in refs if r.urls.get("dem")]
        full = [r for r in refs if r.bbox and None not in r.bbox and bbox_contains(r.bbox, box)]
        if refs:
            ref = (full or refs)[0]
            if not full:
                res.warn("no single 1 m tile contains the whole AOI; reading the first intersecting tile only")
            url = ref.urls["dem"]
            dem = read_window_lonlat(url, box, name="elevation", units="m", evidence=Evidence.MEASURED_DERIVED,
                                     dataset_id=self.info.dataset_id, description=f"3DEP 1 m DEM {ref.title}")
            res.layers.add(dem)
            res.metadata.update({"product": ref.title, "resolution_class": "1 m", "product_date": ref.datetime})
            p = self.store.raw_dir("earth", self.info.dataset_id, "1m") / f"{ref.product_id}__aoi.tif"
            write_geotiff(dem, p)
            self.store.write_metadata(p, {"dataset_id": self.info.dataset_id, "source_url": url, "units": "m",
                                          "crs": dem.crs, "resolution": list(dem.resolution),
                                          "evidence": dem.evidence.value, "product_date": ref.datetime,
                                          "download_utc": utc_now_iso(), "path": str(p), "stats": dem.stats()})
            res.files.append(str(p))
        else:
            items = stac_items(self, PLANETARY_COMPUTER, "3dep-seamless", aoi)
            items = [i for i in items if i.get("properties", {}).get("gsd", 10) <= 10] or items
            if not items:
                raise NotCovered("no 3DEP data for this AOI (US only)")
            item, full_cover = choose_item(items, aoi, key=lambda i: i.get("properties", {}).get("gsd", 99))
            if not full_cover:
                res.warn("AOI crosses tile boundary; first tile only")
            signer = PlanetaryComputerSigner(self.http)
            read_assets(self, res, item, aoi, {"elevation": ("data", "m", Evidence.MEASURED_DERIVED, 1.0,
                                                             "3DEP seamless DEM")},
                        sign=lambda h: signer.sign(h, "3dep-seamless"))
            res.metadata["resolution_class"] = f"{item['properties'].get('gsd')} m seamless"
        if derive and "elevation" in res.layers:
            dem = res.layers["elevation"]
            dx, dy = layer_pixel_size_m(dem, aoi.lat)
            res.layers.add(Layer("slope_derived", terrain.slope_horn(dem.data, dx, dy), dem.transform, dem.crs, "deg",
                                 Evidence.DERIVED_HERE, self.info.dataset_id, f"Horn slope at {dx:.1f} m support"))
        return res
