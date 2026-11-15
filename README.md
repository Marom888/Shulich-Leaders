# Shulich-Leaders — LunarMatch

From Earth to Space: a NASA Space Apps 2026 project by Technion Schulich Leaders.
LunarMatch will identify terrestrial sites suitable for testing lunar-landing
technologies. See [CLAUDE.md](CLAUDE.md) for the full product vision.

**Current phase:** NASA Earthdata acquisition, SRTM raster processing, and
verified visualization. Scoring, site recommendation and cost estimation are
**not** implemented yet.

## Setup (Windows, PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

## NASA Earthdata login (one time)

You need a free account at https://urs.earthdata.nasa.gov. Run this in a
terminal and enter your username and password when prompted:

```powershell
.venv\Scripts\python download_nasa.py --login
```

earthaccess saves the credentials to `%USERPROFILE%\_netrc`, which is outside
the repository. They are never printed or committed. You can also set the
`EARTHDATA_USERNAME` and `EARTHDATA_PASSWORD` environment variables instead.

## Run

```powershell
# Download the Atacama test tile (skipped if nasa_data\S24W070.SRTMGL1.hgt.zip exists)
.venv\Scripts\python download_nasa.py

# Load, print metadata and spot checks, write outputs\terrain_2d.html, terrain_3d.html, slope_2d.html
.venv\Scripts\python visualize_terrain.py
.venv\Scripts\python visualize_terrain.py --max-side 721 --vex 2   # options

# Tests (offline; the real-tile tests skip if the tile is absent)
.venv\Scripts\python -m pytest -q
```

## Rookie 2.0 (three-screen discovery app)

**Find the site. Explain why. Show how to validate.**

```powershell
.venv\Scripts\python run_rookie.py --serve --open             # http://127.0.0.1:8765 (local engine, localhost only)
.venv\Scripts\python run_rookie.py --serve --geocode          # also name areas via OpenStreetMap (sends centroids)
.venv\Scripts\python run_rookie.py --v2                       # static bundle only (search needs --serve)
```

1. **Where on the Moon?** Pick a lunar spot on the globe, the experiments, and the search mode.
2. **Your constraints.** Start location, budget and test-area size. Everything else is under
   *Advanced experiment settings*. What the Earth site cannot reproduce (vacuum, gravity) is always
   shown.
3. **Where to test.** A map of the discovered areas, then for each experiment:
   - **BEST SITE — NOT YET DETERMINED**, with the reason;
   - up to three **DISCOVERED CANDIDATES — NOT YET RANKED**, picked for geographic spread;
   - each card says where, why, what's missing and the next step.

   *Explore site* opens three levels: the decision, why this site, and the technical data.

**What Rookie does not do:**
- It never names a place unless a geocoder returned it.
- It never ranks or scores candidates.
- It offers no candidates for experiments whose required evidence it cannot measure yet.

**Field measurements:** these use `lunarmatch/field_measurements.py`, the future Rookie Scout
record format. Nothing learns automatically.

**Demo links:**
- `#experiments=EXP_02&autorun=1` runs a real search.
- `#job=<id>&exp=EXP_02&site=A&level=2` reopens a result at a given level.

**More documentation:**
- `docs/engineering/spec_comparison_v1_vs_swir.md`
- `docs/integration/data_providers_contract.md`, which includes the coarse-to-fine plan

## Rookie: Your Guide to Lunar Testing

Rookie is the user-facing app; LunarMatch stays the scientific engine. It is
a static, offline web page with no server and no extra dependencies.

```powershell
.venv\Scripts\python run_rookie.py --open     # builds outputs\rookie\index.html and opens it
```

- `outputs\rookie\index.html` is the guided journey: lunar target → experiment
  → parameters → lunar terrain → Earth terrain → results.
- Demo deep link: `index.html#target=mons_mouton_plateau&exp=footpad_penetration&step=3`
- `outputs\rookie\search_preview.html` previews every state of the Rookie
  search animation component.
- **Inputs:** `data/reference/LunarMatch_database_hackathon.xlsx` (team
  planning workbook, read-only) and `assets/animations/rookie_search.gif`.
- **What the app does not do:**
  - Matching is disabled, so the app shows no scores or rankings, and the
    search animation plays only during a real search.
  - Planning experiments are not approved catalog experiments.
  - Data badges distinguish measured, derived, documented, missing and
    not-integrated data.

## Moon–Earth terrain comparison

```powershell
.venv\Scripts\python compare_terrain.py --list-datasets
.venv\Scripts\python compare_terrain.py --moon-point -45 120 10 --earth-bbox -70 -24 -69 -23 --leg-spacing-m 4
.venv\Scripts\python run_rookie.py --open        # steps 4 and 6 show the result
```

- **Lunar region:** any lunar region, given as a point and radius in km, or a
  box. It's described with Moon-sphere geodesy.
- **Earth:** windows are screened over the Earth box, and each window gets
  **per-feature distances** to the lunar reference: Δ p50, Δ p90 and W1 for
  slope and roughness.
- **What it never does:** weight, score, threshold or rank. Results are in
  window-ID order (user decision, 2026-11-15).
