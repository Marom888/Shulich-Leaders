# Rookie ↔ data providers: integration contract (proposal for Ido)

Rookie and the `lunarmatch` engine read terrain only through the
`TerrainConnector` contract in `lunarmatch/terrain/`. Ido's providers live on
`origin/feature/lunarmatch-data-pipeline`, under
`lunar_project/src/lunarmatch/`. They are a **separate package with the same
import name** `lunarmatch`.

Nothing has been merged or renamed. This document proposes how the two
connect.

## 1. Package-name collision
- **Root package:** `lunarmatch/`, containing the engine, Rookie, discovery
  and comparison code.
- **Ido's package:** `lunar_project/src/lunarmatch/`, containing the providers
  and its core (AOI, raster, STAC, HTTP).
- **What goes wrong:** if both are importable, whichever comes first on
  `sys.path` wins, and a pytest run from the repo root would collect both
  test trees.
- **Proposal, needing team approval:**
  1. Keep Ido's code where it is, but rename its import package, for example
     to `lunarmatch_providers`; or install it as a separate distribution with
     that name.
  2. Add a thin adapter module, `lunarmatch/terrain/external.py`. It is
     auto-loaded by `terrain.registry.default_registry()` and wraps his
     providers as `TerrainConnector`s.
  3. Configure pytest with `testpaths = tests lunar_project/tests` once the
     names no longer collide.

## 2. Connector contract (what the engine needs)

| Member | Meaning |
|---|---|
| `dataset_id` | Use the **workbook IDs** (`D_LOLA`, `D_LROC_DTM`, `D_NASADEM`, `D_EARTH_3DEP`, `D_COPDEM` …). Mock connectors keep the `MOCK_` prefix. |
| `body` | `"Earth"` or `"Moon"` |
| `is_mock` | `False` for real data |
| `nominal_spacing_m` | Typical sample spacing in metres |
| `units_for(bbox)` | Cheap list of `CoverageUnit(id, bounds_wsen, area_km2, in_coverage)`. `bbox` may cross the antimeridian (west > east) and may sit near a pole. |
| `fingerprint(unit_id)` | Cheap, stable identity for caching (file SHA-256, product ID + version). `None` means no data. |
| `fetch(unit_id)` | Returns a `TerrainPatch`, or `None` |

## 3. TerrainPatch requirements

| Topic | Requirement |
|---|---|
| CRS and body | Earth: `bodies.EARTH` (WGS84, EPSG:4326). Moon: `bodies.MOON` (IAU_2015:30100, sphere 1737.4 km). Never WGS84 for the Moon. |
| Grid | `GeographicGrid` (lats decreasing, lons increasing) or `ProjectedGrid` (x east increasing, y north decreasing, plus `to_latlon`). Polar LOLA/LROC products should use `ProjectedGrid`. |
| Units | Elevation as float metres. Apply each product's scale and offset; for example, the USGS global LOLA 118 m GeoTIFF stores DN × 0.5. |
| NoData | `NaN`, never 0 or a sentinel value |
| Resolution | Must be correct in `spacing_m()`. The engine refuses comparisons whose spacings differ by more than 25%. It never upsamples, and it coarsens only by integer block mean. |
| Provenance | `Provenance(dataset_id, label, is_mock, source, fingerprint, processing, licence)` |
| Coverage | Report real coverage; a unit with no data returns `None`, never an empty-but-valid patch |
| Errors | Raise exceptions for failures. The engine marks that unit "failed" with the message and continues. |
| Versioning | `fingerprint` must change whenever the data or processing changes, so that cached descriptors are invalidated |

## 4. Mapping Ido's `FetchResult` to `TerrainPatch` (sketch)

```python
class ProviderTerrainConnector:          # in lunarmatch/terrain/external.py
    def __init__(self, provider, layer="elevation", spacing_m=...): ...
    def units_for(self, bbox): ...       # AOI(s) covering bbox -> CoverageUnit
    def fetch(self, unit_id):
        res = self.provider.fetch(aoi_for(unit_id))
        lay = res.layers[self.layer]     # data + transform/CRS + evidence
        # -> GeographicGrid / ProjectedGrid; NaN NoData; Provenance from res.metadata
```

Open questions for Ido:
- Which `FetchResult` layer holds elevation for each DEM provider?
- How are the transform and CRS exposed?
- Is `check_coverage` cheap enough to use in `units_for`?

## 5. Coarse-to-fine global discovery (how new data plug in)

```text
Stage A  coarse screen   global DEM connector (D_COPDEM / D_NASADEM, ~30-90 m), 1° units,
                         10 km windows -> descriptors (cached by fingerprint) -> data-quality
                         + user filters -> eligible windows            [engine: discovery/engine.py]
Stage B  refine          high-res connector (D_EARTH_3DEP ~1 m, LROC DTM on the Moon) fetched
                         only for Stage-A windows -> footprint relief / detrended roughness
Stage C  evidence        geotechnical (D_USGS_CPT, D_WOSIS, D_SOILGRIDS) and field measurements
                         (lunarmatch/field_measurements.py) attached per candidate
Results  candidates.py   experiment-specific cards; unranked until a method is approved
```

- **Coverage is always reported per unit.** Rookie says "searched N of M areas" and never claims a
  global search until every requested unit was processed.
- **Adding global Earth elevation** needs a connector with `units_for` covering the globe and
  `fingerprint` per tile. No engine changes are needed. Also needed:
  - a land mask, so ocean tiles are excluded from coverage;
  - approval for the data volume. Stage A at 1 arc-second is about 375 GB, so use the 3 arc-second
    product or windowed reads.
- **Adding real lunar LOLA/LROC data:** a Moon `ProjectedGrid` connector. The mock is then simply not
  selected, and the MOCK labels disappear because they follow `is_mock`.
- **Adding geotechnical observations:** point records with depth, instrument, protocol and
  uncertainty, in the field-measurement schema. A candidate's "missing" list shrinks only when a
  record is spatially and methodologically matched, which needs an approved matching rule.
- **Adding spectral data (SWIR):** `D_M3` and `D_WORLDCOVER_SWIR` connectors returning reflectance
  layers. These stay research-only, with zero scoring contribution.
- **Adding experiment features:** add the descriptor in `discovery/descriptors.py`, map it in
  `requirements.FEATURE_DESCRIPTORS`, and add its plain-language text in
  `discovery/plain_language.py`. A test fails if a required feature has no text.

## 6. Datasets Rookie will ask for first
1. **Moon:** `D_LOLA` polar products and `D_LROC_DTM` for user-selected
   regions.
2. **Earth:** `D_COPDEM` or `D_NASADEM` for global Stage A screening, and
   `D_EARTH_3DEP` for detailed evaluation in the US.
3. **Research only, never scored:** `D_M3` and `D_WORLDCOVER_SWIR`. Neither
   provider exists yet.
