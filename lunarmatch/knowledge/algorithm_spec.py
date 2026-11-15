"""Read-only interface to the LunarMatch algorithm specification workbooks.

Two versions exist in algorithm/:
  * LunarMatch_Algorithm_Spec_v1.0.xlsx           (spec v1.0)
  * LunarMatch_Algorithm_With_SWIR_Sources.xlsx   (Talia, 2026-11-15; additive SWIR update)

Every sheet is exposed as a list of row dicts keyed by the workbook's own
English headers. Nothing is written. Spec weights and pass thresholds are
exposed for display only and are flagged as NOT authorized for scoring
(CLAUDE.md governance; user decision 2026-11-15). The workbook "enabled"
flag is never treated as experiment approval.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from lunarmatch.config import PROJECT_ROOT
from lunarmatch.knowledge.workbook import WorkbookError, read_sheets

ALGO_DIR = PROJECT_ROOT / "algorithm"
SPEC_FILES = {
    "swir": ALGO_DIR / "LunarMatch_Algorithm_With_SWIR_Sources.xlsx",
    "v1.0": ALGO_DIR / "LunarMatch_Algorithm_Spec_v1.0.xlsx",
}
SHEETS = ["Start_Here", "Experiments", "Experiment_Features", "Moon_Earth_Pairs", "Pair_URLs",
          "Datasets", "Features", "Physical_Models", "Capabilities", "Experiment_Capabilities",
          "Pipeline", "Ranking_Rules", "Score_Demo", "Overall_Ranking", "Per_Test_Winners",
          "Lunar_Mechanical_References"]
SYNTHETIC_SHEETS = {"Score_Demo", "Overall_Ranking", "Per_Test_Winners"}
NOT_AUTHORIZED = "Spec value shown for reference only; NOT authorized for scoring (CLAUDE.md governance)."


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _table(rows: list[list[str]]) -> list[dict]:
    if not rows:
        return []
    head = rows[0]
    return [{head[i]: (r[i] if i < len(r) else "") for i in range(len(head)) if head[i]}
            for r in rows[1:] if r and r[0]]


@dataclass
class AlgorithmSpec:
    path: Path
    version: str
    sha256: str
    tables: dict = field(default_factory=dict)

    @classmethod
    def load(cls, version: str = "swir", path: Path | None = None) -> "AlgorithmSpec":
        path = Path(path or SPEC_FILES[version])
        if not path.is_file():
            raise WorkbookError(f"algorithm spec not found: {path}")
        raw = read_sheets(path)
        missing = [s for s in SHEETS if s not in raw]
        if missing:
            raise WorkbookError(f"{path.name}: missing sheets {missing}")
        return cls(path, version, sha256(path), {s: _table(raw[s]) for s in SHEETS})

    # ------------------------------------------------------------ convenience views
    def rows(self, sheet: str) -> list[dict]:
        if sheet in SYNTHETIC_SHEETS:
            raise WorkbookError(f"{sheet} holds SYNTHETIC demo values and is not exposed as data")
        return self.tables[sheet]

    def start_here(self) -> dict:
        return {r["Topic"]: r.get("Decision / Instruction", "") for r in self.tables["Start_Here"]}

    def dataset(self, dataset_id: str) -> dict | None:
        return next((d for d in self.tables["Datasets"] if d["Dataset_ID"] == dataset_id), None)

    def feature(self, feature_id: str) -> dict | None:
        return next((f for f in self.tables["Features"] if f["Feature_ID"] == feature_id), None)

    def model(self, model_id: str) -> dict | None:
        return next((m for m in self.tables["Physical_Models"] if m["Model_ID"] == model_id), None)

    def experiments(self) -> list[dict]:
        """Experiments with features, model, datasets and capabilities (display contract)."""
        out = []
        for e in self.tables["Experiments"]:
            eid = e["Experiment_ID"]
            feats = [r for r in self.tables["Experiment_Features"] if r["Experiment_ID"] == eid]
            req = [r for r in feats if r["Requirement"].upper().startswith(("REQUIRED", "USER_INPUT_REQUIRED"))]
            opt = [r for r in feats if r not in req]
            datasets = set()
            for r in feats:
                f = self.feature(r["Feature_ID"]) or {}
                for k in ("Moon_Preferred_Dataset", "Earth_Preferred_Dataset"):
                    if f.get(k):
                        datasets.add(f[k])
            caps = [c for c in self.tables["Experiment_Capabilities"] if c["Experiment_ID"] == eid]
            m = self.model(e["Physical_Model_ID"]) or {}
            out.append({
                "experiment_id": eid, "name_en": e["Name_EN"], "name_he": e["Name_HE"],
                "family": e["Family"], "objective": e["Matching_Objective"],
                "notes": e["Notes"], "dev_priority": e["Dev_Priority"],
                "workbook_enabled_flag": e["Default_Enabled"],
                "approval_status": "not approved (workbook flag is not approval)",
                "spec_threshold_pct": {"value": e["Threshold_pct"], "status": NOT_AUTHORIZED},
                "required_features": [self._feat_view(r) for r in req],
                "optional_features": [self._feat_view(r) for r in opt],
                "physical_model": {"id": e["Physical_Model_ID"], "name": m.get("Model_Name", ""),
                                   "validation_status": m.get("Validation_Status", ""),
                                   "validation_gate": m.get("Validation_Gate", ""),
                                   "scope_limits": m.get("Scope_Limits", ""),
                                   "required_inputs": m.get("Required_Inputs", "")},
                "datasets": sorted(datasets),
                "capabilities": [{"id": c["Capability_ID"], "role": c["Role"]} for c in caps],
            })
        return out

    def _feat_view(self, r: dict) -> dict:
        f = self.feature(r["Feature_ID"]) or {}
        return {"feature_id": r["Feature_ID"], "requirement": r["Requirement"],
                "units": f.get("Units", ""), "name": f.get("Canonical_Name", ""),
                "gate": r["Hard_Gate_or_Condition"],
                "spec_weight_pct": {"value": r["Default_Weight_pct"], "status": NOT_AUTHORIZED}}

    def swir(self) -> dict:
        """SWIR additions (research-only), as written in the workbook."""
        feat = self.feature("F_SWIR_BANDPASS")
        if feat is None:
            return {"present": False}
        pair = next((p for p in self.tables["Moon_Earth_Pairs"] if p["Feature_ID"] == "F_SWIR_BANDPASS"), {})
        url = next((p for p in self.tables["Pair_URLs"] if p["Feature_ID"] == "F_SWIR_BANDPASS"), {})
        used_by = [r["Experiment_ID"] for r in self.tables["Experiment_Features"]
                   if r["Feature_ID"] == "F_SWIR_BANDPASS"]
        sh = self.start_here()
        return {
            "present": True, "feature": feat, "pair": pair, "urls": url,
            "moon_dataset": self.dataset(feat["Moon_Preferred_Dataset"]),
            "earth_dataset": self.dataset(feat["Earth_Preferred_Dataset"]),
            "scoring_policy": sh.get("SWIR scoring policy", ""),
            "used_by_experiments": used_by,
        }


def compare_specs(old: AlgorithmSpec, new: AlgorithmSpec) -> dict:
    """Row-level comparison keyed by each sheet's first column (read-only)."""
    out = {}
    for s in SHEETS:
        a, b = old.tables[s], new.tables[s]
        key = (lambda r: tuple(r.values())[:2]) if s in ("Experiment_Features", "Moon_Earth_Pairs",
                                                        "Pair_URLs", "Experiment_Capabilities") \
            else (lambda r: next(iter(r.values())))
        ka, kb = {key(r): r for r in a}, {key(r): r for r in b}
        out[s] = {"added": [k for k in kb if k not in ka], "removed": [k for k in ka if k not in kb],
                  "changed": [k for k in kb if k in ka and kb[k] != ka[k]]}
    return out
