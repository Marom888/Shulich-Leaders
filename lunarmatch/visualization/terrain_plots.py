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
from lunarmatch.geodesy import metres_per_degree  # noqa: F401  (re-exported)

# Single-hue sequential ramp (light = low, dark = high).
ELEVATION_SCALE = [
    [0.00, "#cde2fb"], [0.17, "#9ec5f4"], [0.33, "#6da7ec"],
    [0.50, "#3987e5"], [0.67, "#256abf"], [0.83, "#184f95"], [1.00, "#0d366b"],
]

SOURCE_LABEL = "NASA SRTMGL1 v003"


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


# Second single-hue sequential ramp (orange) for derived layers.
SLOPE_SCALE = [
    [0.00, "#fde4d8"], [0.17, "#f9c1a6"], [0.33, "#f39a74"],
    [0.50, "#eb6834"], [0.67, "#c9521f"], [0.83, "#9c3d15"], [1.00, "#6e2a0e"],
]


def _heatmap(grid: SampledGrid, *, colorbar: str, colorscale, hover_value: str,
             title: str, subtitle: str) -> go.Figure:
    """North-up, east-right lon/lat heatmap with row/col hover (shared core)."""
    z, lats, cd = _flip_north_up(grid)
    lat0 = float(grid.lats.mean())
    mlat, mlon = metres_per_degree(lat0)
    fig = go.Figure(go.Heatmap(
        z=z, x=grid.lons, y=lats, customdata=cd,
        colorscale=colorscale,
        colorbar=dict(title=dict(text=colorbar)),
        hoverongaps=False,
        hovertemplate=("lat %{y:.5f}°, lon %{x:.5f}°<br>"
                       f"<b>{hover_value}</b><br>"
                       "raster row %{customdata[0]}, col %{customdata[1]}"
                       "<extra></extra>"),
    ))
    fig.update_layout(
        title=dict(text=f"{title}<br><sup>{subtitle}</sup>"),
        xaxis=dict(title="Longitude (°E)", constrain="domain"),
        yaxis=dict(title="Latitude (°N)", scaleanchor="x",
                   scaleratio=mlat / mlon, constrain="domain"),
        template="plotly_white", width=900, height=850,
    )
    return fig


def heatmap_figure(grid: SampledGrid, title: str = "") -> go.Figure:
    return _heatmap(
        grid, colorbar="Elevation (m)", colorscale=ELEVATION_SCALE,
        hover_value="%{z:.0f} m (original sample)",
        title=f"{title or 'SRTM elevation'} - 2D heatmap",
        subtitle=f"{SOURCE_LABEL}; {_sampling_note(grid)}; NoData shown as gaps",
    )


def layer_heatmap_figure(grid: SampledGrid, layer, title: str = "",
                         colorscale=SLOPE_SCALE, fmt: str = ".1f") -> go.Figure:
    """Heatmap of a derived layer sampled on the elevation grid's rows/cols.

    ``grid`` must come from :func:`raster_loader.sample_layer`. ``layer`` is a
    :class:`lunarmatch.features.terrain.DerivedLayer`, which supplies the
    method, parameters and provenance shown in the title.
    """
    r, c = grid.source_shape
    units = "°" if layer.units == "deg" else f" {layer.units}"
    params = ", ".join(f"{k}={v}" for k, v in layer.params.items()
                       if k not in ("edge_cells", "nodata"))
    return _heatmap(
        grid, colorbar=f"{layer.name.capitalize()} ({layer.units})",
        colorscale=colorscale,
        hover_value=f"%{{z:{fmt}}}{units} {layer.name}",
        title=(f"{title + ' - ' if title else ''}{layer.name.capitalize()} "
               f"derived from {layer.derived_from}"),
        subtitle=(f"{layer.method}; {params}<br>computed at full {r}x{c} resolution, "
                  f"shown every {grid.step} sample(s) (not interpolated); "
                  f"NaN (edges/NoData) shown as gaps; {layer.scale_note}"),
    )


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
