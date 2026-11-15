"""D_OSM – OpenStreetMap roads/tracks for field-logistics (kept separate from science scores, R04).

Access: Overpass API ``https://overpass-api.de/api/interpreter`` (verified
reachable 2026-11-15; it returned "at capacity / retry with back-off", which
is normal for the public instance).  Additional mirrors can be configured
with the LUNARMATCH_OVERPASS env var (comma-separated URLs).
Respect the public instance: small bounding boxes, back-off on 429/504.
"""
from __future__ import annotations

import math
import os
import time

from ...core.aoi import AOI
from ...core.base import CoverageReport, DataProvider, DatasetInfo, FetchResult, ProviderError
from ...core.bodies import Body
from ...core.evidence import AccessMode, Evidence
from ...core.storage import utc_now_iso
from .wosis import _haversine_km

OVERPASS = "https://overpass-api.de/api/interpreter"
ROAD_TYPES = "motorway|trunk|primary|secondary|tertiary|unclassified|residential|service|track"


class OSMProvider(DataProvider):
    info = DatasetInfo(
        dataset_id="D_OSM", name="OpenStreetMap roads/access", body="Earth", provider="OSM contributors (ODbL)",
        resolution="vector", evidence=Evidence.MEASURED, access=AccessMode.AUTOMATED,
        access_notes="Overpass QL query for highways within (AOI + search radius).",
        endpoints=(OVERPASS,), workbook_source_url="https://www.openstreetmap.org/",
        known_limits="Uneven coverage; permits/accessibility need external verification; logistics only.",
    )

    def endpoints(self) -> list[str]:
        extra = [u.strip() for u in os.environ.get("LUNARMATCH_OVERPASS", "").split(",") if u.strip()]
        return extra + [OVERPASS]

    def check_coverage(self, aoi: AOI) -> CoverageReport:
        self.check_body(aoi, (Body.EARTH,))
        return CoverageReport(self.info.dataset_id, None, "global but uneven – run fetch to see what is mapped")

    def _query(self, q: str) -> dict:
        last = None
        for url in self.endpoints():
            for attempt in range(4):
                r = self.http.session.post(url, data={"data": q}, timeout=(15, 200))
                if r.status_code == 200:
                    return r.json()
                last = f"{url}: HTTP {r.status_code} {r.text[:200]}"
                time.sleep(min(60, 5 * 2 ** attempt))
        raise ProviderError(f"Overpass unavailable: {last}")

    def fetch(self, aoi: AOI, search_radius_km: float = 10.0, **kw) -> FetchResult:
        self.check_body(aoi, (Body.EARTH,))
        big = AOI(aoi.body, aoi.lat, aoi.lon, aoi.width_m + 2000 * search_radius_km,
                  aoi.height_m + 2000 * search_radius_km)
        w, s, e, n = big.geographic_bbox()
        q = f'[out:json][timeout:180];way["highway"~"^({ROAD_TYPES})$"]({s},{w},{n},{e});out tags geom;'
        j = self._query(q)
        rows = []
        for el in j.get("elements", []):
            geom = el.get("geometry") or []
            if not geom:
                continue
            d = min(_haversine_km(aoi.lat, aoi.lon, p["lat"], p["lon"]) for p in geom)
            rows.append({"osm_id": el.get("id"), "highway": el.get("tags", {}).get("highway"),
                         "surface": el.get("tags", {}).get("surface"), "name": el.get("tags", {}).get("name"),
                         "min_distance_km_to_vertex": d, "n_vertices": len(geom)})
        rows.sort(key=lambda r: r["min_distance_km_to_vertex"])
        res = FetchResult(self.info.dataset_id, aoi, metadata={"bbox": (w, s, e, n), "query": q,
                                                               "fetched_utc": utc_now_iso(),
                                                               "license": "ODbL 1.0 – (c) OpenStreetMap contributors"})
        res.tables["roads"] = rows
        res.metadata["nearest_road_km"] = rows[0]["min_distance_km_to_vertex"] if rows else math.inf
        if not rows:
            res.warn(f"no mapped road/track within ~{search_radius_km} km (could be unmapped, not absent)")
        return res
