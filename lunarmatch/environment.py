"""Lunar environment simulation requirements per experiment (planning assessment).

Vacuum is a core requirement: an outdoor terrestrial site does not reproduce
the Moon's near-vacuum, 1/6 g, dust or thermal environment. These profiles
separate what a field site can test (Stage 1) from what needs controlled
environmental validation (Stage 2).

PROVENANCE: drafted by the software assistant from the algorithm spec's
Physical_Models (scope limits, validation gates) and the team brief; they are
planning guidance for engineering review, NOT validated physics. Each field
records which spec entries it relies on.
"""
from __future__ import annotations

import re

STATUS = "planning assessment - needs engineering review (not validated)"

PROFILES = {
    "EXP_02": {
        "vacuum_material": "no",
        "mechanisms_affected": ["contact geometry is unaffected by vacuum",
                                "touchdown dynamics depend on gravity (1/6 g) not reproduced outdoors"],
        "outdoor": ["terrain relief and slope at leg footprints", "static support-polygon geometry"],
        "chamber_required": "no",
        "numerical_simulation": "yes - gravity scaling of static/dynamic stability margins",
        "scalable": "partly - geometry scales; dynamic stability does not scale with footprint alone",
        "not_reproducible": ["lunar gravity", "regolith mechanical response"],
        "spec_refs": ["PM_SUPPORT: 'Simplified static assessment; not touchdown dynamics'"],
    },
    "EXP_04": {
        "vacuum_material": "possibly",
        "mechanisms_affected": ["absence of pore air and moisture changes granular behaviour",
                                "cohesion/friction of terrestrial soils differ from regolith"],
        "outdoor": ["terrain context", "in-situ penetration (CPT) on terrestrial soil",
                    "controlled static loading of a footpad"],
        "chamber_required": "for representative regolith behaviour - lab tests with simulant",
        "numerical_simulation": "yes - settlement only with calibrated constitutive parameters",
        "scalable": "no - footpad settlement depends on footpad size, soil state and gravity",
        "not_reproducible": ["lunar regolith fabric", "1/6 g overburden stress", "vacuum pore conditions"],
        "spec_refs": ["PM_SINKAGE: 'Model-based settlement only if local constitutive parameters or "
                      "calibrated penetration curve exist'", "R08 SOIL_EVIDENCE"],
    },
    "EXP_08": {
        "vacuum_material": "no",
        "mechanisms_affected": ["illumination and atmosphere change object appearance, not geometry"],
        "outdoor": ["rock/crater-like object geometry and density", "detector precision/recall on terrestrial imagery"],
        "chamber_required": "no",
        "numerical_simulation": "optional - rendered lunar illumination for detector stress tests",
        "scalable": "yes for geometry above the common minimum detectable size",
        "not_reproducible": ["lunar photometry (no atmosphere)", "impact-crater morphology on Earth"],
        "spec_refs": ["PM_HAZARD: 'natural Earth depressions need not be impacts'"],
    },
    "EXP_10": {
        "vacuum_material": "no for algorithm validation; hardware qualification is separate",
        "mechanisms_affected": ["atmospheric scattering and haze alter image contrast"],
        "outdoor": ["terrain-relative navigation algorithm validation on terrestrial terrain imagery"],
        "chamber_required": "not for the algorithm; thermal-vacuum qualification for flight hardware",
        "numerical_simulation": "yes - synthetic descent imagery at lunar illumination",
        "scalable": "partly - altitude/field-of-view must be scaled with the terrain",
        "not_reproducible": ["lunar illumination geometry without atmosphere", "flight-like descent dynamics"],
        "spec_refs": ["PM_TRN: 'Not a real onboard navigation dataset by default'"],
    },
    "EXP_SHADOW": {
        "vacuum_material": "no for algorithm validation",
        "mechanisms_affected": ["Earth atmosphere softens shadows and adds diffuse light"],
        "outdoor": ["low-Sun field imagery at a matched solar elevation/azimuth"],
        "chamber_required": "no",
        "numerical_simulation": "yes - DEM ray-traced shadows at the lunar landing time",
        "scalable": "partly - shadow geometry scales with relief; photometry does not",
        "not_reproducible": ["hard lunar shadows without atmospheric scattering", "lunar regolith photometry"],
        "spec_refs": ["PM_SHADOW_NAV: 'No exact lunar photometry on Earth due to atmosphere/albedo'"],
    },
    "EXP_PLUME": {
        "vacuum_material": "yes",
        "mechanisms_affected": ["plume expansion (rarefied flow in vacuum)", "particle entrainment and ejecta transport",
                                "no aerodynamic drag on ejecta in vacuum"],
        "outdoor": ["natural soil/terrain testbed characterisation only"],
        "chamber_required": "yes - vacuum-chamber plume tests and validated plume/erosion models",
        "numerical_simulation": "yes - only if calibrated with vacuum-chamber or flight data",
        "scalable": "no - plume-surface interaction does not scale with geographic footprint",
        "not_reproducible": ["lunar vacuum plume expansion", "ballistic ejecta trajectories", "lunar regolith"],
        "spec_refs": ["PM_PLUME: 'Open atmosphere on Earth is NOT equivalent to lunar vacuum'",
                      "R12 PSI_LAB_GATING", "R13 PSI_CONFIDENCE"],
    },
}

THERMAL_NOTE = ("Thermal behaviour outdoors is dominated by atmospheric convection; lunar "
                "thermal-vacuum conditions need a thermal-vacuum chamber where thermal response matters.")


def assess(experiment_id: str, requirements: dict | None = None) -> dict:
    """Environmental validation plan for one experiment and the user's settings."""
    p = PROFILES.get(experiment_id)
    if p is None:
        return {"experiment_id": experiment_id, "status": "no profile defined",
                "two_stage": None}
    req = requirements or {}
    warnings = []
    if req.get("vacuum") == "required" and p["chamber_required"].startswith("no"):
        warnings.append("Vacuum marked required, but this experiment's physics is not dominated by "
                        "vacuum; check whether a chamber test is really needed.")
    if req.get("vacuum") == "not_required" and p["vacuum_material"] == "yes":
        warnings.append("Vacuum marked not required, but vacuum materially affects this experiment; "
                        "outdoor results cannot represent lunar conditions.")
    if req.get("thermal_vacuum") in ("required", "preferred"):
        warnings.append(THERMAL_NOTE)
    stage2 = p["chamber_required"] if not p["chamber_required"].startswith("no") else \
        p["numerical_simulation"]
    stage2 = re.sub(r"^(yes|no)\s*-\s*", "", stage2)
    stage2 = stage2[:1].upper() + stage2[1:]
    return {
        "experiment_id": experiment_id, "status": STATUS, **p,
        "two_stage": {
            "stage_1_field": p["outdoor"],
            "stage_2_controlled": stage2,
            "sufficiency": "Not established - whether the two stages together are sufficient "
                           "is an engineering decision for each experiment.",
        },
        "warnings": warnings,
    }
