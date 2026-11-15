"""D_SHADOWCAM – KPLO ShadowCam (low-light imaging of permanently shadowed regions).

Discovery: ODE REST ``ihid=KPLO iid=ShadowCam`` with product types (verified
2026-11-15 via ``query=iipy``): ``DTM``, ``CMOS`` (controlled mosaic),
``UMOS`` (uncontrolled mosaic), ``CAL`` (calibrated), ``RAW``.
Derived products on https://pds.shadowcam.im-ldi.com ship Cloud-Optimized
GeoTIFF variants (file descriptions containing "COG"), which are read
remotely with HTTP range requests (rasterio).
"""
from __future__ import annotations

from typing import Optional

from ...core.aoi import AOI
from ...core.base import CoverageReport, DataProvider, DatasetInfo, FetchResult, NotCovered, ProductRef
from ...core.bodies import Body
from ...core.evidence import AccessMode, Evidence
from ...core.ode import OdeClient
from ...core.raster import read_window_native
from ._ode_raster import aoi_bounds_in_crs, save_processed


class ShadowCamProvider(DataProvider):
    info = DatasetInfo(
        dataset_id="D_SHADOWCAM", name="ShadowCam", body="Moon", provider="ShadowCam / ASU via PDS (ODE)",
        resolution="mission dependent (~1.7 m/px nominal)", evidence=Evidence.MEASURED,
        access=AccessMode.SEARCH_AND_DOWNLOAD,
        access_notes="ODE search (KPLO/ShadowCam pt=DTM|CMOS|UMOS|CAL); COG variants read by range requests.",
        endpoints=("https://oderest.rsl.wustl.edu/live2/", "https://pds.shadowcam.im-ldi.com/"),
        workbook_source_url="https://www.shadowcam.asu.edu/",
        known_limits="Selected polar shadowed sites only; low-light radiometry differs from NAC.",
    )

    def search(self, aoi: AOI, pt: str = "CMOS", limit: int = 50, **kw) -> list[ProductRef]:
        self.check_body(aoi, (Body.MOON,))
        b = aoi.geographic_bbox(lon_convention="360")
        prods = OdeClient(self.http).product_search(ihid="KPLO", iid="ShadowCam", pt=pt, bbox_lon360=b, limit=limit)
        return [OdeClient.to_product_ref(p) for p in prods]

    def check_coverage(self, aoi: AOI) -> CoverageReport:
        found = {pt: [r.product_id for r in self.search(aoi, pt=pt, limit=10)] for pt in ("CMOS", "DTM")}
        n = sum(len(v) for v in found.values())
        return CoverageReport(self.info.dataset_id, n > 0, f"ShadowCam products intersecting AOI: {found}", found)

    def fetch(self, aoi: AOI, pt: str = "CMOS", product_id: Optional[str] = None,
              cog_description: str = "COG", layer_name: str = "shadowcam", units: str = "DN/I_F",
              **kw) -> FetchResult:
        """Read the AOI window from the first COG file of a ShadowCam product."""
        refs = self.search(aoi, pt=pt)
        if product_id:
            refs = [r for r in refs if r.product_id == product_id]
        if not refs:
            raise NotCovered(f"no ShadowCam {pt} product intersects the AOI")
        res = FetchResult(self.info.dataset_id, aoi, metadata={"candidates": [r.product_id for r in refs]})
        res.metadata["available_files"] = {r.product_id: list(r.urls) for r in refs[:5]}
        for ref in refs:
            picked = OdeClient.pick_file(ref, cog_description, ".TIF")
            if not picked:
                continue
            fname, url, _ = picked
            import rasterio

            from ...core.raster import GDAL_HTTP_ENV

            with rasterio.Env(**GDAL_HTTP_ENV), rasterio.open(url) as src:
                bounds = aoi_bounds_in_crs(aoi, src.crs.to_wkt())
            lyr = read_window_native(url, bounds, name=layer_name, units=units, evidence=Evidence.MEASURED,
                                     dataset_id=self.info.dataset_id, description=f"{fname} ({ref.product_id})")
            res.layers.add(lyr)
            res.metadata["product_id"] = ref.product_id
            save_processed(self, res, lyr, ref.product_id.replace("/", "_") or "product")
            return res
        raise NotCovered("intersecting ShadowCam products have no COG file; use search() and download manually")
