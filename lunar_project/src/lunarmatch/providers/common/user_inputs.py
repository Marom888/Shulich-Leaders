"""D_USER – lander and mission inputs supplied by the team.

Values are validated for units and plausible ranges and stored with
``Evidence.USER_INPUT``.  The only physics done here is the static nominal
footpad pressure q = m g / (n_legs * A_pad) for Moon and Earth (workbook
F_LOAD); the workbook is explicit that q alone cannot predict settlement.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from ...core.aoi import AOI
from ...core.base import CoverageReport, DataProvider, DatasetInfo, FetchResult
from ...core.bodies import GRAVITY_M_S2, Body
from ...core.evidence import AccessMode, Evidence


@dataclass
class LanderSpec:
    name: str
    mass_kg: float                      # landed mass
    n_legs: int
    footpad_diameter_m: float
    leg_span_m: float                   # footpad-centre to footpad-centre across the lander
    cg_height_m: float
    landing_time_utc: Optional[str] = None      # ISO 8601, needed for sun geometry
    engine_thrust_n: Optional[float] = None
    nozzle_exit_height_m: Optional[float] = None
    notes: str = ""
    extra: dict = field(default_factory=dict)

    def validate(self) -> list[str]:
        errs = []
        if not (1 <= self.mass_kg <= 100_000):
            errs.append("mass_kg outside 1..100000")
        if self.n_legs < 3:
            errs.append("n_legs must be >= 3")
        if not (0.05 <= self.footpad_diameter_m <= 5):
            errs.append("footpad_diameter_m outside 0.05..5 m")
        if not (0.3 <= self.leg_span_m <= 30):
            errs.append("leg_span_m outside 0.3..30 m")
        if not (0.1 <= self.cg_height_m <= 20):
            errs.append("cg_height_m outside 0.1..20 m")
        if self.landing_time_utc:
            try:
                dt = datetime.fromisoformat(self.landing_time_utc.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    errs.append("landing_time_utc must include a timezone (e.g. Z)")
            except ValueError:
                errs.append("landing_time_utc is not ISO 8601")
        return errs

    def footpad_area_m2(self) -> float:
        return math.pi * (self.footpad_diameter_m / 2) ** 2

    def static_pad_pressure_pa(self, body: Body) -> float:
        """Nominal static pressure assuming equal load on all pads (no dynamics)."""
        return self.mass_kg * GRAVITY_M_S2[Body(body)] / (self.n_legs * self.footpad_area_m2())

    def required_dem_resolution_m(self) -> float:
        """Workbook EXP_02 gate: DEM resolution <= leg spacing / 3."""
        return self.leg_span_m / 3.0


class UserInputProvider(DataProvider):
    info = DatasetInfo(
        dataset_id="D_USER", name="User lander and mission inputs", body="Both", provider="User",
        resolution="exact user values", evidence=Evidence.USER_INPUT, access=AccessMode.USER_INPUT,
        access_notes="JSON file data/raw/common/D_USER/<name>.json or LanderSpec object.",
        workbook_source_url="https://ntrs.nasa.gov/citations/20205009125",
        known_limits="Not sensor data; validated for units/plausible ranges only.",
    )

    def save(self, spec: LanderSpec) -> Path:
        errs = spec.validate()
        if errs:
            raise ValueError("; ".join(errs))
        p = self.store.raw_dir("common", "D_USER") / f"{spec.name}.json"
        p.write_text(json.dumps(asdict(spec), indent=2))
        self.store.write_metadata(p, {"dataset_id": "D_USER", "evidence": "USER_INPUT"})
        return p

    def load(self, name: str) -> LanderSpec:
        p = self.store.raw_dir("common", "D_USER") / f"{name}.json"
        return LanderSpec(**json.loads(p.read_text()))

    def check_coverage(self, aoi: AOI) -> CoverageReport:
        return CoverageReport(self.info.dataset_id, True, "user-supplied")

    def fetch(self, aoi: AOI = None, spec: Optional[LanderSpec] = None, name: Optional[str] = None, **kw) -> FetchResult:
        spec = spec or self.load(name)
        errs = spec.validate()
        res = FetchResult(self.info.dataset_id, aoi)
        for e in errs:
            res.warn(e)
        res.tables["lander"] = [{**asdict(spec), "evidence": Evidence.USER_INPUT.value}]
        res.tables["derived"] = [{
            "footpad_area_m2": spec.footpad_area_m2(),
            "static_pad_pressure_moon_pa": spec.static_pad_pressure_pa(Body.MOON),
            "static_pad_pressure_earth_pa": spec.static_pad_pressure_pa(Body.EARTH),
            "required_dem_resolution_m": spec.required_dem_resolution_m(),
            "evidence": Evidence.DERIVED_HERE.value,
            "note": "static q=F/A only; cannot predict settlement (workbook F_LOAD)",
        }]
        return res
