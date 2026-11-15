"""Vocabulary used to label *how* every number was obtained.

The workbook insists that measured, derived, modelled and interpolated
values are never mixed up.  Every layer / table returned by a provider
carries one of these labels.
"""
from __future__ import annotations

from enum import Enum


class Evidence(str, Enum):
    MEASURED = "MEASURED"                    # direct instrument observation (e.g. CPT qc, image DN)
    MEASURED_DERIVED = "MEASURED_DERIVED"    # official product derived from measurements (DEM, slope map)
    INTERPOLATED = "INTERPOLATED"            # gridded value where no direct measurement fell in the cell
    DERIVED_HERE = "DERIVED_HERE"            # computed by this pipeline from another layer
    MODELED = "MODELED"                      # statistical/physical model output (SoilGrids, WorldCover)
    REFERENCE = "REFERENCE"                  # literature / sample reference, not site-specific
    USER_INPUT = "USER_INPUT"                # values supplied by the team
    CALCULATED = "CALCULATED"                # deterministic computation (ephemeris)
    NOT_AVAILABLE = "NOT_AVAILABLE"


class AccessMode(str, Enum):
    """How a dataset can be obtained by this code base."""

    AUTOMATED = "AUTOMATED"                      # anonymous API / direct download implemented
    AUTOMATED_WITH_LOGIN = "AUTOMATED_WITH_LOGIN"  # implemented, needs credentials (~/.netrc etc.)
    SEARCH_AND_DOWNLOAD = "SEARCH_AND_DOWNLOAD"  # catalogue search + whole-file download (no subsetting)
    LOCAL_FILES = "LOCAL_FILES"                  # user supplies files; code parses them
    REFERENCE_ONLY = "REFERENCE_ONLY"            # no data API; registry/provenance record only
    COMPUTED = "COMPUTED"                        # no download; computed locally
    USER_INPUT = "USER_INPUT"
