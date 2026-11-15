"""LunarMatch data-acquisition layer.

One provider per dataset listed in the LunarMatch workbook (sheet "Datasets").
Every provider exposes the same interface (see :mod:`lunarmatch.core.base`):

    provider.check_coverage(aoi)   -> CoverageReport
    provider.search(aoi, ...)      -> list[ProductRef]
    provider.fetch(aoi, ...)       -> FetchResult  (layers / tables + provenance)

Use :func:`lunarmatch.registry.get_provider` to obtain a provider by its
workbook Dataset_ID (e.g. ``"D_LOLA"``, ``"D_NASADEM"``).

This package acquires and validates data only. It deliberately contains no
site scoring, hazard classification or ranking.
"""

__version__ = "0.1.0"

from .core.aoi import AOI  # noqa: E402,F401
from .core.bodies import Body  # noqa: E402,F401
from .registry import get_provider, list_datasets  # noqa: E402,F401
