"""Place names for candidate locations — only when reliably determined.

Default: no network, no names (coordinates are shown). Optional: reverse
geocoding of the candidate-area centroid with OpenStreetMap Nominatim,
enabled explicitly (``python run_rookie.py --serve --geocode``). Results are
cached on disk, rate-limited to 1 request/s, use a generic User-Agent (no
personal data) and carry attribution. A name describes the centroid's
surroundings, never a verified test point.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from lunarmatch.config import OUTPUT_DIR

NOMINATIM = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "Rookie-lunar-analog-discovery/2.0 (hackathon prototype)"
ATTRIBUTION = "Place names © OpenStreetMap contributors (Nominatim reverse geocoding)"


def no_place(lat: float, lon: float) -> dict:
    return {"status": "not_determined", "country": None, "region": None, "label": None,
            "source": None, "coordinates": f"{lat:.4f}°, {lon:.4f}°"}


class NullGeocoder:
    enabled = False

    def place(self, lat: float, lon: float) -> dict:
        return no_place(lat, lon)


class NominatimGeocoder:
    """Reverse geocoding with cache; any failure falls back to coordinates only."""

    enabled = True

    def __init__(self, cache_path: Path = OUTPUT_DIR / "cache" / "geocode.json", fetch=None,
                 min_interval_s: float = 1.0):
        self.cache_path = Path(cache_path)
        self.cache = json.loads(self.cache_path.read_text(encoding="utf-8")) if self.cache_path.is_file() else {}
        self.fetch = fetch or self._http
        self.min_interval_s = min_interval_s
        self._last = 0.0
        self._lock = threading.Lock()

    def _http(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())

    def place(self, lat: float, lon: float) -> dict:
        key = f"{lat:.3f},{lon:.3f}"
        with self._lock:
            if key in self.cache:
                return self.cache[key]
            wait = self.min_interval_s - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
        q = urllib.parse.urlencode({"lat": f"{lat:.5f}", "lon": f"{lon:.5f}", "format": "jsonv2", "zoom": 8})
        try:
            data = self.fetch(f"{NOMINATIM}?{q}")
        except Exception:
            return no_place(lat, lon)                      # not cached: may succeed later
        addr = data.get("address") or {}
        country = addr.get("country")
        region = addr.get("state") or addr.get("region") or addr.get("province") or addr.get("county")
        if not country:
            out = no_place(lat, lon)
            out["status"] = "no_name_found"
        else:
            out = {"status": "reverse_geocoded", "country": country, "region": region,
                   "label": ", ".join(x for x in (region, country) if x),
                   "source": ATTRIBUTION, "coordinates": f"{lat:.4f}°, {lon:.4f}°",
                   "note": "Name of the area around the candidate centroid, not a verified test point."}
        with self._lock:
            self.cache[key] = out
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1), encoding="utf-8")
        return out
