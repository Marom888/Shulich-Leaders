"""Verified catalogue of established terrestrial analog / reference sites (Ordinary Search).

The catalogue ships EMPTY (team decision 2026-11-15). Every entry must carry
provenance; entries without a citation are rejected. Being listed here does
not mean NASA approved the site, and nothing here ranks sites.
"""
from __future__ import annotations

import json
from pathlib import Path

from lunarmatch.config import PROJECT_ROOT

CATALOG_PATH = PROJECT_ROOT / "data" / "reference" / "analog_sites.json"
SCHEMA = "rookie-analog-catalog/1"
REQUIRED = ("site_id", "name", "lat", "lon", "radius_km", "role", "source_citation",
            "source_url", "verified_by", "verified_on")


class CatalogError(ValueError):
    pass


def validate_entry(e: dict) -> None:
    missing = [k for k in REQUIRED if e.get(k) in (None, "")]
    if missing:
        raise CatalogError(f"{e.get('site_id', '?')}: missing {missing} (provenance is mandatory)")
    if not (-90 <= float(e["lat"]) <= 90 and -180 <= float(e["lon"]) <= 180):
        raise CatalogError(f"{e['site_id']}: coordinates out of range")
    if float(e["radius_km"]) <= 0:
        raise CatalogError(f"{e['site_id']}: radius_km must be > 0")
    if "nasa" in str(e.get("role", "")).lower() and "approved" in str(e.get("role", "")).lower():
        raise CatalogError(f"{e['site_id']}: do not label entries 'NASA approved' without evidence")


def load_catalog(path: Path = CATALOG_PATH) -> dict:
    path = Path(path)
    if not path.is_file():
        return {"schema": SCHEMA, "sites": [], "status": "catalogue file missing"}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        raise CatalogError(f"unsupported catalogue schema {data.get('schema')!r}")
    ids = set()
    for e in data.get("sites", []):
        validate_entry(e)
        if e["site_id"] in ids:
            raise CatalogError(f"duplicate site_id {e['site_id']}")
        ids.add(e["site_id"])
    data["status"] = "ok" if data["sites"] else "empty: no verified entries yet"
    return data
