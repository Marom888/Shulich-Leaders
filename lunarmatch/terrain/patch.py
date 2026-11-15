"""TerrainPatch: elevation on a body-aware grid, plus provenance.

Two grid kinds share one interface (``spacing_m``, ``window_bounds``):

* GeographicGrid: regular lat/lon rows/columns (row 0 = north). Metric
  spacing per row comes from the body model (WGS84 for Earth, IAU sphere for
  the Moon). Never mixes bodies.
* ProjectedGrid: regular metric x/y grid (row 0 = north, x east), e.g. a
  polar stereographic product reprojected by a connector, or a local
  azimuthal-equidistant grid. Geographic locations come from ``to_latlon``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Callable

import numpy as np

from lunarmatch.bodies import EARTH, MOON, Body, metres_per_degree

BODIES = {"Earth": EARTH, "Moon": MOON}


@dataclass(frozen=True)
class Provenance:
    dataset_id: str                 # e.g. "SRTMGL1", "MOCK_MOON_DEM"
    label: str                      # human-readable dataset name
    is_mock: bool = False
    source: str = ""                # file name, URL or generator description
    fingerprint: str = ""           # sha256 of source bytes or generator params
    processing: tuple[str, ...] = ()  # e.g. ("block-mean x3",)
    licence: str = ""

    def with_step(self, step: str) -> "Provenance":
        return replace(self, processing=self.processing + (step,))

    def to_dict(self) -> dict:
        return {"dataset_id": self.dataset_id, "label": self.label, "is_mock": self.is_mock,
                "source": self.source, "fingerprint": self.fingerprint,
                "processing": list(self.processing), "licence": self.licence}


@dataclass(frozen=True)
class GeographicGrid:
    body: Body
    lats: np.ndarray                # per row, sample centres, decreasing (north first)
    lons: np.ndarray                # per column, increasing (west first)

    kind = "geographic"

    def __post_init__(self):
        if len(self.lats) > 1 and not np.all(np.diff(self.lats) < 0):
            raise ValueError("lats must decrease (row 0 = north)")
        if len(self.lons) > 1 and not np.all(np.diff(self.lons) > 0):
            raise ValueError("lons must increase (column 0 = west)")

    @property
    def shape(self):
        return (len(self.lats), len(self.lons))

    def _step(self, a):
        return float(abs(a[1] - a[0])) if len(a) > 1 else 0.0

    def spacing_m(self) -> tuple[np.ndarray, np.ndarray]:
        mlat, mlon = metres_per_degree(self.body, self.lats)
        mlat = np.broadcast_to(mlat, self.lats.shape)
        return np.asarray(mlon) * self._step(self.lons), np.asarray(mlat) * self._step(self.lats)

    def window_bounds(self, r0, r1, c0, c1) -> dict:
        hx, hy = self._step(self.lons) / 2, self._step(self.lats) / 2
        w, e = float(self.lons[c0] - hx), float(self.lons[c1 - 1] + hx)
        n, s = float(self.lats[r0] + hy), float(self.lats[r1 - 1] - hy)
        return {"bounds_wsen": [round(w, 6), round(s, 6), round(e, 6), round(n, 6)],
                "centre_lat_lon": [round((s + n) / 2, 6), round((w + e) / 2, 6)]}

    def latlon_of(self, rows, cols):
        return self.lats[np.asarray(rows)], self.lons[np.asarray(cols)]


@dataclass(frozen=True)
class ProjectedGrid:
    body: Body
    x: np.ndarray                   # per column, metres, increasing east
    y: np.ndarray                   # per row, metres, decreasing (north first)
    to_latlon: Callable[[np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray]]
    projection: str = ""

    kind = "projected"

    def __post_init__(self):
        if len(self.y) > 1 and not np.all(np.diff(self.y) < 0):
            raise ValueError("y must decrease (row 0 = north)")
        if len(self.x) > 1 and not np.all(np.diff(self.x) > 0):
            raise ValueError("x must increase (column 0 = west)")

    @property
    def shape(self):
        return (len(self.y), len(self.x))

    def spacing_m(self):
        dx = float(abs(self.x[1] - self.x[0])) if len(self.x) > 1 else 0.0
        dy = float(abs(self.y[1] - self.y[0])) if len(self.y) > 1 else 0.0
        n = len(self.y)
        return np.full(n, dx), np.full(n, dy)

    def window_bounds(self, r0, r1, c0, c1) -> dict:
        dx, dy = self.spacing_m()
        xs = [float(self.x[c0] - dx[0] / 2), float(self.x[c1 - 1] + dx[0] / 2)]
        ys = [float(self.y[r1 - 1] - dy[0] / 2), float(self.y[r0] + dy[0] / 2)]
        clat, clon = self.to_latlon(np.array([(xs[0] + xs[1]) / 2]), np.array([(ys[0] + ys[1]) / 2]))
        cx, cy = np.array([xs[0], xs[1], xs[0], xs[1]]), np.array([ys[0], ys[0], ys[1], ys[1]])
        la, lo = self.to_latlon(cx, cy)
        return {"bounds_xy_m": [round(v, 2) for v in (xs[0], ys[0], xs[1], ys[1])],
                "bounds_wsen": [round(float(lo.min()), 6), round(float(la.min()), 6),
                                round(float(lo.max()), 6), round(float(la.max()), 6)],
                "centre_lat_lon": [round(float(clat[0]), 6), round(float(clon[0]), 6)]}

    def latlon_of(self, rows, cols):
        xx, yy = np.meshgrid(self.x[np.asarray(cols)], self.y[np.asarray(rows)])
        return self.to_latlon(xx, yy)


def azimuthal_equidistant(body: Body, lat0: float, lon0: float):
    """Inverse spherical azimuthal-equidistant projection centred at (lat0, lon0)."""
    R, p0, l0 = body.mean_radius_m, math.radians(lat0), math.radians(lon0)

    def to_latlon(x, y):
        x, y = np.asarray(x, float), np.asarray(y, float)
        rho = np.hypot(x, y)
        c = rho / R
        with np.errstate(invalid="ignore", divide="ignore"):
            lat = np.arcsin(np.cos(c) * math.sin(p0) + np.where(rho > 0, y * np.sin(c) * math.cos(p0) / rho, 0))
            lon = l0 + np.arctan2(x * np.sin(c), rho * math.cos(p0) * np.cos(c) - y * math.sin(p0) * np.sin(c))
        lat = np.where(rho > 0, lat, p0)
        lon = np.where(rho > 0, lon, l0)
        lon = (np.degrees(lon) + 180) % 360 - 180
        return np.degrees(lat), lon

    return to_latlon


@dataclass(frozen=True)
class TerrainPatch:
    id: str                                  # coverage unit ID (e.g. tile "S24W070")
    elevation_m: np.ndarray                  # float64, NaN = no data
    grid: GeographicGrid | ProjectedGrid
    provenance: Provenance
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.elevation_m.shape != self.grid.shape:
            raise ValueError(f"elevation {self.elevation_m.shape} != grid {self.grid.shape}")

    @property
    def body(self) -> Body:
        return self.grid.body

    @property
    def shape(self):
        return self.elevation_m.shape

    def nominal_spacing_m(self) -> tuple[float, float]:
        dx, dy = self.grid.spacing_m()
        mid = len(dx) // 2
        return float(dx[mid]), float(dy[mid])

    @classmethod
    def from_raster(cls, raster, unit_id: str, provenance: Provenance) -> "TerrainPatch":
        """Wrap a lunarmatch ElevationRaster (geographic, Earth)."""
        rows, cols = raster.shape
        grid = GeographicGrid(EARTH, raster.lat_of_row(np.arange(rows)), raster.lon_of_col(np.arange(cols)))
        return cls(unit_id, raster.as_float_nan(), grid, provenance)


def coarsen(patch: TerrainPatch, factor: int) -> TerrainPatch:
    """Block-mean aggregation by an integer factor (coarsening only).

    A block containing any NoData becomes NoData. The result is labelled as
    processed in provenance. Used to match a finer dataset to a coarser one;
    finer data are never synthesised from coarser data.
    """
    if factor < 1 or int(factor) != factor:
        raise ValueError("factor must be a positive integer")
    if factor == 1:
        return patch
    z = patch.elevation_m
    nr, nc = (z.shape[0] // factor) * factor, (z.shape[1] // factor) * factor
    blocks = z[:nr, :nc].reshape(nr // factor, factor, nc // factor, factor)
    zc = blocks.mean(axis=(1, 3))                     # NaN propagates
    g = patch.grid
    if g.kind == "geographic":
        ng = GeographicGrid(g.body, g.lats[:nr].reshape(-1, factor).mean(1),
                            g.lons[:nc].reshape(-1, factor).mean(1))
    else:
        ng = ProjectedGrid(g.body, g.x[:nc].reshape(-1, factor).mean(1),
                           g.y[:nr].reshape(-1, factor).mean(1), g.to_latlon, g.projection)
    return TerrainPatch(patch.id, zc, ng, patch.provenance.with_step(f"block-mean x{factor}"),
                        dict(patch.extra))
