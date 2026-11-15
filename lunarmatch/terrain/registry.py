"""Default connector registry.

Built-in: real local SRTM tiles plus MOCK Earth/Moon connectors.

Integration hook for external connectors: if a module
``lunarmatch.terrain.external`` exists and defines ``register(registry)``,
it is called, so the data-integration developer can add connectors without
editing this file or the engine.
"""
from __future__ import annotations

import importlib

from lunarmatch.terrain.connectors import ConnectorRegistry, LocalSRTMConnector
from lunarmatch.terrain.mock import MockEarthConnector, MockMoonConnector

EXTERNAL_MODULE = "lunarmatch.terrain.external"


def default_registry(include_external: bool = True) -> ConnectorRegistry:
    reg = ConnectorRegistry()
    reg.register(LocalSRTMConnector())
    reg.register(MockEarthConnector())
    reg.register(MockMoonConnector())
    if include_external:
        try:
            mod = importlib.import_module(EXTERNAL_MODULE)
        except ModuleNotFoundError as e:
            if e.name != EXTERNAL_MODULE:
                raise
        else:
            mod.register(reg)
    return reg
