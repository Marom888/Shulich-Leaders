"""DRAFT experiment requirements and gates from the algorithm spec workbook.

Governance (user decision, 2026-11-15): spec gates may be applied as draft
feasibility / data-quality filters, always labelled "DRAFT - not approved".
Nothing here approves, scores or recommends an experiment. Spec weights and
pass thresholds are deliberately NOT read or used.

Rule R05 of the spec is applied: if any REQUIRED feature cannot be computed,
the experiment is INSUFFICIENT_DATA (never a zero, never a pass).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lunarmatch.config import PROJECT_ROOT
from lunarmatch.knowledge.workbook import WorkbookError, read_sheets

DRAFT_LABEL = "DRAFT - from algorithm spec v1.0, not approved"

SPEC_CANDIDATES = [
    PROJECT_ROOT / "data" / "reference" / "algorithm" / "LunarMatch_Algorithm_Spec_v1.0.xlsx",
    PROJECT_ROOT / "algorithm" / "LunarMatch_Algorithm_Spec_v1.0.xlsx",
    PROJECT_ROOT / "algorithm" / "LunarMatch_Algorithm_Spec_v1.0.xlsx.xlsx",
]

# Spec feature -> descriptor computed by this engine (None = not computable yet).
FEATURE_DESCRIPTORS = {
    "F_SLOPE": ("slope_deg", "computed", "Horn slope at dataset spacing"),
    "F_ROUGH": ("roughness_m", "partial",
                "3x3 std of elevation, NOT the spec's detrended RMS; comparable only with itself"),
}

REQUIRED_PREFIXES = ("REQUIRED", "USER_INPUT_REQUIRED")


def find_spec(candidates=None) -> Path | None:
    for p in (candidates or SPEC_CANDIDATES):
        if Path(p).is_file():
            return Path(p)
    return None


def _table(sheets: dict, name: str) -> list[dict]:
    if name not in sheets:
        raise WorkbookError(f"spec sheet {name!r} not found")
    rows = sheets[name]
    head = rows[0]
    return [{head[i]: (r[i] if i < len(r) else "") for i in range(len(head))}
            for r in rows[1:] if r and r[0]]


@dataclass
class DraftSpec:
    path: Path
    experiments: dict          # id -> {name_en, family, physical_model}
    features: dict             # experiment id -> [{feature_id, requirement, gate}]

    @classmethod
    def load(cls, path: Path | None = None) -> "DraftSpec":
        path = path or find_spec()
        if path is None:
            raise WorkbookError("algorithm spec workbook not found")
        sheets = read_sheets(path)
        exps = {r["Experiment_ID"]: {"name_en": r["Name_EN"], "family": r["Family"],
                                     "physical_model": r["Physical_Model_ID"]}
                for r in _table(sheets, "Experiments")}
        feats: dict[str, list] = {}
        for r in _table(sheets, "Experiment_Features"):
            feats.setdefault(r["Experiment_ID"], []).append(
                {"feature_id": r["Feature_ID"], "requirement": r["Requirement"],
                 "gate": r["Hard_Gate_or_Condition"]})
        return cls(Path(path), exps, feats)


def _is_required(requirement: str) -> bool:
    return requirement.upper().startswith(REQUIRED_PREFIXES)


def evaluate_gate(gate_text: str, spacings_m: dict, mission: dict, tolerance: float = 0.25) -> dict:
    """Evaluate the machine-checkable part of one textual spec gate.

    ``spacings_m`` = {"earth": metres, "moon": metres} (dataset sample spacing).
    Returns {"result": pass|unverified|fail|manual_review, "detail": str}.
    """
    text = gate_text.lower()
    worst = max(v for v in spacings_m.values() if v) if any(spacings_m.values()) else None
    if "leg-spacing/3" in text or "leg spacing/3" in text:
        leg = mission.get("leg_spacing_m")
        if leg is None:
            return {"result": "unverified", "detail": "leg spacing not provided (mission input)"}
        limit = leg / 3
        if worst is not None and worst <= limit:
            return {"result": "pass", "detail": f"DEM spacing {worst:.1f} m <= leg spacing/3 = {limit:.2f} m"}
        return {"result": "unverified",
                "detail": f"DEM spacing {worst:.1f} m > leg spacing/3 = {limit:.2f} m (spec: mark UNVERIFIED)"}
    if "same spatial support" in text or "physical meters" in text or "common resolution" in text:
        e, m = spacings_m.get("earth"), spacings_m.get("moon")
        if not (e and m):
            return {"result": "unverified", "detail": "spacing unknown for one body"}
        ratio = max(e, m) / min(e, m)
        ok = ratio <= 1 + tolerance
        return {"result": "pass" if ok else "fail",
                "detail": f"Earth {e:.1f} m vs Moon {m:.1f} m spacing (ratio {ratio:.2f}, limit {1 + tolerance:.2f})"}
    return {"result": "manual_review", "detail": "not machine-checkable"}


def evaluate_experiment(spec: DraftSpec, exp_id: str, spacings_m: dict, mission: dict | None = None,
                        tolerance: float = 0.25) -> dict:
    mission = mission or {}
    if exp_id not in spec.experiments:
        raise KeyError(exp_id)
    rows = []
    missing_required, missing_optional = [], []
    for f in spec.features.get(exp_id, []):
        desc = FEATURE_DESCRIPTORS.get(f["feature_id"])
        computable = desc is not None
        req = _is_required(f["requirement"])
        if not computable:
            (missing_required if req else missing_optional).append(f["feature_id"])
        rows.append({
            "feature_id": f["feature_id"], "requirement": f["requirement"], "required": req,
            "computable": computable,
            "descriptor": desc[0] if desc else None,
            "note": desc[2] if desc else "not computable by this engine yet",
            "gate_text": f["gate"],
            "gate": evaluate_gate(f["gate"], spacings_m, mission, tolerance) if computable else None,
        })
    status = "insufficient_data" if missing_required else "evaluable_partial"
    return {
        "experiment_id": exp_id, "name": spec.experiments[exp_id]["name_en"],
        "label": DRAFT_LABEL, "status": status,
        "missing_required": missing_required, "missing_optional": missing_optional,
        "features": rows,
        "note": ("Spec rule R05: a required feature is unavailable, so no evaluation is made."
                 if missing_required else
                 "Comparable features are shown as per-feature distances; no score is computed."),
    }
