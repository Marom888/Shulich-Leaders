"""User-specified lunar regions (any location, not tied to a named site).

Supported now: a point with a radius, and a lat/lon bounding box. Both use
planetocentric latitude and east-positive longitude in [-180, 180] on the
IAU 2015 Moon sphere. Polygons drawn on a lunar map can be added as a third
kind with the same interface (``contains``, ``area_m2``, ``to_dict``).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from lunarmatch.bodies import MOON, band_area_m2, great_circle_m


class RegionError(ValueError):
    """Invalid region definition."""


def _check_lat(v, name):
    if not -90 <= v <= 90:
        raise RegionError(f"{name} must be within [-90, 90], got {v}")


def _check_lon(v, name):
    if not -180 <= v <= 180:
        raise RegionError(f"{name} must be within [-180, 180], got {v}")


@dataclass(frozen=True)
class LunarRegion:
    kind: str                         # "point_radius" or "bbox"
    params: dict = field(default_factory=dict)
    name: str = ""
    source: str = "user input"        # provenance of the definition
    body: str = "Moon"

    def __post_init__(self):
        p = self.params
        if self.kind == "point_radius":
            _check_lat(p.get("lat", 999), "lat")
            _check_lon(p.get("lon", 999), "lon")
            r = p.get("radius_m", 0)
            if not (isinstance(r, (int, float)) and 0 < r <= math.pi * MOON.mean_radius_m):
                raise RegionError("radius_m must be > 0 and at most half the lunar circumference")
        elif self.kind == "bbox":
            for k in ("west", "east"):
                _check_lon(p.get(k, 999), k)
            for k in ("south", "north"):
                _check_lat(p.get(k, 999), k)
            if not p["south"] < p["north"]:
                raise RegionError("south must be < north")
            if p["west"] == p["east"]:
                raise RegionError("west and east must differ")
        else:
            raise RegionError(f"unsupported region kind {self.kind!r}")

    @classmethod
    def point(cls, lat, lon, radius_m, **kw):
        return cls("point_radius", {"lat": lat, "lon": lon, "radius_m": radius_m}, **kw)

    @classmethod
    def bbox(cls, west, south, east, north, **kw):
        return cls("bbox", {"west": west, "south": south, "east": east, "north": north}, **kw)

    def contains(self, lat: float, lon: float) -> bool:
        p = self.params
        if self.kind == "point_radius":
            return great_circle_m(MOON, p["lat"], p["lon"], lat, lon) <= p["radius_m"]
        if not p["south"] <= lat <= p["north"]:
            return False
        w, e = p["west"], p["east"]
        return w <= lon <= e if w < e else (lon >= w or lon <= e)   # antimeridian wrap

    def mask(self, lat, lon):
        """Vectorized ``contains`` for arrays of latitude/longitude (degrees)."""
        import numpy as np
        lat, lon = np.asarray(lat, float), np.asarray(lon, float)
        p = self.params
        if self.kind == "point_radius":
            p1, p2 = np.radians(p["lat"]), np.radians(lat)
            dp, dl = p2 - p1, np.radians(lon - p["lon"])
            h = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
            d = 2 * MOON.mean_radius_m * np.arcsin(np.minimum(1.0, np.sqrt(h)))
            return d <= p["radius_m"]
        inlat = (lat >= p["south"]) & (lat <= p["north"])
        w, e = p["west"], p["east"]
        inlon = (lon >= w) & (lon <= e) if w < e else (lon >= w) | (lon <= e)
        return inlat & inlon

    def bounds(self) -> tuple[float, float, float, float]:
        """Enclosing (west, south, east, north) box in degrees."""
        p = self.params
        if self.kind == "bbox":
            return (p["west"], p["south"], p["east"], p["north"])
        per_deg = MOON.mean_radius_m * math.pi / 180
        dlat = p["radius_m"] / per_deg
        s, n = max(-90.0, p["lat"] - dlat), min(90.0, p["lat"] + dlat)
        if s <= -90 or n >= 90:
            return (-180.0, s, 180.0, n)                    # region touches a pole
        coslat = max(math.cos(math.radians(max(abs(s), abs(n)))), 1e-6)
        dlon = min(180.0, dlat / coslat)
        w = (p["lon"] - dlon + 180) % 360 - 180
        e = (p["lon"] + dlon + 180) % 360 - 180
        return (w, s, e, n) if dlon < 180 else (-180.0, s, 180.0, n)

    def area_m2(self) -> float:
        p = self.params
        if self.kind == "point_radius":
            r = MOON.mean_radius_m
            return 2 * math.pi * r * r * (1 - math.cos(p["radius_m"] / r))   # spherical cap
        return band_area_m2(MOON, p["west"], p["south"], p["east"], p["north"])

    def to_dict(self) -> dict:
        return {"body": self.body, "crs": MOON.crs, "kind": self.kind, "params": dict(self.params),
                "name": self.name, "source": self.source, "area_km2": round(self.area_m2() / 1e6, 3)}
