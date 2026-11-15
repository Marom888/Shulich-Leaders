"""D_SOILGRIDS – ISRIC SoilGrids 2.0 (250 m, modelled soil properties, 6 depths).

Verified access paths (2026-11-15):
* Point query REST API:
  ``https://rest.isric.org/soilgrids/v2.0/properties/query?lon=..&lat=..&property=bdod&depth=0-5cm&value=mean``
  returns mapped values + ``unit_measure.d_factor`` (e.g. bdod in cg/cm3, d_factor 100 -> kg/dm3).
  ISRIC describes it as a fair-use service; keep request rates low.
* Area windows: VRT mosaics of COGs at
  ``https://files.isric.org/soilgrids/latest/data/<prop>/<prop>_<depth>_<stat>.vrt``
  (Interrupted Goode Homolosine, 250 m) – read with rasterio range requests.

Workbook policy (R08): screening only – NOT bearing capacity, NOT lunar
regolith granulometry.  Uncertainty: request Q0.05/Q0.95 or ``uncertainty``.
"""
from __future__ import annotations

from typing import Iterable

from ...core.aoi import AOI
from ...core.base import CoverageReport, DataProvider, DatasetInfo, FetchResult
from ...core.bodies import Body
from ...core.evidence import AccessMode, Evidence
from ...core.raster import read_window_lonlat, write_geotiff
from ...core.storage import utc_now_iso

REST = "https://rest.isric.org/soilgrids/v2.0/properties/query"
VRT = "https://files.isric.org/soilgrids/latest/data/{prop}/{prop}_{depth}_{stat}.vrt"
DEPTHS = ("0-5cm", "5-15cm", "15-30cm", "30-60cm", "60-100cm", "100-200cm")
# property -> (mapped units, conversion factor to target units, target units) per ISRIC docs/response
PROPERTIES = {
    "bdod": ("cg/cm3", 100, "g/cm3"),
    "sand": ("g/kg", 10, "%"),
    "silt": ("g/kg", 10, "%"),
    "clay": ("g/kg", 10, "%"),
    "cfvo": ("cm3/dm3", 10, "vol %"),
    "soc": ("dg/kg", 10, "g/kg"),
}


class SoilGridsProvider(DataProvider):
    info = DatasetInfo(
        dataset_id="D_SOILGRIDS", name="SoilGrids 2.0", body="Earth", provider="ISRIC",
        resolution="250 m; depths 0-200 cm", evidence=Evidence.MODELED, access=AccessMode.AUTOMATED,
        access_notes="REST point profiles (fair use) + VRT/COG area windows via rasterio.",
        endpoints=(REST, "https://files.isric.org/soilgrids/latest/data/"),
        workbook_source_url="https://isric.org/explore/soilgrids",
        known_limits="Very coarse for a footpad; modelled, not bearing capacity (R08).",
    )

    def check_coverage(self, aoi: AOI) -> CoverageReport:
        self.check_body(aoi, (Body.EARTH,))
        return CoverageReport(self.info.dataset_id, None, "most global land; check returned values for nulls")

    def point_profile(self, lat: float, lon: float, properties: Iterable[str] = ("bdod", "sand", "silt", "clay", "cfvo"),
                      depths: Iterable[str] = DEPTHS, values=("mean", "Q0.05", "Q0.95", "uncertainty")) -> list[dict]:
        params = [("lon", lon), ("lat", lat)] + [("property", p) for p in properties] + \
                 [("depth", d) for d in depths] + [("value", v) for v in values]
        j = self.http.get_json(REST, params=params)
        return parse_rest_response(j)

    def fetch(self, aoi: AOI, properties=("bdod", "sand", "silt", "clay", "cfvo"), depths=("0-5cm", "5-15cm"),
              area: bool = False, stat: str = "mean", **kw) -> FetchResult:
        """Point profile at the AOI centre (default) and optionally 250 m area windows."""
        self.check_body(aoi, (Body.EARTH,))
        res = FetchResult(self.info.dataset_id, aoi, metadata={"evidence": Evidence.MODELED.value,
                                                               "policy": "screening only (workbook R08)"})
        rows = self.point_profile(aoi.lat, aoi.lon, properties, depths)
        res.tables["profile_at_center"] = rows
        if any(r["mean"] is None for r in rows):
            res.warn("some SoilGrids values are null (water, rock outcrop, urban or masked area)")
        if area:
            for prop in properties:
                f, tu = PROPERTIES.get(prop, ("", 1, ""))[1:]
                for d in depths:
                    href = VRT.format(prop=prop, depth=d, stat=stat)
                    lyr = read_window_lonlat(href, aoi.geographic_bbox(), name=f"{prop}_{d}_{stat}", units=tu,
                                             evidence=Evidence.MODELED, dataset_id=self.info.dataset_id,
                                             scale=1.0 / f, description=f"SoilGrids {prop} {d} {stat}")
                    res.add_layer(lyr)
                    p = self.store.raw_dir("earth", self.info.dataset_id) / f"{prop}_{d}_{stat}__aoi.tif"
                    write_geotiff(lyr, p)
                    self.store.write_metadata(p, {"dataset_id": self.info.dataset_id, "source_url": href,
                                                  "units": tu, "evidence": "MODELED", "crs": lyr.crs,
                                                  "resolution": list(lyr.resolution), "download_utc": utc_now_iso(),
                                                  "path": str(p)})
                    res.files.append(str(p))
        return res


def parse_rest_response(j: dict) -> list[dict]:
    """Flatten the SoilGrids REST JSON into rows with values converted to target units."""
    rows = []
    for layer in j.get("properties", {}).get("layers", []):
        um = layer.get("unit_measure", {})
        d = um.get("d_factor", 1) or 1
        for depth in layer.get("depths", []):
            vals = depth.get("values", {})
            row = {"property": layer.get("name"), "depth": depth.get("label"),
                   "top_cm": depth.get("range", {}).get("top_depth"),
                   "bottom_cm": depth.get("range", {}).get("bottom_depth"),
                   "units": um.get("target_units"), "mapped_units": um.get("mapped_units"), "d_factor": d,
                   "evidence": Evidence.MODELED.value}
            for k, v in vals.items():
                # 'uncertainty' is ISRIC's relative uncertainty index – kept as returned (not unit-converted)
                row[k] = (v / d) if (v is not None and k != "uncertainty") else v
            row.setdefault("mean", None)
            rows.append(row)
    return rows
