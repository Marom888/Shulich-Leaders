# LunarMatch — Master Project Context and Development Instructions

## NASA Space Apps Challenge 2026

You are joining an existing software development project called **LunarMatch**.

Your role is to act as a senior software architect, Python engineer, and geospatial data engineer.

You must understand the complete product vision while respecting the current development phase.

**Do not attempt to implement the entire product immediately.**

We are developing this project as a three-person team under a hackathon deadline. Our immediate objective is to establish a reliable, reusable technical foundation.

---

# 1. Project Overview

We are participating in the NASA Space Apps Challenge 2026.

Challenge:

**Permanent Moon Base Locations and Mars**

Challenge page:

https://www.spaceappschallenge.org/2026/challenges/permanent-moon-base-locations-and-mars/

Although the challenge addresses both the Moon and Mars, our project currently focuses exclusively on **lunar landing missions**.

Do not implement Mars functionality, rover mobility analysis, or general planetary exploration.

## Product Vision

LunarMatch is an AI-assisted engineering decision-support platform that identifies terrestrial locations suitable for testing technologies and systems used in lunar landing missions.

The platform will combine:

- Historical lunar landing failures and successes.
- A curated catalog of approximately 20 engineering experiments.
- Lunar terrain and environmental datasets.
- Earth geospatial datasets.
- Experiment-specific matching algorithms.
- Explainable engineering prioritization.
- Global terrestrial site discovery.
- Logistics and cost estimation.
- Interactive geographic visualization.

Our main goal is to discover potentially overlooked terrestrial analog sites rather than relying exclusively on established NASA analog locations.

The system must provide a separate winning terrestrial site for every selected engineering experiment.

**Engineering suitability determines the winner. Cost is displayed separately and does not affect the engineering matching score.**

---

# 2. Current Development Status

We have already established a working connection to NASA Earthdata using Python.

We successfully:

1. Authenticated with NASA Earthdata.
2. Searched for elevation datasets.
3. Downloaded real SRTM elevation data.
4. Saved the downloaded file locally.

We are now working on reliably reading and visualizing that data.

**Current development priority: NASA data acquisition, raster processing, and visualization.**

Do not implement the final recommendation or scoring engine during this phase.

However, design the software architecture so these components can be added later without major restructuring.

---

# 3. Development Environment

Our current environment is:

| Component | Technology |
|---|---|
| Operating system | Windows |
| IDE | Visual Studio Code |
| Language | Python |
| NASA data access | earthaccess |
| Raster processing | rasterio |
| Numerical processing | numpy |
| Visualization | plotly |
| Version control | Git / GitHub |

Use these technologies for the initial implementation.

Do not introduce unnecessary frameworks, cloud infrastructure, databases, or frontend technologies unless they provide a clear immediate benefit.

Prefer a simple, modular Python project.

## Required Python packages

```powershell
python -m pip install earthaccess rasterio numpy plotly
```

Use a virtual environment where appropriate.

Create a `requirements.txt` containing the dependencies actually used by the project.

---

# 4. Existing NASA Earthdata Authentication

A NASA Earthdata Login account has already been created.

Authentication is performed using:

```python
import earthaccess

earthaccess.login(persist=True)
```

The first login may require interactive authentication.

Credentials may be stored locally in `.netrc` or `_netrc`.

## Security requirements

- Never hardcode credentials.
- Never print passwords or authentication tokens.
- Never commit credential files.
- Do not store authentication information inside project configuration files.
- Add appropriate exclusions to `.gitignore`.
- Reuse existing authentication when available.

Authentication should be isolated in a reusable data-access module.

---

# 5. Existing Successful NASA Download

We successfully downloaded data from the Shuttle Radar Topography Mission.

Dataset:

| Property | Value |
|---|---|
| Short name | SRTMGL1 |
| Version | 003 |
| Data type | Digital Elevation Model |
| Approximate sampling | 1 arc-second |
| Approximate latitude spacing | 30 meters |
| Download format | `.hgt.zip` |

## Test region

Atacama Desert, Chile.

Bounding box:

```python
bbox = (-69.6, -23.7, -69.2, -23.3)
```

Coordinate order:

```text
(west, south, east, north)
```

