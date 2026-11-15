# Algorithm specification: v1.0 vs Talia's SWIR workbook

Both workbooks were read cell by cell, values and formulas, on 2026-11-15.
Neither file was modified.

| File | SHA-256 | Sheets | Cells |
|---|---|---|---|
| `algorithm/LunarMatch_Algorithm_Spec_v1.0.xlsx` | `fa8a508d0701927f5c1e012fd534fa29e0ae007b0eae9c1ab6c99f54386108cd` | 16 | 2716 |
| `algorithm/LunarMatch_Algorithm_With_SWIR_Sources.xlsx` | `4027381b68c873c0e74df504099c5ccbec754dba69771dd7da6d2ad346404184` | 16 | 2786 |

Both carry the revision label "REVISION 2026-11-15". The SWIR workbook adds a
dated note: "SWIR addition (2026-11-15)".

## Result: the update is purely additive
Across all 16 sheets: **0 cells changed, 0 cells removed, 70 cells added**.

| Sheet | Change |
|---|---|
| Experiments, Experiment_Features, Physical_Models, Capabilities, Experiment_Capabilities, Pipeline, Ranking_Rules, Score_Demo, Overall_Ranking, Per_Test_Winners, Lunar_Mechanical_References | **identical** |
| Datasets | + `D_M3` (Chandrayaan-1 M³, PDS reflectance, ~70–140 m) and + `D_WORLDCOVER_SWIR` (ESA WorldCover Sentinel-2 B11/B12 annual composites, 20 m, AWS COG, uint8 scale 0.004, NoData 255). Both are `OPTIONAL_RESEARCH_NOT_INTEGRATED`. |
| Features | + `F_SWIR_BANDPASS` (status `OPTIONAL_NOT_SCORED`, priority P2, QA requirement `NO_RANKING_WEIGHT`) |
| Moon_Earth_Pairs, Pair_URLs | + one `RESEARCH_ONLY` pair for `F_SWIR_BANDPASS`, with evidence level `CONDITIONAL_SPECTRAL_PROXY_NOT_VALIDATED` |
| Start_Here | + the SWIR addition note, and a SWIR scoring policy: "OPTIONAL / RESEARCH_ONLY; 0 scoring contribution and no Experiment_Features rows added" |

**What did not change:** no experiment was added or removed, and no experiment
weight or threshold changed. Every contradiction recorded in the earlier
v1.0 audit is still present (see "Unresolved" below).

## SWIR as specified (research only)
- **Method:** resample M³ L2 reflectance to the Sentinel-2 B11/B12 spectral
  response, apply quality and illumination masks, then compare spectral
  ratios and distributions with uncertainty.
- **Scale:** the common effective footprint must be at least the coarser M³
  pixel.
- **Units:** dimensionless reflectance (0–1), or unitless band ratios.
- **Limitations stated by the workbook:**
  - The Earth data has only two SWIR bands.
  - The 2020/2021 composites are not contemporaneous with M³.
  - Minerals, BRDF, illumination and atmosphere all differ between the two
    bodies.
  - Shadowed M³ pixels are unusable; south-pole grazing illumination reduces
    the usable data.
  - Coverage of the exact lunar polygon is not verified.
  - SWIR is **no proxy for mechanical strength**.
- **Note on M³ coverage:** the workbook's coverage text for M³ refers to the
  "Connecting Ridge" region, not to Mons Mouton Plateau or Nobile Rim 2.

## Dataset availability and integration

| Dataset | Listed | Identified online | Downloaded | Integrated | Validated |
|---|---|---|---|---|---|
| D_M3 | yes | URL in workbook; not checked by Rookie | no | no (no provider in either branch) | no |
| D_WORLDCOVER_SWIR | yes | URL in workbook; not checked by Rookie | no | no | no |
| D_SENT2 (B11/B12 single scenes) | yes (v1.0) | Ido: Earth Search STAC (his note says verified 2026-11-15) | no | Ido's branch only | no |

## Unresolved conflicts (unchanged since the v1.0 audit)
1. The spec makes scoring and ranking P0, but CLAUDE.md §2/§20 forbid them in
   this phase. The user decision of 2026-11-15 allows per-feature distances
   only.
2. CAP_23 (overall multi-experiment ranking) conflicts with CLAUDE.md §15
   (independent winners per experiment). Rookie shows **Pending Engineering
   Validation**.
3. The workbook's "Default_Enabled" flags and "Approved update" notes are not
   catalog approval. The catalog is empty.
4. Spec IDs (`EXP_02`) don't match the catalog schema (`EXP-NNN`).
5. No similarity function, no rule for optional-feature weights, and no
   handling of "insufficient data" in the pass count; zero passes gives a mean
   of 0. The demo scores are synthetic.
6. Sheet contradictions: `F_SHADOW` preferred vs paired datasets; the
   friction/cohesion Earth sources; bulk-density units; `F_CPT` priority
   P2 vs required; the CAP_26 row's column shift.
7. Most primary Earth datasets (3DEP, NAIP, USGS CPT) cover the US only, which
   limits truly global discovery.
8. The lunar targets in the workbook (south pole, Connecting Ridge for M³)
   differ from the user's targets (Mons Mouton Plateau, Nobile Rim 2). Neither
   has published coordinates.
