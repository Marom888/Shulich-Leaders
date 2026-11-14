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

# Load, print metadata and spot checks, write outputs\terrain_2d.html and terrain_3d.html
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

## Layout

```text
download_nasa.py                 CLI wrapper: login / cached download
visualize_terrain.py             CLI: load -> verify -> 2D/3D HTML
lunarmatch/config.py             project-root-relative paths, Atacama bbox
lunarmatch/data/earthdata_client.py   auth, SRTMGL1 search, skip-if-present download
lunarmatch/data/raster_loader.py      zip extraction, ElevationRaster, stride downsampling
lunarmatch/visualization/terrain_plots.py  Plotly heatmap + metric 3D surface
lunarmatch/experiments/README.md planned extension interfaces (not implemented)
tests/                           pytest; synthetic big-endian int16 HGT fixtures
nasa_data/                       data (only the shared tile zip is tracked)
outputs/                         generated HTML (git-ignored)
```
