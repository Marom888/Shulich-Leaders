"""Planetary body constants.

Moon and Earth are never interchangeable: every AOI, projection and
ephemeris call carries an explicit :class:`Body`.
"""
from __future__ import annotations

import math
from enum import Enum


class Body(str, Enum):
    MOON = "moon"
    EARTH = "earth"


# IAU/LOLA reference sphere used by the PGDA LOLA products (read from the
# GeoTIFF GeoKeys of the files themselves: semi-major = semi-minor = 1737400 m).
MOON_RADIUS_M = 1_737_400.0

# WGS84 ellipsoid
WGS84_A = 6_378_137.0
WGS84_F = 1.0 / 298.257223563
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)

# Standard surface gravity (used only for user-provided load calculations)
GRAVITY_M_S2 = {Body.MOON: 1.62, Body.EARTH: 9.80665}


def earth_radii_m(lat_deg: float) -> tuple[float, float]:
    """Return (meridional radius M, prime-vertical radius N) of WGS84 at a latitude."""
    phi = math.radians(lat_deg)
    s2 = math.sin(phi) ** 2
    w = math.sqrt(1.0 - WGS84_E2 * s2)
    n = WGS84_A / w
    m = WGS84_A * (1.0 - WGS84_E2) / w**3
    return m, n
