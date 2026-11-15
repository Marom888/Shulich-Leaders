"""Per-feature Moon-Earth terrain distances (no weights, no score, no ranking).

Governance (user decision, 2026-11-15): comparison is limited to per-feature
distances in physical units between descriptors computed the same way on
both bodies at a matched sample spacing. Results are not combined, not
thresholded and not ordered by similarity.
"""
from __future__ import annotations

from lunarmatch.discovery.descriptors import QUANTILE_LEVELS

COMPARABLE = {
    "slope_deg": {"unit": "deg", "spec_feature": "F_SLOPE",
                  "caveat": "Slope magnitude depends on sample spacing; spacings are checked."},
    "roughness_m": {"unit": "m", "spec_feature": "F_ROUGH",
                    "caveat": "3x3 std of elevation (not detrended); not the spec's F_ROUGH metric."},
}

GOVERNANCE = {
    "per_feature_distances": True,
    "weights_used": False,
    "score_computed": False,
    "pass_fail_computed": False,
    "ranking_computed": False,
    "ordering": "window_id",
    "decision": "User decision 2026-11-15: per-feature distances only; no ranking; draft gates labelled.",
}


def w1_from_quantiles(qa: list[float], qb: list[float]) -> float:
    """1-D Wasserstein distance approximated from matched quantile vectors.

    W1 = integral over p in [0,1] of |Qa(p) - Qb(p)|, trapezoidal on the 21
    stored levels (0, 5, ..., 100 %). Same units as the feature.
    """
    if len(qa) != len(qb) or len(qa) != len(QUANTILE_LEVELS):
        raise ValueError("quantile vectors must match QUANTILE_LEVELS")
    d = [abs(a - b) for a, b in zip(qa, qb)]
    step = 1 / (len(d) - 1)
    return sum((d[i] + d[i + 1]) / 2 * step for i in range(len(d) - 1))


def _mean_spacing(rec: dict) -> float | None:
    s = rec.get("spacing_m")
    if not s:
        return None
    return (s["east_west"] + s["north_south"]) / 2


def spacing_check(moon_ref: dict, earth_rec: dict, tolerance: float = 0.25) -> dict:
    a, b = _mean_spacing(moon_ref), _mean_spacing(earth_rec)
    if not (a and b):
        return {"comparable": False, "detail": "sample spacing unknown"}
    ratio = max(a, b) / min(a, b)
    return {"comparable": ratio <= 1 + tolerance, "ratio": round(ratio, 3),
            "moon_spacing_m": round(a, 2), "earth_spacing_m": round(b, 2),
            "detail": f"spacing ratio {ratio:.2f} (limit {1 + tolerance:.2f})"}


def compare_feature(name: str, moon: dict | None, earth: dict | None) -> dict:
    meta = COMPARABLE[name]
    if moon is None or earth is None:
        return {"status": "missing", "unit": meta["unit"],
                "detail": "no value on " + ("the Moon" if moon is None else "Earth")}
    return {
        "status": "computed", "unit": meta["unit"],
        "earth": {k: earth[k] for k in earth if k != "q"},
        "moon": {k: moon[k] for k in moon if k != "q"},
        "delta": {k: round(earth[k] - moon[k], 3) for k in ("p50", "p90") if k in earth and k in moon},
        "w1": round(w1_from_quantiles(moon["q"], earth["q"]), 3),
    }


def compare_window(moon_ref: dict, earth_rec: dict, tolerance: float = 0.25,
                   passes_filters: bool | None = None) -> dict:
    """Per-feature distances between the lunar reference and one Earth window."""
    sc = spacing_check(moon_ref, earth_rec, tolerance)
    out = {
        "window_id": earth_rec["window_id"],
        "centre_lat_lon": earth_rec.get("centre_lat_lon"),
        "bounds_wsen": earth_rec.get("bounds_wsen"),
        "is_mock": bool(earth_rec.get("is_mock")) or bool(moon_ref.get("is_mock")),
        "passes_filters": passes_filters,
        "spacing": sc,
        "features": {},
    }
    for name in COMPARABLE:
        if earth_rec.get("status") != "ok":
            out["features"][name] = {"status": "insufficient_data", "unit": COMPARABLE[name]["unit"]}
        elif not sc["comparable"]:
            out["features"][name] = {"status": "scale_mismatch", "unit": COMPARABLE[name]["unit"],
                                     "detail": sc["detail"]}
        else:
            out["features"][name] = compare_feature(name, moon_ref.get(name), earth_rec.get(name))
    return out
