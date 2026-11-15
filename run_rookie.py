"""Build and open Rookie, the guided lunar-testing app (static, offline).

Usage:
    python run_rookie.py            # build outputs/rookie/index.html
    python run_rookie.py --open     # build and open in the default browser
    python run_rookie.py --refresh-plots   # regenerate terrain plots first
"""
import argparse
import subprocess
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from lunarmatch.config import OUTPUT_DIR  # noqa: E402
from lunarmatch.knowledge.workbook import WorkbookError  # noqa: E402
from rookie.build import build, find_search_gif  # noqa: E402
from rookie.earth import PLOTS  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--open", action="store_true", help="open in the default browser")
    ap.add_argument("--refresh-plots", action="store_true", help="re-run visualize_terrain.py")
    args = ap.parse_args()

    missing = [f for _, f in PLOTS.values() if not (OUTPUT_DIR / f).is_file()]
    if args.refresh_plots or missing:
        print("Generating terrain plots (visualize_terrain.py)...")
        r = subprocess.run([sys.executable, str(ROOT / "visualize_terrain.py")])
        if r.returncode != 0:
            print("Terrain plots could not be generated; Rookie will show them as unavailable.")

    try:
        out = build()
    except WorkbookError as e:
        print(f"Cannot build Rookie: {e}", file=sys.stderr)
        return 1
    print(f"Rookie built: {out}")
    print(f"Search component preview: {out.parent / 'search_preview.html'}")
    gif = find_search_gif()
    if gif is None:
        print("Note: Rookie animation not found (assets/animations/rookie_search.gif).")
    elif gif.name != "rookie_search.gif":
        print(f"Note: using {gif.name}; consider renaming it to rookie_search.gif.")
    if args.open:
        webbrowser.open(out.as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
