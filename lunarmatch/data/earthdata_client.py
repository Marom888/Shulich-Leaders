"""NASA Earthdata access: authentication, search, and cached download.

Credentials are never handled here directly. earthaccess reads them from
~/.netrc / ~/_netrc, from EARTHDATA_USERNAME / EARTHDATA_PASSWORD, or asks
interactively. Nothing in this module prints or stores secrets.
"""
from __future__ import annotations

from pathlib import Path

from lunarmatch.config import DATA_DIR, SRTM_SHORT_NAME, SRTM_VERSION


class EarthdataAuthError(RuntimeError):
    """Raised when no usable Earthdata credentials are available."""


def login(interactive: bool = True):
    """Authenticate with NASA Earthdata, reusing stored credentials.

    Tries the netrc file and environment variables first. If neither works
    and ``interactive`` is True, prompts for username/password and persists
    them to the user's netrc file (outside the repository).
    """
    import earthaccess

    for strategy in ("netrc", "environment"):
        try:
            auth = earthaccess.login(strategy=strategy)
        except Exception:
            auth = None
        if auth is not None and getattr(auth, "authenticated", False):
            return auth

    if not interactive:
        raise EarthdataAuthError(
            "No Earthdata credentials found. Run "
            "`python download_nasa.py --login` once in a terminal, or set "
            "EARTHDATA_USERNAME and EARTHDATA_PASSWORD."
        )

    auth = earthaccess.login(strategy="interactive", persist=True)
    if auth is None or not getattr(auth, "authenticated", False):
        raise EarthdataAuthError("Interactive Earthdata login failed.")
    return auth


def search_srtm(bbox, count: int = 10):
    """Search SRTMGL1 v003 granules intersecting ``bbox`` (W, S, E, N)."""
    import earthaccess

    return earthaccess.search_data(
        short_name=SRTM_SHORT_NAME,
        version=SRTM_VERSION,
        bounding_box=tuple(bbox),
        count=count,
    )


def granule_filename(granule) -> str:
    """File name of a granule's first data link (e.g. S24W070.SRTMGL1.hgt.zip)."""
    links = granule.data_links()
    if not links:
        raise ValueError("Granule has no data links.")
    return links[0].rstrip("/").split("/")[-1]


def download_srtm(
    bbox,
    dest: Path = DATA_DIR,
    count: int = 10,
    interactive: bool = True,
    force: bool = False,
) -> list[Path]:
    """Return local SRTM archives for ``bbox``, downloading only missing ones.

    The NASA search requires authentication, so if the bounding box is the
    known Atacama tile and it is already on disk, call
    :func:`find_local_tile` first to avoid any network access.
    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)

    login(interactive=interactive)
    results = search_srtm(bbox, count=count)
    if not results:
        raise FileNotFoundError(f"No {SRTM_SHORT_NAME} granules found for bbox {bbox}.")

    local, missing = [], []
    for g in results:
        path = dest / granule_filename(g)
        if path.exists() and not force:
            local.append(path)
        else:
            missing.append(g)

    if missing:
        import earthaccess

        files = earthaccess.download(missing, local_path=str(dest))
        failed = [f for f in files if isinstance(f, Exception)]
        if failed:
            raise RuntimeError(f"{len(failed)} download(s) failed: {failed[0]}")
        local.extend(Path(f) for f in files)
    return sorted(local)


def find_local_tile(tile: str, search_dirs: list[Path] | None = None) -> Path | None:
    """Locate an existing tile as ``<tile>.SRTMGL1.hgt.zip`` or ``<tile>.hgt``.

    Search order: the zip in nasa_data/, then any bare .hgt in nasa_data/
    (recursively), then any bare .hgt under the project root.
    """
    from lunarmatch.config import PROJECT_ROOT

    dirs = search_dirs or [DATA_DIR, PROJECT_ROOT]
    for d in dirs:
        z = Path(d) / f"{tile}.{SRTM_SHORT_NAME}.hgt.zip"
        if z.is_file():
            return z
    for d in dirs:
        d = Path(d)
        if not d.is_dir():
            continue
        for p in sorted(d.rglob(f"{tile}.hgt")):
            if p.is_file() and ".venv" not in p.parts:
                return p
    return None
