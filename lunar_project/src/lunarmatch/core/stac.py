"""Minimal STAC API client (no pystac dependency) + Planetary Computer signing.

Endpoints verified live on 2026-11-15:
* Earth Search (Element 84, anonymous):  https://earth-search.aws.element84.com/v1
  collection ``sentinel-2-l2a`` – assets are public COGs on S3.
* Microsoft Planetary Computer:          https://planetarycomputer.microsoft.com/api/stac/v1
  collections ``nasadem``, ``3dep-seamless``, ``naip``, ``esa-worldcover``.
  Asset URLs are Azure blobs that need a short-lived SAS token, obtained
  anonymously from https://planetarycomputer.microsoft.com/api/sas/v1/token/<collection>.
"""
from __future__ import annotations

import time
from typing import Any, Iterator, Optional

from .http import HttpClient, default_client

EARTH_SEARCH = "https://earth-search.aws.element84.com/v1"
PLANETARY_COMPUTER = "https://planetarycomputer.microsoft.com/api/stac/v1"
PC_SAS_TOKEN = "https://planetarycomputer.microsoft.com/api/sas/v1/token/{collection}"


class PlanetaryComputerSigner:
    """Caches one SAS token per collection until shortly before expiry."""

    def __init__(self, client: Optional[HttpClient] = None):
        self.http = client or default_client()
        self._tokens: dict[str, tuple[str, float]] = {}

    def token(self, collection: str) -> str:
        tok, exp = self._tokens.get(collection, ("", 0.0))
        if time.time() < exp - 120:
            return tok
        j = self.http.get_json(PC_SAS_TOKEN.format(collection=collection))
        tok = j["token"]
        exp_s = j.get("msft:expiry", "")
        try:
            from datetime import datetime

            exp = datetime.fromisoformat(exp_s.replace("Z", "+00:00")).timestamp()
        except ValueError:
            exp = time.time() + 1800
        self._tokens[collection] = (tok, exp)
        return tok

    def sign(self, href: str, collection: str) -> str:
        if ".blob.core.windows.net" not in href:
            return href
        sep = "&" if "?" in href else "?"
        return f"{href}{sep}{self.token(collection)}"


class StacClient:
    def __init__(self, root: str, client: Optional[HttpClient] = None):
        self.root = root.rstrip("/")
        self.http = client or default_client()

    def search(self, collections: list[str], bbox: tuple[float, float, float, float], *,
               datetime: Optional[str] = None, query: Optional[dict] = None,
               sortby: Optional[list] = None, limit: int = 50, max_items: int = 200) -> Iterator[dict[str, Any]]:
        body: dict[str, Any] = {"collections": collections, "bbox": list(bbox), "limit": limit}
        if datetime:
            body["datetime"] = datetime
        if query:
            body["query"] = query
        if sortby:
            body["sortby"] = sortby
        url, method = f"{self.root}/search", "POST"
        n = 0
        while url:
            page = self.http.post_json(url, body) if method == "POST" else self.http.get_json(url)
            for feat in page.get("features", []):
                yield feat
                n += 1
                if n >= max_items:
                    return
            nxt = next((l for l in page.get("links", []) if l.get("rel") == "next"), None)
            if not nxt:
                return
            url = nxt["href"]
            method = nxt.get("method", "GET").upper()
            if method == "POST":
                body = nxt.get("body", body) if not nxt.get("merge") else {**body, **nxt.get("body", {})}
