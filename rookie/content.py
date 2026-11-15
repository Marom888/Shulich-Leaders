"""Curated Rookie MVP content: regions, experiment choices, data-status rules.

Every statement here is either (a) verified against a cited source on the
stated date, (b) taken from the team's planning workbook (cited by row ID),
or (c) a statement of what this repository does or does not contain.
No measurements are entered here.
"""
from __future__ import annotations

VERIFIED_ON = "2026-11-15"
ARTEMIS_REGIONS_URL = (
    "https://www.nasa.gov/news-release/nasa-provides-update-on-artemis-iii-moon-landing-regions/")

# --------------------------------------------------------------------------
# Data-status vocabulary (shown as labelled badges, never colour alone)
# --------------------------------------------------------------------------
STATUS = {
    "measured": "Measured: real data loaded in this project",
    "derived": "Derived: computed in this project from real data",
    "model_estimate": "Model estimate",
    "documented": "Documented in a source: not yet extracted or verified",
    "not_integrated": "Source exists: not yet integrated",
    "missing": "Missing: no measurement available",
    "control": "Control condition: not a similarity parameter",
    "demo": "Demonstration only",
}

DOMAINS = {"TOP": "Topographic", "GEO": "Geological", "SOIL": "Geotechnical"}

# --------------------------------------------------------------------------
# Lunar regions
# --------------------------------------------------------------------------
LUNAR_TARGETS = [
    {
        "key": "mons_mouton_plateau",
        "name": "Mons Mouton Plateau",
        "role": "Primary target",
        "designation": "Candidate landing region (Artemis III)",
        "status_note": ("Listed by NASA on 28 Oct 2024 as one of nine Artemis III candidate "
                        "landing regions, \"in no priority order\". NASA will select sites "
                        "within regions after launch dates are set. Not a confirmed landing site."),
        "naming_note": ("NASA lists \"Mons Mouton\" and \"Mons Mouton Plateau\" as separate "
                        "regions; this is Mons Mouton Plateau."),
        "coordinates": None,
        "coordinates_note": "Not recorded: boundaries must come from an authoritative source.",
        "source": ARTEMIS_REGIONS_URL,
        "verified_on": VERIFIED_ON,
        "workbook_ref": "MOON-04 (recorded as \"Mons Mouton / South Pole\")",
    },
    {
        "key": "nobile_rim_2",
        "name": "Nobile Rim 2",
        "role": "Secondary target",
        "designation": "Candidate landing region (Artemis III)",
        "status_note": ("Listed by NASA on 28 Oct 2024 as one of nine Artemis III candidate "
                        "landing regions, \"in no priority order\". Not a confirmed landing site."),
        "naming_note": "",
        "coordinates": None,
        "coordinates_note": "Not recorded: boundaries must come from an authoritative source.",
        "source": ARTEMIS_REGIONS_URL,
        "verified_on": VERIFIED_ON,
        "workbook_ref": "Not in the workbook yet",
    },
]

APOLLO_16 = {
    "key": "apollo_16",
    "name": "Apollo 16 (Descartes Highlands)",
    "role": "Historical validation reference",
    "designation": "Historical crewed landing site (1972)",
    "status_note": ("Used to check experiments against documented in-situ soil measurements. "
                    "Measurements are point data at stations, not maps, and have not yet been "
                    "extracted into this project."),
    "source": "https://www.lpi.usra.edu/lunar/documents/NASA%20SP%20315.pdf",
    "workbook_ref": "MOON-01 to MOON-03",
}

EARTH_TEST_REGION = {
    "key": "atacama_s24w070",
    "name": "Atacama Desert test tile (SRTM S24W070)",
    "role": "Earth test region (pipeline verification)",
    "designation": "Not a matched analog candidate",
    "status_note": ("This tile was chosen to build and verify the data pipeline. It has not been "
                    "selected by any matching method."),
    "workbook_ref": "EARTH-01",
}

# --------------------------------------------------------------------------
# Rookie MVP experiment choices -> workbook planning experiments
# --------------------------------------------------------------------------
EXPERIMENTS = [
    {
        "key": "footpad_penetration",
        "label": "Static lander footpad penetration",
        "workbook_id": "EXP-01",
        "brief_additions": ["TOP-02", "TOP-03"],
        "focus": "soil",
    },
    {
        "key": "slope_stability",
        "label": "Lander stability on inclined terrain",
        "workbook_id": "EXP-04",
        "brief_additions": [],
        "focus": "slope",
    },
    {
        "key": "asymmetric_settlement",
        "label": "Asymmetric landing-leg settlement",
        "workbook_id": "EXP-05",
        "brief_additions": [],
        "focus": "soil",
    },
]
BRIEF_ADDITION_NOTE = ("Added by the Rookie MVP brief (2026-11-15); not listed in the workbook "
                       "experiment. Team to confirm.")

GOVERNANCE_NOTE = ("These are planning experiments from the team workbook. They are not "
                   "entries in the approved experiment catalog, and no physical test has "
                   "been performed.")

MATCHING = {
    "enabled": False,
    "reason": ("Matching and ranking are not enabled. CLAUDE.md keeps scoring and site "
               "recommendation out of the current phase, and no experiment in the governed "
               "catalog is approved with a matching algorithm."),
    "prerequisites": [
        "Team decision to start the matching phase (CLAUDE.md section 18 to 20)",
        "An approved catalog experiment that names a matching algorithm and weights",
        "A lunar DEM for the target region, integrated with lunar geodesy",
        "Lunar and Earth terrain features computed over the same window in metres",
    ],
}

LUNAR_TERRAIN_BLOCKERS = [
    "No lunar elevation dataset is downloaded or integrated in this project yet.",
    ("Lunar geodesy is not implemented: lunarmatch/geodesy.py uses the Earth WGS84 ellipsoid "
     "and must not be used for the Moon."),
    "The LOLA/LROC product ID and projection for this region have not been identified yet.",
]

SCALE_LIMITATION = ("SRTM samples about every 30 m. Slope and roughness describe terrain at "
                    "about 30 to 90 m scale, not at the scale of a lander's legs (metres).")
