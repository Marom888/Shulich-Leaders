# Extension points (mostly planned; see status per section)

These are interface sketches meant to keep the current foundation extensible.
Sections not marked IMPLEMENTED are not implemented. No experiment is approved. Only the
engineering team can approve experiments, by setting `status: approved`
explicitly. See CLAUDE.md §10–17.

## Experiment catalog — IMPLEMENTED: `schema.py` and `catalog.json`
- `catalog.json` is **empty** on purpose. The engineering team adds
  experiments and approves them through a reviewed git change that sets
  `"status": "approved"`.
- `load_catalog(path) -> list[Experiment]` validates the catalog against the
  CLAUDE.md §11 schema. The rules are documented in `schema.validate`.
- `approved_experiments(exps)` returns only the experiments marked
  `approved`.
- `Experiment` is frozen, and no code changes `status`.

## Historical incident import — `lunarmatch/history/`
- `load_incidents(xlsx_path)` reads the Failures and Successes sheets.
- Each record keeps `observed_outcome` and `suspected_cause` as separate fields.
- No failure probabilities are derived from incident counts.

## Lunar dataset access — `lunarmatch/data/lunar_client.py`
- It should mirror `earthdata_client` and return the same raster container as
  `raster_loader.ElevationRaster` (data, mask, CRS, transform, extents). That
  way feature extraction stays dataset-agnostic.
- Lunar CRSs (for example IAU_2015:30100) must be carried through and never
  mixed with EPSG:4326.

## Feature extraction — PARTLY IMPLEMENTED: `lunarmatch/features/terrain.py` (slope, roughness)
- Signature: `feature(raster: ElevationRaster, **params) -> DerivedLayer`, for
  features such as slope, roughness and gradient.
- Every layer records its units, the resolution it was computed at, and its
  provenance.
- Slope must be computed in metric units (see
  `lunarmatch.geodesy`).

## Matching algorithms — `lunarmatch/matching/`
- Signature: `match(experiment, lunar_features, candidate_features, weights) -> ranking`.
- Must be deterministic, use explicit hard constraints, report missing data,
  and produce a per-feature explanation.
- One independent winner per experiment.

## Cost estimation — `lunarmatch/cost/`
- Computed and displayed separately. It never feeds into the engineering
  score.
- Outputs are labelled as estimates, not quotations.
