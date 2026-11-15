"""EXP_10 – Terrain-relative navigation: input data bundle (no scoring).

Workbook features for EXP_10 and the data each needs (Moon | Earth):

  F_LANDMARK  40 %  map-projected image          | image          -> keypoints / matchability
  F_RELIEF    25 %  DEM                          | DEM            -> relief seen by the camera
  F_TEXTURE   20 %  image at the *same* GSD      | image          -> texture entropy
  F_VISIBILITY 15 % DEM (+ camera trajectory)    | DEM            -> occlusion along descent

Datasets used here (global variant; see config/exp10_datasets.json):

  Moon image   D_LROC_NAC_MAP  NAC 1 m south-pole mosaic tile, or DTM orthophoto
  Moon DEM     D_LROC_DTM      NAC stereo DTM (2-5 m); fallback D_LOLA (5 m, polar sites)
  Earth DEM    D_COPDEM        Copernicus GLO-30 (global);  D_EARTH_3DEP if the site is in the USA
  Earth image  D_SENT2         Sentinel-2 red band (10 m, global); D_NAIP (0.6 m) if in the USA
  Sun          Sentinel-2 scene sun angles; lunar sun via D_EPHEM (needs landing time)

All four rasters are block-averaged to one common GSD (the coarsest native
GSD unless a coarser one is requested) – never up-sampled.  The bundle is
written to data/processed/experiments/EXP_10/<run_name>/ with a manifest that
records every source, native GSD, block factor, evidence type, and every
dataset that was unavailable (instead of silently substituting).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from ..core.aoi import AOI
from ..core.bodies import Body
from ..core.raster import Layer, write_geotiff
from ..core.resample import to_gsd
from ..core.storage import DataStore, utc_now_iso
from ..providers.earth._stac_cog import layer_pixel_size_m
from ..registry import get_provider


@dataclass
class Exp10Bundle:
    run_name: str
    moon_aoi: AOI
    earth_aoi: AOI
    common_gsd_m: Optional[float] = None
    layers: dict = field(default_factory=dict)   # "moon_image", "moon_dem", "earth_image", "earth_dem"
    native: dict = field(default_factory=dict)
    sources: dict = field(default_factory=dict)
    status: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    files: list = field(default_factory=list)


def _px_m(lyr: Layer, aoi: AOI) -> tuple[float, float]:
    return layer_pixel_size_m(lyr, aoi.lat) if aoi.body is Body.EARTH else lyr.resolution


def _try(bundle: Exp10Bundle, key: str, attempts):
    """attempts: list of (label, callable -> (Layer, metadata dict)). First success wins."""
    errors = []
    for label, fn in attempts:
        try:
            lyr, meta = fn()
            bundle.layers[key] = lyr
            bundle.sources[key] = {"dataset": label, **meta}
            bundle.status[key] = "OK"
            if errors:
                bundle.status[key] = f"OK via fallback {label} (" + "; ".join(errors) + ")"
            return
        except Exception as exc:  # record and try the next source
            errors.append(f"{label}: {type(exc).__name__}: {exc}")
    bundle.status[key] = "UNAVAILABLE – " + " | ".join(errors)
    bundle.warnings.append(f"{key} unavailable")


def collect_exp10_inputs(moon_aoi: AOI, earth_aoi: AOI, *, run_name: str = "exp10_run",
                         common_gsd_m: Optional[float] = None, earth_in_usa: bool = False,
                         prefer_low_sun: bool = True, s2_datetime: Optional[str] = None,
                         store: Optional[DataStore] = None, save: bool = True) -> Exp10Bundle:
    if moon_aoi.body is not Body.MOON or earth_aoi.body is not Body.EARTH:
        raise ValueError("moon_aoi must be on the Moon and earth_aoi on Earth")
    store = store or DataStore()
    b = Exp10Bundle(run_name, moon_aoi, earth_aoi)

    def moon_image_mosaic():
        r = get_provider("D_LROC_NAC_MAP", store=store).fetch(moon_aoi, source="polar_mosaic")
        return r.layers["image"], {**r.metadata, "warnings": r.warnings}

    def moon_image_ortho():
        r = get_provider("D_LROC_NAC_MAP", store=store).fetch(moon_aoi, source="dtm_orthophoto")
        return r.layers["image"], {**r.metadata, "warnings": r.warnings}

    def moon_dem_lroc():
        r = get_provider("D_LROC_DTM", store=store).fetch(moon_aoi, derive=False)
        return r.layers["elevation"], {**r.metadata, "warnings": r.warnings}

    def moon_dem_lola():
        r = get_provider("D_LOLA", store=store).fetch(moon_aoi, layers=["elevation", "measurement_density"])
        return r.layers["elevation"], {k: v for k, v in r.metadata.items() if k != "corners_latlon"} | {"warnings": r.warnings}

    def earth_dem(pid):
        def f():
            r = get_provider(pid, store=store).fetch(earth_aoi, derive=False)
            return r.layers["elevation"], {**r.metadata, "warnings": r.warnings}
        return f

    def earth_img_s2():
        r = get_provider("D_SENT2", store=store).fetch(earth_aoi, bands=["red"], prefer_low_sun=prefer_low_sun,
                                                       datetime=s2_datetime)
        return r.layers["red"], {**r.metadata, "band": "B04 red (closest S2 band to NAC ~600 nm)",
                                 "warnings": r.warnings}

    def earth_img_naip():
        r = get_provider("D_NAIP", store=store).fetch(earth_aoi, bands=["red"])
        return r.layers["red"], {**r.metadata, "warnings": r.warnings}

    moon_img = [("D_LROC_NAC_MAP polar mosaic", moon_image_mosaic)] if moon_aoi.lat < -85 else []
    _try(b, "moon_image", moon_img + [("D_LROC_NAC_MAP DTM orthophoto", moon_image_ortho)])
    _try(b, "moon_dem", [("D_LROC_DTM", moon_dem_lroc), ("D_LOLA", moon_dem_lola)])
    dems = ([("D_EARTH_3DEP", earth_dem("D_EARTH_3DEP"))] if earth_in_usa else []) + \
           [("D_COPDEM", earth_dem("D_COPDEM")), ("D_NASADEM", earth_dem("D_NASADEM"))]
    _try(b, "earth_dem", dems)
    imgs = ([("D_NAIP", earth_img_naip)] if earth_in_usa else []) + [("D_SENT2", earth_img_s2)]
    _try(b, "earth_image", imgs)

    # ---- common GSD (coarsest native unless a coarser one was requested)
    for k, lyr in b.layers.items():
        aoi = moon_aoi if k.startswith("moon") else earth_aoi
        b.native[k] = list(_px_m(lyr, aoi))
    if b.native:
        coarsest = max(max(v) for v in b.native.values())
        b.common_gsd_m = max(common_gsd_m or 0.0, coarsest)
        for k, lyr in list(b.layers.items()):
            aoi = moon_aoi if k.startswith("moon") else earth_aoi
            b.layers[k] = to_gsd(lyr, b.common_gsd_m, tuple(b.native[k]))
        imgs_ = [b.native[k] for k in ("moon_image", "earth_image") if k in b.native]
        if len(imgs_) == 2 and max(imgs_[1]) / max(imgs_[0]) > 5:
            b.warnings.append(f"image GSDs differ strongly (Moon {max(imgs_[0]):.1f} m vs Earth {max(imgs_[1]):.1f} m); "
                              f"both compared at {b.common_gsd_m:.1f} m – this represents the high-altitude phase of "
                              "a descent, not final-approach navigation")

    if save:
        out = store.processed_dir("experiments", "EXP_10", run_name)
        for k, lyr in b.layers.items():
            p = out / f"{k}.tif"
            write_geotiff(lyr, p)
            b.files.append(str(p))
        manifest = {
            "experiment": "EXP_10", "run_name": run_name, "created_utc": utc_now_iso(),
            "moon_aoi": moon_aoi.to_dict(), "earth_aoi": earth_aoi.to_dict(), "common_gsd_m": b.common_gsd_m,
            "native_pixel_m": b.native, "status": b.status, "warnings": b.warnings,
            "layers": {k: {**lyr.metadata(), "stats": lyr.stats()} for k, lyr in b.layers.items()},
            "sources": json.loads(json.dumps(b.sources, default=str)),
            "note": "Data bundle only – no navigation performance or similarity score computed.",
        }
        mp = out / "manifest.json"
        mp.write_text(json.dumps(manifest, indent=2, default=str))
        b.files.append(str(mp))
    return b
