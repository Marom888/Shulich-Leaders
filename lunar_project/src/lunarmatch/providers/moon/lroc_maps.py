"""Map-projected LROC NAC imagery for terrain-relative navigation (EXP_10).

Raw NAC CDR frames are not map-projected (see lroc_nac.py).  Two LROC
products *are* map-projected and therefore usable as a navigation map:

1. **NAC south-pole mosaic tiles** – ODE ``ihid=LRO iid=LROC pt=BDRNPL``
   (verified 2026-11-15).  1 m/px polar-stereographic tiles, e.g.
   ``NAC_POLE_P892S2250`` (centre 89.25°S, 225°E, covers Shackleton ridge;
   ``.IMG`` ≈ 7.7 GB with a PDS4 ``.xml`` label – read *remotely* by window,
   never downloaded whole).  ODE also lists variants
   ``nac_pole_south_cm_005 … cm_065``; their meaning is not documented in the
   ODE response – check ``NAC_POLE_SOUTH_README.TXT`` before using them.
2. **Orthophotos inside NAC DTM products** (``pt=SDNDTM``, file description
   "ORTHOPHOTO IN PDS FORMAT"), co-registered with the DTM: map + terrain on
   the same grid.  Typically 6–42 MB, downloaded whole.

Reading uses GDAL's PDS4 driver through rasterio (label + raw IMG over
HTTP range requests).  Not run inside the development sandbox (no GDAL /
no access to pds.lroc.im-ldi.com there).
"""
from __future__ import annotations

from typing import Optional

from ...core.aoi import AOI
from ...core.base import CoverageReport, DataProvider, DatasetInfo, FetchResult, NotCovered, ProductRef
from ...core.bodies import Body
from ...core.evidence import AccessMode, Evidence
from ...core.ode import OdeClient
from ...core.raster import GDAL_HTTP_ENV, read_window_native
from ._ode_raster import aoi_bounds_in_crs, save_processed


def _label_url(ref: ProductRef) -> Optional[str]:
    """PDS4 label whose file stem equals the product id (ODE also lists sibling browse labels)."""
    stem = ref.product_id.split(".")[-1].upper()
    for key, url in ref.urls.items():
        desc, fname = key.split(" :: ", 1)
        if "LABEL" in desc.upper() and fname.upper() == f"{stem}.XML":
            return url
    picked = OdeClient.pick_file(ref, "PDS4 PRODUCT LABEL", ".XML")
    return picked[1] if picked else None


class LROCMapsProvider(DataProvider):
    info = DatasetInfo(
        dataset_id="D_LROC_NAC_MAP", name="LROC NAC map-projected imagery (polar mosaic / DTM orthophotos)",
        body="Moon", provider="LROC/ASU via PDS (ODE)", resolution="1 m (polar mosaic); 1-2 m (orthophotos)",
        evidence=Evidence.MEASURED, access=AccessMode.AUTOMATED,
        access_notes="ODE search pt=BDRNPL / SDNDTM; GDAL PDS4 window reads (polar mosaic remote, orthophoto local).",
        endpoints=("https://oderest.rsl.wustl.edu/live2/",),
        workbook_source_url="https://www.lroc.asu.edu/data/support/downloads/LROC_NAC_Processing_Guide.pdf",
        known_limits="Mosaics mix illumination of many images; orthophotos limited to DTM footprints.",
    )

    def search(self, aoi: AOI, source: str = "polar_mosaic", limit: int = 50, **kw) -> list[ProductRef]:
        self.check_body(aoi, (Body.MOON,))
        pt = "BDRNPL" if source == "polar_mosaic" else "SDNDTM"
        b = aoi.geographic_bbox(lon_convention="360")
        refs = [OdeClient.to_product_ref(p) for p in
                OdeClient(self.http).product_search(ihid="LRO", iid="LROC", pt=pt, bbox_lon360=b, limit=limit)]
        if source == "polar_mosaic":
            # the plain 1 m tiles; psr_* (shadowed-region stretch) and cm_* variants are listed separately
            refs.sort(key=lambda r: (".nac_pole_south." not in r.product_id, r.product_id))
        return refs

    def check_coverage(self, aoi: AOI) -> CoverageReport:
        if aoi.body is not Body.MOON:
            return CoverageReport(self.info.dataset_id, False, "Moon only")
        mos = [r.product_id for r in self.search(aoi, "polar_mosaic")] if aoi.lat < -85 else []
        dtm = [r.product_id for r in self.search(aoi, "dtm_orthophoto")]
        ok = bool(mos or dtm)
        return CoverageReport(self.info.dataset_id, ok, f"polar mosaic tiles: {mos[:3]}; DTM orthophotos: {dtm[:3]}",
                              mos + dtm)

    def fetch(self, aoi: AOI, source: str = "polar_mosaic", product_id: Optional[str] = None,
              orthophoto_contains: str = "", **kw) -> FetchResult:
        """source='polar_mosaic' (remote window of the 1 m tile) or 'dtm_orthophoto'."""
        import rasterio

        refs = self.search(aoi, source)
        if product_id:
            refs = [r for r in refs if r.product_id == product_id]
        if not refs:
            raise NotCovered(f"no LROC {source} product intersects the AOI")
        ref = refs[0]
        res = FetchResult(self.info.dataset_id, aoi, metadata={"source": source, "product_id": ref.product_id,
                                                               "alternatives": [r.product_id for r in refs[1:10]]})
        if source == "polar_mosaic":
            url = _label_url(ref)
            if not url:
                raise NotCovered(f"{ref.product_id}: no PDS4 label listed")
            path = url  # GDAL reads label + IMG remotely with range requests
        else:
            cands = [(k, u) for k, u in ref.urls.items()
                     if k.startswith("ORTHOPHOTO PDS4 LABEL") and orthophoto_contains.upper() in k.upper()]
            if not cands:
                raise NotCovered(f"{ref.product_id}: no orthophoto label")
            key, url = sorted(cands)[0]
            img_key = key.replace("ORTHOPHOTO PDS4 LABEL", "ORTHOPHOTO IN PDS FORMAT").rsplit(".", 1)[0] + ".IMG"
            img_url = ref.urls.get(img_key)
            d = self.store.raw_dir("moon", self.info.dataset_id, ref.product_id.split(".")[-1])
            lbl = self.http.download(url, d / url.rsplit("/", 1)[-1])
            if img_url:
                self.http.download(img_url, d / img_url.rsplit("/", 1)[-1])
            path = str(lbl)
            res.files += [str(lbl)]
        with rasterio.Env(**GDAL_HTTP_ENV):
            with rasterio.open(path) as src:
                bounds = aoi_bounds_in_crs(aoi, src.crs.to_wkt())
        lyr = read_window_native(path, bounds, name="image", units="I/F or DN (see label)", evidence=Evidence.MEASURED,
                                 dataset_id=self.info.dataset_id, description=f"{source} {ref.product_id}")
        lyr.source_url = url
        lyr.extra.update({"observation_time": ref.properties.get("Observation_time"),
                          "utc_start": ref.properties.get("UTC_start_time"),
                          "utc_stop": ref.properties.get("UTC_stop_time"),
                          "map_resolution": ref.properties.get("Map_resolution_text") or ref.properties.get("Map_resolution")})
        res.layers.add(lyr)
        save_processed(self, res, lyr, ref.product_id.split(".")[-1])
        if source == "polar_mosaic":
            res.warn("polar mosaic combines many NAC frames acquired under different illumination; "
                     "for lighting-specific tests use single NAC observations (D_LROC_NAC)")
        return res
