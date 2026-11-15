"""Client for the PDS Geosciences Node Orbital Data Explorer (ODE) REST API.

Verified live on 2026-11-15:
  https://oderest.rsl.wustl.edu/live2/?query=product&target=moon&output=JSON
      &ihid=LRO&iid=LROC&pt=SDNDTM&minlat=..&maxlat=..&westlon=..&eastlon=..
returns ``ODEResults.Products.Product[]`` each with ``Product_files.Product_file[]``
(Description, FileName, KBytes, Type, URL).  Product types (``pt``) used here,
as listed by ``query=iipy&target=moon``:

* LRO/LROC  SDNDTM  – NAC Digital Terrain Models (GeoTIFF DTM, ortho, confidence)
* LRO/LROC  CDRNAC4 – calibrated NAC images (PDS IMG, NOT map-projected)
* LRO/LOLA  GDRDEM / GDRDSM / GDRDRM – gridded shape / slope / roughness maps
* KPLO/ShadowCam  DTM, CMOS (controlled mosaic), UMOS, CAL

ODE longitudes are 0..360 East.  Spatial filtering is done server-side
against product footprints.
"""
from __future__ import annotations

from typing import Any, Optional

from .base import ProductRef
from .http import HttpClient, default_client

ODE_REST = "https://oderest.rsl.wustl.edu/live2/"


def _as_list(x) -> list:
    if x is None or isinstance(x, str):
        return []
    return x if isinstance(x, list) else [x]


class OdeClient:
    def __init__(self, client: Optional[HttpClient] = None, base: str = ODE_REST):
        self.http = client or default_client()
        self.base = base

    def product_search(self, *, ihid: str, iid: str, pt: str,
                       bbox_lon360: tuple[float, float, float, float],
                       target: str = "moon", limit: int = 100, offset: int = 0,
                       extra: Optional[dict] = None) -> list[dict[str, Any]]:
        west, south, east, north = bbox_lon360
        params = {
            # results=fp is the form verified to return Product_files with URLs
            "query": "product", "target": target, "output": "JSON", "results": "fp",
            "ihid": ihid, "iid": iid, "pt": pt,
            "minlat": south, "maxlat": north, "westlon": west, "eastlon": east,
            "limit": limit, "offset": offset,
        }
        if extra:
            params.update(extra)
        j = self.http.get_json(self.base, params=params)
        res = j.get("ODEResults", {})
        if res.get("Status") not in (None, "Success"):
            raise RuntimeError(f"ODE error: {res.get('Error') or res}")
        return _as_list((res.get("Products") or {}).get("Product") if isinstance(res.get("Products"), dict) else None)

    @staticmethod
    def to_product_ref(p: dict[str, Any]) -> ProductRef:
        urls, sizes = {}, {}
        for f in _as_list((p.get("Product_files") or {}).get("Product_file")):
            if not isinstance(f, dict) or "URL" not in f:
                continue
            key = f"{f.get('Description', '').strip()} :: {f.get('FileName', '')}"
            urls[key] = f["URL"]
            try:
                sizes[key] = int(float(f.get("KBytes", 0)) * 1024)
            except ValueError:
                pass
        bbox = None
        try:
            bbox = (float(p["Westernmost_longitude"]), float(p["Minimum_latitude"]),
                    float(p["Easternmost_longitude"]), float(p["Maximum_latitude"]))
        except (KeyError, ValueError, TypeError):
            pass
        props = {k: v for k, v in p.items() if k != "Product_files"}
        pid = p.get("pdsid") or ""
        if not pid and urls:  # some PDS4 derived products (e.g. ShadowCam) carry no pdsid
            pid = next(iter(urls)).split(" :: ", 1)[1].rsplit(".", 1)[0]
        return ProductRef(product_id=pid, title=p.get("Product_title", ""), urls=urls,
                          sizes=sizes, bbox=bbox, datetime=p.get("Observation_time") or p.get("UTC_start_time"),
                          properties=props)

    @staticmethod
    def pick_file(ref: ProductRef, description_contains: str, filename_suffix: str = "") -> Optional[tuple[str, str, int]]:
        """Return (filename, url, size_bytes) of the first file whose description matches."""
        d = description_contains.upper()
        for key, url in ref.urls.items():
            desc, fname = key.split(" :: ", 1)
            if d in desc.upper() and fname.upper().endswith(filename_suffix.upper()):
                return fname, url, ref.sizes.get(key, 0)
        return None
