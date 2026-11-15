"""Structured mission input consumed by the discovery job (Rookie 2.0).

``MissionInput.from_dict`` validates user input and returns a list of
human-readable errors instead of guessing. Budget, travel distance and start
location are planning inputs only: they never influence scientific results,
and automated cost evaluation is not implemented.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from lunarmatch.lunar_presets import preset
from lunarmatch.regions import LunarRegion, RegionError

SEARCH_MODES = ("ordinary", "extraordinary")
VACUUM = ("required", "preferred", "not_required")
GRAVITY = ("physical_simulation", "numerical_correction", "not_required")
LEVEL = ("required", "preferred", "not_required")


class MissionError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass
class LunarTarget:
    preset_id: str
    lat: float | None
    lon: float | None
    radius_km: float
    label: str = ""

    def region(self) -> LunarRegion:
        return LunarRegion.point(self.lat, self.lon, self.radius_km * 1000, name=self.label,
                                 source=f"preset:{self.preset_id}")


@dataclass
class EarthConstraints:
    scope_bbox: tuple[float, float, float, float]                 # W, S, E, N
    start_location: dict | None = None                            # {"lat", "lon", "label"}
    budget: float | None = None
    currency: str = ""
    max_travel_km: float | None = None
    equipment: list[str] = field(default_factory=list)


@dataclass
class ScaleSpec:
    lunar_footprint_m: float
    terrestrial_footprint_m: float
    characteristic_lengths_m: dict = field(default_factory=dict)  # e.g. {"leg_spacing": 4.0}

    @property
    def geometric_ratio(self) -> float:
        return self.terrestrial_footprint_m / self.lunar_footprint_m

    def to_dict(self) -> dict:
        return {**asdict(self), "geometric_ratio": round(self.geometric_ratio, 6),
                "limitation": "Geometric scaling does not establish dynamic, thermal or "
                              "geotechnical similarity; no dimensionless similarity conditions "
                              "are defined in the engineering specification."}


@dataclass
class EnvironmentRequirements:
    vacuum: str = "required"
    gravity: str = "numerical_correction"
    dust: str = "preferred"
    thermal_vacuum: str = "not_required"
    illumination: str = "preferred"


@dataclass
class MissionInput:
    target: LunarTarget
    search_mode: str
    earth: EarthConstraints
    scale: ScaleSpec
    environment: EnvironmentRequirements
    experiments: list[str]
    moon_dataset: str = "MOCK_MOON_DEM"
    earth_dataset: str = "SRTMGL1"
    constraints: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict, known_experiments: set[str] | None = None) -> "MissionInput":
        errs: list[str] = []
        t = d.get("target") or {}
        pid = t.get("preset_id", "custom")
        try:
            p = preset(pid)
        except KeyError:
            errs.append(f"unknown lunar preset {pid!r}")
            p = {"point": None, "status": "user_defined", "name": ""}
        lat, lon = t.get("lat"), t.get("lon")
        if p["status"] == "verified_point" and (lat is None or lon is None):
            lat, lon = p["point"]["lat"], p["point"]["lon"]
        if lat is None or lon is None:
            errs.append("lunar target coordinates are missing" +
                        (f" ({p['name']} coordinates are pending validation; enter coordinates)"
                         if p["status"] == "coordinates_pending_validation" else ""))
        radius = _num(t.get("radius_km"), "lunar search radius (km)", errs, positive=True)
        target = LunarTarget(pid, _f(lat), _f(lon), radius or 0.0, t.get("label") or p.get("name", ""))
        if not errs:
            try:
                target.region()
            except RegionError as e:
                errs.append(f"lunar region: {e}")

        mode = d.get("search_mode")
        if mode not in SEARCH_MODES:
            errs.append(f"search_mode must be one of {SEARCH_MODES}")

        e = d.get("earth") or {}
        bbox = e.get("scope_bbox")
        if not (isinstance(bbox, (list, tuple)) and len(bbox) == 4):
            errs.append("Earth search scope must be a box [W, S, E, N]")
            bbox = (0, 0, 0, 0)
        else:
            from lunarmatch.discovery.grid import GridError, validate_bbox
            try:
                validate_bbox(*map(float, bbox))
            except (GridError, ValueError) as ex:
                errs.append(f"Earth search scope: {ex}")
        start = e.get("start_location")
        if start:
            if not (-90 <= _f(start.get("lat"), 999) <= 90 and -180 <= _f(start.get("lon"), 999) <= 180):
                errs.append("start location latitude/longitude out of range")
        budget = _num(e.get("budget"), "budget", errs, allow_none=True, positive=False)
        if budget is not None and budget < 0:
            errs.append("budget must not be negative")
        if budget is not None and not e.get("currency"):
            errs.append("currency is required when a budget is given")
        travel = _num(e.get("max_travel_km"), "maximum travel distance", errs, allow_none=True, positive=True)
        earth = EarthConstraints(tuple(map(float, bbox)), start, budget, e.get("currency", ""),
                                 travel, list(e.get("equipment") or []))

        s = d.get("scale") or {}
        lf = _num(s.get("lunar_footprint_m"), "lunar reference footprint (m)", errs, positive=True)
        tf_ = _num(s.get("terrestrial_footprint_m"), "terrestrial test footprint (m)", errs, positive=True)
        scale = ScaleSpec(lf or 1.0, tf_ or 1.0, dict(s.get("characteristic_lengths_m") or {}))

        env = d.get("environment") or {}
        envr = EnvironmentRequirements(**{k: env.get(k, getattr(EnvironmentRequirements, k))
                                          for k in ("vacuum", "gravity", "dust", "thermal_vacuum",
                                                    "illumination")})
        for k, allowed in (("vacuum", VACUUM), ("gravity", GRAVITY), ("dust", LEVEL),
                           ("thermal_vacuum", LEVEL), ("illumination", LEVEL)):
            if getattr(envr, k) not in allowed:
                errs.append(f"environment.{k} must be one of {allowed}")

        exps = list(d.get("experiments") or [])
        if not exps:
            errs.append("select at least one experiment")
        if known_experiments is not None:
            unknown = [x for x in exps if x not in known_experiments]
            if unknown:
                errs.append(f"unknown experiments: {unknown}")
        if errs:
            raise MissionError(errs)
        return cls(target, mode, earth, scale, envr, exps,
                   d.get("moon_dataset", "MOCK_MOON_DEM"), d.get("earth_dataset", "SRTMGL1"),
                   list(d.get("constraints") or []))

    def to_dict(self) -> dict:
        return {"target": asdict(self.target), "search_mode": self.search_mode,
                "earth": {**asdict(self.earth), "scope_bbox": list(self.earth.scope_bbox),
                          "planning_only": "Budget, start location and travel distance are planning "
                                           "inputs; automated cost/logistics evaluation is not implemented."},
                "scale": self.scale.to_dict(), "environment": asdict(self.environment),
                "experiments": self.experiments, "moon_dataset": self.moon_dataset,
                "earth_dataset": self.earth_dataset, "constraints": self.constraints}


def _f(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _num(v, name, errs, allow_none=False, positive=False):
    if v is None or v == "":
        if not allow_none:
            errs.append(f"{name} is required")
        return None
    x = _f(v)
    if x is None or not math.isfinite(x):
        errs.append(f"{name} must be a number")
        return None
    if positive and x <= 0:
        errs.append(f"{name} must be > 0")
        return None
    return x
