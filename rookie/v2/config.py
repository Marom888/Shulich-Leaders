"""Configuration payload for the Rookie 2.0 front end (shared by build and server).

Everything here comes from the engineering workbooks, the governed catalog,
the connector registry, or verified presets; nothing is invented.
"""
from __future__ import annotations

from lunarmatch.analog_catalog import load_catalog
from lunarmatch.discovery.job import OVERALL_WINNER, STAGES, swir_status
from lunarmatch.discovery.requirements import FEATURE_DESCRIPTORS
from lunarmatch.discovery.candidates import PREVIEW_RULE, vacuum_sentence
from lunarmatch.environment import PROFILES, STATUS as ENV_STATUS, THERMAL_NOTE, assess
from lunarmatch.experiments import schema as catalog_schema
from lunarmatch.knowledge.algorithm_spec import SPEC_FILES, AlgorithmSpec, compare_specs
from lunarmatch.lunar_presets import PRESETS

MOON_RADIUS_KM = 1737.4


def load_spec():
    """Prefer Talia's SWIR workbook (additive superset), fall back to v1.0."""
    for v in ("swir", "v1.0"):
        if SPEC_FILES[v].is_file():
            return AlgorithmSpec.load(v)
    return None


def spec_versions() -> dict:
    out = {}
    for v, p in SPEC_FILES.items():
        if p.is_file():
            s = AlgorithmSpec.load(v)
            out[v] = {"file": p.name, "sha256": s.sha256,
                      "revision": s.start_here().get("LunarMatch / Algorithm - selected experiments", "")}
    if len(out) == 2:
        diff = compare_specs(AlgorithmSpec.load("v1.0"), AlgorithmSpec.load("swir"))
        out["changes_v1_to_swir"] = {k: v for k, v in diff.items() if any(v.values())}
    return out


def experiment_cards(spec) -> list[dict]:
    approved = {e.experiment_id for e in catalog_schema.approved_experiments(catalog_schema.load_catalog())}
    cards = []
    for e in (spec.experiments() if spec else []):
        req = [f["feature_id"] for f in e["required_features"]]
        computable = {f: (FEATURE_DESCRIPTORS[f][1] if f in FEATURE_DESCRIPTORS else "not computable yet")
                      for f in req + [f["feature_id"] for f in e["optional_features"]]}
        missing = [f for f in req if f not in FEATURE_DESCRIPTORS]
        env = assess(e["experiment_id"])
        cards.append({**e, "catalog_approved": e["experiment_id"] in approved,
                      "vacuum_sentence": vacuum_sentence(env),
                      "field_test": (env.get("two_stage") or {}).get("stage_1_field", []),
                      "lab_validation": (env.get("two_stage") or {}).get("stage_2_controlled"),
                      "approval_status": "approved in catalog" if e["experiment_id"] in approved
                      else "planning only - not approved (workbook flag is not approval)",
                      "engine_support": computable, "missing_information": missing,
                      "environment_profile": PROFILES.get(e["experiment_id"])})
    return cards


def _local_units(connector) -> list[str]:
    """Coverage units present on disk (local-file connectors only; mocks have none)."""
    src = getattr(connector, "_source", None)
    return sorted(src.index()) if src is not None and hasattr(src, "index") else []


def coverage_extent(units: list[str]):
    """Bounding box (W, S, E, N) of locally available 1-degree tiles, or None."""
    from lunarmatch.discovery.grid import GridError, Tile
    b = []
    for u in units:
        try:
            b.append(Tile.from_id(u).bounds)
        except GridError:
            continue
    if not b:
        return None
    return [min(x[0] for x in b), min(x[1] for x in b), max(x[2] for x in b), max(x[3] for x in b)]


def build_config(registry) -> dict:
    spec = load_spec()
    cat = load_catalog()
    return {
        "product": {"name": "Rookie", "version": "2.0", "engine": "LunarMatch"},
        "moon_radius_km": MOON_RADIUS_KM, "moon_crs": "IAU_2015:30100",
        "presets": PRESETS,
        "experiments": experiment_cards(spec),
        "spec": {"loaded": spec.path.name if spec else None, "sha256": spec.sha256 if spec else None,
                 "versions": spec_versions()},
        "swir": swir_status(spec),
        "environment": {"status": ENV_STATUS, "thermal_note": THERMAL_NOTE},
        "datasets": [{"id": c.dataset_id, "body": c.body, "is_mock": c.is_mock,
                      "spacing_m": round(c.nominal_spacing_m, 1), "label": getattr(c, "label", c.dataset_id),
                      "local_units": _local_units(c), "coverage_extent": coverage_extent(_local_units(c))}
                     for c in (registry.for_body("Moon") + registry.for_body("Earth"))],
        "catalog": {"status": cat["status"], "sites": len(cat["sites"])},
        "stages": [{"id": s, "label": l} for s, l in STAGES],
        "preview_rule": PREVIEW_RULE,
        "overall_winner": OVERALL_WINNER,
        "cost": {"status": "unavailable", "note": "Budget, currency, start location and travel distance are "
                 "recorded as planning inputs only. Automated cost and logistics evaluation is not "
                 "implemented or approved and never affects scientific results."},
    }
