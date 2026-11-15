"""D_NAIP – USDA National Agriculture Imagery Program (0.6–1 m RGB+NIR, USA).

Access: Planetary Computer STAC collection ``naip`` (verified 2026-11-15):
asset ``image`` is a 4-band COG (R, G, B, NIR) in UTM; anonymous SAS token.
Only the AOI window is transferred.
"""
from __future__ import annotations

from ...core.aoi import AOI
from ...core.base import CoverageReport, DataProvider, DatasetInfo, FetchResult, ProductRef
from ...core.bodies import Body
from ...core.evidence import AccessMode, Evidence
from ...core.raster import read_window_lonlat
from ...core.stac import PLANETARY_COMPUTER, PlanetaryComputerSigner
from ._stac_cog import choose_item, item_to_ref, stac_items

BANDS = {"red": 1, "green": 2, "blue": 3, "nir": 4}


class NAIPProvider(DataProvider):
    info = DatasetInfo(
        dataset_id="D_NAIP", name="USDA NAIP", body="Earth", provider="USDA (via Microsoft Planetary Computer)",
        resolution="~0.6-1 m", evidence=Evidence.MEASURED, access=AccessMode.AUTOMATED,
        access_notes="STAC search, newest acquisition first, COG window reads.",
        endpoints=(PLANETARY_COMPUTER + "/collections/naip",),
        workbook_source_url="https://naip-usdaonline.hub.arcgis.com/",
        known_limits="USA only; acquired near midday in leaf-on season – illumination differs from lunar scenes.",
    )

    def search(self, aoi: AOI, **kw) -> list[ProductRef]:
        self.check_body(aoi, (Body.EARTH,))
        return [item_to_ref(i) for i in stac_items(self, PLANETARY_COMPUTER, "naip", aoi,
                                                   sortby=[{"field": "datetime", "direction": "desc"}])]

    def check_coverage(self, aoi: AOI) -> CoverageReport:
        refs = self.search(aoi)
        return CoverageReport(self.info.dataset_id, bool(refs), f"{len(refs)} NAIP scene(s)", [r.product_id for r in refs])

    def fetch(self, aoi: AOI, bands=("red", "green", "blue", "nir"), year: str = None, **kw) -> FetchResult:
        self.check_body(aoi, (Body.EARTH,))
        dt = f"{year}-01-01/{year}-12-31" if year else None
        items = stac_items(self, PLANETARY_COMPUTER, "naip", aoi, datetime=dt,
                           sortby=[{"field": "datetime", "direction": "desc"}])
        item, full = choose_item(items, aoi)
        res = FetchResult(self.info.dataset_id, aoi, metadata={"stac_item": item["id"],
                                                               "datetime": item["properties"].get("datetime"),
                                                               "gsd": item["properties"].get("gsd")})
        if not full:
            res.warn("AOI not inside a single NAIP quarter-quad; first scene only")
        href = item["assets"]["image"]["href"]
        url = PlanetaryComputerSigner(self.http).sign(href, "naip")
        for b in bands:
            lyr = read_window_lonlat(url, aoi.geographic_bbox(), name=b, band=BANDS[b], units="DN (8-bit)",
                                     evidence=Evidence.MEASURED, dataset_id=self.info.dataset_id,
                                     description=f"NAIP {b} band")
            lyr.source_url = href
            res.add_layer(lyr)
        return res