## Existing downloaded file

```text
nasa_data/S24W070.SRTMGL1.hgt.zip
```

The previous download returned:

```text
Found 1 files

Downloaded:
nasa_data\S24W070.SRTMGL1.hgt.zip
```

This confirms that NASA Earthdata authentication, search, and download worked in our existing environment.

Do not assume the file is located in the current repository until you inspect the actual filesystem.

If it exists, reuse it.

Avoid unnecessary downloads.

---

# 6. Existing Download Script

We previously implemented a script called:

`download_nasa.py`

The script uses `earthaccess` to search and download SRTM data.

Its essential implementation is:

```python
import earthaccess
from pathlib import Path

project_folder = Path(__file__).resolve().parent

download_folder = project_folder / "nasa_data"
download_folder.mkdir(parents=True, exist_ok=True)

print("Project folder:", project_folder)
print("Download folder:", download_folder)

earthaccess.login(persist=True)

bbox = (-69.6, -23.7, -69.2, -23.3)

print("\nSearching NASA Earthdata...")

results = earthaccess.search_data(
    short_name="SRTMGL1",
    version="003",
    bounding_box=bbox,
    count=2
)

print(f"Found {len(results)} files")

if results:
    print("\nDownloading files...")

    files = earthaccess.download(
        results,
        local_path=str(download_folder)
    )

    print("\nDownloaded files:")

    for file in files:
        print(file)

    print("\nDownload completed successfully!")
    print("Files saved in:", download_folder)

else:
    print("No matching data found.")
```

## Important file-path requirement

Always use paths derived from the script or a clearly defined project root.

Do not rely on the terminal's current working directory.

For example:

```python
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

DATA_DIR = PROJECT_ROOT / "nasa_data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
```

If the project is reorganized into packages, adapt the root resolution accordingly.

Preserve compatibility with Windows paths.

---

# 7. Current Technical Objective

The immediate goal is to reliably process and visualize the downloaded NASA elevation data.

We need two visualizations:

1. A 2D elevation heatmap.
2. An interactive 3D terrain surface.

Both visualizations must originate from the same elevation raster.

The visualizations should help us verify that the dataset has been loaded and interpreted correctly.

## Required workflow

1. Locate the downloaded `.hgt.zip` file.
2. Extract the `.hgt` file using Python's `zipfile` library.
3. Open the extracted file with `rasterio`.
4. Read the elevation values into a NumPy array.
5. Handle missing and invalid values correctly.
6. Inspect the coordinate reference system.
7. Inspect the raster bounds.
8. Calculate valid minimum and maximum elevations.
9. Extract geographic coordinates using the raster transform.
10. Downsample the raster for visualization if necessary.
11. Generate a 2D elevation heatmap using Plotly.
12. Generate an interactive 3D terrain visualization using Plotly.
13. Save the visualizations as HTML.
14. Verify that displayed elevation values match the source raster.

## Important HGT characteristics

A typical SRTMGL1 tile:

- Covers approximately 1° × 1°.
- Contains 3601 × 3601 elevation samples.
- Stores signed 16-bit elevation values.
- Uses geographic coordinates.
- May contain missing elevation values.

Do not assume all raster files have the same dimensions.

Read metadata dynamically.

---

# 8. Scientific Requirements for Visualization

The visualization must preserve the meaning of the original measurements.

### Elevation integrity

Do not modify elevation values merely to improve visual appearance.

If smoothing, interpolation, or resampling is introduced, explicitly label the resulting data as processed.

### Missing values

Handle missing elevations using masks or equivalent methods.

Do not silently replace missing elevations with zero.

### Geographic orientation

Ensure that:

- North and south are not reversed.
- East and west are not reversed.
- Raster row and column coordinates are interpreted correctly.
- Geographic bounds match the source metadata.

### Downsampling

A 3601 × 3601 raster may be unnecessarily large for interactive 3D visualization.

Downsampling is acceptable.

However:

- Preserve the original raster.
- Clearly report the downsampling factor.
- Distinguish sampled values from original values.
- Verify that selected sampled values correspond to the original raster.

### 3D geometry

Longitude and latitude are angular coordinates.

Elevation is measured in meters.

