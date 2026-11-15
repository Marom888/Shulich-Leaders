"""GDAL/rasterio configuration for remote (HTTP range) raster access.

Import this module before opening any remote raster. It does two things:

1. **CA bundle on non-ASCII paths (Windows).** rasterio points GDAL's curl at
   certifi's ``cacert.pem`` inside the virtual environment. When the project
   lives under a non-ASCII directory (for example a Hebrew folder name),
   curl receives that path in the ANSI code page, cannot open it, and every
   HTTPS read fails with a garbled ``UnicodeDecodeError``. We copy the
   bundle to an ASCII-only location (the system temp directory, or the
   Windows 8.3 short path when available) and point GDAL at the copy.

2. **Robust /vsicurl defaults.** Retries, timeouts, no directory listing on
   open, and a block cache. These are GDAL config options, not credentials.

Nothing here reads or prints secrets.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

_CONFIGURED = False

GDAL_HTTP_DEFAULTS = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.TIF,.tiff,.TIFF,.img,.IMG,.lbl,.LBL,.hgt,.zip,.vrt",
    "GDAL_HTTP_MAX_RETRY": "5",
    "GDAL_HTTP_RETRY_DELAY": "2",
    "GDAL_HTTP_TIMEOUT": "120",
    "GDAL_HTTP_CONNECTTIMEOUT": "30",
    "VSI_CACHE": "TRUE",
    "VSI_CACHE_SIZE": str(64 * 1024 * 1024),
    "GDAL_HTTP_MULTIRANGE": "YES",
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    # Larger chunks: fewer round trips on slow archives (PGDA ~3 s latency
    # per request). Costs at most one extra chunk per read on COGs.
    "CPL_VSIL_CURL_CHUNK_SIZE": str(1024 * 1024),
}


def _is_ascii(p: str) -> bool:
    try:
        p.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def _ascii_ca_bundle() -> str | None:
    try:
        import certifi
    except ImportError:  # pragma: no cover - certifi ships with requests
        return None
    src = certifi.where()
    if _is_ascii(src):
        return src
    if os.name == "nt":  # try the 8.3 short path first (no copy needed)
        try:
            import ctypes

            buf = ctypes.create_unicode_buffer(1024)
            if ctypes.windll.kernel32.GetShortPathNameW(src, buf, 1024) and _is_ascii(buf.value):
                return buf.value
        except Exception:
            pass
    tmp = tempfile.gettempdir()
    if not _is_ascii(tmp):
        return None
    dst = Path(tmp) / "lunarmatch_cacert.pem"
    if not dst.is_file() or dst.stat().st_size != Path(src).stat().st_size:
        shutil.copyfile(src, dst)
    return str(dst)


def configure() -> dict:
    """Apply the configuration once per process. Returns the applied options."""
    global _CONFIGURED
    applied = {}
    if _CONFIGURED:
        return applied
    bundle = _ascii_ca_bundle()
    if bundle:
        for key in ("GDAL_CURL_CA_BUNDLE", "CURL_CA_BUNDLE", "PROJ_CURL_CA_BUNDLE"):
            os.environ[key] = bundle
            applied[key] = bundle
    for key, val in GDAL_HTTP_DEFAULTS.items():
        if key not in os.environ:
            os.environ[key] = val
            applied[key] = val
    _CONFIGURED = True
    return applied


configure()
