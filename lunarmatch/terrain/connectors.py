"""Connector contract and registry.

A connector turns "this body, this lat/lon box" into TerrainPatch objects.
External dataset connectors (owned by the data-integration developer)
implement the same four members as the built-in ones here:

    dataset_id: str            unique, e.g. "LOLA_LDEM_85S_20M"
    body: str                  "Earth" or "Moon"
    is_mock: bool
    nominal_spacing_m: float   typical sample spacing
    units_for(bbox) -> list[CoverageUnit]      cheap, no data transfer
    fingerprint(unit_id) -> str | None         cheap identity for caching; None = no data
    fetch(unit_id) -> TerrainPatch | None      the actual data

Register with ``REGISTRY.register(MyConnector(...))``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from lunarmatch.bodies import EARTH, MOON, band_area_m2
from lunarmatch.config import EXTRACT_DIR
from lunarmatch.terrain.patch import Provenance, TerrainPatch


@dataclass(frozen=True)
class CoverageUnit:
    id: str
    bounds_wsen: tuple[float, float, float, float]
    area_km2: float
    in_coverage: bool = True       # False: outside the dataset's documented extent


@runtime_checkable
class TerrainConnector(Protocol):
    dataset_id: str
    body: str
    is_mock: bool
    nominal_spacing_m: float

    def units_for(self, bbox) -> list[CoverageUnit]: ...
    def fingerprint(self, unit_id: str) -> str | None: ...
    def fetch(self, unit_id: str) -> TerrainPatch | None: ...


class ConnectorRegistry:
    def __init__(self):
        self._items: dict[str, TerrainConnector] = {}

    def register(self, connector, replace: bool = False):
        if not isinstance(connector, TerrainConnector):
            raise TypeError("connector does not implement the TerrainConnector contract")
        if connector.body not in ("Earth", "Moon"):
            raise ValueError("body must be 'Earth' or 'Moon'")
        if connector.dataset_id in self._items and not replace:
            raise ValueError(f"connector {connector.dataset_id!r} already registered")
        self._items[connector.dataset_id] = connector
        return connector

    def get(self, dataset_id: str):
        if dataset_id not in self._items:
            raise KeyError(f"no connector {dataset_id!r}; registered: {sorted(self._items)}")
        return self._items[dataset_id]

    def for_body(self, body: str, include_mock: bool = True) -> list:
        return [c for c in self._items.values()
                if c.body == body and (include_mock or not c.is_mock)]

    def ids(self):
        return sorted(self._items)


def unit_area_km2(body_name: str, bounds) -> float:
    return band_area_m2(EARTH if body_name == "Earth" else MOON, *bounds) / 1e6


@dataclass
class LocalSRTMConnector:
    """Real SRTMGL1 v003 tiles already on disk (no download)."""

    search_dirs: list[Path] | None = None
    extract_dir: Path = EXTRACT_DIR
    dataset_id: str = "SRTMGL1"
    body: str = "Earth"
    is_mock: bool = False
    nominal_spacing_m: float = 30.0
    label: str = "NASA SRTMGL1 v003 (local files)"
    _source: object = field(default=None, repr=False)
    _hash: dict = field(default_factory=dict, repr=False)

    def __post_init__(self):
        from lunarmatch.discovery.sources import LocalSRTMSource
        self._source = (LocalSRTMSource(self.search_dirs) if self.search_dirs is not None
                        else LocalSRTMSource())

    def units_for(self, bbox):
        from lunarmatch.discovery.grid import in_dataset_coverage, tiles_in_bbox
        return [CoverageUnit(t.id, t.bounds, t.area_km2(), in_dataset_coverage(t, "SRTMGL1"))
                for t in tiles_in_bbox(*bbox)]

    def path(self, unit_id):
        from lunarmatch.discovery.grid import Tile
        return self._source.locate(Tile.from_id(unit_id))

    def fingerprint(self, unit_id):
        from lunarmatch.discovery.sources import sha256_file
        p = self.path(unit_id)
        if p is None:
            return None
        if unit_id not in self._hash:
            self._hash[unit_id] = sha256_file(p)
        return self._hash[unit_id]

    def fetch(self, unit_id):
        from lunarmatch.data import raster_loader as rl
        p = self.path(unit_id)
        if p is None:
            return None
        raster = rl.load_raster(p, self.extract_dir)
        prov = Provenance(self.dataset_id, self.label, False, Path(p).name,
                          self.fingerprint(unit_id), licence="NASA open data")
        return TerrainPatch.from_raster(raster, unit_id, prov)


REGISTRY = ConnectorRegistry()
