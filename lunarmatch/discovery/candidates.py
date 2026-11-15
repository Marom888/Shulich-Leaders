"""Experiment-specific candidate locations with plain-language conclusions.

Governance (CLAUDE.md, user decisions 2026-11-15):
* Candidates are DISCOVERED, NOT RANKED. Up to three are shown as a preview,
  chosen by a transparent geographic-spread rule (farthest-point sampling over
  the windows that passed data-quality checks and the user's constraints),
  never by suitability.
* "Best site" stays NOT YET DETERMINED until a ranking method is approved.
* An experiment whose required features Rookie cannot measure gets no
  candidates, rather than misleading terrain-only ones.
* Every sentence is backed by a measurement, an explicit spec requirement or
  a stated rule; place names come only from a reliable geocoder.
"""
from __future__ import annotations

from lunarmatch.bodies import EARTH, great_circle_m
from lunarmatch.discovery.plain_language import FEATURES, feature_text
from lunarmatch.discovery.requirements import FEATURE_DESCRIPTORS
from lunarmatch.geo_naming import NullGeocoder

PREVIEW_SIZE = 3
LABELS = "ABC"
PREVIEW_RULE = ("Up to three areas that passed Rookie's data checks, picked to be spread across the "
                "searched region so you can compare different terrain. They are not ranked by suitability.")
POINT_TYPE = "candidate-area centroid (not a verified or accessible test point)"


def spread_select(windows: list[dict], k: int = PREVIEW_SIZE) -> list[dict]:
    """Deterministic farthest-point sampling on the Earth sphere (starts at the lowest window ID)."""
    pool = sorted(windows, key=lambda w: w["window_id"])
    if not pool:
        return []
    chosen = [pool[0]]
    while len(chosen) < min(k, len(pool)):
        def mind(w):
            return min(great_circle_m(EARTH, *w["centre_lat_lon"], *c["centre_lat_lon"]) for c in chosen)
        rest = [w for w in pool if w not in chosen]
        chosen.append(max(rest, key=lambda w: (mind(w), w["window_id"])))
    return chosen


def ring(bounds):
    w, s, e, n = bounds
    return [[w, s], [e, s], [e, n], [w, n], [w, s]]


def _vs(moon_mock: bool) -> str:
    return "the MOCK lunar reference" if moon_mock else "the lunar reference"


def why_bullets(w, comp, relevant, constraints, moon_mock) -> list[str]:
    out = [f"Inside the area Rookie could search, with elevation data for {w['valid_fraction'] * 100:.0f}% "
           f"of a {w['area_km2']:.0f} km² area."]
    f = comp.get("slope_deg", {})
    if "slope_deg" in relevant and f.get("status") == "computed":
        d = f["delta"]["p90"]
        word = "steeper" if d > 0 else "gentler"
        out.append(f"Its steepest slopes ({f['earth']['p90']:.1f}°, 90th percentile) are "
                   f"{abs(d):.1f}° {word} than {_vs(moon_mock)}.")
    for c in constraints:                                   # the user's own requirement comes first
        if c.startswith("slope_deg.p90<="):
            out.append(f"Meets your limit: steepest slopes at most {float(c.split('<=')[1]):g}°.")
    r = comp.get("roughness_m", {})
    if "roughness_m" in relevant and r.get("status") == "computed":
        d = r["delta"]["p90"]
        out.append(f"Its terrain roughness at ~30 m scale differs from {_vs(moon_mock)} by {abs(d):.1f} m "
                   "(90th percentile).")
    return out[:3]