For physically meaningful terrain proportions, horizontal coordinates must be converted to metric distances or projected into an appropriate local coordinate reference system.

Do not treat degrees of longitude as meters.

If vertical exaggeration is used, display the exaggeration factor.

### Verification

Check selected raster cells against their plotted values.

This verifies processing consistency.

It does not independently validate the geographic accuracy of NASA measurements.

---

# 9. Suggested Initial Project Structure

Inspect the existing repository before changing its structure.

If no suitable structure exists, consider:

```text
LunarMatch/
│
├── README.md
├── requirements.txt
├── .gitignore
│
├── download_nasa.py
├── visualize_terrain.py
│
├── nasa_data/
│   └── downloaded NASA files
│
├── outputs/
│   ├── terrain_2d.html
│   └── terrain_3d.html
│
├── lunarmatch/
│   ├── __init__.py
│   │
│   ├── data/
│   │   ├── __init__.py
│   │   ├── earthdata_client.py
│   │   └── raster_loader.py
│   │
│   ├── visualization/
│   │   ├── __init__.py
│   │   └── terrain_plots.py
│   │
│   └── experiments/
│       ├── __init__.py
│       └── README.md
│
└── tests/
    ├── test_raster_loader.py
    └── test_visualization.py
```

This structure is a suggestion, not a mandatory redesign.

Do not delete or overwrite existing working code without inspecting it.

Avoid changing unrelated projects.

---

# 10. Future System Architecture

The following components describe the intended final product.

They are included so the current foundation remains extensible.

**Do not implement all of these components yet.**

## 10.1 Mission Definition

Users will eventually provide:

- Lunar landing coordinates or region.
- Planned landing date and time.
- Lander mass and dimensions.
- Landing-leg configuration.
- Center-of-mass height.
- Touchdown velocity.
- Relevant sensor parameters.
- Development team location on Earth.

The required inputs will depend on the selected experiments.

---

## 10.2 Historical Failure Intelligence

We have a separate Excel workbook containing historical lunar landing failures and successes.

The workbook includes worksheets for:

- Failures.
- Successes.
- Dataset characteristics.
- Classification summary.

The system will eventually use this dataset to:

- Identify documented failure mechanisms.
- Connect failures to relevant engineering experiments.
- Support experiment recommendations.
- Explain why certain tests are important.

Historical incident descriptions must distinguish observed outcomes from suspected causes.

Do not infer failure probabilities directly from the number of recorded failures.

Do not fabricate missing engineering measurements.

This workbook is a future integration input.

Do not assume it exists in the repository until verified.

---

# 11. Curated Catalog of Approximately 20 Experiments

This is a confirmed product requirement.

The system will maintain a catalog of approximately 20 engineering experiments related to lunar landing operations and historical incidents.

**Only our engineering team can approve experiments.**

The AI may recommend experiments from the approved catalog.

The AI must not independently add new approved experiments.

## Experiment states

Suggested states:

```text
draft
approved
deprecated
```

Only experiments marked `approved` may be recommended as approved experiments.

Experiment approval must be an explicit team-controlled action.

## Suggested experiment schema

```json
{
  "experiment_id": "EXP-001",
  "name": "Terrain-Aware Altitude Estimation",
  "status": "draft",
  "version": "0.1",
  "objective": "Evaluate altitude estimation robustness over rapidly changing terrain.",
  "related_failure_modes": [
    "altitude_estimation_error"
  ],
  "required_features": [
    "elevation_gradient",
    "terrain_discontinuity"
  ],
  "optional_features": [
    "local_roughness"
  ],
  "default_weights": {
    "elevation_gradient": 0.6,
    "terrain_discontinuity": 0.4
  },
  "matching_algorithm": "terrain_altitude_matcher",
  "limitations": [
    "Terrain similarity does not establish sensor performance."
  ]
}
```

This is an illustrative schema.

The engineering team must approve the final definitions and weights.

---

# 12. Draft Experiment Categories

The future catalog may contain approximately 20 experiments.

Potential categories include:

### Touchdown mechanics

- Stability on sloped terrain.
- Stability on uneven terrain.
- Landing footprint height variation.
- Boulder interference.
- Landing-leg clearance.
- Lateral sliding.
- Landing gear–soil interaction.

