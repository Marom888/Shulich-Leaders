"""Tile data sources. Discovery reads local files only; it never downloads.

``plan_downloads`` asks NASA's public catalogue (no login, no download) which
granules exist for missing tiles and their sizes, so a download can be
approved explicitly before it happens.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from lunarmatch.config import DATA_DIR, PROJECT_ROOT
from lunarmatch.discovery.grid import Tile


SKIP_DIRS = {".venv", "venv", ".git", "__pycache__", ".pytest_cache", "outputs", "node_modules"}
_TILE_FILE = re.compile(r"^([NS]\d{2}[EW]\d{3})(\.SRTMGL1\.hgt\.zip|\.hgt)$")


@dataclass
class LocalSRTMSource:
    """SRTMGL1 v003 tiles already on disk (.hgt or .SRTMGL1.hgt.zip).

    The search directories are scanned once (skipping virtual environments,
    git data and generated outputs). Zip archives take precedence over bare
    .hgt files, matching earthdata_client.find_local_tile.
    """

    search_dirs: list[Path] = field(default_factory=lambda: [DATA_DIR, PROJECT_ROOT])
    dataset: str = "SRTMGL1"
    label: str = "NASA SRTMGL1 v003 (local files)"
    _index: dict | None = field(default=None, repr=False)

    def index(self) -> dict[str, Path]:
        if self._index is None:
            found: dict[str, Path] = {}
            for d in self.search_dirs:
                d = Path(d)
                if not d.is_dir():
                    continue
                for root, dirs, files in os.walk(d):
                    dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
                    for f in sorted(files):
                        m = _TILE_FILE.match(f)
                        if not m:
                            continue
                        tid, p = m.group(1), Path(root) / f
                        prev = found.get(tid)
                        if prev is None or (p.suffix == ".zip" and prev.suffix != ".zip"):
                            found[tid] = p
            self._index = found
        return self._index

    def locate(self, tile: Tile) -> Path | None:
        return self.index().get(tile.id)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def plan_downloads(tiles: list[Tile], search=None) -> dict:
    """Granules available from NASA CMR for ``tiles`` (metadata only).

    ``search(bbox)`` defaults to the unauthenticated SRTMGL1 catalogue search.
    Returns names and sizes; the caller decides whether to download.
    """
    if search is None:
        from lunarmatch.data.earthdata_client import search_srtm

        def search(bbox):
            return search_srtm(bbox, count=1)

    found, missing, total_mb = [], [], 0.0
    for t in tiles:
        w, s, e, n = t.bounds
        results = search((w + 0.25, s + 0.25, e - 0.25, n - 0.25)) or []
        match = None
        for g in results:
            name = g.data_links()[0].rsplit("/", 1)[-1] if g.data_links() else ""
            if name.startswith(t.id):
                match = (name, float(g.size() or 0.0))
                break
        if match:
            found.append({"tile": t.id, "granule": match[0], "size_mb": round(match[1], 2)})
            total_mb += match[1]
        else:
            missing.append(t.id)
    return {"available": found, "not_in_catalogue": missing, "total_mb": round(total_mb, 1)}
