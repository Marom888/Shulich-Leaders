# LunarMatch – data acquisition layer (Moon ⇄ Earth)

One Python provider per dataset in `config/LunarMatch_Algorithm_Final_Approved_1.xlsx`
(sheet **Datasets**, 19 rows).  All providers share one interface so the future
Moon–Earth matching layer can call any of them the same way:

```python
from lunarmatch import AOI, Body, get_provider

moon = AOI(Body.MOON, -89.46311, 222.51, width_m=1000, height_m=1000)
lola = get_provider("D_LOLA")
print(lola.check_coverage(moon).detail)
res = lola.fetch(moon, layers=["elevation", "slope", "measurement_density",
                               "elevation_uncertainty", "roughness"])
res.layers["elevation"].data        # numpy array (NaN = no data)
res.layers.to_xarray()              # aligned xarray.Dataset
res.warnings, res.metadata, res.files

earth = AOI(Body.EARTH, 36.10, -112.10, 1000, 1000)
s2 = get_provider("D_SENT2").fetch(earth, bands=["red", "green", "blue", "nir"])
```

This stage contains **no** scoring, hazard classification, site selection or ML.

## Datasets and how each is accessed

Endpoints marked ✔ were checked live on 2026-11-15.

| ID | Access implemented | Subsetting | Login |
|---|---|---|---|
| D_LOLA | PGDA product 78, 5 m south-pole sites ✔ (27 sites, bounds read from file headers); ODE search for global GDR grids | HTTP Range on uncompressed strips (~160 kB/layer for 1 km²) | none |
| D_LROC_DTM | ODE REST `pt=SDNDTM` ✔ → GeoTIFF DTM download, AOI cut, slope/roughness derived | whole file (10–25 MB) | none |
| D_LROC_NAC | ODE REST `pt=CDRNAC4` ✔ → observation geometry table; optional file download | whole file (~0.5 GB, not map-projected) | none |
| D_SHADOWCAM | ODE REST KPLO/ShadowCam `DTM/CMOS/UMOS/CAL` ✔; COG variants | COG range reads | none |
| D_LUNAR_SOIL | workbook reference list + team-verified `observations.csv` | – | – |
| D_SCALPSS | reference-only (no public data API confirmed); `register_file()` | – | – |
| D_NASADEM | Planetary Computer COG ✔; Earthdata/LP DAAC via CMR ✔ (needs `~/.netrc`); local `.hgt` | COG range reads | none / Earthdata |
| D_EARTH_3DEP | TNM Access API 1 m tiles ✔; PC `3dep-seamless` 10 m ✔ | COG range reads | none |
| D_NAIP | PC STAC `naip` ✔ | COG range reads | none (SAS token auto) |
| D_SENT2 | Earth Search STAC `sentinel-2-l2a` ✔ | COG range reads | none |
| D_WORLDCOVER | PC STAC `esa-worldcover` ✔ + class fractions | COG range reads | none |
| D_SOILGRIDS | REST point API ✔; VRT/COG area windows ✔ | point / range reads | none (fair use) |
| D_WOSIS | WFS 2.0 `wosis_latest` ✔ (BBOX, GeoJSON) | server-side bbox | none |
| D_USGS_CPT | ScienceBase item listing (often bot-protected) or local folder; schema from FGDC metadata ✔ | nearest soundings | none |
| D_TERN | WCS 2.0.1 (endpoint from TERN catalogue, *not* live-tested) or a COG URL | server-side subset | none |
| D_OSM | Overpass API ✔ (public instance often busy → back-off, mirrors via env) | server-side bbox | none |
| D_PSI_TEST | reference-only; `register_file()` | – | – |
| D_EPHEM | Earth: NOAA equations (offline); Moon: skyfield + DE421 / MOON_ME_DE421 | – | – |
| D_USER | `LanderSpec` validation + static pad pressure | – | – |