### Navigation and altitude estimation

- Terrain-aware altitude estimation.
- Crater-rim altitude transitions.
- Terrain-relative navigation.
- Visual feature matching.
- Navigation in low-texture environments.

### Hazard detection

- Boulder detection.
- Crater detection.
- Safe landing zone classification.
- Hazard detection under variable illumination.

### Illumination and optical performance

- Low Sun-angle navigation.
- Long-shadow hazard detection.
- High-contrast optical navigation.
- Sensor performance across terrain elevation changes.

These are candidate definitions only.

They are not yet approved experiments.

---

# 13. Future Lunar and Earth Dataset Integration

The current phase uses terrestrial SRTM data.

Later phases will integrate additional lunar and Earth datasets.

## Lunar datasets

### LOLA / LROC DTM

- Elevation.
- Slope.
- Geometric roughness.
- Terrain morphology.

### LROC NAC

- Optical texture.
- Crater detection.
- Boulder detection where resolution permits.
- Visual navigation characteristics.

### Solar geometry

- Solar incidence.
- Illumination.
- Shadow geometry.

## Earth datasets

### NASADEM / SRTM

- Elevation.
- Slope.
- Topography.

### USGS 3DEP

- High-resolution elevation where available.

### High-resolution aerial imagery

- Terrain texture.
- Obstacle identification.
- Optical navigation features.

## Advanced optional datasets

### Radar

Lunar:
Mini-RF.

Earth:
NISAR or Sentinel-1.

### Spectral

Lunar:
Moon Mineralogy Mapper.

Earth:
EMIT, Sentinel-2, Landsat.

### Thermal

Lunar:
Diviner.

Earth:
Landsat TIRS.

These sources must not be treated as physically interchangeable without appropriate calibration and validation.

---

# 14. Future Site Discovery Engine

The eventual system will search terrestrial geospatial datasets for locations suitable for individual engineering experiments.

The search should be algorithmic.

It should not rely exclusively on a predefined list of famous analog sites.

## Intended workflow

```text
Lunar Mission
      |
      v
Historical Failure Analysis
      |
      v
Approved Experiment Recommendations
      |
      v
User Experiment Selection
      |
      v
Engineering Parameter Prioritization
      |
      v
Lunar Feature Extraction
      |
      v
Terrestrial Candidate Discovery
      |
      v
Experiment-Specific Matching
      |
      v
Independent Winner Per Experiment
      |
      v
Results and Cost Visualization
      |
      v
User Re-Prioritization
```

The platform should eventually support worldwide terrestrial discovery.

For the MVP, geographic coverage may be limited.

Actual coverage must always be disclosed.

---

# 15. Future Engineering Matching Engine

Every experiment will have its own matching requirements.

A shared framework should support:

- Feature extraction.
- Feature normalization.
- Experiment-specific weights.
- Hard feasibility constraints.
- Missing-data handling.
- Engineering score calculation.
- Ranking.
- Explainability.

The numerical algorithms must be deterministic and reproducible.

AI should support experiment selection and interpretation.

AI should not replace validated numerical calculations.

## Engineering priorities

Before searching, the AI will propose initial parameter weights.

Users may modify those weights.

After receiving results, users may modify them again.

Rankings should update accordingly.

## Independent experiment winners

Each experiment receives its own winning site.

Do not optimize for a single site serving every experiment.

The system should also identify the best candidate for each individual feature.

---

# 16. Future Cost Engine

The system will estimate logistical costs based on:

- Development team location.
- Travel distance.
- Transportation requirements.
- Equipment logistics.
- Accommodation.
- Testing duration.
- Site accessibility.

Costs must be presented separately from engineering matching scores.

A site with the highest engineering score remains the engineering winner even if it is expensive.

The interface should explain significant cost differences.

Cost estimates must be clearly distinguished from verified quotations.

---

# 17. Future User Interface

The final application should provide:

### Mission configuration

Input parameters for the lunar landing mission.

### Experiment selection

Recommendations from the approved experiment catalog.

### Parameter prioritization

Editable engineering weights.

### Interactive Earth map

