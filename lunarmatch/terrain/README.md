# Terrain connectors: integration guide

The discovery and comparison engine reads terrain only through **connectors**.
To make a dataset (for example LOLA, LROC NAC DTM, NASADEM or Copernicus DEM)
usable by Rookie, write one connector class. No engine code needs to change.

## The contract

```python
class MyConnector:
    dataset_id = "LOLA_LDEM_85S_20M"   # unique; must NOT start with "MOCK_" for real data
    body = "Moon"                      # "Earth" or "Moon"
    is_mock = False
    nominal_spacing_m = 20.0           # typical sample spacing in metres
    label = "LRO LOLA LDEM 85S 20 m"   # optional, shown in provenance

    def units_for(self, bbox):         # (W, S, E, N) degrees on this body
        """Cheap: which coverage units (tiles/products) intersect the box."""
        return [CoverageUnit(id, bounds_wsen, area_km2, in_coverage=True), ...]

    def fingerprint(self, unit_id):
        """Cheap identity for caching (e.g. sha256 of the file). None = no data."""

    def fetch(self, unit_id):
        """Return a TerrainPatch, or None if the data is not available."""
```

`CoverageUnit`, `TerrainPatch`, `GeographicGrid`, `ProjectedGrid` and
`Provenance` are in `connectors.py` and `patch.py`.

## TerrainPatch rules
- **Elevation:** `elevation_m` is float, in metres. NoData must be `NaN`,
  never 0. Apply any scale or offset the source defines; for example, the
  USGS global LOLA 118 m GeoTIFF stores DN × 0.5.
- **Grid orientation:** row 0 is north and column 0 is west.
  - `GeographicGrid`: `lats` decreasing, `lons` increasing.
  - `ProjectedGrid`: `x` increasing, `y` decreasing.
- **Body:** use the right body model. `bodies.EARTH` is WGS84;
  `bodies.MOON` is the IAU 2015 sphere, 1737.4 km. Never use WGS84 for the
  Moon.
- **Projected products** (such as polar stereographic LOLA): provide
  `x`/`y` in metres and a `to_latlon(x, y)` function, so windows and region
  masks can be placed on the body.
- **Provenance:** fill in the dataset ID, a source file or URL, a
  fingerprint, and any processing applied.

## Registering
Create `lunarmatch/terrain/external.py`:

```python
def register(registry):
    registry.register(MyConnector(...))
```

`terrain.registry.default_registry()` calls it automatically. Check with
`python compare_terrain.py --list-datasets`.

## What the engine does with patches
- Splits them into windows of a physical size.
- Computes Horn slope and 3×3 roughness with the patch's own metric spacing.
- Coarsens a much finer lunar patch to the Earth dataset's spacing with an
  integer block mean (it never upsamples).
- Compares only when sample spacings match within 25%.

Mock connectors (`mock.py`) show the full contract in a few lines each.