def build_experiment_results(*, experiments, gates, windows, comps, passed, env, mission, moon_mock,
                             earth_label, earth_mock, coverage_note, geocoder=None) -> list[dict]:
    geocoder = geocoder or NullGeocoder()
    leg = mission.scale.characteristic_lengths_m.get("leg_spacing")
    start = mission.earth.start_location or {}
    out = []
    for exp in experiments:
        eid = exp["experiment_id"]
        g = gates.get(eid) or {"missing_required": [f["feature_id"] for f in exp["required_features"]
                                                    if f["feature_id"] not in FEATURE_DESCRIPTORS]}
        required = [f["feature_id"] for f in exp["required_features"]]
        relevant = [FEATURE_DESCRIPTORS[f][0] for f in required if f in FEATURE_DESCRIPTORS]
        missing = [feature_text(f) for f in g["missing_required"]]
        e = env.get(eid) or {}
        field = (e.get("two_stage") or {}).get("stage_1_field", [])
        lab = (e.get("two_stage") or {}).get("stage_2_controlled")
        base = {
            "experiment_id": eid, "name": exp["name_en"],
            "approval": "planning only (not approved)",
            "best_site": {"status": "not_determined", "label": "BEST SITE — NOT YET DETERMINED",
                          "reason": (f"{missing[0]['topic'].capitalize()} is still unmeasured and no ranking "
                                     "method has been approved yet." if missing else
                                     "No ranking method has been approved yet.")},
            "preview_label": "DISCOVERED CANDIDATES — NOT YET RANKED",
            "preview_rule": PREVIEW_RULE,
            "missing": missing,
            "validation": {"field": field, "lab": lab, "vacuum_matters": e.get("vacuum_material"),
                           "vacuum_sentence": vacuum_sentence(e)},
            "candidates": [], "alternatives": [], "no_candidates_reason": None,
        }
        if not relevant:
            topics = ", ".join(FEATURES.get(f, {}).get("topic", f) for f in required)
            base["no_candidates_reason"] = (f"Rookie cannot yet measure any of this experiment's required evidence "
                                            f"({topics}), so it does not suggest locations for it.")
            out.append(base)
            continue
        eligible = [windows[wid] for wid in sorted(passed)
                    if all(comps[wid]["features"].get(d, {}).get("status") == "computed" for d in relevant)]
        if not eligible:
            base["no_candidates_reason"] = ("No searched area passed the data checks for this experiment. "
                                            + (coverage_note or ""))
            out.append(base)
            continue
        preview = spread_select(eligible)
        for i, w in enumerate(preview):
            base["candidates"].append(candidate_card(w, comps[w["window_id"]]["features"], LABELS[i], exp, relevant,
                                                     missing, mission, moon_mock, earth_label, earth_mock,
                                                     leg, start, geocoder, e))
        base["alternatives"] = [{"id": w["window_id"], "centroid": w["centre_lat_lon"],
                                 "boundary": ring(w["bounds_wsen"]), "area_km2": w["area_km2"]}
                                for w in eligible if w not in preview]
        out.append(base)
    return out


def vacuum_sentence(e: dict) -> str:
    v = e.get("vacuum_material", "")
    if v == "yes":
        return ("Outdoor testing cannot reproduce lunar vacuum behaviour; vacuum-chamber validation is needed "
                "for lunar-representative conclusions.")
    if v == "possibly":
        return ("Soil behaviour and loading need laboratory validation before terrestrial results can be "
                "translated to lunar conditions.")
    if v.startswith("no"):
        return ("The tested physics is not dominated by vacuum; field tests are meaningful, but lunar gravity "
                "and lighting still differ.")
    return "Environmental requirements for this experiment have not been assessed."


def candidate_card(w, comp, label, exp, relevant, missing, mission, moon_mock, earth_label, earth_mock,
                   leg, start, geocoder, env) -> dict:
    lat, lon = w["centre_lat_lon"]
    miss = [m["missing"] for m in missing]
    sp = w.get("spacing_m") or {}
    spacing = max(sp.get("east_west", 0), sp.get("north_south", 0))
    if leg and spacing > leg / 3 and "F_RELIEF" in [f["feature_id"] for f in exp["required_features"]]:
        miss = [f"The available elevation data (~{spacing:.0f} m) are too coarse to verify lander-footprint "
                f"conditions (needs about {leg / 3:.1f} m or finer for {leg:g} m leg spacing)."] + \
               [m for m in miss if "too coarse" not in m]
    actions = []
    for m in missing:
        if m["action"] not in actions:
            actions.append(m["action"])
    invalidate = ["Site access, land ownership and permits are unknown."]
    if any(m["feature_id"].startswith(("F_SOIL", "F_CPT", "F_COHESION", "F_FRICTION", "F_COARSE")) for m in missing):
        invalidate.append("Soil properties at the site may differ from lunar regolith.")
    invalidate.append("Terrain details smaller than the data spacing (boulders, small slopes) are not visible yet.")
    dist = None
    if start.get("lat") is not None and start.get("lon") is not None:
        dist = round(great_circle_m(EARTH, start["lat"], start["lon"], lat, lon) / 1000, 1)
    return {
        "id": f"{exp['experiment_id']}-{label}", "label": label, "window_id": w["window_id"],
        "experiment_id": exp["experiment_id"], "experiment_name": exp["name_en"],
        "title": "DISCOVERED TEST LOCATION",
        "status": "unverified candidate — terrain screening only",
        "point_type": POINT_TYPE,
        "centroid": {"lat": lat, "lon": lon}, "boundary": ring(w["bounds_wsen"]), "bounds_wsen": w["bounds_wsen"],
        "area_km2": w["area_km2"], "size_km": [round(w["size_m"]["east_west"] / 1000, 2),
                                                round(w["size_m"]["north_south"] / 1000, 2)],
        "place": geocoder.place(lat, lon),
        "distance_from_start_km": dist,
        "why": why_bullets(w, comp, relevant, mission.constraints, moon_mock),
        "missing": miss[:3], "next_actions": actions[:3], "could_invalidate": invalidate,
        "validation": {"field": (env.get("two_stage") or {}).get("stage_1_field", []),
                       "lab": (env.get("two_stage") or {}).get("stage_2_controlled"),
                       "vacuum_sentence": vacuum_sentence(env)},
        "provenance": {"earth": earth_label, "earth_is_mock": earth_mock,
                       "lunar_is_mock": moon_mock, "window_id": w["window_id"]},
    }