Candidate terrestrial testing sites.

### Experiment tournament

Separate rankings and winners for every experiment.

### Scientific evidence

Data sources, measurements, limitations, and confidence.

### Cost comparison

Estimated logistical costs displayed separately.

### Sensitivity analysis

Updated rankings when users change feature weights.

---

# 18. Current Implementation Plan

Follow the phases below.

## Phase 1 — Inspect and preserve existing work

Before editing files:

1. Inspect the repository.
2. Identify existing Python scripts.
3. Locate downloaded NASA data.
4. Review the existing `.gitignore`.
5. Identify dependencies.
6. Confirm the current working directory and project root.
7. Avoid modifying unrelated repositories or projects.

Produce a brief summary of what already exists.

## Phase 2 — Stabilize NASA data access

Implement or improve:

- NASA Earthdata authentication.
- Dataset search.
- Download handling.
- Reliable local file paths.
- Clear error handling.
- Reuse of existing downloaded files.

Keep the existing Atacama test case operational.

## Phase 3 — Implement raster loading

Create reusable functions to:

- Locate ZIP archives.
- Extract HGT files.
- Load rasters.
- Read metadata.
- Handle NoData values.
- Return elevation arrays.
- Return geographic coordinates.

## Phase 4 — Implement visualization

Generate:

- Interactive 2D elevation heatmap.
- Interactive 3D terrain surface.

Save both as HTML.

Use the same underlying sampled elevation data.

Ensure correct geographic orientation.

## Phase 5 — Add verification tests

Test:

- File-path handling.
- Raster dimensions.
- Coordinate extraction.
- NoData handling.
- Elevation integrity.
- Downsampling consistency.
- Plot input consistency.

Prefer tests that can run without NASA authentication or internet access.

## Phase 6 — Prepare future extension points

Document interfaces for:

- Lunar dataset access.
- Experiment catalog.
- Historical incident import.
- Feature extraction.
- Matching algorithms.
- Cost estimation.

Do not implement the full engines yet.

---

# 19. Acceptance Criteria for the Current Phase

The current development phase is successful when:

1. The project runs on Windows using Python.
2. NASA Earthdata authentication works.
3. The Atacama SRTM dataset can be located or downloaded.
4. The HGT archive can be opened reliably.
5. Elevation values are loaded correctly.
6. Raster metadata is displayed.
7. A 2D elevation heatmap is generated.
8. An interactive 3D terrain visualization is generated.
9. Both visualizations use consistent elevation values.
10. Missing data is handled correctly.
11. Outputs are saved to HTML files.
12. Automated tests verify essential processing behavior.
13. The README explains how to run the project.
14. The architecture supports future expansion without major restructuring.

Do not claim completion unless the relevant functionality has been tested.

---

# 20. Instructions for Autonomous Development

You may implement the current phase without requesting approval for routine technical decisions.

Use the existing repository and preserve working functionality.

Prefer small, testable modules.

After each major change:

- Run relevant tests.
- Verify the expected outputs.
- Fix errors before proceeding.
- Record any unresolved issues.

Do not introduce fabricated scientific data.

Do not commit credentials.

Do not silently change the scientific scope of the project.

Do not implement the scoring, site recommendation, or cost algorithms during the current phase.

If the NASA service is unavailable, use the existing downloaded dataset for local testing.

If no real dataset is available, report the blocker rather than fabricating a successful NASA download.

---

# 21. Required Final Development Report

At the end of the implementation session, provide:

1. Summary of completed work.
2. Files created or modified.
3. Dependencies installed.
4. Commands required to run the project.
5. Test results.
6. Location of generated HTML visualizations.
7. Known limitations.
8. Recommended next development steps.

Clearly distinguish implemented functionality from planned functionality.

---

# Final Objective

LunarMatch will ultimately connect historical lunar landing experience, approved engineering experiments, lunar geospatial measurements, and terrestrial geospatial discovery.

The immediate goal is narrower:

**Establish a reliable NASA Earthdata acquisition, raster-processing, and visualization foundation that can support the future LunarMatch engineering recommendation platform.**

Start by inspecting the existing project and preserving the working NASA download workflow.

Then implement and verify the current development phase.