Every layer/table carries an **evidence label** (`MEASURED`, `MEASURED_DERIVED`,
`INTERPOLATED`, `DERIVED_HERE`, `MODELED`, `REFERENCE`, `USER_INPUT`, `CALCULATED`).
Values computed by this code (slope from a DEM, roughness, relief) are always
`DERIVED_HERE` and never replace an official layer.

### LOLA facts that matter
* Files are float32, uncompressed, 1 row per strip, NaN nodata, south-polar
  stereographic (R = 1 737 400 m), MOON_ME/DE421.  Not COGs → the pipeline computes
  the byte range itself.
* `ldec` (= `measurement_density`) counts LOLA spots per 5 m pixel. At the Site01
  centre only ~10 % of pixels contain a shot; the rest of the elevation grid is
  interpolated. The provider reports this and can output `measured_mask`.
* No official roughness product exists → `roughness` is `DERIVED_HERE`.
* The task's example point (−89.5°, 150°E) lies ~0.6 km outside Site04; the
  test area is the centre of **Site01 "Connecting ridge"** (89.463°S, 222.51°E).

## Focus experiment: EXP_10 terrain-relative navigation

`lunarmatch.experiments.exp10_trn.collect_exp10_inputs(moon_aoi, earth_aoi)` gathers the
four inputs EXP_10 needs (Moon map image, Moon DEM, Earth image, Earth DEM), block-averages
all of them to one common GSD (never up-sampled), and writes them with a manifest.
For a global Earth search it uses two **proposed** datasets that are not yet in the
approved workbook (see `config/exp10_datasets.json`):

| Role | Moon | Earth (global) | Earth (USA option) |
|---|---|---|---|
| Map image (F_LANDMARK, F_TEXTURE) | `D_LROC_NAC_MAP`: 1 m NAC south-pole mosaic tile (ODE `BDRNPL`) or DTM orthophoto | `D_SENT2` red band, 10 m; scene sun elevation/azimuth recorded | `D_NAIP` 0.6 m |
| DEM (F_RELIEF, F_VISIBILITY) | `D_LROC_DTM` (2–5 m), fallback `D_LOLA` (5 m) | `D_COPDEM` Copernicus GLO-30 (proposed), fallback `D_NASADEM` | `D_EARTH_3DEP` 1 m |

```bash
python examples/exp10_trn_inputs.py                       # Shackleton ridge vs. Atacama
python examples/exp10_trn_inputs.py --usa 36.10 -112.10   # USA site: 3DEP + NAIP
```
With global data the common GSD is ~30 m (Copernicus DEM). That corresponds to the
high-altitude phase of a descent, not to final-approach navigation; the manifest says so.

## Folder layout
```
lunar_project/
  config/      workbook + exported dataset table + lunar reference list
  data/raw/<body>/<dataset_id>/        original bytes (or exact windows) + .meta.json
  data/processed/<body>/<dataset_id>/  derived/cut products + .meta.json
  data/manifest.jsonl                  log of every file written
  src/lunarmatch/core/       AOI, projections, HTTP (retry/resume/range), storage, rasters, STAC, ODE
  src/lunarmatch/providers/  moon/, earth/, common/, reference_only.py
  examples/  tests/
```
Set `LUNARMATCH_DATA=/some/path` to keep data elsewhere.

## Run it from the VS Code terminal
```bash
cd lunar_project
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt        # on Windows, if rasterio fails: conda install -c conda-forge rasterio
python -m pytest -q tests              # offline tests
python examples/shackleton_lola_demo.py      # real LOLA download + validation + plots
python examples/earth_srtm_local_demo.py     # offline, uses the repo's SRTM tile
python examples/dataset_status.py --check    # live coverage check of all 19 datasets
```
For NASADEM via Earthdata add to `~/.netrc` (Windows: `%USERPROFILE%\_netrc`):
`machine urs.earthdata.nasa.gov login <user> password <pass>` – credentials are read
once, never prompted.

## Adding a dataset
Subclass `core.base.DataProvider`, fill `info`, implement `check_coverage()` and
`fetch()`, register the ID in `registry.py`.
