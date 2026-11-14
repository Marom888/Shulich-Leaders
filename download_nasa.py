"""Download the Atacama SRTMGL1 test tile from NASA Earthdata.

Thin wrapper around lunarmatch.data.earthdata_client. Skips the NASA
request entirely when the tile archive already exists in nasa_data/.

Usage:
    python download_nasa.py            # download if missing
    python download_nasa.py --login    # only authenticate (stores netrc)
    python download_nasa.py --force    # re-download even if present
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lunarmatch.config import ATACAMA_BBOX, ATACAMA_TILE, DATA_DIR, SRTM_SHORT_NAME  # noqa: E402
from lunarmatch.data import earthdata_client as ed  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--login", action="store_true", help="authenticate only")
    ap.add_argument("--force", action="store_true", help="re-download")
    args = ap.parse_args()

    print("Download folder:", DATA_DIR)

    if args.login:
        ed.login(interactive=True)
        print("Earthdata login OK (credentials stored by earthaccess, not printed).")
        return 0

    archive = DATA_DIR / f"{ATACAMA_TILE}.{SRTM_SHORT_NAME}.hgt.zip"
    if archive.is_file() and not args.force:
        print(f"Already present, skipping NASA download: {archive}")
        return 0

    try:
        files = ed.download_srtm(ATACAMA_BBOX, dest=DATA_DIR, force=args.force)
    except ed.EarthdataAuthError as e:
        print("Authentication error:", e, file=sys.stderr)
        return 2
    except Exception as e:  # network / service errors
        print(f"NASA download failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print(f"Found {len(files)} file(s):")
    for f in files:
        print(" ", f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
