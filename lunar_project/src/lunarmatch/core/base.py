"""Common provider interface.

Every dataset in the workbook gets one subclass of :class:`DataProvider`.
The orchestration layer (future: Moon<->Earth matching) only talks to this
interface, so new providers (Diviner, Mini-RF, Mars datasets...) plug in
without changing callers.
"""
from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from .aoi import AOI
from .bodies import Body
from .evidence import AccessMode, Evidence
from .http import HttpClient, default_client
from .raster import LayerStack
from .storage import DataStore

log = logging.getLogger(__name__)


class ProviderError(RuntimeError):
    pass


class NotCovered(ProviderError):
    """The AOI is outside the dataset's coverage."""


class NotAvailable(ProviderError):
    """The dataset has no machine-readable access path (reference-only)."""


@dataclass(frozen=True)
class DatasetInfo:
    dataset_id: str
    name: str
    body: str                     # "Moon" | "Earth" | "Both" | "Earth / lab"
    provider: str
    resolution: str
    evidence: Evidence
    access: AccessMode
    access_notes: str
    endpoints: tuple[str, ...] = ()
    workbook_source_url: str = ""
    auth: str = "none"
    known_limits: str = ""


@dataclass
class CoverageReport:
    dataset_id: str
    covered: Optional[bool]       # None = could not be determined without a remote query
    detail: str
    products: list = field(default_factory=list)

    def __bool__(self):
        return bool(self.covered)


@dataclass
class ProductRef:
    product_id: str
    title: str = ""
    urls: dict[str, str] = field(default_factory=dict)      # role -> URL
    sizes: dict[str, int] = field(default_factory=dict)     # role -> bytes
    bbox: Optional[tuple[float, float, float, float]] = None
    datetime: Optional[str] = None
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class FetchResult:
    dataset_id: str
    aoi: AOI
    layers: LayerStack = field(default_factory=LayerStack)   # all on one grid
    other_layers: dict = field(default_factory=dict)          # valid layers on a different grid
    tables: dict[str, list[dict]] = field(default_factory=dict)
    files: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def add_layer(self, layer):
        """Add to ``layers`` if aligned, otherwise keep in ``other_layers`` (never resampled silently)."""
        try:
            self.layers.add(layer)
        except ValueError:
            self.other_layers[layer.name] = layer
            self.warn(f"layer '{layer.name}' is on a different grid ({layer.resolution}); kept in other_layers")

    def warn(self, msg: str):
        log.warning("[%s] %s", self.dataset_id, msg)
        self.warnings.append(msg)


class DataProvider(abc.ABC):
    info: DatasetInfo

    def __init__(self, store: Optional[DataStore] = None, client: Optional[HttpClient] = None):
        self.store = store or DataStore()
        self.http = client or default_client()

    # --- interface ------------------------------------------------------
    @property
    def body_dir(self) -> str:
        return {"Moon": "moon", "Earth": "earth"}.get(self.info.body, "common")

    def describe(self) -> dict:
        i = self.info
        return {"dataset_id": i.dataset_id, "name": i.name, "body": i.body, "provider": i.provider,
                "resolution": i.resolution, "evidence": i.evidence.value, "access": i.access.value,
                "auth": i.auth, "endpoints": list(i.endpoints), "notes": i.access_notes,
                "known_limits": i.known_limits}

    def check_body(self, aoi: AOI, allowed: tuple[Body, ...]):
        if aoi.body not in allowed:
            raise ProviderError(f"{self.info.dataset_id} serves {[b.value for b in allowed]}, got AOI on {aoi.body.value}")

    @abc.abstractmethod
    def check_coverage(self, aoi: AOI) -> CoverageReport: ...

    def search(self, aoi: AOI, **kw) -> list[ProductRef]:
        return []

    @abc.abstractmethod
    def fetch(self, aoi: AOI, **kw) -> FetchResult: ...
