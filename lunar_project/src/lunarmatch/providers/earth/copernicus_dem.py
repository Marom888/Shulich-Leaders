"""D_COPDEM – Copernicus DEM GLO-30 (global, 1 arc-second ≈ 30 m).

PROPOSED ADDITION – not yet in the approved workbook (added for a global,
non-US Earth search; see config/exp10_datasets.json).

Access: Planetary Computer STAC collection ``cop-dem-glo-30`` (verified
2026-11-15): 1°x1° COG tiles, asset ``data``, EPSG:4326, global coverage
(-90..90).  Source: TanDEM-X radar interferometry.

It is a *surface* model (DSM): heights include vegetation and buildings –
fine for bare/sparse candidate terrain, misleading in forests or towns.
"""
from __future__ import annotations

from ...core import terrain
from ...core.aoi import AOI
from ...core.base import CoverageReport, DataProvider, DatasetInfo, FetchResult, ProductRef
from ...core.bodies import Body
from ...core.evidence import AccessMode, Evidence
from ...core.raster import Layer
from ...core.stac import PLANETARY_COMPUTER, PlanetaryComputerSigner
from ._stac_cog import choose_item, item_to_ref, layer_pixel_size_m, read_assets, stac_items

COLLECTION = "cop-dem-glo-30"


class CopernicusDEMProvider(DataProvider):
    info = DatasetInfo(
        dataset_id="D_COPDEM", name="Copernicus DEM GLO-30", body="Earth", provider="ESA / Airbus (via Planetary Computer)",
        resolution="1 arc-second (~30 m)", evidence=Evidence.MEASURED_DERIVED, access=AccessMode.AUTOMATED,
        access_notes="STAC search + COG window reads (anonymous SAS). PROPOSED addition to the workbook.",
        endpoints=(PLANETARY_COMPUTER + "/collections/" + COLLECTION,),
        workbook_source_url="",
        known_limits="Surface model (vegetation/buildings included); 30 m cannot resolve lander-leg geometry (R07).",
    )

    def search(self, aoi: AOI, **kw) -> list[ProductRef]:
        self.check_body(aoi, (Body.EARTH,))
        return [item_to_ref(i) for i in stac_items(self, PLANETARY_COMPUTER, COLLECTION, aoi)]

    def check_coverage(self, aoi: AOI) -> CoverageReport:
        self.check_body(aoi, (Body.EARTH,))
        return CoverageReport(self.info.dataset_id, True, "global 1-degree tiles (ocean tiles absent)")

    def fetch(self, aoi: AOI, derive: bool = True, **kw) -> FetchResult:
        self.check_body(aoi, (Body.EARTH,))
        item, full = choose_item(stac_items(self, PLANETARY_COMPUTER, COLLECTION, aoi), aoi)
        res = FetchResult(self.info.dataset_id, aoi, metadata={"stac_item": item["id"],
                                                               "platform": item["properties"].get("platform")})
        if not full:
            res.warn("AOI crosses a 1-degree tile boundary; first tile only")
        signer = PlanetaryComputerSigner(self.http)
        read_assets(self, res, item, aoi, {"elevation": ("data", "m (EGM2008)", Evidence.MEASURED_DERIVED, 1.0,
                                                         "Copernicus DSM GLO-30")},
                    sign=lambda h: signer.sign(h, COLLECTION))
        if derive and "elevation" in res.layers:
            dem = res.layers["elevation"]
            dx, dy = layer_pixel_size_m(dem, aoi.lat)
            res.layers.add(Layer("slope_derived", terrain.slope_horn(dem.data, dx, dy), dem.transform, dem.crs, "deg",
                                 Evidence.DERIVED_HERE, self.info.dataset_id, f"Horn slope at ~{dx:.0f} m support"))
            res.metadata["pixel_size_m"] = [dx, dy]
        return res
