"""D_SENT2 – Sentinel-2 MSI Level-2A surface reflectance.

Access: Element 84 Earth Search STAC v1, collection ``sentinel-2-l2a``
(verified 2026-11-15).  Assets are public COGs on AWS S3 (no login):
``blue`` B02, ``green`` B03, ``red`` B04, ``nir`` B08 (10 m);
``rededge1-3``, ``nir08``, ``swir16`` B11, ``swir22`` B12, ``scl`` (20 m).
Reflectance = DN * 1e-4 (BOA, processing baseline offset handled below).
"""
from __future__ import annotations

from typing import Optional

from ...core.aoi import AOI
from ...core.base import CoverageReport, DataProvider, DatasetInfo, FetchResult, ProductRef
from ...core.bodies import Body
from ...core.evidence import AccessMode, Evidence
from ...core.stac import EARTH_SEARCH
from ._stac_cog import choose_item, item_to_ref, read_assets, stac_items

REFLECTANCE_ASSETS = {"blue", "green", "red", "nir", "rededge1", "rededge2", "rededge3", "nir08", "nir09",
                      "swir16", "swir22", "coastal"}


class Sentinel2Provider(DataProvider):
    info = DatasetInfo(
        dataset_id="D_SENT2", name="Sentinel-2 MSI L2A", body="Earth", provider="ESA Copernicus (AWS Earth Search)",
        resolution="10 m VNIR; 20 m SWIR", evidence=Evidence.MEASURED, access=AccessMode.AUTOMATED,
        access_notes="STAC search with cloud filter; least-cloudy scene; COG window reads.",
        endpoints=(EARTH_SEARCH + "/collections/sentinel-2-l2a",),
        workbook_source_url="https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/S2L1C.html",
        known_limits="20 m SWIR cannot resolve individual small rocks; screening only.",
    )

    def search(self, aoi: AOI, datetime: Optional[str] = None, max_cloud: float = 10.0, **kw) -> list[ProductRef]:
        self.check_body(aoi, (Body.EARTH,))
        items = stac_items(self, EARTH_SEARCH, "sentinel-2-l2a", aoi, datetime=datetime,
                           query={"eo:cloud_cover": {"lt": max_cloud}}, max_items=100)
        return [item_to_ref(i) for i in items]

    def illumination_table(self, aoi: AOI, datetime: Optional[str] = None, max_cloud: float = 10.0) -> list[dict]:
        """Sun elevation/azimuth of every clear scene – lets EXP_10/EXP_SHADOW pick lighting conditions."""
        rows = []
        for r in self.search(aoi, datetime=datetime, max_cloud=max_cloud):
            pr = r.properties
            rows.append({"item": r.product_id, "datetime": r.datetime, "cloud_cover": pr.get("eo:cloud_cover"),
                         "sun_elevation_deg": pr.get("view:sun_elevation"), "sun_azimuth_deg": pr.get("view:sun_azimuth")})
        return sorted(rows, key=lambda x: (x["sun_elevation_deg"] is None, x["sun_elevation_deg"]))

    def check_coverage(self, aoi: AOI) -> CoverageReport:
        refs = self.search(aoi, max_cloud=20)
        return CoverageReport(self.info.dataset_id, bool(refs), f"{len(refs)} scene(s) <20% cloud")

    def fetch(self, aoi: AOI, bands=("red", "green", "blue", "nir", "swir16", "swir22", "scl"),
              datetime: Optional[str] = None, max_cloud: float = 10.0, item_id: Optional[str] = None,
              prefer_low_sun: bool = False, **kw) -> FetchResult:
        self.check_body(aoi, (Body.EARTH,))
        items = stac_items(self, EARTH_SEARCH, "sentinel-2-l2a", aoi, datetime=datetime,
                           query={"eo:cloud_cover": {"lt": max_cloud}}, max_items=100)
        if item_id:
            items = [i for i in items if i["id"] == item_id]
        if prefer_low_sun:  # long shadows: closer to lunar landing illumination
            key = lambda i: (i["properties"].get("view:sun_elevation") or 90, i["properties"].get("eo:cloud_cover", 100))  # noqa: E731
        else:
            key = lambda i: i["properties"].get("eo:cloud_cover", 100)  # noqa: E731
        item, full = choose_item(items, aoi, key=key)
        p = item["properties"]
        res = FetchResult(self.info.dataset_id, aoi, metadata={
            "stac_item": item["id"], "datetime": p.get("datetime"), "cloud_cover": p.get("eo:cloud_cover"),
            # illumination/viewing geometry published per scene (verified field names)
            "sun_elevation_deg": p.get("view:sun_elevation"), "sun_azimuth_deg": p.get("view:sun_azimuth"),
            "view_incidence_deg": p.get("view:incidence_angle")})
        if not full:
            res.warn("AOI crosses an MGRS tile edge; only one tile read")
        # Processing baseline >= 04.00 adds +1000 offset to L2A DN; Earth Search exposes it as
        # raster:bands offset/scale in the asset metadata – use it when present.
        assets = {}
        for b in bands:
            a = item["assets"].get(b, {})
            rb = (a.get("raster:bands") or [{}])[0]
            scale = rb.get("scale", 1e-4 if b in REFLECTANCE_ASSETS else 1.0)
            offset = rb.get("offset", 0.0)
            if offset:
                res.metadata.setdefault("offsets", {})[b] = offset
            units = "reflectance" if b in REFLECTANCE_ASSETS else "class"
            assets[b] = (b, units, Evidence.MEASURED, scale, f"S2 L2A {b}")
        read_assets(self, res, item, aoi, assets)
        for b, off in res.metadata.get("offsets", {}).items():
            for store in (res.layers, res.other_layers):
                if b in store:
                    store[b].data = store[b].data + off
        return res
