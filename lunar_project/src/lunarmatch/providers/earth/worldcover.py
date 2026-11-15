"""D_WORLDCOVER – ESA WorldCover 10 m land cover (v200, 2021).

Access: Planetary Computer STAC collection ``esa-worldcover`` (verified
2026-11-15), asset ``map`` = 3°x3° COG tiles; ``input_quality`` also available.
Class 60 = "Bare / sparse vegetation" (pre-screening filter, NOT proof of
lunar analogy – workbook D_WORLDCOVER).
"""
from __future__ import annotations

import numpy as np

from ...core.aoi import AOI
from ...core.base import CoverageReport, DataProvider, DatasetInfo, FetchResult, ProductRef
from ...core.bodies import Body
from ...core.evidence import AccessMode, Evidence
from ...core.stac import PLANETARY_COMPUTER, PlanetaryComputerSigner
from ._stac_cog import choose_item, item_to_ref, read_assets, stac_items

CLASSES = {10: "Tree cover", 20: "Shrubland", 30: "Grassland", 40: "Cropland", 50: "Built-up",
           60: "Bare / sparse vegetation", 70: "Snow and ice", 80: "Permanent water bodies",
           90: "Herbaceous wetland", 95: "Mangroves", 100: "Moss and lichen"}


class WorldCoverProvider(DataProvider):
    info = DatasetInfo(
        dataset_id="D_WORLDCOVER", name="ESA WorldCover 2021", body="Earth", provider="ESA (via Planetary Computer)",
        resolution="10 m", evidence=Evidence.MODELED, access=AccessMode.AUTOMATED,
        access_notes="STAC search, COG window reads; class fractions computed for the AOI.",
        endpoints=(PLANETARY_COMPUTER + "/collections/esa-worldcover",),
        workbook_source_url="https://esa-worldcover.org/en/data-access",
        known_limits="Class map is a screening filter, not physical lunar analog proof.",
    )

    def search(self, aoi: AOI, **kw) -> list[ProductRef]:
        self.check_body(aoi, (Body.EARTH,))
        return [item_to_ref(i) for i in stac_items(self, PLANETARY_COMPUTER, "esa-worldcover", aoi)]

    def check_coverage(self, aoi: AOI) -> CoverageReport:
        ok = -60 <= aoi.lat <= 82.75
        return CoverageReport(self.info.dataset_id, ok, "global land 60S-82.75N")

    def fetch(self, aoi: AOI, **kw) -> FetchResult:
        self.check_body(aoi, (Body.EARTH,))
        items = stac_items(self, PLANETARY_COMPUTER, "esa-worldcover", aoi)
        items = [i for i in items if "v200" in i["id"]] or items
        item, full = choose_item(items, aoi)
        res = FetchResult(self.info.dataset_id, aoi, metadata={"stac_item": item["id"]})
        if not full:
            res.warn("AOI crosses a 3-degree tile boundary; first tile only")
        signer = PlanetaryComputerSigner(self.http)
        read_assets(self, res, item, aoi, {"landcover": ("map", "class", Evidence.MODELED, 1.0, "WorldCover class")},
                    sign=lambda h: signer.sign(h, "esa-worldcover"))
        lc = res.layers["landcover"].data
        valid = np.isfinite(lc) & (lc > 0)
        rows = []
        for code, name in CLASSES.items():
            frac = float((lc[valid] == code).mean()) if valid.any() else 0.0
            if frac > 0:
                rows.append({"class": code, "name": name, "fraction": frac})
        res.tables["class_fractions"] = sorted(rows, key=lambda r: -r["fraction"])
        res.metadata["bare_sparse_fraction"] = next((r["fraction"] for r in rows if r["class"] == 60), 0.0)
        return res
