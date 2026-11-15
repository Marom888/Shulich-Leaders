"""MOCK terrain connectors: synthetic, deterministic, clearly labelled.

These stand in for real Earth/Moon connectors until the data-integration
developer's connectors are registered. Every patch they produce carries
``is_mock=True`` and dataset IDs starting with "MOCK_"; the engine and Rookie
propagate that flag to every value. Mock terrain is NOT a model of any real
place; it is a fractal surface (plus bowl craters for the Moon) used only to
exercise the pipeline.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass

import numpy as np

from lunarmatch.bodies import EARTH, MOON
from lunarmatch.terrain.connectors import CoverageUnit, unit_area_km2
from lunarmatch.terrain.patch import (GeographicGrid, ProjectedGrid, Provenance, TerrainPatch,
                                      azimuthal_equidistant)

MOCK_VERSION = "mock-terrain/1"


def fractal_surface(shape, spacing_m, seed, hurst=0.8, rms_m=40.0, cutoff_m=200.0):
    """Gaussian random surface with a power-law spectrum (deterministic per seed)."""
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal(shape)
    ky = np.fft.fftfreq(shape[0], d=spacing_m)
    kx = np.fft.rfftfreq(shape[1], d=spacing_m)
    k = np.hypot(*np.meshgrid(ky, kx, indexing="ij"))
    k[0, 0] = np.inf
    filt = (k ** 2 + (1 / cutoff_m) ** 2) ** (-(hurst + 1) / 2)
    filt[0, 0] = 0
    z = np.fft.irfft2(np.fft.rfft2(noise) * filt, s=shape)
    return z / z.std() * rms_m


def add_craters(z, spacing_m, seed, n=40, d_min_m=150.0, d_max_m=3000.0):
    """Simple bowl craters (depth 0.2 D) with raised rims; power-law sizes."""
    rng = np.random.default_rng(seed + 1)
    rows, cols = np.indices(z.shape)
    out = z.copy()
    a = 2.0
    u = rng.random(n)
    diam = (d_min_m ** (1 - a) + u * (d_max_m ** (1 - a) - d_min_m ** (1 - a))) ** (1 / (1 - a))
    for d in diam:
        r0, c0 = rng.integers(0, z.shape[0]), rng.integers(0, z.shape[1])
        R = d / 2
        r = np.hypot(rows - r0, cols - c0) * spacing_m
        inside = r < R
        out[inside] += 0.2 * d * ((r[inside] / R) ** 2 - 1)
        out += 0.04 * d * np.exp(-((r - R) / (0.3 * R)) ** 2)
    return out


def _fingerprint(params: dict) -> str:
    return hashlib.sha256(json.dumps({**params, "v": MOCK_VERSION}, sort_keys=True).encode()).hexdigest()


@dataclass
class MockEarthConnector:
    """MOCK Earth DEM on 1° geographic tiles at ``arcsec`` sample spacing."""

    seed: int = 7
    arcsec: float = 3.0
    rms_m: float = 40.0
    cutoff_m: float = 3000.0
    dataset_id: str = "MOCK_EARTH_DEM"
    body: str = "Earth"
    is_mock: bool = True
    label: str = "MOCK Earth DEM (synthetic, not real terrain)"

    @property
    def nominal_spacing_m(self):
        return 30.87 * self.arcsec

    def units_for(self, bbox):
        from lunarmatch.discovery.grid import tiles_in_bbox
        return [CoverageUnit(t.id, t.bounds, unit_area_km2("Earth", t.bounds)) for t in tiles_in_bbox(*bbox)]

    def _params(self, unit_id):
        return {"unit": unit_id, "seed": self.seed, "arcsec": self.arcsec, "rms": self.rms_m,
                "cutoff": self.cutoff_m}

    def fingerprint(self, unit_id):
        return _fingerprint(self._params(unit_id))

    def fetch(self, unit_id):
        from lunarmatch.discovery.grid import Tile
        t = Tile.from_id(unit_id)
        n = int(round(3600 / self.arcsec)) + 1
        step = self.arcsec / 3600
        lats = (t.lat + 1) - np.arange(n) * step
        lons = t.lon + np.arange(n) * step
        tile_seed = self.seed * 100_003 + (t.lat + 90) * 361 + (t.lon + 180)
        z = 1500 + fractal_surface((n, n), self.nominal_spacing_m, tile_seed, rms_m=self.rms_m,
                                   cutoff_m=self.cutoff_m)
        prov = Provenance(self.dataset_id, self.label, True, f"fractal generator seed={tile_seed}",
                          self.fingerprint(unit_id), licence="synthetic")
        return TerrainPatch(unit_id, z, GeographicGrid(EARTH, lats, lons), prov)


@dataclass
class MockMoonConnector:
    """MOCK lunar DEM: one local azimuthal-equidistant patch per request box."""

    seed: int = 11
    spacing: float = 30.0
    rms_m: float = 6.0
    cutoff_m: float = 800.0
    craters: int = 60
    max_extent_m: float = 60_000.0
    dataset_id: str = "MOCK_MOON_DEM"
    body: str = "Moon"
    is_mock: bool = True
    label: str = "MOCK Moon DEM (synthetic fractal + craters, not real terrain)"

    @property
    def nominal_spacing_m(self):
        return self.spacing

    @staticmethod
    def unit_id(bbox):
        return "MOCKMOON[" + ",".join(f"{v:g}" for v in bbox) + "]"

    @staticmethod
    def parse(unit_id):
        return tuple(float(v) for v in unit_id[len("MOCKMOON["):-1].split(","))

    def units_for(self, bbox):
        return [CoverageUnit(self.unit_id(bbox), tuple(bbox), unit_area_km2("Moon", bbox))]

    def fingerprint(self, unit_id):
        return _fingerprint({"unit": unit_id, "seed": self.seed, "spacing": self.spacing,
                             "rms": self.rms_m, "cutoff": self.cutoff_m, "craters": self.craters})

    def fetch(self, unit_id):
        w, s, e, n = self.parse(unit_id)
        lat0, lon0 = (s + n) / 2, (w + e) / 2
        per_deg = MOON.mean_radius_m * math.pi / 180
        height = min((n - s) * per_deg, self.max_extent_m)
        width = min(((e - w) % 360 or 360) * per_deg * max(math.cos(math.radians(lat0)), 1e-3),
                    self.max_extent_m)
        nr, nc = max(3, int(height / self.spacing)), max(3, int(width / self.spacing))
        x = (np.arange(nc) - (nc - 1) / 2) * self.spacing
        y = ((nr - 1) / 2 - np.arange(nr)) * self.spacing
        seed = int(_fingerprint({"u": unit_id, "s": self.seed})[:8], 16)   # deterministic
        z = fractal_surface((nr, nc), self.spacing, seed, rms_m=self.rms_m, cutoff_m=self.cutoff_m)
        z = add_craters(z, self.spacing, seed, n=self.craters)
        grid = ProjectedGrid(MOON, x, y, azimuthal_equidistant(MOON, lat0, lon0),
                             f"local azimuthal equidistant on IAU 2015 Moon sphere at ({lat0:g}, {lon0:g})")
        prov = Provenance(self.dataset_id, self.label, True, f"fractal+craters seed={seed}",
                          self.fingerprint(unit_id), licence="synthetic")
        return TerrainPatch(unit_id, z, grid, prov)
