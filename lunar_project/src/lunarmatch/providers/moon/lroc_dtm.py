"""D_LROC_DTM – LROC NAC stereo Digital Terrain Models (ASU / PDS).

Discovery: ODE REST, ``ihid=LRO iid=LROC pt=SDNDTM`` (verified 2026-11-15).
Each product lists, among others:
  "DTM IN GEOTIFF FORMAT"  NAC_DTM_<NAME>.TIF        – elevation, ~2–5 m/px
  "CONFIDENCE MAP"         NAC_DTM_<NAME>_CONF.IMG   – stereo match confidence
  "ORTHOPHOTO IN PDS FORMAT" ..._<img>_<res>.IMG     – orthorectified NAC images
  "COLOR SLOPE MAP"        NAC_DTM_<NAME>_SLOPE.TIF  – *colourised* (RGB) slope, not numeric
Example near the test region: NAC_DTM_SHACKRDGE02 (Shackleton ridge, ~10 MB DTM).

The DTM GeoTIFFs are whole-file downloads (10–25 MB typical); the AOI is
cut out locally.  Slope/roughness must be computed from the DTM
(DERIVED_HERE) because the published slope map is a colour visualisation.
"""
from __future__ import annotations

from typing import Optional

from ...core.aoi import AOI
from ...core.base import CoverageReport, DataProvider, DatasetInfo, FetchResult, NotCovered, ProductRef
from ...core.bodies import Body
from ...core.evidence import AccessMode, Evidence
from ...core.ode import OdeClient
from ...core import terrain
from ...core.raster import Layer
from ._ode_raster import download_and_window, save_processed


class LROCDTMProvider(DataProvider):
    info = DatasetInfo(
        dataset_id="D_LROC_DTM", name="LROC NAC Stereo DTM", body="Moon", provider="LROC/ASU via PDS (ODE)",
        resolution="~2-5 m/px (product dependent)", evidence=Evidence.MEASURED_DERIVED,
        access=AccessMode.SEARCH_AND_DOWNLOAD,
        access_notes="ODE REST footprint search (pt=SDNDTM), whole-file GeoTIFF download, local AOI cut.",
        endpoints=("https://oderest.rsl.wustl.edu/live2/",),
        workbook_source_url="https://www.lroc.asu.edu/data/support/downloads/LROC_NAC_Processing_Guide.pdf",
        known_limits="Fragmented footprints; check CONFIDENCE map; slope map in product is RGB.",
    )

    def search(self, aoi: AOI, limit: int = 50, **kw) -> list[ProductRef]:
        self.check_body(aoi, (Body.MOON,))
        b = aoi.geographic_bbox(lon_convention="360")
        prods = OdeClient(self.http).product_search(ihid="LRO", iid="LROC", pt="SDNDTM", bbox_lon360=b, limit=limit)
        return [OdeClient.to_product_ref(p) for p in prods]

    def check_coverage(self, aoi: AOI) -> CoverageReport:
        refs = self.search(aoi)
        if not refs:
            return CoverageReport(self.info.dataset_id, False, "no NAC DTM footprint intersects the AOI")
        return CoverageReport(self.info.dataset_id, True,
                              f"{len(refs)} NAC DTM product(s) intersect the AOI (verify the AOI is fully inside "
                              "the valid-data area after download)", [r.product_id for r in refs])

    def fetch(self, aoi: AOI, product_id: Optional[str] = None, derive: bool = True,
              roughness_window_m: float = 10.0, **kw) -> FetchResult:
        refs = self.search(aoi)
        if product_id:
            refs = [r for r in refs if r.product_id == product_id]
        if not refs:
            raise NotCovered("no LROC NAC DTM covers this AOI")
        ref = refs[0]
        res = FetchResult(self.info.dataset_id, aoi, metadata={"product_id": ref.product_id,
                                                               "candidates": [r.product_id for r in refs]})
        subdir = ref.product_id.split(".")[-1] if ref.product_id else "product"
        dem, path = download_and_window(self, ref, "DTM IN GEOTIFF FORMAT", ".TIF", aoi, layer_name="elevation",
                                        units="m", evidence=Evidence.MEASURED_DERIVED, subdir=subdir)
        if dem is None:
            raise NotCovered(f"{ref.product_id} has no GeoTIFF DTM file")
        res.files.append(str(path))
        res.layers.add(dem)
        nan_frac = float((~(dem.data == dem.data)).mean())
        if nan_frac > 0:
            res.warn(f"{100 * nan_frac:.1f}% of AOI pixels are NoData in {ref.product_id}")
        if derive:
            dx, dy = dem.resolution
            res.layers.add(Layer("slope_derived", terrain.slope_horn(dem.data, dx, dy), dem.transform, dem.crs,
                                 "deg", Evidence.DERIVED_HERE, self.info.dataset_id, "Horn slope from NAC DTM"))
            n = terrain.window_px_for(roughness_window_m, dx)
            res.layers.add(Layer("roughness", terrain.detrended_rms_roughness(dem.data, n, dx, dy), dem.transform,
                                 dem.crs, "m RMS", Evidence.DERIVED_HERE, self.info.dataset_id,
                                 f"detrended RMS, {n * dx:.1f} m window"))
            for name in ("slope_derived", "roughness"):
                save_processed(self, res, res.layers[name], subdir)
        save_processed(self, res, dem, subdir)
        return res
