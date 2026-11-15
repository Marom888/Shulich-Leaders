"""D_TERN – TERN Soil and Landscape Grid of Australia (SLGA), ~90 m, 6 depths.

Access: OGC WCS 2.0.1 on TERN's GeoServer, one coverage service per
product.  The endpoint pattern
``https://geoserver.tern.org.au/geoserver/slga/<PRODUCT>/ows`` comes from the
official catalogue record for "Bulk Density – Whole Earth – Release 2"
(BDW_v2, data.gov.au / TERN GeoNetwork).  It was NOT live-tested from this
environment, so the provider first calls GetCapabilities and only requests
coverage ids that the server actually advertises.

TERN also publishes the same products as Cloud-Optimised GeoTIFFs; if you
have a COG URL from the SLGA "COGs Data Store" page, pass it as ``cog_url``
to read just the AOI window.
"""
from __future__ import annotations

import re
from typing import Optional

from ...core.aoi import AOI
from ...core.base import CoverageReport, DataProvider, DatasetInfo, FetchResult, NotCovered
from ...core.bodies import Body
from ...core.evidence import AccessMode, Evidence
from ...core.raster import read_window_lonlat, write_geotiff
from ...core.storage import utc_now_iso

WCS = "https://geoserver.tern.org.au/geoserver/slga/{product}/ows"
AUS_BBOX = (112.91, -43.65, 153.64, -10.0)


class TERNProvider(DataProvider):
    info = DatasetInfo(
        dataset_id="D_TERN", name="TERN Soil Landscape Grid of Australia", body="Earth", provider="TERN",
        resolution="~90 m (3 arc-sec)", evidence=Evidence.MODELED, access=AccessMode.AUTOMATED,
        access_notes="WCS 2.0.1 GetCoverage (endpoint from catalogue metadata; capabilities checked at runtime) "
                     "or COG window via cog_url.",
        endpoints=(WCS.format(product="BDW_v2"),),
        workbook_source_url="https://esoil.io/TERNLandscapes/Public/Pages/SLGA/ProductDetails.html",
        known_limits="Australia only; modelled, not direct shear/bearing observations.",
    )

    def check_coverage(self, aoi: AOI) -> CoverageReport:
        self.check_body(aoi, (Body.EARTH,))
        w, s, e, n = AUS_BBOX
        ok = w <= aoi.lon <= e and s <= aoi.lat <= n
        return CoverageReport(self.info.dataset_id, ok, "inside Australia bbox" if ok else "outside Australia")

    def coverage_ids(self, product: str = "BDW_v2") -> list[str]:
        r = self.http.get(WCS.format(product=product), params={"service": "WCS", "version": "2.0.1",
                                                               "request": "GetCapabilities"})
        return re.findall(r"<wcs:CoverageId>([^<]+)</wcs:CoverageId>", r.text)

    def fetch(self, aoi: AOI, product: str = "BDW_v2", coverage_id: Optional[str] = None,
              cog_url: Optional[str] = None, units: str = "g/cm3", **kw) -> FetchResult:
        if not self.check_coverage(aoi).covered:
            raise NotCovered("TERN SLGA covers Australia only")
        res = FetchResult(self.info.dataset_id, aoi, metadata={"product": product, "evidence": "MODELED"})
        w, s, e, n = aoi.geographic_bbox()
        if cog_url:
            lyr = read_window_lonlat(cog_url, (w, s, e, n), name=product, units=units, evidence=Evidence.MODELED,
                                     dataset_id=self.info.dataset_id, description=f"SLGA {product}")
            res.add_layer(lyr)
            return res
        ids = self.coverage_ids(product)
        if not ids:
            raise NotCovered(f"WCS for {product} advertises no coverages")
        cid = coverage_id or ids[0]
        if cid not in ids:
            raise NotCovered(f"coverage {cid} not offered; available: {ids}")
        url = WCS.format(product=product)
        params = [("service", "WCS"), ("version", "2.0.1"), ("request", "GetCoverage"), ("coverageId", cid),
                  ("format", "image/geotiff"), ("subset", f"Long({w},{e})"), ("subset", f"Lat({s},{n})")]
        dest = self.store.raw_dir("earth", self.info.dataset_id, product) / f"{cid.replace(':', '_')}__{aoi.lat:.4f}_{aoi.lon:.4f}.tif"
        r = self.http.get(url, params=params)
        if not r.headers.get("Content-Type", "").startswith("image/"):
            raise NotCovered(f"WCS returned {r.headers.get('Content-Type')}: {r.text[:300]}")
        dest.write_bytes(r.content)
        self.store.write_metadata(dest, {"dataset_id": self.info.dataset_id, "source_url": r.url, "coverage": cid,
                                         "units": units, "evidence": "MODELED", "download_utc": utc_now_iso()})
        res.files.append(str(dest))
        lyr = read_window_lonlat(str(dest), (w, s, e, n), name=cid, units=units, evidence=Evidence.MODELED,
                                 dataset_id=self.info.dataset_id, description=f"SLGA {cid}")
        res.add_layer(lyr)
        res.metadata["available_coverages"] = ids
        return res
