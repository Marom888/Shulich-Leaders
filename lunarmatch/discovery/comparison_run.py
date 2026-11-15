"""Moon region -> Earth search -> per-feature comparison (one run).

1. Lunar reference: fetch the lunar region through a Moon connector, coarsen
   it (integer block mean) if it is much finer than the Earth dataset, and
   summarise the samples inside the region.
2. Earth screening: the Stage A engine over the Earth search box.
3. Draft gates for each spec experiment (labelled, not approved).
4. Per-feature distances for every described Earth window (window-ID order).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

from lunarmatch.discovery import descriptors as dsc
from lunarmatch.discovery.compare import COMPARABLE, GOVERNANCE, compare_window
from lunarmatch.discovery.engine import Constraint, SearchRequest, run_search
from lunarmatch.discovery.requirements import DraftSpec, evaluate_experiment
from lunarmatch.regions import LunarRegion
from lunarmatch.terrain.patch import coarsen

COMPARISON_SCHEMA = "rookie-comparison-result/1"


@dataclass
class ComparisonRequest:
    lunar_region: LunarRegion
    earth_bbox: tuple[float, float, float, float]
    window_m: float = 10_000.0
    constraints: list[Constraint] = field(default_factory=list)
    mission_inputs: dict = field(default_factory=dict)      # e.g. {"leg_spacing_m": 4.0}
    spacing_tolerance: float = 0.25
    min_valid_fraction: float = 0.9


def lunar_reference(region: LunarRegion, connector, target_spacing_m: float | None,
                    min_valid_fraction: float = 0.9, progress=None) -> dict:
    """Pooled descriptor of the samples inside ``region`` (all coverage units)."""
    emit = progress or (lambda e: None)
    units = connector.units_for(region.bounds())
    zs, ss, rs, provs, spacings, n_total = [], [], [], [], [], 0
    for i, u in enumerate(units, start=1):
        patch = connector.fetch(u.id) if u.in_coverage else None
        emit({"stage": "moon", "units_total": len(units), "units_done": i, "unit": u.id,
              "status": "processed" if patch is not None else "no_data"})
        if patch is None:
            continue
        native = patch.nominal_spacing_m()
        if target_spacing_m:
            factor = int(round(target_spacing_m / np.mean(native)))
            if factor >= 2:
                patch = coarsen(patch, factor)
        slope, rough = dsc.layers(patch)
        rows, cols = np.arange(patch.shape[0]), np.arange(patch.shape[1])
        if patch.grid.kind == "geographic":
            lat, lon = np.meshgrid(patch.grid.lats, patch.grid.lons, indexing="ij")
        else:
            lat, lon = patch.grid.latlon_of(rows, cols)
        m = region.mask(lat, lon)
        n_total += int(m.sum())
        zs.append(patch.elevation_m[m])
        ss.append(slope[m])
        rs.append(rough[m])
        provs.append(patch.provenance.to_dict())
        spacings.append(patch.nominal_spacing_m())
    base = {"region": region.to_dict(), "dataset_id": connector.dataset_id,
            "is_mock": bool(connector.is_mock), "provenance": provs, "units": len(units)}
    if not n_total:
        return {**base, "status": "no_data", "slope_deg": None, "roughness_m": None,
                "elevation_m": None, "spacing_m": None}
    z, s, r = np.concatenate(zs), np.concatenate(ss), np.concatenate(rs)
    valid = float(np.isfinite(z).sum() / z.size)
    sp = np.mean(spacings, axis=0)
    rec = {**base, "n_samples": int(z.size), "valid_fraction": round(valid, 4),
           "spacing_m": {"east_west": round(float(sp[0]), 3), "north_south": round(float(sp[1]), 3)}}
    if valid < min_valid_fraction:
        return {**rec, "status": "insufficient_data", "slope_deg": None, "roughness_m": None,
                "elevation_m": None}
    return {**rec, "status": "ok", **dsc.summarize(z, s, r)}


def run_comparison(req: ComparisonRequest, moon_connector, earth_connector, cache=None,
                   progress=None, spec: DraftSpec | None = None, experiments=None) -> dict:
    t0 = time.monotonic()
    if moon_connector.body != "Moon" or earth_connector.body != "Earth":
        raise ValueError("connectors must be a Moon connector and an Earth connector")
    ref = lunar_reference(req.lunar_region, moon_connector, earth_connector.nominal_spacing_m,
                          req.min_valid_fraction, progress)
    earth = run_search(SearchRequest(bbox=tuple(req.earth_bbox), window_m=req.window_m,
                                     min_valid_fraction=req.min_valid_fraction,
                                     constraints=list(req.constraints)),
                       earth_connector, cache, progress)
    passed = set(earth["filters"]["passed"])
    comps = []
    if ref["status"] == "ok":
        comps = [compare_window(ref, w, req.spacing_tolerance, w["window_id"] in passed)
                 for w in sorted(earth["windows"], key=lambda w: w["window_id"])]

    ok = [w for w in earth["windows"] if w.get("spacing_m")]
    earth_sp = float(np.median([(w["spacing_m"]["east_west"] + w["spacing_m"]["north_south"]) / 2
                                for w in ok])) if ok else None
    moon_sp = ((ref["spacing_m"]["east_west"] + ref["spacing_m"]["north_south"]) / 2
               if ref.get("spacing_m") else None)
    drafts = []
    if spec is not None:
        for eid in (experiments or list(spec.experiments)):
            drafts.append(evaluate_experiment(spec, eid, {"earth": earth_sp, "moon": moon_sp},
                                              req.mission_inputs, req.spacing_tolerance))
    contains_mock = bool(ref["is_mock"] or earth.get("contains_mock_data"))
    return {
        "schema": COMPARISON_SCHEMA,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "elapsed_s": round(time.monotonic() - t0, 2),
        "contains_mock_data": contains_mock,
        "request": {"lunar_region": req.lunar_region.to_dict(), "earth_bbox": list(req.earth_bbox),
                    "window_m": req.window_m, "constraints": [str(c) for c in req.constraints],
                    "mission_inputs": req.mission_inputs, "spacing_tolerance": req.spacing_tolerance},
        "moon": ref,
        "earth": {k: v for k, v in earth.items() if k != "schema"},
        "comparable_features": COMPARABLE,
        "comparisons": comps,
        "experiments_draft": drafts,
        "governance": GOVERNANCE,
        "limitations": dsc.LIMITATIONS + [
            "Per-feature distances describe topography only; they are not geotechnical equivalence.",
            "The lunar reference pools all samples inside the region; Earth values are per window.",
            "W1 is approximated from 21 stored quantiles.",
        ],
    }
