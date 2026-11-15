"""Earth search-space partitioning into 1° × 1° tiles (SRTM/NASADEM naming).

A tile is named by its south-west corner: S24W070 covers latitude -24..-23
and longitude -70..-69. Tiles are the unit of data access and caching;
windows (descriptors.py) subdivide tiles into physically sized areas.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from lunarmatch.bodies import EARTH, band_area_m2

TILE_RE = re.compile(r"^([NS])(\d{2})([EW])(\d{3})$")

# Latitude range of tile south edges each dataset can contain (inclusive).
DATASET_TILE_LAT_RANGE = {
    "SRTMGL1": (-56, 59),     # SRTM: 56°S to 60°N
    "NASADEM": (-56, 59),
}


class GridError(ValueError):
    """Invalid tile ID or search region."""


@dataclass(frozen=True, order=True)
class Tile:
    lat: int    # south edge, degrees
    lon: int    # west edge, degrees

    def __post_init__(self):
        if not (-90 <= self.lat <= 89 and -180 <= self.lon <= 179):
            raise GridError(f"tile corner out of range: {self.lat}, {self.lon}")

    @property
    def id(self) -> str:
        return (f"{'N' if self.lat >= 0 else 'S'}{abs(self.lat):02d}"
                f"{'E' if self.lon >= 0 else 'W'}{abs(self.lon):03d}")

    @property
    def bounds(self) -> tuple[int, int, int, int]:
        return (self.lon, self.lat, self.lon + 1, self.lat + 1)

    def area_km2(self) -> float:
        return band_area_m2(EARTH, *self.bounds) / 1e6

    @classmethod
    def from_id(cls, tile_id: str) -> "Tile":
        m = TILE_RE.match(tile_id)
        if not m:
            raise GridError(f"not a tile ID: {tile_id!r}")
        lat = int(m.group(2)) * (1 if m.group(1) == "N" else -1)
        lon = int(m.group(4)) * (1 if m.group(3) == "E" else -1)
        return cls(lat, lon)


def validate_bbox(west: float, south: float, east: float, north: float) -> None:
    for v, n in ((west, "west"), (east, "east")):
        if not -180 <= v <= 180:
            raise GridError(f"{n} must be within [-180, 180]")
    for v, n in ((south, "south"), (north, "north")):
        if not -90 <= v <= 90:
            raise GridError(f"{n} must be within [-90, 90]")
    if not south < north:
        raise GridError("south must be < north")
    if west == east:
        raise GridError("west and east must differ")


def tiles_in_bbox(west: float, south: float, east: float, north: float) -> list[Tile]:
    """All 1° tiles intersecting the box. west > east crosses the antimeridian."""
    validate_bbox(west, south, east, north)
    lats = range(math.floor(south), min(math.ceil(north), 90))
    if west < east:
        lon_ranges = [(west, east)]
    else:
        lon_ranges = [(west, 180), (-180, east)]
    lons: list[int] = []
    for w, e in lon_ranges:
        lons.extend(x for x in range(math.floor(w), min(math.ceil(e), 180)) if x not in lons)
    return sorted(Tile(la, lo) for la in lats for lo in lons)


def in_dataset_coverage(tile: Tile, dataset: str) -> bool:
    lo, hi = DATASET_TILE_LAT_RANGE[dataset]
    return lo <= tile.lat <= hi
