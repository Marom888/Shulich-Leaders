"""Build the deterministic Rookie journey payload.

Inputs: the planning workbook, the Earth tile summary, and the governed
experiment catalog. Output: a JSON-serialisable dict rendered by the static
app. No scores, ranks or similarity values are produced (matching is off).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from lunarmatch.experiments import schema as catalog_schema
from lunarmatch.knowledge.workbook import PlanningWorkbook, resolve_parameter_tokens
from rookie import content as C

APOLLO_DOCUMENTED = {"SOIL-01", "SOIL-02", "SOIL-03", "SOIL-04", "SOIL-07", "SOIL-11"}


def _domain(pid: str) -> str:
    return pid.split("-")[0]


# --------------------------------------------------------------------------
# Availability rules (one place, tested)
# --------------------------------------------------------------------------
def availability(param: dict, site: str, earth: dict | None = None) -> dict:
    """Data status of one parameter at one site.

    ``site`` is "lunar_target", "apollo_16" or "earth_test". Returns
    {"status", "note", "source"}; status is a key of content.STATUS.
    """
    pid, dom = param["id"], _domain(param["id"])
    if pid == "SOIL-12":
        return {"status": "control", "source": "Workbook SOIL-12",
                "note": "Record it as a test condition. It must not be used to rank lunar similarity."}

    if site == "lunar_target":
        if dom == "SOIL":
            return {"status": "missing", "source": "Workbook MOON-04",
                    "note": ("No in-situ geotechnical measurements exist for this region. "
                             "It cannot be inferred from topography.")}
        return {"status": "not_integrated", "source": f"Workbook: {param['lunar_source']}",
                "note": ("Not computed: no lunar DEM in the project and no lunar geodesy yet."
                         if dom == "TOP" else "Lunar dataset not integrated.")}

    if site == "apollo_16":
        if dom == "SOIL":
            if pid in APOLLO_DOCUMENTED:
                return {"status": "documented", "source": "Workbook MOON-01 to 03; SRC-07, SRC-08",
                        "note": "Point measurements reported in Apollo sources. Not yet extracted."}
            return {"status": "missing", "source": f"Workbook: {param['lunar_status']}",
                    "note": "Limited or no Apollo 16 data recorded in the workbook."}
        return {"status": "not_integrated",
                "source": "Workbook SRC-06 (LROC NAC Apollo 16 DTM)" if dom == "TOP"
                else f"Workbook: {param['lunar_source']}",
                "note": "Not downloaded or integrated."}

    if site == "earth_test":
        ready = bool(earth and earth.get("available"))
        if dom == "TOP" and pid in ("TOP-01", "TOP-02", "TOP-03"):
            if not ready:
                return {"status": "not_integrated", "source": "SRTMGL1",
                        "note": "SRTM tile not found locally."}
            if pid == "TOP-01":
                return {"status": "measured", "source": f"{earth['dataset']} ({earth['tile']})",
                        "note": (f"{earth['elevation_m']['min']:.0f} to "
                                 f"{earth['elevation_m']['max']:.0f} m, "
                                 f"{earth['nodata_count']} NoData cells")}
            layer = earth["slope"] if pid == "TOP-02" else earth["roughness"]
            s, unit = layer["stats"], "°" if pid == "TOP-02" else " m"
            return {"status": "derived", "source": layer["label"],
                    "note": (f"median {s['median']:.1f}{unit}, 90th percentile "
                             f"{s['p90']:.1f}{unit} (describes ~30 to 90 m scale, not lander-leg scale)")}
        if dom == "TOP":
            return {"status": "not_integrated", "source": f"Workbook: {param['earth_source']}",
                    "note": "Derivable from SRTM. Not implemented yet."}
        if dom == "GEO":
            return {"status": "not_integrated", "source": f"Workbook: {param['earth_source']}",
                    "note": "Earth dataset not integrated."}
        return {"status": "missing", "source": f"Workbook: {param['earth_source']}",
                "note": ("No field or lab measurement for this site. Physical tests are "
                         "planned in the workbook, not performed.")}

    raise ValueError(f"unknown site {site!r}")


# --------------------------------------------------------------------------
# Experiment -> parameters
# --------------------------------------------------------------------------
def experiment_parameters(wb: PlanningWorkbook, choice: dict) -> dict:
    exp = wb.experiment(choice["workbook_id"])
    ids, unresolved = resolve_parameter_tokens(exp["parameters"], wb.parameters)
    origin = {pid: f"Workbook {exp['id']}" for pid in ids}
    for pid in choice["brief_additions"]:
        if pid not in origin:
            ids.append(pid)
            origin[pid] = C.BRIEF_ADDITION_NOTE
    return {"experiment": exp, "ids": ids, "unresolved": unresolved, "origin": origin}


def parameter_rows(wb: PlanningWorkbook, ids: list[str], origin: dict, earth: dict) -> list[dict]:
    rows = []
    for pid in ids:
        p = wb.parameter(pid)
        rows.append({
            "id": pid, "domain": C.DOMAINS[_domain(pid)],
            "name_en": p["name_en"], "name_he": p["name_he"], "symbol": p["symbol"],
            "units": p["units"], "landing_use_he": p["landing_use"],
            "limitations_he": p["limitations"], "origin": origin[pid],
            "lunar_target": availability(p, "lunar_target"),
            "apollo_16": availability(p, "apollo_16"),
            "earth_test": availability(p, "earth_test", earth),
        })
    return rows


# --------------------------------------------------------------------------
# Guidance (deterministic, rule-based)
# --------------------------------------------------------------------------
def _count(rows, col):
    out = {}
    for r in rows:
        out[r[col]["status"]] = out.get(r[col]["status"], 0) + 1
    return out


def guidance(target: dict, choice: dict, rows: list[dict], earth: dict,
             unresolved: list[str]) -> dict:
    """Return {step: {"mood", "messages": [{"tone", "text"}]}}."""
    soil_missing = [r for r in rows if r["domain"] == "Geotechnical"
                    and r["lunar_target"]["status"] == "missing"]
    earth_soil_missing = [r for r in rows if r["domain"] == "Geotechnical"
                          and r["earth_test"]["status"] == "missing"]
    counts = _count(rows, "lunar_target")
    g = {}

    g["region"] = {"mood": "looking", "messages": [
        {"tone": "info", "text": (f"{target['name']} is a candidate landing region, not a "
                                  "confirmed landing site. I'll keep that label on everything.")},
        {"tone": "info", "text": ("Apollo 16 is our historical reference. That's where real "
                                  "soil measurements were made on the Moon.")},
    ]}

    msgs = [{"tone": "info", "text": (f"{choice['label']} links to {len(rows)} parameters. "
                                      "Let's check what we actually know.")}]
    if choice["brief_additions"]:
        msgs.append({"tone": "info", "text": ("I added slope and roughness from the Rookie brief. "
                                              "The team still needs to confirm them.")})
    if unresolved:
        msgs.append({"tone": "caution", "text": ("Some workbook parameter names don't match a "
                                                 f"defined parameter: {', '.join(unresolved)}.")})
    msgs.append({"tone": "info", "text": "This is a planning experiment. No physical test has been run."})
    g["experiment"] = {"mood": "walking", "messages": msgs}

    pmsgs = [{"tone": "info", "text": (
        f"For {target['name']}: {counts.get('missing', 0)} missing, "
        f"{counts.get('not_integrated', 0)} not integrated yet, "
        f"{counts.get('control', 0)} control condition(s).")}]
    if soil_missing:
        pmsgs.insert(0, {"tone": "caution", "text": (
            f"Soil strength data is missing for {target['name']}. "
            "I can't judge soil similarity there yet.")})
    g["parameters"] = {"mood": "caution" if soil_missing else "looking", "messages": pmsgs}

    g["lunar"] = {"mood": "caution", "messages": [
        {"tone": "caution", "text": (f"I can't compute slopes for {target['name']} yet. No lunar "
                                     "elevation data is loaded.")},
        {"tone": "info", "text": "Lunar distances need a Moon model, not Earth's WGS84 ellipsoid."},
    ]}

    if earth.get("available"):
        s = earth["slope"]["stats"]
        g["earth"] = {"mood": "celebrate", "messages": [
            {"tone": "success", "text": (f"I analysed the real Atacama test tile. Median slope is "
                                         f"{s['median']:.1f}°, 90th percentile {s['p90']:.1f}°.")},
            {"tone": "info", "text": "This tile tests the pipeline. It was not picked by matching."},
        ]}
    else:
        g["earth"] = {"mood": "caution", "messages": [
            {"tone": "caution", "text": "The SRTM test tile isn't on this computer, so I have no Earth terrain to show."}]}

    rmsgs = []
    if earth.get("available") and earth_soil_missing:
        rmsgs.append({"tone": "caution", "text": (
            "This location has real slope data, but soil strength data is missing. "
            "Let's check the soil properties before recommending it.")})
    if choice["focus"] == "slope":
        rmsgs.append({"tone": "info", "text": (
            "Slope over SRTM's ~85 m window isn't the slope under a lander's footpads.")})
    rmsgs.append({"tone": "info", "text": "Matching is switched off until the team approves a method."})
    g["results"] = {"mood": "caution", "messages": rmsgs}
    return g


# --------------------------------------------------------------------------
# Payload
# --------------------------------------------------------------------------
def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def results_card(choice: dict, rows: list[dict], earth: dict) -> dict:
    """Result view for the Earth test region. No similarity is computed."""
    missing = [f"{r['name_en']} ({r['id']})" for r in rows
               if r["earth_test"]["status"] in ("missing", "not_integrated")]
    available = [{"id": r["id"], "name": r["name_en"], **r["earth_test"]} for r in rows
                 if r["earth_test"]["status"] in ("measured", "derived")]
    return {
        "site": C.EARTH_TEST_REGION,
        "location_wsen": earth.get("sample_extent_wsen"),
        "available_measurements": available,
        "similarity": {"computed": False, "value": None, "reason": C.MATCHING["reason"]},
        "missing": missing,
        "uncertainty": [
            "SRTM vertical accuracy and radar smoothing are not quantified in this project.",
            "There is no lunar reference to compare against, so there is no similarity uncertainty.",
        ],
        "limitations": [
            C.SCALE_LIMITATION,
            "Topographic similarity is not geotechnical equivalence.",
            "1 g Earth tests don't reproduce lunar gravity or vacuum (workbook control notes 5 and 6).",
        ],
    }


def build_payload(wb: PlanningWorkbook, earth: dict,
                  catalog_path: Path = catalog_schema.DEFAULT_CATALOG) -> dict:
    catalog = catalog_schema.load_catalog(catalog_path)
    approved = catalog_schema.approved_experiments(catalog)
    experiments, journeys = [], {}
    for choice in C.EXPERIMENTS:
        ep = experiment_parameters(wb, choice)
        rows = parameter_rows(wb, ep["ids"], ep["origin"], earth)
        e = ep["experiment"]
        experiments.append({
            **choice, "workbook": {k: e[k] for k in (
                "id", "name_en", "name_he", "objective", "equipment", "deliverable",
                "priority", "controls", "status", "duration", "dependencies")},
            "unresolved": ep["unresolved"], "parameters": rows,
            "results": results_card(choice, rows, earth),
        })
        for t in C.LUNAR_TARGETS:
            journeys[f"{t['key']}|{choice['key']}"] = guidance(t, choice, rows, earth, ep["unresolved"])
    return {
        "product": {"name": "Rookie", "tagline": "Your Guide to Lunar Testing",
                    "engine": "LunarMatch"},
        "status_labels": C.STATUS,
        "targets": C.LUNAR_TARGETS,
        "reference": C.APOLLO_16,
        "earth_region": C.EARTH_TEST_REGION,
        "experiments": experiments,
        "journeys": journeys,
        "lunar_terrain": {"available": False, "blockers": C.LUNAR_TERRAIN_BLOCKERS},
        "earth": earth,
        "matching": C.MATCHING,
        "governance": {
            "note": C.GOVERNANCE_NOTE,
            "approved_catalog_experiments": len(approved),
            "catalog_experiments": len(catalog),
        },
        "provenance": {
            "workbook": Path(wb.path).name,
            "workbook_sha256": _sha256(wb.path),
            "catalog": Path(catalog_path).name,
        },
    }
