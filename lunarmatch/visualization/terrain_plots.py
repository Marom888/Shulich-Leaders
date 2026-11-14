"""Plotly 2D heatmap and 3D surface built from one SampledGrid.

Both figures are fed the *same* SampledGrid, so every plotted elevation is
an unmodified original SRTM sample (stride decimation; NoData -> NaN gaps).

Geometry
--------
* 2D: longitude/latitude axes, rows flipped so latitude ascends upward
  (north up, east right). The y/x display ratio is set to the WGS84 ratio of
  metres-per-degree latitude to metres-per-degree longitude at the tile
  centre, so the map is not horizontally stretched.
* 3D: horizontal axes are kilometres east/north of the tile centre, using
  WGS84 local scaling at the centre latitude (a local equirectangular
  approximation: over a 1-degree tile at ~23.5 S the east-west scale varies
  by about +/-0.4 %). Vertical exaggeration is applied only through the
  scene aspect ratio and is stated in the title; z values stay in metres.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import plotly.graph_objects as go

from lunarmatch.data.raster_loader import SampledGrid

WGS84_A = 6378137.0
WGS84_F = 1 / 298.257223563
WGS84_E2 = WGS84_F * (2 - WGS84_F)

# Single-hue sequential ramp (light = low, dark = high).
ELEVATION_SCALE = [
    [0.00, "#cde2fb"], [0.17, "#9ec5f4"], [0.33, "#6da7ec"],
    [0.50, "#3987e5"], [0.67, "#256abf"], [0.83, "#184f95"], [1.00, "#0d366b"],
]

SOURCE_LABEL = "NASA SRTMGL1 v003"


def metres_per_degree(lat_deg: float) -> tuple[float, float]:
    """(m per degree latitude, m per degree longitude) on WGS84 at ``lat_deg``."""
    phi = np.radians(lat_deg)
    s2 = np.sin(phi) ** 2
    m = WGS84_A * (1 - WGS84_E2) / (1 - WGS84_E2 * s2) ** 1.5   # meridional
    n = WGS84_A / np.sqrt(1 - WGS84_E2 * s2)                     # prime vertical
    return float(m * np.pi / 180), float(n * np.cos(phi) * np.pi / 180)


def local_km(grid: SampledGrid) -> tuple[np.ndarray, np.ndarray, float, float]:
    """x_km per column, y_km per row (east/north of the grid centre)."""
    lat0 = float((grid.lats.max() + grid.lats.min()) / 2)
    lon0 = float((grid.lons.max() + grid.lons.min()) / 2)
    mlat, mlon = metres_per_degree(lat0)
    x = (grid.lons - lon0) * mlon / 1000.0
    y = (grid.lats - lat0) * mlat / 1000.0
    return x, y, lat0, lon0


def _index_customdata(grid: SampledGrid) -> np.ndarray:
    rr, cc = np.meshgrid(grid.rows, grid.cols, indexing="ij")
    return np.stack([rr, cc], axis=-1)


def _flip_north_up(grid: SampledGrid):
    """Arrays ordered with latitude ascending (last plotted row = north)."""
    return grid.values[::-1], grid.lats[::-1], _index_customdata(grid)[::-1]


def _sampling_note(grid: SampledGrid) -> str:
    r, c = grid.source_shape
    return (f"stride decimation: every {grid.step} sample(s) of {r}x{c} "
            f"-> {grid.shape[0]}x{grid.shape[1]}; original values, not interpolated")


def heatmap_figure(grid: SampledGrid, title: str = "") -> go.Figure:
    z, lats, cd = _flip_north_up(grid)
    lat0 = float(grid.lats.mean())
    mlat, mlon = metres_per_degree(lat0)
    fig = go.Figure(go.Heatmap(
        z=z, x=grid.lons, y=lats, customdata=cd,
        colorscale=ELEVATION_SCALE,
        colorbar=dict(title=dict(text="Elevation (m)")),
        hoverongaps=False,
        hovertemplate=("lat %{y:.5f}°, lon %{x:.5f}°<br>"
                       "<b>%{z:.0f} m</b> (original sample)<br>"
                       "raster row %{customdata[0]}, col %{customdata[1]}"
                       "<extra></extra>"),
    ))
    fig.update_layout(
        title=dict(text=f"{title or 'SRTM elevation'} - 2D heatmap<br>"
                        f"<sup>{SOURCE_LABEL}; {_sampling_note(grid)}; "
                        f"NoData shown as gaps</sup>"),
        xaxis=dict(title="Longitude (°E)", constrain="domain"),
        yaxis=dict(title="Latitude (°N)", scaleanchor="x",
                   scaleratio=mlat / mlon, constrain="domain"),
        template="plotly_white", width=900, height=850,
    )
    return fig


def surface_figure(grid: SampledGrid, vertical_exaggeration: float = 3.0,
                   title: str = "") -> go.Figure:
    if vertical_exaggeration <= 0:
        raise ValueError("vertical_exaggeration must be > 0")
    x_km, y_km, lat0, lon0 = local_km(grid)
    z, _, cd = _flip_north_up(grid)
    y_km = y_km[::-1]

    xr = float(x_km.max() - x_km.min())
    yr = float(y_km.max() - y_km.min())
    zr_km = float(np.nanmax(z) - np.nanmin(z)) / 1000.0 if np.isfinite(z).any() else 0.0
    base = max(xr, yr)
    aspect = dict(x=xr / base, y=yr / base,
                  z=max(zr_km * vertical_exaggeration / base, 1e-3))

    fig = go.Figure(go.Surface(
        x=x_km, y=y_km, z=z, customdata=cd,
        colorscale=ELEVATION_SCALE,
        colorbar=dict(title=dict(text="Elevation (m)")),
        hovertemplate=("%{x:.2f} km E, %{y:.2f} km N of centre<br>"
                       "<b>%{z:.0f} m</b> (original sample)<br>"
                       "raster row %{customdata[0]}, col %{customdata[1]}"
                       "<extra></extra>"),
    ))
    fig.update_layout(
        title=dict(text=f"{title or 'SRTM elevation'} - 3D terrain "
                        f"(vertical exaggeration ×{vertical_exaggeration:g})<br>"
                        f"<sup>{SOURCE_LABEL}; {_sampling_note(grid)}; "
                        f"x/y = km from ({lat0:.4f}°, {lon0:.4f}°), WGS84 local scaling</sup>"),
        scene=dict(
            xaxis=dict(title="East (km)"),
            yaxis=dict(title="North (km)"),
            zaxis=dict(title="Elevation (m)"),
            aspectmode="manual", aspectratio=aspect,
            camera=dict(eye=dict(x=-0.6, y=-1.6, z=1.0)),  # looking from the south
        ),
        template="plotly_white", width=1000, height=850,
        meta={"vertical_exaggeration": vertical_exaggeration,
              "lat0": lat0, "lon0": lon0},
    )
    return fig


def check_figures(grid: SampledGrid, fig2d: go.Figure, fig3d: go.Figure) -> None:
    """Assert both figures carry exactly the grid's values and indices."""
    expected = grid.values[::-1]
    for fig in (fig2d, fig3d):
        z = np.asarray(fig.data[0].z, dtype=float)
        if not np.array_equal(z, expected, equal_nan=True):
            raise AssertionError("figure z differs from sampled grid")
        cd = np.asarray(fig.data[0].customdata)
        if not (np.array_equal(cd[..., 0][:, 0], grid.rows[::-1])
                and np.array_equal(cd[..., 1][0], grid.cols)):
            raise AssertionError("figure row/col indices differ from sampled grid")


def save_html(fig: go.Figure, path: Path) -> Path:
    """Write a self-contained HTML file (plotly.js embedded; works offline)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(path, include_plotlyjs=True, full_html=True)
    return path
