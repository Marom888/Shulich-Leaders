"""Stage A discovery run: tiles → windows → descriptors → filters → result.

Progress events are emitted only for work that actually happens. Coverage
is reported explicitly: a run over part of the Earth never claims to be a
global search. No similarity, score or rank is computed here.
"""
from __future__ import annotations

import operator
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from lunarmatch.config import EXTRACT_DIR
from lunarmatch.discovery import descriptors as dsc
from lunarmatch.discovery.sources import LocalSRTMSource
from lunarmatch.discovery.store import RESULT_SCHEMA, DescriptorCache, cache_key

EARTH_SURFACE_KM2 = 510_065_622.0   # WGS84 authalic sphere, for context only
MOON_SURFACE_KM2 = 4 * 3.141592653589793 * 1737.4 ** 2   # IAU 2015 sphere

GOVERNANCE = {
    "similarity_computed": False,
    "scores_computed": False,
    "ranking_computed": False,
    "note": ("Stage A screening only. Moon-Earth similarity, scoring and ranking are not "
             "enabled (CLAUDE.md phase rule; no approved catalog experiment). Windows passing "
             "filters are unranked and listed by window ID."),
}

# ---------------------------------------------------------------- constraints
_OPS = {"<=": operator.le, ">=": operator.ge, "<": operator.lt, ">": operator.gt}
_FIELDS = {
    "elevation_m.min", "elevation_m.p50", "elevation_m.max", "elevation_m.range",
    "slope_deg.p10", "slope_deg.p50", "slope_deg.p90",
    "roughness_m.p50", "roughness_m.p90", "valid_fraction",
}


@dataclass(frozen=True)
class Constraint:
    """An explicit user search constraint on one descriptor, e.g. slope_deg.p90 <= 15."""

    field: str
    op: str
    value: float

    def __post_init__(self):
        if self.field not in _FIELDS:
            raise ValueError(f"unknown descriptor field {self.field!r}; choose from {sorted(_FIELDS)}")
        if self.op not in _OPS:
            raise ValueError(f"operator must be one of {list(_OPS)}")

    @classmethod
    def parse(cls, text: str) -> "Constraint":
        m = re.fullmatch(r"\s*([a-z_.0-9]+)\s*(<=|>=|<|>)\s*(-?\d+(?:\.\d+)?)\s*", text)
        if not m:
            raise ValueError(f"cannot parse constraint {text!r} (example: slope_deg.p90<=15)")
        return cls(m.group(1), m.group(2), float(m.group(3)))

    def evaluate(self, rec: dict) -> str:
        """'pass', 'fail' or 'not_evaluable' (missing value is never a pass or a zero)."""
        v = rec
        for part in self.field.split("."):
            v = v.get(part) if isinstance(v, dict) else None
            if v is None:
                return "not_evaluable"
        return "pass" if _OPS[self.op](v, self.value) else "fail"

    def __str__(self):
        return f"{self.field}{self.op}{self.value:g}"


@dataclass
class SearchRequest:
    bbox: tuple[float, float, float, float]            # Earth W, S, E, N
    window_m: float = 10_000.0
    dataset: str = "SRTMGL1"
    min_valid_fraction: float = 0.9
    constraints: list[Constraint] = field(default_factory=list)
    lunar_region: dict | None = None                     # context only (no lunar features yet)


# ---------------------------------------------------------------- run
def run_search(req: SearchRequest, source=None, cache: DescriptorCache | None = None,
               progress=None, extract_dir: Path = EXTRACT_DIR) -> dict:
    connector = as_connector(source, extract_dir)
    cache = cache or DescriptorCache()
    emit = progress or (lambda event: None)
    t0 = time.monotonic()
    units = connector.units_for(req.bbox)
    tile_reports, windows, sources = [], [], []
    emit({"stage": "plan", "tiles_total": len(units), "tiles_done": 0,
          "body": connector.body, "dataset": connector.dataset_id})

    for i, unit in enumerate(units, start=1):
        rep = {"tile": unit.id, "area_km2": round(unit.area_km2, 1)}
        try:
            rep.update(_process_unit(unit, connector, req, cache, windows, sources))
        except Exception as e:  # keep searching; report the failure
            rep["status"] = "failed"
            rep["error"] = f"{type(e).__name__}: {e}"
        tile_reports.append(rep)
        emit({"stage": "tiles", "tiles_total": len(units), "tiles_done": i,
              "tile": unit.id, "status": rep["status"]})

    filt = apply_filters(windows, req.constraints)
    emit({"stage": "done", "tiles_total": len(units), "tiles_done": len(units),
          "windows": len(windows)})
    return {
        "schema": RESULT_SCHEMA,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "elapsed_s": round(time.monotonic() - t0, 2),
        "body": connector.body,
        "dataset_id": connector.dataset_id,
        "contains_mock_data": bool(connector.is_mock),
        "request": {**asdict(req), "dataset": connector.dataset_id,
                    "constraints": [str(c) for c in req.constraints],
                    "descriptor_version": dsc.DESCRIPTOR_VERSION},
        "coverage": coverage(tile_reports, connector.body),
        "tiles": tile_reports,
        "sources": sources,
        "methods": dsc.METHODS,
        "windows": windows,
        "filters": filt,
        "governance": GOVERNANCE,
        "limitations": dsc.LIMITATIONS,
        "cache": {"hits": cache.hits, "misses": cache.misses},
    }


