"""Plots that use only the numbers in a :class:`Layer` (no synthetic data).

Every figure title states dataset, layer, evidence type and resolution, and
the axes are in the layer's native projected coordinates (km) so the plotted
extent can be checked against the AOI.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from .core.raster import Layer


def _extent_km(lyr: Layer):
    xmin, ymin, xmax, ymax = lyr.bounds
    return [xmin / 1000, xmax / 1000, ymin / 1000, ymax / 1000]


def plot_map(lyr: Layer, ax=None, cmap: str = "terrain", title: Optional[str] = None, unit_label: Optional[str] = None):
    import matplotlib.pyplot as plt

    ax = ax or plt.subplots(figsize=(6, 5))[1]
    im = ax.imshow(lyr.data, extent=_extent_km(lyr), origin="upper", cmap=cmap, interpolation="nearest")
    cb = plt.colorbar(im, ax=ax, shrink=0.85)
    cb.set_label(unit_label or f"{lyr.name} [{lyr.units}]")
    dx, dy = lyr.resolution
    ax.set_title(title or f"{lyr.dataset_id} · {lyr.name} ({lyr.evidence.value}) · {dx:g}×{dy:g} m px", fontsize=9)
    ax.ticklabel_format(useOffset=False)
    ax.set_xlabel("x [km] (projected)")
    ax.set_ylabel("y [km] (projected)")
    ax.set_aspect("equal")
    return ax


def plot_3d(lyr: Layer, ax=None, stride: int = 1, vertical_exaggeration: float = 1.0):
    import matplotlib.pyplot as plt

    if ax is None:
        fig = plt.figure(figsize=(7, 5))
        ax = fig.add_subplot(111, projection="3d")
    xs, ys = lyr.pixel_centers()
    X, Y = np.meshgrid(xs / 1000, ys / 1000)
    Z = lyr.data
    ax.plot_surface(X[::stride, ::stride], Y[::stride, ::stride], Z[::stride, ::stride],
                    cmap="terrain", linewidth=0, antialiased=True, rcount=200, ccount=200)
    ax.set_xlabel("x [km]")
    ax.set_ylabel("y [km]")
    ax.set_zlabel(f"{lyr.name} [{lyr.units}]")
    span_xy = max(np.ptp(xs), np.ptp(ys))
    span_z = np.nanmax(Z) - np.nanmin(Z)
    if span_xy > 0 and span_z > 0:
        ax.set_box_aspect((np.ptp(xs) / span_xy, np.ptp(ys) / span_xy,
                           min(1.0, vertical_exaggeration * span_z / span_xy)))
    ax.set_title(f"{lyr.dataset_id} {lyr.name} – 3-D (vertical exaggeration {vertical_exaggeration:g}×)", fontsize=9)
    return ax
