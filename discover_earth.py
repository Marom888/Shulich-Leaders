"""Stage A Earth analog screening over a bounding box (local data only).

Examples:
    python discover_earth.py --bbox -71 -25 -68 -22
    python discover_earth.py --bbox -71 -25 -68 -22 --window-km 5 --constraint "slope_deg.p90<=10"
    python discover_earth.py --bbox -71 -25 -68 -22 --plan-downloads   # catalogue sizes, no download

Computes terrain descriptors for physically sized windows, filters on data
quality and explicit constraints, and writes outputs/discovery/latest.json.
No similarity, scores or rankings are computed.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lunarmatch.config import OUTPUT_DIR  # noqa: E402
from lunarmatch.discovery.engine import Constraint, SearchRequest, run_search  # noqa: E402
from lunarmatch.discovery.grid import Tile  # noqa: E402
from lunarmatch.discovery.sources import plan_downloads  # noqa: E402
from lunarmatch.discovery.store import write_result  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bbox", nargs=4, type=float, required=True, metavar=("W", "S", "E", "N"))
    ap.add_argument("--window-km", type=float, default=10.0)
    ap.add_argument("--min-valid", type=float, default=0.9)
    ap.add_argument("--constraint", action="append", default=[],
                    help='e.g. "slope_deg.p90<=15" (repeatable)')
    ap.add_argument("--plan-downloads", action="store_true",
                    help="list catalogue granules and sizes for tiles without local data")
    ap.add_argument("--out", type=Path, default=OUTPUT_DIR / "discovery" / "latest.json")
    args = ap.parse_args()

    req = SearchRequest(bbox=tuple(args.bbox), window_m=args.window_km * 1000,
                        min_valid_fraction=args.min_valid,
                        constraints=[Constraint.parse(c) for c in args.constraint])

    def progress(ev):
        if ev["stage"] == "tiles":
            print(f"  [{ev['tiles_done']}/{ev['tiles_total']}] {ev['tile']}: {ev['status']}")
        elif ev["stage"] == "plan":
            print(f"Searching {ev['tiles_total']} tiles...")

    result = run_search(req, progress=progress)
    path = write_result(result, args.out)
    cov, f = result["coverage"], result["filters"]
    print("\n" + cov["statement"])
    print(f"Windows described: {len(result['windows'])}; insufficient data: "
          f"{len(f['insufficient_data'])}; passing filters: {len(f['passed'])} (unranked)")
    print(f"Cache: {result['cache']}; elapsed {result['elapsed_s']} s")
    print(f"Result: {path}")

    if args.plan_downloads:
        missing = [Tile.from_id(t["tile"]) for t in result["tiles"] if t["status"] == "no_local_data"]
        if missing:
            print(f"\nQuerying NASA's catalogue for {len(missing)} missing tiles (no download)...")
            plan = plan_downloads(missing)
            print(f"  available: {len(plan['available'])} granules, ~{plan['total_mb']} MB total")
            print(f"  not in catalogue (likely ocean): {', '.join(plan['not_in_catalogue']) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
