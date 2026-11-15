"""Area of interest (AOI) defined by a centre point and a size in metres.

The same AOI object is used for Moon and Earth; the body decides which
geodesy is applied.  Two representations are provided:

* :meth:`AOI.geographic_bbox` – lon/lat box (used by STAC/OGC/ODE searches).
* :meth:`AOI.polar_stereo_box` – exact metric box in lunar polar
  stereographic metres (used for the PGDA LOLA grids).

Near the lunar poles a lon/lat box is badly conditioned (a 1 km box at
-89.5° spans ~3.9° of longitude); the metric box is therefore the primary
representation for polar lunar data.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from .bodies import MOON_RADIUS_M, Body, earth_radii_m
from .projections import (
    lon_to_180,
    polar_stereo_forward,
    polar_stereo_inverse,
    polar_stereo_scale_factor,
)


@dataclass(frozen=True)
class AOI:
    body: Body
    lat: float
    lon: float
    width_m: float
    height_m: float
    name: str = ""

    def __post_init__(self):
        object.__setattr__(self, "body", Body(self.body))
        if not -90.0 <= self.lat <= 90.0:
            raise ValueError(f"latitude out of range: {self.lat}")
        if self.width_m <= 0 or self.height_m <= 0:
            raise ValueError("width_m and height_m must be positive")

    # ------------------------------------------------------------------ geodesy
    def _radii(self) -> tuple[float, float]:
        if self.body is Body.MOON:
            return MOON_RADIUS_M, MOON_RADIUS_M
        return earth_radii_m(self.lat)

    def geographic_bbox(self, lon_convention: str = "180") -> tuple[float, float, float, float]:
        """(lon_min, lat_min, lon_max, lat_max) in degrees.

        If the box reaches a pole, the full longitude range is returned and the
        latitude limit is clamped to +-90.
        """
        m_rad, n_rad = self._radii()
        dlat = math.degrees((self.height_m / 2.0) / m_rad)
        lat_min, lat_max = self.lat - dlat, self.lat + dlat
        if lat_max >= 90.0 or lat_min <= -90.0 or abs(self.lat) > 89.999:
            lat_min, lat_max = max(lat_min, -90.0), min(lat_max, 90.0)
            lo, hi = (-180.0, 180.0) if lon_convention == "180" else (0.0, 360.0)
            return (lo, lat_min, hi, lat_max)
        # Use the most poleward latitude so the box fully contains the AOI.
        lat_edge = max(abs(lat_min), abs(lat_max))
        dlon = math.degrees((self.width_m / 2.0) / (n_rad * math.cos(math.radians(lat_edge))))
        if dlon >= 180.0:
            lo, hi = (-180.0, 180.0) if lon_convention == "180" else (0.0, 360.0)
            return (lo, lat_min, hi, lat_max)
        lon_c = float(lon_to_180(self.lon)) if lon_convention == "180" else self.lon % 360.0
        return (lon_c - dlon, lat_min, lon_c + dlon, lat_max)

    def polar_stereo_center(self) -> tuple[float, float]:
        if self.body is not Body.MOON:
            raise ValueError("polar stereographic helpers are defined for the Moon here")
        x, y = polar_stereo_forward(self.lat, self.lon, south=self.lat < 0)
        return float(x), float(y)

    def polar_stereo_box(self) -> tuple[float, float, float, float]:
        """(xmin, ymin, xmax, ymax) in lunar polar-stereographic metres.

        The box is axis-aligned with the projection grid (not with local
        north).  Width/height are corrected for the projection scale factor at
        the centre (k ~ 1.00002 at -89.5°, i.e. negligible near the pole).
        """
        x, y = self.polar_stereo_center()
        k = float(polar_stereo_scale_factor(self.lat, south=self.lat < 0))
        hw, hh = k * self.width_m / 2.0, k * self.height_m / 2.0
        return (x - hw, y - hh, x + hw, y + hh)

    def polar_stereo_corners_latlon(self):
        xmin, ymin, xmax, ymax = self.polar_stereo_box()
        xs = [xmin, xmax, xmax, xmin]
        ys = [ymax, ymax, ymin, ymin]
        lat, lon = polar_stereo_inverse(xs, ys, south=self.lat < 0)
        return list(zip(lat.tolist(), lon.tolist()))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["body"] = self.body.value
        return d
