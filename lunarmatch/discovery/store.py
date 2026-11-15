"""Descriptor cache and result serialization (local JSON, no database).

Cache entries are keyed by everything that determines the descriptors: the
source file's SHA-256, dataset, window size, quality threshold and the
descriptor algorithm version. Changing any of them is a cache miss.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lunarmatch.config import OUTPUT_DIR

DEFAULT_CACHE_DIR = OUTPUT_DIR / "cache" / "discovery"
RESULT_SCHEMA = "rookie-discovery-result/1"


def cache_key(**parts) -> str:
    blob = json.dumps(parts, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class DescriptorCache:
    def __init__(self, root: Path = DEFAULT_CACHE_DIR):
        self.root = Path(root)
        self.hits = 0
        self.misses = 0

    def _path(self, dataset: str, tile: str, key: str) -> Path:
        return self.root / dataset / tile / f"{key[:24]}.json"

    def get(self, dataset: str, tile: str, key: str):
        p = self._path(dataset, tile, key)
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            if data.get("key") == key:
                self.hits += 1
                return data["descriptors"]
        self.misses += 1
        return None

    def meta(self, dataset: str, tile: str, key: str):
        p = self._path(dataset, tile, key)
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            if data.get("key") == key:
                return data.get("meta")
        return None

    def put(self, dataset: str, tile: str, key: str, descriptors: list[dict], meta: dict) -> Path:
        p = self._path(dataset, tile, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"key": key, "meta": meta, "descriptors": descriptors},
                                  ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
        return p


def write_result(result: dict, path: Path) -> Path:
    if result.get("schema") != RESULT_SCHEMA:
        raise ValueError("not a discovery result")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def write_json(result: dict, path: Path) -> Path:
    """Write any discovery/comparison result that declares a schema."""
    if not str(result.get("schema", "")).startswith("rookie-"):
        raise ValueError("result has no rookie schema")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def read_result(path: Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != RESULT_SCHEMA:
        raise ValueError(f"unsupported discovery result schema: {data.get('schema')!r}")
    return data