- **Experiment gates:** these come from the algorithm spec. They are shown as
  **DRAFT, not approved**; today every experiment reports insufficient data,
  because each one needs features the engine can't compute yet.
- **Data:** connectors plug in through `lunarmatch/terrain/` (see its
  README). Until real lunar connectors exist, the default lunar dataset is
  `MOCK_MOON_DEM`. Rookie then shows a persistent **MOCK DATA** banner and
  MOCK badges.

## Earth analog discovery (Stage A screening)

Rookie discovers candidate terrain windows anywhere data exists; it does not
use a list of known analog sites. Stage A works on local data only:

```powershell
.venv\Scripts\python discover_earth.py --bbox -71 -25 -68 -22                     # W S E N
.venv\Scripts\python discover_earth.py --bbox -71 -25 -68 -22 --constraint "slope_deg.p90<=10"
.venv\Scripts\python discover_earth.py --bbox -71 -25 -68 -22 --plan-downloads    # sizes only, no download
```

- **How it works:** the search box is split into 1° tiles, then into windows
  of a physical size (default 10 km).
- **Per window it reports:** elevation, slope and roughness statistics with
  provenance, cached by source-file hash.
- **Output:** `outputs/discovery/latest.json`, which Rookie's Results step
  summarizes as search coverage.
- **Coverage is explicit:** tiles without local data are reported, never
  assumed.
- **Filters:**
  - windows below the data-quality threshold are marked insufficient data,
    with no numbers;
  - user constraints never pass missing values;
  - windows that pass are unranked.
- **Not computed:** Moon–Earth similarity, scores and rankings. These wait for
  approval under CLAUDE.md.
- **Lunar regions:** `lunarmatch/regions.py` accepts any point and radius, or
  a bounding box, on the IAU 2015 Moon sphere (`lunarmatch/bodies.py`).

## Data handling guarantees

- **Pixel-is-point.** HGT samples sit on integer-degree posts. The loader
  reports both the cell-edge footprint, which is half a cell larger on every
  side, and the sample-centre extent, for example exactly −70…−69 °E and
  −24…−23 °N.
- **NoData.** The SRTM NoData value (−32768) is kept as a mask and plotted as
  NaN gaps. It is never replaced with 0.
- **Downsampling.** Downsampling uses stride decimation (every *k*-th sample,
  plus the last row and column). Every plotted value is an unmodified original
  sample, and hover text shows its original raster row and column. Both
  figures use the same sampled grid.
- **Orientation.** North is up and east is right. This is covered by tests.
- **3D geometry.** The horizontal axes are km east and north of the tile
  centre, using WGS84 local scaling at the centre latitude (about ±0.4 %
  east–west scale variation across a 1° tile). The vertical exaggeration is
  shown in the title.
- **What the checks cover.** They confirm processing consistency, meaning the
  plotted values equal the source values. They do not validate the accuracy of
  NASA's measurements.

## Derived terrain products (`lunarmatch/features/terrain.py`)

These are deterministic derived products, **not scores**. Each layer has the
same shape as the source raster and is labelled "derived from SRTMGL1 v003",
with its method and parameters.

| Layer | Definition | Window (Atacama tile, centre row) |
|---|---|---|
| `slope_deg` | Horn (1981) 3×3 finite differences. East–west spacing uses WGS84 at each row's latitude; north–south spacing uses the meridional radius. Degrees are never treated as metres. | 3 samples ≈ 85 m E–W × 92 m N–S (28.37 m × 30.76 m spacing) |
| `roughness` | Population standard deviation of raw elevation in an N×N window. It is **not detrended**, so a uniform slope also contributes. | N samples; N=3 ≈ 85 m × 92 m, N=5 ≈ 142 m × 154 m |

- Edge cells, and any cell whose window contains NoData, are **NaN**, never 0.
- `outputs/slope_2d.html` shows slope computed at full resolution. It uses the
  same rows and columns, and the same north-up, east-right orientation, as the
  elevation heatmap.

> **Scale limitation.** SRTMGL1 is sampled about every 30 m. Slope and
> roughness here describe terrain at **≥30–90 m scale, not lander-leg
> (metre) scale**. Boulders, small craters and decimetre-scale relief are not
> resolved, and SRTM radar also smooths fine relief. Leg-scale analysis needs
> higher-resolution data, such as USGS 3DEP lidar or aerial stereo.

## Layout

```text
download_nasa.py                 CLI wrapper: login / cached download
visualize_terrain.py             CLI: load -> verify -> 2D/3D HTML
lunarmatch/config.py             project-root-relative paths, Atacama bbox
lunarmatch/data/earthdata_client.py   auth, SRTMGL1 search, skip-if-present download
lunarmatch/data/raster_loader.py      zip extraction, ElevationRaster, stride downsampling
lunarmatch/geodesy.py            WGS84 metres-per-degree, per-row spacing
lunarmatch/features/terrain.py   slope (Horn) and roughness derived layers
lunarmatch/visualization/terrain_plots.py  Plotly heatmaps + metric 3D surface
lunarmatch/experiments/README.md planned extension interfaces (not implemented)
tests/                           pytest; synthetic big-endian int16 HGT fixtures
nasa_data/                       data (only the shared tile zip is tracked)
outputs/                         generated HTML (git-ignored)
```