def _process_unit(unit, connector, req, cache, windows, sources) -> dict:
    if not unit.in_coverage:
        return {"status": "outside_dataset_coverage"}
    digest = connector.fingerprint(unit.id)
    if digest is None:
        return {"status": "no_local_data"}
    key = cache_key(dataset=connector.dataset_id, tile=unit.id, source_sha256=digest,
                    window_m=req.window_m, min_valid=req.min_valid_fraction,
                    version=dsc.DESCRIPTOR_VERSION)
    recs = cache.get(connector.dataset_id, unit.id, key)
    rep = {"cache": "hit" if recs is not None else "miss"}
    if recs is None:
        patch = connector.fetch(unit.id)
        if patch is None:
            return {**rep, "status": "no_local_data"}
        recs = dsc.describe_patch(patch, dsc.partition_patch(patch, req.window_m),
                                  req.min_valid_fraction)
        meta = {"source": patch.provenance.source, "source_sha256": digest,
                "label": patch.provenance.label, "version": dsc.DESCRIPTOR_VERSION}
        cache.put(connector.dataset_id, unit.id, key, recs, meta)
    else:
        meta = cache.meta(connector.dataset_id, unit.id, key) or {}
    windows.extend(recs)
    sources.append({"tile": unit.id,
                    "dataset": meta.get("label", getattr(connector, "label", connector.dataset_id)),
                    "dataset_id": connector.dataset_id, "is_mock": bool(connector.is_mock),
                    "file": Path(str(meta.get("source", unit.id))).name, "sha256": digest})
    return {**rep, "status": "processed", "windows": len(recs)}


def as_connector(source, extract_dir: Path = EXTRACT_DIR):
    """Accept a TerrainConnector, the older LocalSRTMSource, or None (local SRTM)."""
    from lunarmatch.terrain.connectors import LocalSRTMConnector, TerrainConnector
    if source is None:
        return LocalSRTMConnector(extract_dir=extract_dir)
    if isinstance(source, LocalSRTMSource):
        return LocalSRTMConnector(search_dirs=list(source.search_dirs), extract_dir=extract_dir)
    if isinstance(source, TerrainConnector):
        return source
    raise TypeError("source must be a TerrainConnector or LocalSRTMSource")


def coverage(tile_reports: list[dict], body: str = "Earth") -> dict:
    by = {}
    for t in tile_reports:
        by.setdefault(t["status"], []).append(t)
    req_area = sum(t["area_km2"] for t in tile_reports)
    done_area = sum(t["area_km2"] for t in by.get("processed", []))
    frac = done_area / req_area if req_area else 0.0
    surface = EARTH_SURFACE_KM2 if body == "Earth" else MOON_SURFACE_KM2
    return {
        "body": body,
        "tiles_requested": len(tile_reports),
        "tiles_processed": len(by.get("processed", [])),
        "tiles_no_local_data": len(by.get("no_local_data", [])),
        "tiles_outside_dataset_coverage": len(by.get("outside_dataset_coverage", [])),
        "tiles_failed": len(by.get("failed", [])),
        "area_requested_km2": round(req_area, 1),
        "area_processed_km2": round(done_area, 1),
        "fraction_of_request_processed": round(frac, 4),
        "fraction_of_body_surface_processed": round(done_area / surface, 8),
        "statement": (f"Searched {len(by.get('processed', []))} of {len(tile_reports)} requested "
                      f"coverage units ({frac:.1%} of the requested area, "
                      f"{done_area / surface:.4%} of the {body}'s surface). "
                      + ("Tile areas include ocean; no land mask is applied. " if body == "Earth" else "")
                      + "This is not a global search."),
    }


def apply_filters(windows: list[dict], constraints: list[Constraint]) -> dict:
    """Data-quality gate, then explicit user constraints. No ordering by quality."""
    passed, failed, not_eval, insufficient = [], [], [], []
    for w in windows:
        if w["status"] != "ok":
            insufficient.append(w["window_id"])
            continue
        results = [c.evaluate(w) for c in constraints]
        if "not_evaluable" in results:
            not_eval.append(w["window_id"])
        elif all(r == "pass" for r in results):
            passed.append(w["window_id"])
        else:
            failed.append(w["window_id"])
    return {
        "constraints": [str(c) for c in constraints],
        "passed": sorted(passed),
        "failed_count": len(failed),
        "not_evaluable": sorted(not_eval),
        "insufficient_data": sorted(insufficient),
        "note": "Passing windows are unranked candidates for Stage B, listed by window ID.",
    }
