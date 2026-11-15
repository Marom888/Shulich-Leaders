"""Shared logic for Earth datasets served as COGs through a STAC API."""
from __future__ import annotations

import math
from typing import Callable, Optional

from ...core.aoi import AOI
from ...core.base import FetchResult, NotCovered, ProductRef
from ...core.bodies import earth_radii_m
from ...core.evidence import Evidence
from ...core.raster import Layer, read_window_lonlat, write_geotiff
from ...core.stac import StacClient
from ...core.storage import utc_now_iso


def bbox_contains(outer, inner) -> bool:
    return outer[0] <= inner[0] and outer[1] <= inner[1] and outer[2] >= inner[2] and outer[3] >= inner[3]


def stac_items(provider, root: str, collection: str, aoi: AOI, **kw) -> list[dict]:
    return list(StacClient(root, provider.http).search([collection], aoi.geographic_bbox(), **kw))


def item_to_ref(item: dict) -> ProductRef:
    return ProductRef(product_id=item["id"], urls={k: a["href"] for k, a in item.get("assets", {}).items()},
                      bbox=tuple(item["bbox"]) if item.get("bbox") else None,
                      datetime=item.get("properties", {}).get("datetime"), properties=item.get("properties", {}))


def choose_item(items: list[dict], aoi: AOI, key: Optional[Callable[[dict], float]] = None) -> tuple[dict, bool]:
    """Prefer items whose bbox fully contains the AOI; then by ``key`` (lower = better)."""
    if not items:
        raise NotCovered("no STAC item intersects the AOI")
    box = aoi.geographic_bbox()
    full = [i for i in items if i.get("bbox") and bbox_contains(i["bbox"], box)]
    pool = full or items
    if key:
        pool = sorted(pool, key=key)
    return pool[0], bool(full)


def read_assets(provider, res: FetchResult, item: dict, aoi: AOI, assets: dict, *,
                sign: Optional[Callable[[str], str]] = None, save: bool = True):
    """assets: layer_name -> (asset_key, units, Evidence, scale, description)."""
    box = aoi.geographic_bbox()
    for lname, (akey, units, ev, scale, desc) in assets.items():
        if akey not in item.get("assets", {}):
            res.warn(f"item {item['id']} has no asset '{akey}'")
            continue
        href = item["assets"][akey]["href"]
        url = sign(href) if sign else href
        lyr = read_window_lonlat(url, box, name=lname, units=units, evidence=ev, scale=scale,
                                 dataset_id=provider.info.dataset_id, description=desc)
        lyr.source_url = href  # never store signed (token) URLs
        lyr.extra.update({"stac_item": item["id"], "datetime": item.get("properties", {}).get("datetime")})
        res.add_layer(lyr)
        if save:
            p = provider.store.raw_dir("earth", provider.info.dataset_id, item["id"]) / f"{lname}__aoi.tif"
            write_geotiff(lyr, p)
            provider.store.write_metadata(p, {
                "dataset_id": provider.info.dataset_id, "dataset_name": provider.info.name,
                "kind": "AOI window of original COG (no resampling)", "stac_item": item["id"],
                "source_url": href, "product_date": item.get("properties", {}).get("datetime"),
                "crs": lyr.crs, "resolution": list(lyr.resolution), "units": units, "evidence": ev.value,
                "download_utc": utc_now_iso(), "path": str(p), "stats": lyr.stats()})
            res.files.append(str(p))


def geographic_pixel_size_m(lat_deg: float, dlon_deg: float, dlat_deg: float) -> tuple[float, float]:
    m, n = earth_radii_m(lat_deg)
    return (math.radians(abs(dlon_deg)) * n * math.cos(math.radians(lat_deg)), math.radians(abs(dlat_deg)) * m)


def layer_pixel_size_m(lyr: Layer, lat_deg: float) -> tuple[float, float]:
    """Pixel size in metres, handling geographic (degree) grids."""
    dx, dy = lyr.resolution
    if "4326" in lyr.crs or "longlat" in lyr.crs.lower() or dx < 0.1:
        return geographic_pixel_size_m(lat_deg, dx, dy)
    return dx, dy


__all__ = ["stac_items", "item_to_ref", "choose_item", "read_assets", "layer_pixel_size_m", "Evidence"]
