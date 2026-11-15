"""D_WOSIS – ISRIC World Soil Information Service, ``wosis_latest`` point data.

Access: OGC WFS 2.0 at ``https://maps.isric.org/mapserv?map=/map/wosis_latest.map``
(verified 2026-11-15; no authentication).  Feature types include
``ms:wosis_latest_profiles``, ``ms:wosis_latest_bdfi33`` (bulk density fine
earth @33 kPa), ``..._bdfiod``, ``..._bdwsod``, ``..._sand``, ``..._silt``,
``..._clay``, ``..._cfvo``, ``..._orgc``, ...  Output formats offered include
``application/json; subtype=geojson`` and ``text/csv``.

Spatial subsetting is done server-side with a BBOX filter, so only the
profiles around the AOI are transferred.
"""
from __future__ import annotations

import math

from ...core.aoi import AOI
from ...core.base import CoverageReport, DataProvider, DatasetInfo, FetchResult
from ...core.bodies import Body
from ...core.evidence import AccessMode, Evidence
from ...core.storage import utc_now_iso

WFS = "https://maps.isric.org/mapserv?map=/map/wosis_latest.map"
DEFAULT_LAYERS = ("profiles", "bdfi33", "bdfiod", "sand", "silt", "clay", "cfvo")


class WoSISProvider(DataProvider):
    info = DatasetInfo(
        dataset_id="D_WOSIS", name="WoSIS point soil observations (wosis_latest)", body="Earth", provider="ISRIC",
        resolution="point", evidence=Evidence.MEASURED, access=AccessMode.AUTOMATED,
        access_notes="WFS 2.0 GetFeature with BBOX, GeoJSON output.",
        endpoints=(WFS,), workbook_source_url="https://isric.org/explore/wosis",
        known_limits="Sparse, uneven density; heterogeneous lab protocols; no friction angle guaranteed.",
    )

    def get_features(self, layer: str, bbox_lonlat, count: int = 5000) -> list[dict]:
        w, s, e, n = bbox_lonlat
        params = {
            "SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
            "TYPENAMES": f"ms:wosis_latest_{layer}",
            # WFS 2.0 + EPSG:4326 URN => lat,lon axis order
            "BBOX": f"{s},{w},{n},{e},urn:ogc:def:crs:EPSG::4326",
            "OUTPUTFORMAT": "application/json; subtype=geojson", "COUNT": count,
        }
        r = self.http.get(WFS, params=params)
        j = r.json()
        out = []
        for f in j.get("features", []):
            props = dict(f.get("properties", {}))
            geom = f.get("geometry") or {}
            if geom.get("type") == "Point":
                props["lon"], props["lat"] = geom["coordinates"][:2]
            props["evidence"] = Evidence.MEASURED.value
            out.append(props)
        return out

    def check_coverage(self, aoi: AOI) -> CoverageReport:
        self.check_body(aoi, (Body.EARTH,))
        prof = self.get_features("profiles", aoi.geographic_bbox(), count=50)
        return CoverageReport(self.info.dataset_id, bool(prof), f"{len(prof)} profile(s) inside the AOI")

    def fetch(self, aoi: AOI, layers=DEFAULT_LAYERS, search_radius_km: float = 0.0, **kw) -> FetchResult:
        """Return attribute tables for profiles inside the AOI (optionally enlarged).

        Point data are sparse: use ``search_radius_km`` to look around the AOI.
        Distances from the AOI centre are added to every row.
        """
        self.check_body(aoi, (Body.EARTH,))
        big = AOI(aoi.body, aoi.lat, aoi.lon, max(aoi.width_m, 2000 * search_radius_km),
                  max(aoi.height_m, 2000 * search_radius_km))
        box = big.geographic_bbox()
        res = FetchResult(self.info.dataset_id, aoi, metadata={"bbox_used": box, "wfs": WFS})
        for layer in layers:
            rows = self.get_features(layer, box)
            for r in rows:
                if "lat" in r:
                    r["distance_km"] = _haversine_km(aoi.lat, aoi.lon, r["lat"], r["lon"])
            res.tables[layer] = sorted(rows, key=lambda r: r.get("distance_km", math.inf))
        if not res.tables.get("profiles"):
            res.warn("no WoSIS profiles in the search box; increase search_radius_km")
        import json

        p = self.store.raw_dir("earth", self.info.dataset_id) / f"wosis_{aoi.lat:.4f}_{aoi.lon:.4f}.json"
        p.write_text(json.dumps(res.tables, default=str))
        self.store.write_metadata(p, {"dataset_id": self.info.dataset_id, "source_url": WFS, "bbox": box,
                                      "layers": list(layers), "evidence": "MEASURED", "download_utc": utc_now_iso()})
        res.files.append(str(p))
        return res


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
