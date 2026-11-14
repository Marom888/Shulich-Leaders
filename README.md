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

`visualize_terrain.py` looks for the tile in this order:
1. `nasa_data/S24W070.SRTMGL1.hgt.zip`
2. any `S24W070.hgt` under `nasa_data/`
3. any `S24W070.hgt` under the project root

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
