"""Unified Earth/Moon terrain data interface.

Connectors (see connectors.py and README.md) return TerrainPatch objects:
elevation in metres on a geographic or projected grid of a specific body,
with metric sample spacing and provenance. Everything downstream (windows,
descriptors, comparison) works on TerrainPatch and never on dataset-specific
formats, so new connectors plug in without touching the engine.
"""
