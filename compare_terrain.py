"""Compare a lunar region with Earth terrain windows (per-feature distances only).

Examples:
    # MOCK lunar region vs the real local Atacama SRTM tile
    python compare_terrain.py --moon-point -45 120 10 --earth-bbox -70 -24 -69 -23
    # all-MOCK demo
    python compare_terrain.py --moon-bbox 10 -5 10.6 -4.4 --earth-bbox -70 -24 -68 -22 --earth-dataset MOCK_EARTH_DEM
    python compare_terrain.py --list-datasets

Writes outputs/discovery/latest_comparison.json, shown in Rookie's Results step.
No weights, scores, pass/fail or ranking are computed (user decision 2026-11-15).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lunarmatch.config import OUTPUT_DIR  # noqa: E402
from lunarmatch.discovery.comparison_run import ComparisonRequest, run_comparison  # noqa: E402
from lunarmatch.discovery.engine import Constraint  # noqa: E402
from lunarmatch.discovery.requirements import DraftSpec, find_spec  # noqa: E402
from lunarmatch.discovery.store import DescriptorCache, write_json  # noqa: E402
from lunarmatch.regions import LunarRegion  # noqa: E402
from lunarmatch.terrain.registry import default_registry  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--moon-point", nargs=3, type=float, metavar=("LAT", "LON", "RADIUS_KM"))
    g.add_argument("--moon-bbox", nargs=4, type=float, metavar=("W", "S", "E", "N"))
    ap.add_argument("--moon-dataset", default="MOCK_MOON_DEM")
    ap.add_argument("--earth-bbox", nargs=4, type=float, metavar=("W", "S", "E", "N"))
    ap.add_argument("--earth-dataset", default="SRTMGL1")
    ap.add_argument("--window-km", type=float, default=10.0)
    ap.add_argument("--constraint", action="append", default=[])
    ap.add_argument("--leg-spacing-m", type=float, help="lander leg spacing (mission input)")
    ap.add_argument("--list-datasets", action="store_true")
    ap.add_argument("--out", type=Path, default=OUTPUT_DIR / "discovery" / "latest_comparison.json")
    args = ap.parse_args()

    reg = default_registry()
    if args.list_datasets:
        for body in ("Moon", "Earth"):
            for c in reg.for_body(body):
                print(f"{body:5s} {c.dataset_id:20s} {'MOCK' if c.is_mock else 'real':4s} "
                      f"~{c.nominal_spacing_m:.0f} m  {getattr(c, 'label', '')}")
        return 0
    if not (args.moon_point or args.moon_bbox) or not args.earth_bbox:
        ap.error("--moon-point or --moon-bbox, and --earth-bbox, are required")

    region = (LunarRegion.point(args.moon_point[0], args.moon_point[1], args.moon_point[2] * 1000,
                                name="user point region") if args.moon_point
              else LunarRegion.bbox(*args.moon_bbox, name="user box region"))
    moon, earth = reg.get(args.moon_dataset), reg.get(args.earth_dataset)
    mission = {"leg_spacing_m": args.leg_spacing_m} if args.leg_spacing_m else {}
    req = ComparisonRequest(region, tuple(args.earth_bbox), args.window_km * 1000,
                            [Constraint.parse(c) for c in args.constraint], mission)
    spec_path = find_spec()
    spec = DraftSpec.load(spec_path) if spec_path else None

    def progress(ev):
        if ev["stage"] == "moon":
            print(f"  Moon [{ev['units_done']}/{ev['units_total']}] {ev['unit']}: {ev['status']}")
        elif ev["stage"] == "tiles":
            print(f"  Earth [{ev['tiles_done']}/{ev['tiles_total']}] {ev['tile']}: {ev['status']}")

    print(f"Moon: {moon.dataset_id}{' (MOCK)' if moon.is_mock else ''}; "
          f"Earth: {earth.dataset_id}{' (MOCK)' if earth.is_mock else ''}")
    res = run_comparison(req, moon, earth, DescriptorCache(), progress, spec)
    path = write_json(res, args.out)
    ref = res["moon"]
    if res["contains_mock_data"]:
        print("\n*** MOCK DATA - not real terrain ***")
    if ref["status"] == "ok":
        print(f"\nLunar reference: slope p50 {ref['slope_deg']['p50']}°, p90 {ref['slope_deg']['p90']}°, "
              f"spacing {ref['spacing_m']}")
    else:
        print(f"\nLunar reference: {ref['status']}")
    print(res["earth"]["coverage"]["statement"])
    comp = [c for c in res["comparisons"] if c["features"]["slope_deg"]["status"] == "computed"]
    print(f"Earth windows compared: {len(comp)} of {len(res['comparisons'])} "
          "(per-feature distances; not ranked)")
    for d in res["experiments_draft"]:
        print(f"  [DRAFT] {d['experiment_id']:10s} {d['status']:18s} "
              f"missing required: {', '.join(d['missing_required']) or '-'}")
    print(f"Result: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
