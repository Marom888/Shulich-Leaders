"""D_NASADEM – NASADEM HGT 001 (1 arc-second, ~30 m), coverage 56°S–60°N.

Access paths (all verified 2026-11-15):
1. Microsoft Planetary Computer STAC, collection ``nasadem`` – one COG per
   1°x1° tile, asset ``elevation`` (no login; anonymous SAS token).  The AOI
   window is read with HTTP range requests.            -> default
2. NASA Earthdata / LP DAAC (CMR collection NASADEM_HGT v001, cloud hosted)
   – zipped HGT tiles, requires Earthdata login in ``~/.netrc``.  -> fallback
3. Local SRTM/NASADEM ``.hgt`` files (e.g. the repo's S24W070.hgt) –
   parsed with numpy, no GDAL needed.                  -> read_hgt()

Heights are metres above the EGM96 geoid; horizontal datum WGS84.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Optional

import numpy as np

from ...core import terrain
from ...core.aoi import AOI
from ...core.base import CoverageReport, DataProvider, DatasetInfo, FetchResult, NotCovered, ProductRef
from ...core.bodies import Body
from ...core.evidence import AccessMode, Evidence
from ...core.raster import Layer
from ...core.stac import PLANETARY_COMPUTER, PlanetaryComputerSigner
from ._stac_cog import choose_item, item_to_ref, layer_pixel_size_m, read_assets, stac_items

CMR_GRANULES = "https://cmr.earthdata.nasa.gov/search/granules.json"
HGT_RE = re.compile(r"([NS])(\d{2})([EW])(\d{3})", re.I)


def hgt_tile_origin(path) -> tuple[int, int]:
    """(lat, lon) of the lower-left corner encoded in an HGT file name."""
    m = HGT_RE.search(Path(path).name)
    if not m:
        raise ValueError(f"cannot parse tile name {path}")
    lat = int(m.group(2)) * (1 if m.group(1).upper() == "N" else -1)
    lon = int(m.group(4)) * (1 if m.group(3).upper() == "E" else -1)
    return lat, lon


def read_hgt(path, aoi: Optional[AOI] = None, dataset_id: str = "D_NASADEM") -> Layer:
    """Read an SRTM/NASADEM .hgt tile (big-endian int16; void = -32768).

    Samples are on whole-arc-second *grid points* (PixelIsPoint), so the
    pixel-corner transform is shifted by half a sample.  Memory-mapped: only
    the AOI rows are touched.
    """
    path = Path(path)
    size = path.stat().st_size
    n = int(round(math.sqrt(size / 2)))
    if n * n * 2 != size:
        raise ValueError(f"{path} is not a square int16 HGT file")
    lat0, lon0 = hgt_tile_origin(path)
    res = 1.0 / (n - 1)
    x0, y0 = lon0 - res / 2, lat0 + 1 + res / 2
    mm = np.memmap(path, dtype=">i2", mode="r", shape=(n, n))
    r0, r1, c0, c1 = 0, n, 0, n
    if aoi is not None:
        w, s, e, nn = aoi.geographic_bbox()
        if e < x0 or w > x0 + n * res or nn < y0 - n * res or s > y0:
            raise NotCovered(f"AOI outside tile {path.name}")
        c0, c1 = max(0, int(math.floor((w - x0) / res))), min(n, int(math.ceil((e - x0) / res)))
        r0, r1 = max(0, int(math.floor((y0 - nn) / res))), min(n, int(math.ceil((y0 - s) / res)))
    arr = np.array(mm[r0:r1, c0:c1], dtype="float64")
    arr[arr == -32768] = np.nan
    return Layer(name="elevation", data=arr, transform=(x0 + c0 * res, res, 0.0, y0 - r0 * res, 0.0, -res),
                 crs="EPSG:4326", units="m (EGM96)", evidence=Evidence.MEASURED_DERIVED, dataset_id=dataset_id,
                 description=f"HGT tile {path.name}", source_url=str(path), nodata_original=-32768)


class NASADEMProvider(DataProvider):
    info = DatasetInfo(
        dataset_id="D_NASADEM", name="NASADEM HGT 001", body="Earth", provider="NASA/USGS/JPL",
        resolution="1 arc-second (~30 m)", evidence=Evidence.MEASURED_DERIVED, access=AccessMode.AUTOMATED,
        access_notes="Planetary Computer COG (anonymous, range reads); Earthdata fallback via ~/.netrc; local .hgt.",
        endpoints=(PLANETARY_COMPUTER + "/collections/nasadem", CMR_GRANULES),
        workbook_source_url="https://developers.google.com/earth-engine/datasets/catalog/NASA_NASADEM_HGT_001",
        auth="none (PC) / Earthdata login (LP DAAC)",
        known_limits="Not footpad-scale (R07): 30 m cannot resolve lander-leg geometry; 56S-60N only.",
    )

    def check_coverage(self, aoi: AOI) -> CoverageReport:
        self.check_body(aoi, (Body.EARTH,))
        ok = -56.0 <= aoi.lat <= 60.0
        return CoverageReport(self.info.dataset_id, ok, "inside NASADEM 56S-60N" if ok else "outside 56S-60N")

    def search(self, aoi: AOI, **kw) -> list[ProductRef]:
        return [item_to_ref(i) for i in stac_items(self, PLANETARY_COMPUTER, "nasadem", aoi)]

    def search_earthdata(self, aoi: AOI) -> list[ProductRef]:
        w, s, e, n = aoi.geographic_bbox()
        j = self.http.get_json(CMR_GRANULES, params={"short_name": "NASADEM_HGT", "version": "001",
                                                     "bounding_box": f"{w},{s},{e},{n}", "page_size": 50})
        out = []
        for g in j.get("feed", {}).get("entry", []):
            links = {l.get("title", l["href"]): l["href"] for l in g.get("links", [])
                     if l.get("rel", "").endswith("/data#") and l["href"].startswith("https")}
            out.append(ProductRef(product_id=g.get("producer_granule_id") or g.get("title"), urls=links,
                                  datetime=g.get("time_start")))
        return out

    def fetch(self, aoi: AOI, source: str = "planetary_computer", local_hgt: Optional[str] = None,
              derive: bool = True, **kw) -> FetchResult:
        self.check_body(aoi, (Body.EARTH,))
        res = FetchResult(self.info.dataset_id, aoi, metadata={"source": source})
        if local_hgt:
            dem = read_hgt(local_hgt, aoi)
            res.layers.add(dem)
            res.metadata["source"] = f"local file {local_hgt}"
        elif source == "earthdata":
            refs = self.search_earthdata(aoi)
            if not refs:
                raise NotCovered("no NASADEM granule in CMR for this AOI")
            import zipfile

            ref = refs[0]
            url = next(iter(ref.urls.values()))
            dest = self.store.raw_dir("earth", self.info.dataset_id) / url.rsplit("/", 1)[-1]
            self.http.download(url, dest)  # Earthdata credentials come from ~/.netrc
            with zipfile.ZipFile(dest) as z:
                name = next(n for n in z.namelist() if n.lower().endswith(".hgt"))
                out = dest.with_suffix("")
                out.mkdir(exist_ok=True)
                z.extract(name, out)
            dem = read_hgt(out / name, aoi)
            res.layers.add(dem)
            res.files.append(str(dest))
        else:
            items = stac_items(self, PLANETARY_COMPUTER, "nasadem", aoi)
            item, full = choose_item(items, aoi)
            if not full:
                res.warn("AOI crosses a 1-degree tile boundary; only the first tile was read (mosaic not implemented)")
            signer = PlanetaryComputerSigner(self.http)
            read_assets(self, res, item, aoi, {"elevation": ("elevation", "m (EGM96)", Evidence.MEASURED_DERIVED,
                                                             1.0, "NASADEM elevation")},
                        sign=lambda h: signer.sign(h, "nasadem"))
        if derive and "elevation" in res.layers:
            dem = res.layers["elevation"]
            dx, dy = layer_pixel_size_m(dem, aoi.lat)
            res.layers.add(Layer("slope_derived", terrain.slope_horn(dem.data, dx, dy), dem.transform, dem.crs,
                                 "deg", Evidence.DERIVED_HERE, self.info.dataset_id,
                                 f"Horn slope at native ~{dx:.0f}x{dy:.0f} m support (NOT leg scale)"))
            res.metadata["pixel_size_m"] = [dx, dy]
        return res
