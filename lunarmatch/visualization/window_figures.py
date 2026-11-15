"""Plotly figures for one candidate window, reusing terrain_plots.

Elevation heatmap, slope heatmap, roughness heatmap and 3D surface are built
from the real patch samples of the window (stride-decimated for display,
values unmodified). Slope and roughness are computed on the full patch so
window edges are not artificially NaN.
"""
from __future__ import annotations

import numpy as np

from lunarmatch.data.raster_loader import SampledGrid, stride_indices
from lunarmatch.discovery import descriptors as dsc
from lunarmatch.features.terrain import DerivedLayer
from lunarmatch.visualization import terrain_plots as tp


def window_grid(values, patch, rows, cols, max_side=160) -> SampledGrid:
    if patch.grid.kind != "geographic":
        raise ValueError("window figures need a geographic grid")
    r0, r1 = rows
    c0, c1 = cols
    step = max(1, int(np.ceil(max(r1 - r0, c1 - c0) / max_side)))
    rr = r0 + stride_indices(r1 - r0, step)
    cc = c0 + stride_indices(c1 - c0, step)
    return SampledGrid(values=np.asarray(values, float)[np.ix_(rr, cc)], rows=rr, cols=cc,
                       lats=patch.grid.lats[rr], lons=patch.grid.lons[cc], step=step,
                       source_shape=patch.shape)


def figures(patch, rows, cols, title="", layers=None, max_side=160, vex=3.0) -> dict:
    slope, rough = layers if layers is not None else dsc.layers(patch)
    prov = patch.provenance
    label = prov.label + (" — MOCK, not real terrain" if prov.is_mock else "")
    g = window_grid(patch.elevation_m, patch, rows, cols, max_side)
    derived = f"{prov.dataset_id} ({prov.source or patch.id})"
    sl = DerivedLayer(slope, "slope", "deg", "Horn 3x3, body-aware metric spacing",
                      {"window_samples": 3}, derived)
    ro = DerivedLayer(rough, "roughness", "m", "std of elevation in 3x3 window (not detrended)",
                      {"window_samples": 3}, derived)
    figs = {
        "elevation": tp.heatmap_figure(g, title, source_label=label),
        "slope": tp.layer_heatmap_figure(window_grid(slope, patch, rows, cols, max_side), sl, title),
        "roughness": tp.layer_heatmap_figure(window_grid(rough, patch, rows, cols, max_side), ro, title),
        "terrain_3d": tp.surface_figure(g, vex, title, source_label=label),
    }
    for f in figs.values():
        f.update_layout(width=None, height=520, autosize=True)
    return {"figures": {k: f.to_plotly_json() for k, f in figs.items()},
            "grid": {"step": g.step, "shape": list(g.shape), "rows": [int(rows[0]), int(rows[1])],
                     "cols": [int(cols[0]), int(cols[1])]},
            "provenance": prov.to_dict()}
