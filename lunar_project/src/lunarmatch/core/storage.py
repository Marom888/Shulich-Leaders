"""Local storage layout and metadata sidecars.

Layout (relative to the project root, configurable with LUNARMATCH_DATA):

    data/
      raw/<body>/<dataset_id>/...        original bytes as downloaded (or exact
                                         byte-for-byte windows of them)
      processed/<body>/<dataset_id>/...  derived, aligned or converted products
      manifest.jsonl                     append-only log of every file written

Every data file gets a ``<file>.meta.json`` sidecar with dataset name, source
URL, product date, CRS, resolution, units, evidence type, download timestamp
and raw/processed paths.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]  # .../lunar_project


def _default_root() -> Path:
    env = os.environ.get("LUNARMATCH_DATA")
    return Path(env) if env else PROJECT_ROOT / "data"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class DataStore:
    def __init__(self, root: Optional[os.PathLike] = None):
        self.root = Path(root) if root else _default_root()

    def raw_dir(self, body: str, dataset_id: str, *sub: str) -> Path:
        p = self.root.joinpath("raw", body, dataset_id, *sub)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def processed_dir(self, body: str, dataset_id: str, *sub: str) -> Path:
        p = self.root.joinpath("processed", body, dataset_id, *sub)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @staticmethod
    def meta_path(data_path: os.PathLike) -> Path:
        data_path = Path(data_path)
        return data_path.with_name(data_path.name + ".meta.json")

    def write_metadata(self, data_path: os.PathLike, meta: dict[str, Any]) -> Path:
        meta = dict(meta)
        meta.setdefault("written_utc", utc_now_iso())
        meta.setdefault("file", str(Path(data_path)))
        mp = self.meta_path(data_path)
        mp.write_text(json.dumps(meta, indent=2, default=str))
        self.root.mkdir(parents=True, exist_ok=True)
        with open(self.root / "manifest.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(meta, default=str) + "\n")
        return mp

    def read_metadata(self, data_path: os.PathLike) -> Optional[dict[str, Any]]:
        mp = self.meta_path(data_path)
        if mp.exists():
            return json.loads(mp.read_text())
        return None

    def has(self, data_path: os.PathLike) -> bool:
        """True if the data file *and* its metadata sidecar exist (i.e. a completed fetch)."""
        p = Path(data_path)
        return p.exists() and self.meta_path(p).exists()
