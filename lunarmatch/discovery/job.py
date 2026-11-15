"""Rookie 2.0 discovery job: mission input -> staged, honest discovery result.

Reuses the existing engine (lunar_reference, run_search, compare_window,
draft gates). Progress events are emitted only for work actually performed;
real blockers (missing coordinates, no data in scope, empty catalogue,
unresolvable footprint) stop the job with the actual reason.

Governance (CLAUDE.md + user decisions 2026-11-15): no weights, scores,
pass/fail, ranking, top-N or overall winner are computed. Candidates are an
evidence-based, unranked list in window-ID order.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import numpy as np

from lunarmatch.analog_catalog import load_catalog
from lunarmatch.discovery.candidates import build_experiment_results
from lunarmatch.discovery.compare import COMPARABLE, GOVERNANCE, compare_window
from lunarmatch.discovery.plain_language import coverage_blocker
from lunarmatch.discovery.comparison_run import lunar_reference
from lunarmatch.discovery.engine import Constraint, SearchRequest, run_search
from lunarmatch.discovery.requirements import DraftSpec, evaluate_experiment
from lunarmatch.environment import assess
from lunarmatch.mission import MissionInput

JOB_SCHEMA = "rookie2-discovery-job/1"
STAGES = [
    ("lunar_target", "Loading lunar target"),
    ("requirements", "Reading experiment requirements"),
    ("coverage", "Checking dataset coverage"),
    ("earth_search", "Searching Earth terrain"),
    ("compare", "Comparing available features"),
    ("evidence", "Evaluating evidence quality"),
    ("results", "Preparing candidate results"),
]
MIN_SAMPLES_PER_WINDOW_SIDE = 10

OVERALL_WINNER = {
    "status": "pending_engineering_validation",
    "label": "Pending Engineering Validation",
    "required_before_computation": [
        "A mathematically specified similarity function",
        "Experiment-specific passing criteria",
        "Missing-data rules",
        "Normalization across experiments",
        "Overall aggregation methodology",
        "Tie-breaking",
        "Eligibility rules",
        "Scientific validation requirements",
    ],
    "note": "Independent per-experiment results are never replaced by an overall winner.",
}


class JobBlocked(Exception):
    def __init__(self, stage: str, reason: str, detail: dict | None = None):
        super().__init__(reason)
        self.stage, self.reason, self.detail = stage, reason, detail or {}


def swir_status(spec) -> dict:
    """SWIR availability ladder; research-only, never scored."""
    sw = spec.swir() if spec is not None else {"present": False}
    if not sw.get("present"):
        return {"present": False, "status": "not defined in the loaded specification"}

    def ladder(ds):
        return {"dataset_id": ds["Dataset_ID"], "name": ds["Dataset_Name"],
                "resolution": ds["Typical_Resolution"], "integration_status": ds["Integration_Status"],
                "evidence_type": ds["Evidence_Type"], "known_limits": ds["Known_Limits"],
                "source_url": ds["Source_URL"],
                "listed_in_workbook": True, "identified_online": "URL listed; not verified by Rookie",
                "downloaded": False, "integrated": False, "validated": False}

    return {"present": True, "scoring": "excluded (research-only; 0 scoring contribution)",
            "scoring_policy": sw["scoring_policy"], "used_by_experiments": sw["used_by_experiments"],
            "method": sw["feature"]["Calculation_Method"], "units": sw["feature"]["Units"],
            "limitations": sw["feature"]["Scientific_Limitations"],
            "comparability": sw["feature"]["Comparability_Limitation"],
            "moon": ladder(sw["moon_dataset"]), "earth": ladder(sw["earth_dataset"]),
            "data_status": "no spectral data loaded; nothing is displayed or inferred"}


def run_job(mission: MissionInput, registry, spec=None, cache=None, emit=None,
            draft: DraftSpec | None = None, geocoder=None) -> dict:
    emit = emit or (lambda e: None)
    t0 = time.monotonic()
    result = {"schema": JOB_SCHEMA, "mission": mission.to_dict(), "stages": [], "status": "running",
              "governance": GOVERNANCE, "overall_winner": OVERALL_WINNER,
              "swir": swir_status(spec)}

    def stage(sid, state, detail="", **extra):
        ev = {"stage": sid, "label": dict(STAGES)[sid], "state": state, "detail": detail, **extra}
        result["stages"].append(ev)
        emit(ev)

    try:
        # 1. lunar target -------------------------------------------------------------
        stage("lunar_target", "running")
        region = mission.target.region()
        moon = registry.get(mission.moon_dataset)
        earth = registry.get(mission.earth_dataset)
        if moon.body != "Moon" or earth.body != "Earth":
            raise JobBlocked("lunar_target", "dataset/body mismatch")
        ref = lunar_reference(region, moon, earth.nominal_spacing_m,
                              progress=lambda e: emit({"stage": "lunar_target", "state": "progress", **e}))
        if ref["status"] != "ok":
            raise JobBlocked("lunar_target", f"lunar reference: {ref['status']} for this region in {moon.dataset_id}")
        result["moon"] = {k: v for k, v in ref.items()}
        stage("lunar_target", "done", f"{region.to_dict()['area_km2']} km² on {moon.dataset_id}"
              + (" (MOCK)" if moon.is_mock else ""))

        # 2. requirements --------------------------------------------------------------
        stage("requirements", "running")
        views = {e["experiment_id"]: e for e in (spec.experiments() if spec else [])}
        selected = [views[x] for x in mission.experiments if x in views]
        result["experiments"] = selected
        stage("requirements", "done", f"{len(selected)} experiment(s) from {spec.path.name if spec else 'no spec'}; "
              "none approved")

        # 3. coverage ------------------------------------------------------------------
        stage("coverage", "running")
        if mission.search_mode == "ordinary":
            cat = load_catalog()
            result["catalog"] = {"status": cat["status"], "sites": len(cat["sites"])}
            if not cat["sites"]:
                raise JobBlocked("coverage", "Ordinary Search: the verified analog catalogue has no "
                                 "entries yet, so there is nothing to search.")
        units = earth.units_for(mission.earth.scope_bbox)
        with_data = [u.id for u in units if u.in_coverage and earth.fingerprint(u.id) is not None]
        result["coverage_check"] = {"units_in_scope": len(units), "units_with_data": with_data,
                                    "dataset": earth.dataset_id, "is_mock": earth.is_mock}
        if not with_data:
            raise JobBlocked("coverage", f"No {earth.dataset_id} terrain data in the selected scope "
                             f"(0 of {len(units)} coverage units available locally).",
                             {"units_in_scope": len(units)})
        min_window = MIN_SAMPLES_PER_WINDOW_SIDE * earth.nominal_spacing_m
        if mission.scale.terrestrial_footprint_m < min_window:
            raise JobBlocked("coverage", f"Terrestrial footprint {mission.scale.terrestrial_footprint_m:g} m is "
                             f"below the resolvable size for {earth.dataset_id} (~{earth.nominal_spacing_m:g} m "
                             f"spacing; minimum {min_window:g} m = {MIN_SAMPLES_PER_WINDOW_SIDE} samples per side).")
        stage("coverage", "done", f"{len(with_data)} of {len(units)} units have data")

        # 4. Earth search --------------------------------------------------------------
        stage("earth_search", "running")
        req = SearchRequest(bbox=mission.earth.scope_bbox, window_m=mission.scale.terrestrial_footprint_m,
                            constraints=[Constraint.parse(c) for c in mission.constraints])
        search = run_search(req, earth, cache,
                            lambda e: emit({"stage": "earth_search", "state": "progress", **e}))
        result["earth"] = {k: v for k, v in search.items() if k not in ("schema", "windows")}
        stage("earth_search", "done", search["coverage"]["statement"])

        # 5. compare -------------------------------------------------------------------
        stage("compare", "running")
        passed = set(search["filters"]["passed"])
        windows = {w["window_id"]: w for w in search["windows"]}
        comps = {wid: compare_window(ref, w, 0.25, wid in passed) for wid, w in sorted(windows.items())}
        n_comp = sum(c["features"]["slope_deg"]["status"] == "computed" for c in comps.values())
        stage("compare", "done", f"per-feature distances for {n_comp} of {len(comps)} windows (no score)")

        # 6. evidence ------------------------------------------------------------------
        stage("evidence", "running")
        ok = [w for w in windows.values() if w.get("spacing_m")]
        earth_sp = float(np.median([(w["spacing_m"]["east_west"] + w["spacing_m"]["north_south"]) / 2
                                    for w in ok])) if ok else None
        moon_sp = (ref["spacing_m"]["east_west"] + ref["spacing_m"]["north_south"]) / 2
        leg = mission.scale.characteristic_lengths_m.get("leg_spacing")
        gates = {}
        if draft is not None:
            for eid in mission.experiments:
                if eid in draft.experiments:
                    gates[eid] = evaluate_experiment(draft, eid, {"earth": earth_sp, "moon": moon_sp},
                                                     {"leg_spacing_m": leg} if leg else {})
        env = {eid: assess(eid, result["mission"]["environment"]) for eid in mission.experiments}
        stage("evidence", "done", ", ".join(f"{k}: {v['status']}" for k, v in gates.items()) or "no gates")

        # 7. results -------------------------------------------------------------------
        stage("results", "running")
        missing_req = sorted({f for g in gates.values() for f in g["missing_required"]})
        not_repro = sorted({x for e in env.values() for x in e.get("not_reproducible", [])})
        candidates = []
        for wid in sorted(passed):
            w, c = windows[wid], comps[wid]
            candidates.append({
                "id": wid, "tile": w["tile"], "rows": w["rows"], "cols": w["cols"],
                "centre_lat_lon": w.get("centre_lat_lon"),
                "bounds_wsen": w.get("bounds_wsen"), "size_m": w.get("size_m"), "area_km2": w.get("area_km2"),
                "dataset": {"id": earth.dataset_id, "is_mock": earth.is_mock,
                            "label": getattr(earth, "label", earth.dataset_id),
                            "sources": [s for s in search["sources"] if s["tile"] == w["tile"]]},
                "measurements": {"elevation_m": _strip(w.get("elevation_m")), "slope_deg": _strip(w.get("slope_deg")),
                                 "roughness_m": _strip(w.get("roughness_m")),
                                 "status": {"elevation_m": "measured (DEM samples)",
                                            "slope_deg": "derived", "roughness_m": "derived"}},
                "comparison": c["features"], "spacing_check": c["spacing"],
                "missing_required_measurements": missing_req,
                "evidence_status": "topographic descriptors only; no experiment's requirements are met",
                "resolution_limitation": f"{w['spacing_m']['east_west']:.1f} x {w['spacing_m']['north_south']:.1f} m "
                                         "sample spacing; describes terrain at >= 30-90 m scale, not lander-leg scale",
                "environment_limitations": not_repro,
                "is_mock": bool(c["is_mock"]),
            })
        per_exp = []
        for eid in mission.experiments:
            g = gates.get(eid)
            per_exp.append({
                "experiment_id": eid, "name": (views.get(eid) or {}).get("name_en", eid),
                "evaluation_status": g["status"] if g else "no draft gates available",
                "missing_required": g["missing_required"] if g else [],
                "gate_label": g["label"] if g else "",
                "candidate_ids": sorted(passed),
                "top_three": None,
                "top_three_status": ("withheld: no approved comparison methodology and required "
                                     "measurements are missing; showing an unranked evidence list"),
                "environment": env[eid],
            })
        coverage_note = coverage_blocker(search["coverage"])
        exp_results = build_experiment_results(
            experiments=selected, gates=gates, windows=windows, comps=comps, passed=passed, env=env,
            mission=mission, moon_mock=bool(moon.is_mock), earth_label=getattr(earth, "label", earth.dataset_id),
            earth_mock=bool(earth.is_mock), coverage_note=coverage_note, geocoder=geocoder)
        result.update({
            "experiment_results": exp_results, "coverage_note": coverage_note,
            "geocoding": "enabled (OpenStreetMap Nominatim)" if geocoder is not None and geocoder.enabled
            else "disabled (coordinates only)",
            "candidates": candidates, "per_experiment": per_exp,
            "comparable_features": COMPARABLE, "scale": mission.scale.to_dict(),
            "contains_mock_data": bool(moon.is_mock or earth.is_mock),
            "status": "complete",
        })
        stage("results", "done", f"{len(candidates)} unranked candidate windows")
    except JobBlocked as b:
        stage(b.stage, "blocked", b.reason, **b.detail)
        result.update(status="blocked", blocker={"stage": b.stage, "reason": b.reason, **b.detail})
    except Exception as e:  # report real failures, do not hide them
        result["stages"].append({"stage": "error", "state": "failed", "detail": f"{type(e).__name__}: {e}"})
        emit(result["stages"][-1])
        result.update(status="failed", error=f"{type(e).__name__}: {e}")
    result["elapsed_s"] = round(time.monotonic() - t0, 2)
    result["created_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return result


def _strip(d):
    return None if d is None else {k: v for k, v in d.items() if k != "q"}
