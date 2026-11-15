"""Planetary body models. Earth and Moon geodesy are never interchangeable.

* Earth: WGS84 ellipsoid (the existing lunarmatch.geodesy functions).
* Moon: IAU 2015 reference sphere, radius 1737.4 km (CRS IAU_2015:30100,
  planetocentric latitude, east-positive longitude).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from lunarmatch import geodesy


@dataclass(frozen=True)
class Body:
    name: str
    crs: str
    model: str                 # "ellipsoid" or "sphere"
    semi_major_m: float
    flattening: float = 0.0

    @property
    def mean_radius_m(self) -> float:
        """Authalic (equal-area) radius; equals the radius for a sphere."""
        if self.model == "sphere":
            return self.semi_major_m
        a, f = self.semi_major_m, self.flattening
        e2 = f * (2 - f)
        e = math.sqrt(e2)
        q = (1 - e2) * (1 / (1 - e2) - math.log((1 - e) / (1 + e)) / (2 * e))
        return a * math.sqrt(q / 2)


EARTH = Body("Earth", "EPSG:4326", "ellipsoid", geodesy.WGS84_A, geodesy.WGS84_F)
MOON = Body("Moon", "IAU_2015:30100", "sphere", 1_737_400.0)


def metres_per_degree(body: Body, lat_deg):
    """(m per degree latitude, m per degree longitude) at ``lat_deg`` on ``body``."""
    if body.model == "ellipsoid":
        if body is not EARTH and (body.semi_major_m, body.flattening) != (
                EARTH.semi_major_m, EARTH.flattening):
            raise ValueError("only the WGS84 ellipsoid is implemented")
        return geodesy.metres_per_degree(lat_deg)
    lat = np.asarray(lat_deg, dtype=np.float64)
    per_deg = body.semi_major_m * math.pi / 180
    mlon = per_deg * np.cos(np.radians(lat))
    if np.ndim(mlon) == 0:
        return per_deg, float(mlon)
    return np.full_like(mlon, per_deg), mlon


def band_area_m2(body: Body, west: float, south: float, east: float, north: float) -> float:
    """Area of a lat/lon box (degrees) on the body's authalic sphere.

    Exact for the Moon sphere. For Earth it uses the authalic radius with
    geodetic latitudes, an approximation within about 0.3% for 1° tiles.
    Longitudes may wrap (west > east crosses the antimeridian).
    """
    dlon = (east - west) % 360 or (360.0 if east != west else 0.0)
    r = body.mean_radius_m
    return r * r * math.radians(dlon) * (math.sin(math.radians(north)) - math.sin(math.radians(south)))


def great_circle_m(body: Body, lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance on the body's mean sphere (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * body.mean_radius_m * math.asin(min(1.0, math.sqrt(h)))
