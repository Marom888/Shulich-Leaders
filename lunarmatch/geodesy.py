"""WGS84 local metric scaling for geographic (lat/lon) rasters.

Longitude and latitude are angles; these helpers convert angular sample
spacing to metres so that slopes and 3D geometry are physically meaningful.
"""
from __future__ import annotations

import numpy as np

WGS84_A = 6378137.0
WGS84_F = 1 / 298.257223563
WGS84_E2 = WGS84_F * (2 - WGS84_F)


def metres_per_degree(lat_deg):
    """(m per degree latitude, m per degree longitude) on WGS84 at ``lat_deg``.

    Latitude uses the meridional radius of curvature M; longitude uses the
    prime-vertical radius N times cos(lat). Accepts scalars or arrays.
    """
    phi = np.radians(np.asarray(lat_deg, dtype=np.float64))
    s2 = np.sin(phi) ** 2
    m = WGS84_A * (1 - WGS84_E2) / (1 - WGS84_E2 * s2) ** 1.5
    n = WGS84_A / np.sqrt(1 - WGS84_E2 * s2)
    mlat = m * np.pi / 180
    mlon = n * np.cos(phi) * np.pi / 180
    if mlat.ndim == 0:
        return float(mlat), float(mlon)
    return mlat, mlon


def row_spacing_m(lats_deg, dlat_deg: float, dlon_deg: float):
    """Per-row metric sample spacing.

    Returns ``(dx, dy)`` arrays in metres: east-west spacing ``dx`` (which
    shrinks with cos(latitude)) and north-south spacing ``dy``, for each row
    latitude in ``lats_deg``.
    """
    mlat, mlon = metres_per_degree(np.atleast_1d(lats_deg))
    return mlon * abs(dlon_deg), mlat * abs(dlat_deg)
