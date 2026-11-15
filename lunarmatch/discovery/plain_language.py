"""Plain-language engineering rules: what a missing feature means and what to do next.

Each entry restates the algorithm spec's own requirement for that feature
(Experiment_Features "Hard_Gate_or_Condition", Features limitations) in
user-facing language, and names the measurement that would supply it. The
`basis` field cites what the sentence relies on. Nothing here is a
measurement or a result.
"""
from __future__ import annotations

# kind: "field" (on-site measurement), "lab" (laboratory / chamber), "input" (engineering input),
#       "analysis" (computation from data Rookie does not have yet)
FEATURES = {
    "F_SLOPE": {"topic": "slopes",
                "missing": "Slopes could not be computed for this area.",
                "action": "Obtain elevation data covering the candidate area.", "kind": "analysis",
                "basis": "F_SLOPE: DEM gradient at matched spatial support"},
    "F_RELIEF": {"topic": "lander-footprint relief",
                 "missing": "The available elevation data are too coarse to verify lander-footprint conditions.",
                 "action": "Survey the area with a high-resolution terrain scan (spec: DEM spacing at most leg spacing / 3).",
                 "kind": "field", "basis": "EXP_02 F_RELIEF gate: 'High-res DEM <= leg-spacing/3 required'"},
    "F_ROUGH": {"topic": "footprint-scale roughness",
                "missing": "Roughness is known only at the ~30 m data scale, not at the scale of the lander's feet.",
                "action": "Measure detrended roughness from a high-resolution terrain scan at leg-footprint scale.",
                "kind": "field", "basis": "F_ROUGH: detrended RMS at identical physical window"},
    "F_ROCK_DENS": {"topic": "boulders",
                    "missing": "Boulders have not been mapped here.",
                    "action": "Map boulders above a common minimum size from high-resolution imagery or a walk-over survey.",
                    "kind": "field", "basis": "F_ROCK_DENS: counts above common resolvable Dmin"},
    "F_ROCK_SIZE": {"topic": "boulder sizes",
                    "missing": "Boulder sizes have not been measured.",
                    "action": "Measure boulder diameters in the same survey, above the same minimum size as on the Moon.",
                    "kind": "field", "basis": "F_ROCK_SIZE: equal detectability on Moon and Earth"},
    "F_CRATER_DENS": {"topic": "crater-like depressions",
                      "missing": "Crater-like depressions have not been mapped.",
                      "action": "Map circular depressions from high-resolution imagery or terrain data, with geomorphic labels.",
                      "kind": "analysis", "basis": "F_CRATER_DENS: geomorphic annotation required"},
    "F_CRATER_SIZE": {"topic": "depression sizes",
                      "missing": "Depression sizes have not been measured.",
                      "action": "Measure depression diameters above the same minimum size used for the Moon.",
                      "kind": "analysis", "basis": "F_CRATER_SIZE: same Dmin and scene area"},
    "F_TEXTURE": {"topic": "image texture",
                  "missing": "Image texture has not been compared.",
                  "action": "Collect imagery at matched resolution and lighting, then compare texture.",
                  "kind": "analysis", "basis": "F_TEXTURE: same ground sample distance"},
    "F_LANDMARK": {"topic": "navigation landmarks",
                   "missing": "Navigation landmarks have not been evaluated.",
                   "action": "Run the navigation feature extractor on simulated descent views of this area.",
                   "kind": "analysis", "basis": "F_LANDMARK: synthetic descent views and independent images"},
    "F_VISIBILITY": {"topic": "landmark visibility",
                     "missing": "Landmark visibility along the descent path has not been computed.",
                     "action": "Compute visibility from the camera field of view and descent trajectory.",
                     "kind": "analysis", "basis": "F_VISIBILITY: camera FOV, pose trajectory and DEM needed"},
    "F_SHADOW": {"topic": "shadows",
                 "missing": "Shadow conditions have not been simulated.",
                 "action": "Ray-trace terrain shadows for the lunar landing time and a matching Earth date and hour.",
                 "kind": "analysis", "basis": "F_SHADOW: solar geometry + sufficiently resolved DEM"},
    "F_SUN": {"topic": "Sun angle",
              "missing": "Sun elevation and direction have not been matched.",
              "action": "Compute the lunar Sun angle at landing and find Earth dates/hours with a matching Sun angle.",
              "kind": "analysis", "basis": "F_SUN: compute Moon and Earth times independently"},
    "F_CONTRAST": {"topic": "image contrast",
                   "missing": "Shadow/sunlit image contrast has not been measured.",
                   "action": "Capture field images at the matched Sun angle and compare normalised contrast.",
                   "kind": "field", "basis": "F_CONTRAST: normalised contrast, not raw radiance"},
    "F_SOIL_BD": {"topic": "soil density",
                  "missing": "Soil density has not been measured.",
                  "action": "Take soil samples and measure dry bulk density at the relevant depth.",
                  "kind": "lab", "basis": "F_SOIL_BD: compare density intervals at comparable depth"},
    "F_SOIL_PSD": {"topic": "grain size",
                   "missing": "Soil grain size has not been measured.",
                   "action": "Sieve-test soil samples from the site.",
                   "kind": "lab", "basis": "F_SOIL_PSD: lab sieve data preferred"},
    "F_COARSE": {"topic": "coarse fragments",
                 "missing": "The amount of coarse fragments in the soil is unknown.",
                 "action": "Record coarse-fragment content and depth from soil pits or samples.",
                 "kind": "field", "basis": "F_COARSE: depth and lithology metadata required"},
    "F_CPT": {"topic": "soil strength",
              "missing": "Soil strength must be measured before this site can be approved for a settlement experiment.",
              "action": "Run cone-penetration tests at the site.",
              "kind": "field", "basis": "EXP_04 F_CPT gate: 'If no nearby CPT, no quantitative sinkage claim'"},
    "F_LOAD": {"topic": "lander loads",
               "missing": "Lander loads and footpad geometry have not been provided.",
               "action": "Provide lander mass, footpad area and the gravity scaling to be used.",
               "kind": "input", "basis": "F_LOAD: need gravity scaling and contact assumptions"},
    "F_COHESION": {"topic": "soil cohesion",
                   "missing": "Soil cohesion has not been measured.",
                   "action": "Run laboratory shear tests on site samples.",
                   "kind": "lab", "basis": "F_COHESION: compare only where measured explicitly"},
    "F_FRICTION": {"topic": "soil friction angle",
                   "missing": "Soil friction angle has not been measured.",
                   "action": "Run laboratory shear tests on site samples.",
                   "kind": "lab", "basis": "F_FRICTION: lab shear parameters only"},
    "F_PLUME_GEOM": {"topic": "engine geometry",
                     "missing": "Engine plume geometry has not been provided.",
                     "action": "Provide engine thrust, nozzle height and angle for the plume-footprint calculation.",
                     "kind": "input", "basis": "F_PLUME_GEOM: engine/vehicle geometry input required"},
}

GENERIC = {"missing": "This required measurement is not yet available.",
           "action": "Collect the measurement listed in the engineering specification.", "kind": "field",
           "basis": "algorithm spec"}


def feature_text(feature_id: str) -> dict:
    return {"feature_id": feature_id, **FEATURES.get(feature_id, GENERIC)}


def coverage_blocker(coverage: dict) -> str | None:
    """One short, honest sentence about unsearched coverage."""
    req, done = coverage.get("tiles_requested", 0), coverage.get("tiles_processed", 0)
    if req and done < req:
        return (f"Rookie had terrain data for {done} of {req} areas in your search region; "
                "adding Earth terrain coverage would let it search the rest.")
    return None
