"""Field-measurement records (future "Rookie Scout": people or robots in the field).

DISCOVER -> MEASURE -> VALIDATE -> LEARN. This module implements MEASURE as a
validated record format and an append-only local store. Nothing here learns,
re-scores or approves anything automatically; feeding measurements back into
discovery requires an approved method.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

from lunarmatch.config import PROJECT_ROOT

STORE = PROJECT_ROOT / "data" / "field_measurements" / "measurements.jsonl"
SCHEMA = "rookie-field-measurement/1"
MEASUREMENT_TYPES = {
    "penetration_resistance": "MPa",
    "dry_bulk_density": "kg/m3",
    "grain_size_distribution": "percent",
    "cohesion": "kPa",
    "friction_angle": "deg",
    "terrain_scan": "m",              # e.g. DEM spacing; value = resolution, file in provenance
    "boulder_observation": "count/km2",
    "spectral_reflectance": "unitless",
}


class MeasurementError(ValueError):
    pass


@dataclass
class FieldMeasurement:
    site_id: str
    lat: float
    lon: float
    experiment_id: str
    measurement_type: str
    instrument: str
    calibration: str
    measured_on: str                     # ISO date
    value: float
    units: str
    uncertainty: float                   # same units, 1-sigma or stated
    provenance: str                      # who/what measured it, file references
    sampling_depth_m: float | None = None
    notes: str = ""
    extra: dict = field(default_factory=dict)

    def validate(self) -> None:
        errs = []
        for k in ("site_id", "experiment_id", "instrument", "calibration", "measured_on", "provenance"):
            if not str(getattr(self, k)).strip():
                errs.append(f"{k} is required")
        if not (-90 <= self.lat <= 90 and -180 <= self.lon <= 180):
            errs.append("coordinates out of range")
        if self.measurement_type not in MEASUREMENT_TYPES:
            errs.append(f"unknown measurement_type {self.measurement_type!r}")
        elif self.units != MEASUREMENT_TYPES[self.measurement_type]:
            errs.append(f"units must be {MEASUREMENT_TYPES[self.measurement_type]} for {self.measurement_type}")
        for k in ("value", "uncertainty"):
            v = getattr(self, k)
            if not isinstance(v, (int, float)) or not math.isfinite(v):
                errs.append(f"{k} must be a finite number")
        if isinstance(self.uncertainty, (int, float)) and self.uncertainty < 0:
            errs.append("uncertainty must be >= 0")
        if self.sampling_depth_m is not None and self.sampling_depth_m < 0:
            errs.append("sampling_depth_m must be >= 0")
        if errs:
            raise MeasurementError("; ".join(errs))


def append(m: FieldMeasurement, store: Path = STORE) -> Path:
    m.validate()
    store = Path(store)
    store.parent.mkdir(parents=True, exist_ok=True)
    with open(store, "a", encoding="utf-8") as f:
        f.write(json.dumps({"schema": SCHEMA, **asdict(m)}, ensure_ascii=False) + "\n")
    return store


def load(store: Path = STORE, site_id: str | None = None) -> list[FieldMeasurement]:
    store = Path(store)
    if not store.is_file():
        return []
    out = []
    for line in store.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        if d.pop("schema", None) != SCHEMA:
            raise MeasurementError("unsupported measurement schema")
        m = FieldMeasurement(**d)
        m.validate()
        if site_id is None or m.site_id == site_id:
            out.append(m)
    return out
