"""Build and open Rookie, the guided lunar-testing app.

Usage:
    python run_rookie.py --serve           # Rookie 2.0 with the local engine: http://127.0.0.1:8765
    python run_rookie.py --v2              # build Rookie 2.0 static bundle only (outputs/rookie2)
    python run_rookie.py                   # build the original six-step app (outputs/rookie)
    python run_rookie.py --open            # build the original app and open it
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
    ap.add_argument("--v2", action="store_true", help="build the Rookie 2.0 bundle")
    ap.add_argument("--serve", action="store_true", help="build Rookie 2.0 and serve it with the local engine")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--geocode", action="store_true",
                    help="name candidate areas via OpenStreetMap Nominatim (sends centroid coordinates; off by default)")
    args = ap.parse_args()

    if args.v2 or args.serve:
        from rookie.v2.build import build as build_v2
        out = build_v2()
        print(f"Rookie 2.0 built: {out}")
        if not args.serve:
            return 0
        from rookie.v2.server import Engine, serve
        geocoder = None
        if args.geocode:
            from lunarmatch.geo_naming import NominatimGeocoder
            geocoder = NominatimGeocoder()
            print("Place names: OpenStreetMap Nominatim (candidate centroids are sent to nominatim.openstreetmap.org)")
        httpd = serve(args.port, Engine(geocoder=geocoder))
        url = f"http://127.0.0.1:{args.port}/"
        print(f"Rookie 2.0 engine running at {url}  (Ctrl+C to stop; localhost only)")
        if args.open:
            webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            httpd.shutdown()
        return 0

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
