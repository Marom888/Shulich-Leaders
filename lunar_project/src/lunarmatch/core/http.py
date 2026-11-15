"""HTTP utilities: retries, timeouts, range reads, resumable downloads.

* A single :class:`HttpClient` per process keeps a pooled ``requests.Session``.
* Retries with exponential back-off on connection errors and 429/5xx.
* ``download()`` streams to ``<dest>.part`` and resumes with an HTTP Range
  request if a partial file exists; the final file is renamed atomically.
* ``read_range()`` fetches an exact byte range (used for windowed reads of
  remote GeoTIFFs without downloading the whole file).
* NASA Earthdata: credentials are read once from ``~/.netrc``
  (``machine urs.earthdata.nasa.gov login ... password ...``) and kept on
  redirects to the Earthdata login host, so the user is never prompted again.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = (15, 120)  # (connect, read) seconds
USER_AGENT = "LunarMatch-data-pipeline/0.1 (+https://github.com/Marom888/Shulich-Leaders)"
EARTHDATA_HOST = "urs.earthdata.nasa.gov"


class DownloadError(RuntimeError):
    pass


class _EarthdataSession(requests.Session):
    """Keep Authorization header when redirected to/from the Earthdata login host."""

    def rebuild_auth(self, prepared_request, response):  # noqa: D401
        headers = prepared_request.headers
        url = prepared_request.url
        if "Authorization" in headers:
            original = urlparse(response.request.url).hostname
            redirect = urlparse(url).hostname
            if original != redirect and redirect != EARTHDATA_HOST and original != EARTHDATA_HOST:
                del headers["Authorization"]


def _progress(prefix: str):
    """Return a callable(done_bytes, total_bytes) that renders progress."""
    try:
        from tqdm import tqdm  # type: ignore

        bar = {"obj": None}

        def update(done, total):
            if bar["obj"] is None:
                bar["obj"] = tqdm(total=total or None, initial=done, unit="B", unit_scale=True, desc=prefix)
            else:
                bar["obj"].update(done - bar["obj"].n)

        def close():
            if bar["obj"] is not None:
                bar["obj"].close()

        update.close = close  # type: ignore[attr-defined]
        return update
    except ImportError:
        state = {"last": 0.0}

        def update(done, total):
            now = time.time()
            if now - state["last"] < 0.5 and done != total:
                return
            state["last"] = now
            if total:
                sys.stderr.write(f"\r{prefix}: {done / 1e6:8.1f} / {total / 1e6:.1f} MB ({100 * done / total:5.1f}%)")
            else:
                sys.stderr.write(f"\r{prefix}: {done / 1e6:8.1f} MB")
            sys.stderr.flush()

        def close():
            sys.stderr.write("\n")

        update.close = close  # type: ignore[attr-defined]
        return update


class HttpClient:
    def __init__(self, retries: int = 5, backoff: float = 1.0, timeout=DEFAULT_TIMEOUT):
        self.timeout = timeout
        self.session = _EarthdataSession()
        self.session.headers["User-Agent"] = USER_AGENT
        retry = Retry(
            total=retries,
            connect=retries,
            read=retries,
            status=retries,
            backoff_factor=backoff,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET", "HEAD", "POST"]),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    # ------------------------------------------------------------------ simple
    def get(self, url, **kw) -> requests.Response:
        kw.setdefault("timeout", self.timeout)
        r = self.session.get(url, **kw)
        r.raise_for_status()
        return r

    def get_json(self, url, params=None, **kw):
        return self.get(url, params=params, **kw).json()

    def post_json(self, url, payload, **kw):
        kw.setdefault("timeout", self.timeout)
        r = self.session.post(url, json=payload, **kw)
        r.raise_for_status()
        return r.json()

    def head(self, url, **kw) -> requests.Response:
        kw.setdefault("timeout", self.timeout)
        kw.setdefault("allow_redirects", True)
        r = self.session.head(url, **kw)
        r.raise_for_status()
        return r

    def remote_size(self, url) -> Optional[int]:
        try:
            r = self.head(url)
            n = r.headers.get("Content-Length")
            return int(n) if n is not None else None
        except requests.RequestException:
            return None

    # ------------------------------------------------------------------ ranges
    def read_range(self, url: str, start: int, end_inclusive: int) -> bytes:
        """Fetch bytes [start, end_inclusive]. Requires server Range support (HTTP 206)."""
        if end_inclusive < start:
            return b""
        headers = {"Range": f"bytes={start}-{end_inclusive}"}
        r = self.session.get(url, headers=headers, timeout=self.timeout)
        r.raise_for_status()
        expected = end_inclusive - start + 1
        if r.status_code != 206:
            # Server ignored Range: refuse silently consuming a full file.
            raise DownloadError(f"server did not honour Range request for {url} (HTTP {r.status_code})")
        data = r.content
        if len(data) != expected:
            raise DownloadError(f"short range read from {url}: got {len(data)} of {expected} bytes")
        return data

    # ------------------------------------------------------------------ download
    def download(self, url: str, dest: os.PathLike, *, expected_size: Optional[int] = None,
                 chunk: int = 1 << 20, progress: bool = True, overwrite: bool = False,
                 max_resume_attempts: int = 5) -> Path:
        """Stream ``url`` to ``dest`` with resume support. Returns the final path.

        If ``dest`` already exists (and matches ``expected_size`` when given)
        it is reused without any network request.
        """
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and not overwrite:
            if expected_size is None or dest.stat().st_size == expected_size:
                log.info("reusing cached file %s", dest)
                return dest
            log.warning("cached file %s has wrong size; re-downloading", dest)
            dest.unlink()

        part = dest.with_name(dest.name + ".part")
        bar = _progress(dest.name) if progress else None
        attempts = 0
        try:
            while True:
                have = part.stat().st_size if part.exists() else 0
                headers = {"Range": f"bytes={have}-"} if have else {}
                try:
                    with self.session.get(url, headers=headers, stream=True, timeout=self.timeout) as r:
                        if r.status_code == 416:  # already complete
                            break
                        r.raise_for_status()
                        if have and r.status_code != 206:
                            log.warning("server ignored resume request; restarting %s", url)
                            have = 0
                            part.unlink(missing_ok=True)
                        total = expected_size
                        if total is None:
                            cr = r.headers.get("Content-Range")
                            if cr and "/" in cr and not cr.endswith("*"):
                                total = int(cr.rsplit("/", 1)[1])
                            elif r.headers.get("Content-Length"):
                                total = have + int(r.headers["Content-Length"])
                        mode = "ab" if have else "wb"
                        done = have
                        with open(part, mode) as fh:
                            for block in r.iter_content(chunk_size=chunk):
                                if block:
                                    fh.write(block)
                                    done += len(block)
                                    if bar:
                                        bar(done, total)
                        if total is not None and done < total:
                            raise DownloadError(f"connection closed early ({done}/{total} bytes)")
                    break
                except (requests.ConnectionError, requests.Timeout, DownloadError) as exc:
                    attempts += 1
                    if attempts > max_resume_attempts:
                        raise DownloadError(f"download failed after {attempts} attempts: {url}: {exc}") from exc
                    wait = min(60, 2 ** attempts)
                    log.warning("download interrupted (%s); resuming in %ss", exc, wait)
                    time.sleep(wait)
        finally:
            if bar:
                bar.close()  # type: ignore[attr-defined]

        if expected_size is not None and part.stat().st_size != expected_size:
            raise DownloadError(f"size mismatch for {url}: {part.stat().st_size} != {expected_size}")
        os.replace(part, dest)
        return dest


_default_client: Optional[HttpClient] = None


def default_client() -> HttpClient:
    global _default_client
    if _default_client is None:
        _default_client = HttpClient()
    return _default_client
