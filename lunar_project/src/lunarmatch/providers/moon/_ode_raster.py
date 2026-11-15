"""Shared helpers for lunar raster products discovered through ODE."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

from ...core.aoi import AOI
from ...core.base import FetchResult, ProductRef, ProviderError
from ...core.evidence import Evidence
from ...core.ode import OdeClient
from ...core.raster import Layer, read_window_native, write_geotiff
from ...core.storage import utc_now_iso


def aoi_bounds_in_crs(aoi: AOI, crs_wkt: str) -> tuple[float, float, float, float]:
    """AOI box in the native CRS of a lunar raster (needs pyproj for non-polar CRSs)."""
    try:
        from pyproj import CRS, Transformer
    except ImportError as exc:  # pragma: no cover
        raise ImportError("pyproj is required to map an AOI into a lunar product CRS: pip install pyproj") from exc
    crs = CRS.from_user_input(crs_wkt)
    geo = crs.geodetic_crs  # the product's own lunar geographic CRS (sphere radius from the file)
    tr = Transformer.from_crs(geo, crs, always_xy=True)
    x, y = tr.transform(aoi.lon, aoi.lat)
    # Local scale: project a point 1 m north/east (on the product's sphere) and measure
    r = geo.ellipsoid.semi_major_metre
    dlat = math.degrees(1.0 / r)
    dlon = math.degrees(1.0 / (r * max(math.cos(math.radians(aoi.lat)), 1e-6)))
    xe, ye = tr.transform(aoi.lon + dlon, aoi.lat)
    xn, yn = tr.transform(aoi.lon, aoi.lat + dlat)
    kx = math.hypot(xe - x, ye - y) or 1.0
    ky = math.hypot(xn - x, yn - y) or 1.0
    k = max(kx, ky)
    hw, hh = k * aoi.width_m / 2, k * aoi.height_m / 2
    return (x - hw, y - hh, x + hw, y + hh)


def download_and_window(provider, ref: ProductRef, desc: str, suffix: str, aoi: AOI, *, layer_name: str,
                        units: str, evidence: Evidence, subdir: str, max_bytes: Optional[int] = None,
                        band: int = 1) -> tuple[Optional[Layer], Optional[Path]]:
    picked = OdeClient.pick_file(ref, desc, suffix)
    if not picked:
        return None, None
    fname, url, size = picked
    if max_bytes and size and size > max_bytes:
        raise ProviderError(f"{fname} is {size / 1e6:.0f} MB > max_bytes; pass a larger max_bytes to download it")
    dest = provider.store.raw_dir("moon", provider.info.dataset_id, subdir) / fname
    provider.http.download(url, dest)
    if not provider.store.has(dest):
        provider.store.write_metadata(dest, {
            "dataset_id": provider.info.dataset_id, "dataset_name": provider.info.name, "kind": "raw product file",
            "product_id": ref.product_id, "source_url": url, "product_date": ref.properties.get("Product_creation_time"),
            "download_utc": utc_now_iso(), "path": str(dest)})
    import rasterio  # required to read these GeoTIFFs (CRS is a lunar WKT)

    with rasterio.open(dest) as src:
        bounds = aoi_bounds_in_crs(aoi, src.crs.to_wkt())
    lyr = read_window_native(str(dest), bounds, name=layer_name, units=units, evidence=evidence,
                             dataset_id=provider.info.dataset_id, band=band,
                             description=f"{desc} from {ref.product_id}")
    lyr.source_url = url
    return lyr, dest


def save_processed(provider, res: FetchResult, lyr: Layer, product_id: str):
    p = provider.store.processed_dir("moon", provider.info.dataset_id, product_id) / f"{lyr.name}_aoi.tif"
    write_geotiff(lyr, p)
    provider.store.write_metadata(p, {"dataset_id": provider.info.dataset_id, "kind": "AOI window",
                                      "product_id": product_id, "source_url": lyr.source_url, "units": lyr.units,
                                      "evidence": lyr.evidence.value, "crs": lyr.crs,
                                      "resolution": list(lyr.resolution), "stats": lyr.stats(), "path": str(p)})
    res.files.append(str(p))
