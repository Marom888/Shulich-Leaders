"""Dataset_ID -> provider class.  One entry per row of the workbook "Datasets" sheet."""
from __future__ import annotations

import importlib
import json
from typing import Optional

from .core.storage import PROJECT_ROOT

_PROVIDERS = {
    # Moon
    "D_LOLA": "providers.moon.lola:LOLAProvider",
    "D_LROC_DTM": "providers.moon.lroc_dtm:LROCDTMProvider",
    "D_LROC_NAC": "providers.moon.lroc_nac:LROCNACProvider",
    "D_SHADOWCAM": "providers.moon.shadowcam:ShadowCamProvider",
    "D_LUNAR_SOIL": "providers.moon.lunar_soil:LunarSoilProvider",
    "D_SCALPSS": "providers.reference_only:SCALPSSProvider",
    "D_LROC_NAC_MAP": "providers.moon.lroc_maps:LROCMapsProvider",   # proposed (EXP_10)
    # Earth
    "D_NASADEM": "providers.earth.nasadem:NASADEMProvider",
    "D_EARTH_3DEP": "providers.earth.usgs_3dep:USGS3DEPProvider",
    "D_NAIP": "providers.earth.naip:NAIPProvider",
    "D_SENT2": "providers.earth.sentinel2:Sentinel2Provider",
    "D_WORLDCOVER": "providers.earth.worldcover:WorldCoverProvider",
    "D_SOILGRIDS": "providers.earth.soilgrids:SoilGridsProvider",
    "D_WOSIS": "providers.earth.wosis:WoSISProvider",
    "D_USGS_CPT": "providers.earth.usgs_cpt:USGSCPTProvider",
    "D_TERN": "providers.earth.tern:TERNProvider",
    "D_OSM": "providers.earth.osm:OSMProvider",
    "D_PSI_TEST": "providers.reference_only:PSITestProvider",
    "D_COPDEM": "providers.earth.copernicus_dem:CopernicusDEMProvider",  # proposed (global Earth DEM)
    # Both
    "D_EPHEM": "providers.common.ephemeris:EphemerisProvider",
    "D_USER": "providers.common.user_inputs:UserInputProvider",
}


def provider_class(dataset_id: str):
    try:
        mod, cls = _PROVIDERS[dataset_id].split(":")
    except KeyError:
        raise KeyError(f"unknown dataset id {dataset_id!r}; known: {sorted(_PROVIDERS)}") from None
    return getattr(importlib.import_module(f"{__package__}.{mod}"), cls)


def get_provider(dataset_id: str, **kw):
    return provider_class(dataset_id)(**kw)


PROPOSED = {"D_LROC_NAC_MAP", "D_COPDEM"}  # not (yet) rows of the approved workbook


def list_datasets(include_proposed: bool = True) -> list[str]:
    return [d for d in _PROVIDERS if include_proposed or d not in PROPOSED]


def workbook_datasets() -> list[dict]:
    """Rows of the workbook 'Datasets' sheet (exported to config/datasets_workbook.json)."""
    p = PROJECT_ROOT / "config" / "datasets_workbook.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def status_table(aoi=None) -> list[dict]:
    """Describe every provider (and optionally its coverage of ``aoi``)."""
    rows = []
    for did in list_datasets():
        p = get_provider(did)
        row = p.describe()
        if aoi is not None:
            try:
                if p.info.body in ("Moon", "Earth") and p.info.body.lower() != aoi.body.value:
                    row["coverage"] = "n/a (other body)"
                else:
                    c = p.check_coverage(aoi)
                    row["coverage"] = {True: "COVERED", False: "NOT COVERED", None: "UNKNOWN"}[c.covered] + f" – {c.detail}"
            except Exception as exc:  # network etc.
                row["coverage"] = f"ERROR: {exc}"
        rows.append(row)
    return rows
