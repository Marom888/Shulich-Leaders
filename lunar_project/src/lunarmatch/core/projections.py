"""Map projections that are needed without GDAL/PROJ.

Polar stereographic on a sphere is implemented here explicitly because the
NASA PGDA LOLA south-pole products use exactly that projection
(latitude of origin -90, central meridian 0, scale factor 1,
sphere R = 1 737 400 m — read from the GeoKeys of the files).

Conventions follow PROJ ``+proj=stere +lat_0=-90 +lon_0=0 +k=1 +R=1737400``:

* South pole:  x =  rho * sin(lon - lon0),  y =  rho * cos(lon - lon0)
* North pole:  x =  rho * sin(lon - lon0),  y = -rho * cos(lon - lon0)
* rho = 2 R k0 tan(pi/4 - |lat|/2)   (|lat| measured toward the projection pole)
"""
from __future__ import annotations

import numpy as np

from .bodies import MOON_RADIUS_M

PROJ4_MOON_SOUTH_POLAR_STEREO = (
    "+proj=stere +lat_0=-90 +lon_0=0 +k=1 +x_0=0 +y_0=0 +R=1737400 +units=m +no_defs"
)
PROJ4_MOON_NORTH_POLAR_STEREO = (
    "+proj=stere +lat_0=90 +lon_0=0 +k=1 +x_0=0 +y_0=0 +R=1737400 +units=m +no_defs"
)


def polar_stereo_forward(lat_deg, lon_deg, *, south: bool = True,
                         radius: float = MOON_RADIUS_M, lon0_deg: float = 0.0, k0: float = 1.0):
    lat = np.radians(np.asarray(lat_deg, dtype=float))
    dlon = np.radians(np.asarray(lon_deg, dtype=float) - lon0_deg)
    if south:
        rho = 2.0 * radius * k0 * np.tan(np.pi / 4.0 + lat / 2.0)
        return rho * np.sin(dlon), rho * np.cos(dlon)
    rho = 2.0 * radius * k0 * np.tan(np.pi / 4.0 - lat / 2.0)
    return rho * np.sin(dlon), -rho * np.cos(dlon)


def polar_stereo_inverse(x, y, *, south: bool = True,
                         radius: float = MOON_RADIUS_M, lon0_deg: float = 0.0, k0: float = 1.0):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    rho = np.hypot(x, y)
    c = 2.0 * np.arctan(rho / (2.0 * radius * k0))  # angular distance from the pole
    if south:
        lat = -(np.pi / 2.0 - c)
        lon = np.arctan2(x, y)
    else:
        lat = np.pi / 2.0 - c
        lon = np.arctan2(x, -y)
    lon_deg = (np.degrees(lon) + lon0_deg) % 360.0
    return np.degrees(lat), lon_deg


def polar_stereo_scale_factor(lat_deg, *, south: bool = True, k0: float = 1.0):
    """Point scale factor k of the projection (map distance / true distance)."""
    lat = np.radians(np.asarray(lat_deg, dtype=float))
    s = -np.sin(lat) if south else np.sin(lat)
    return 2.0 * k0 / (1.0 + s)


def lon_to_180(lon_deg):
    return (np.asarray(lon_deg, dtype=float) + 180.0) % 360.0 - 180.0


def lon_to_360(lon_deg):
    return np.asarray(lon_deg, dtype=float) % 360.0
