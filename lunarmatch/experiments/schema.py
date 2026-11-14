"""Experiment catalog schema (CLAUDE.md section 11), JSON loader and validation.

Governance
----------
* Only the engineering team approves experiments, by editing the catalog
  JSON (``"status": "approved"``) in a reviewed git change.
* Nothing in this module changes ``status``. :class:`Experiment` is frozen.
* :func:`approved_experiments` is the only supported way to get the
  experiments that may be recommended as approved.

Catalog file format::

    {"schema_version": "1", "experiments": [ {<experiment>}, ... ]}
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

SCHEMA_VERSION = "1"
STATUSES = ("draft", "approved", "deprecated")
ID_PATTERN = re.compile(r"^EXP-\d{3}$")
DEFAULT_CATALOG = Path(__file__).resolve().parent / "catalog.json"

_REQUIRED = ("experiment_id", "name", "status", "version", "objective")
_LISTS = ("related_failure_modes", "required_features", "optional_features", "limitations")
_ALLOWED = set(_REQUIRED) | set(_LISTS) | {"default_weights", "matching_algorithm"}


class ExperimentValidationError(ValueError):
    """Raised when a catalog or experiment definition is invalid."""


@dataclass(frozen=True)
class Experiment:
    experiment_id: str
    name: str
    status: str
    version: str
    objective: str
    related_failure_modes: tuple[str, ...] = ()
    required_features: tuple[str, ...] = ()
    optional_features: tuple[str, ...] = ()
    default_weights: dict = field(default_factory=dict)
    matching_algorithm: str = ""
    limitations: tuple[str, ...] = ()

    @property
    def is_approved(self) -> bool:
        return self.status == "approved"

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in _LISTS:
            d[k] = list(d[k])
        d["default_weights"] = dict(self.default_weights)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Experiment":
        """Validate a mapping and build an Experiment (see :func:`validate`)."""
        validate(d)
        kw = {k: d[k] for k in _REQUIRED}
        for k in _LISTS:
            kw[k] = tuple(d.get(k, ()))
        kw["default_weights"] = {k: float(v) for k, v in d.get("default_weights", {}).items()}
        kw["matching_algorithm"] = d.get("matching_algorithm", "")
        return cls(**kw)


def _err(d, msg: str) -> ExperimentValidationError:
    eid = d.get("experiment_id", "?") if isinstance(d, dict) else "?"
    return ExperimentValidationError(f"{eid}: {msg}")


def validate(d) -> None:
    """Check one experiment mapping. Raises ExperimentValidationError.

    Rules:
    * required keys are present and unknown keys are rejected (catches typos)
    * ``experiment_id`` looks like ``EXP-001``
    * ``status`` is one of draft / approved / deprecated
    * text fields are non-empty strings, list fields are lists of non-empty
      strings, and no feature is both required and optional
    * ``default_weights`` maps declared features to finite numbers >= 0
    * ``approved`` additionally needs required_features, default_weights and
      a matching_algorithm. Weight values themselves are the engineering
      team's decision and are not normalised or second-guessed here.
    """
    if not isinstance(d, dict):
        raise ExperimentValidationError("experiment must be a JSON object")
    missing = [k for k in _REQUIRED if k not in d]
    if missing:
        raise _err(d, f"missing required field(s): {missing}")
    unknown = sorted(set(d) - _ALLOWED)
    if unknown:
        raise _err(d, f"unknown field(s): {unknown}")

    for k in _REQUIRED + ("matching_algorithm",):
        if k in d and not isinstance(d[k], str):
            raise _err(d, f"{k} must be a string")
    for k in _REQUIRED:
        if not d[k].strip():
            raise _err(d, f"{k} must not be empty")
    if not ID_PATTERN.match(d["experiment_id"]):
        raise _err(d, "experiment_id must match EXP-NNN")
    if d["status"] not in STATUSES:
        raise _err(d, f"status must be one of {STATUSES}, got {d['status']!r}")

    for k in _LISTS:
        v = d.get(k, [])
        if not isinstance(v, list) or not all(isinstance(s, str) and s.strip() for s in v):
            raise _err(d, f"{k} must be a list of non-empty strings")
        if len(set(v)) != len(v):
            raise _err(d, f"{k} contains duplicates")

    req, opt = set(d.get("required_features", [])), set(d.get("optional_features", []))
    if req & opt:
        raise _err(d, f"features both required and optional: {sorted(req & opt)}")

    w = d.get("default_weights", {})
    if not isinstance(w, dict):
        raise _err(d, "default_weights must be an object")
    undeclared = sorted(set(w) - req - opt)
    if undeclared:
        raise _err(d, f"weights for undeclared features: {undeclared}")
    for k, v in w.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
            raise _err(d, f"weight {k!r} must be a finite number >= 0")

    if d["status"] == "approved":
        if not req:
            raise _err(d, "approved experiment needs required_features")
        if not w:
            raise _err(d, "approved experiment needs default_weights")
        if not d.get("matching_algorithm", "").strip():
            raise _err(d, "approved experiment needs matching_algorithm")


def parse_catalog(data) -> list[Experiment]:
    """Validate a parsed catalog object and return its experiments."""
    if not isinstance(data, dict) or "experiments" not in data:
        raise ExperimentValidationError('catalog must be {"schema_version", "experiments": [...]}')
    if str(data.get("schema_version")) != SCHEMA_VERSION:
        raise ExperimentValidationError(
            f"unsupported schema_version {data.get('schema_version')!r} (expected {SCHEMA_VERSION})")
    if not isinstance(data["experiments"], list):
        raise ExperimentValidationError("experiments must be a list")
    exps = [Experiment.from_dict(d) for d in data["experiments"]]
    ids = [e.experiment_id for e in exps]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise ExperimentValidationError(f"duplicate experiment_id(s): {dup}")
    return exps


def load_catalog(path: Path = DEFAULT_CATALOG) -> list[Experiment]:
    """Load and validate a catalog JSON file (UTF-8)."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ExperimentValidationError(f"{path.name}: invalid JSON: {e}") from e
    return parse_catalog(data)


def approved_experiments(experiments) -> list[Experiment]:
    """Only experiments explicitly marked ``approved`` by the engineering team."""
    return [e for e in experiments if e.status == "approved"]
