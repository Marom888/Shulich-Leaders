"""D_LOLA – LRO LOLA topography.

Primary product: NASA PGDA product 78, "High-Resolution LOLA Topography for
Lunar South Pole Sites" (Barker et al.), 5 m/pixel
https://pgda.gsfc.nasa.gov/products/78

Facts verified from the live file headers on 2026-11-15:
* Single-band float32, uncompressed, one row per strip (not a COG, no
  overviews), NoData = NaN, server answers HTTP Range requests with 206,
  no authentication.
* South polar stereographic, lat0 = -90, lon0 = 0, k = 1, sphere R = 1 737 400 m
  (MOON_ME frame, DE421).  PixelIsArea; the tiepoint is the upper-left corner.
* Per site the following layers exist (URL pattern
  ``https://pgda.gsfc.nasa.gov/data/LOLA_5mpp/<SITE>/<SITE>_final_adj_5mpp_<suffix>.tif``):

    surf    elevation (surface-interpolated)           m       MEASURED_DERIVED / INTERPOLATED
    slp     slope                                      deg     MEASURED_DERIVED
    ldec    number of LOLA spots in the pixel          count   MEASURED
    toterr  total RMS height uncertainty               m       MODELED (from 100 clones)
    slperr  RMS slope uncertainty                      deg     MODELED

  There is NO official roughness layer; roughness is computed here
  (DERIVED_HERE).

Because the files are uncompressed and striped, a window is fetched with a
single HTTP Range request (≈160 kB per layer for 1 km x 1 km), see
:mod:`lunarmatch.core.geotiff_lite`.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

from ...core.aoi import AOI
from ...core.base import (CoverageReport, DataProvider, DatasetInfo, FetchResult, NotCovered, ProductRef,
                          ProviderError)
from ...core.bodies import Body
from ...core.evidence import AccessMode, Evidence
from ...core.geotiff_lite import file_reader, http_reader, read_info, read_window
from ...core.ode import OdeClient
from ...core.projections import PROJ4_MOON_SOUTH_POLAR_STEREO, polar_stereo_inverse
from ...core.raster import Layer, LayerStack, write_geotiff
from ...core.storage import utc_now_iso
from ...core import terrain

PGDA_BASE = "https://pgda.gsfc.nasa.gov/data/LOLA_5mpp"
PGDA_PRODUCT_PAGE = "https://pgda.gsfc.nasa.gov/products/78"
PIXEL_M = 5.0


@dataclass(frozen=True)
class PgdaSite:
    name: str
    x0: float          # upper-left corner x (m)
    y0: float          # upper-left corner y (m)
    size_px: int       # square grids
    file_bytes: int    # size of the _surf.tif file
    last_modified: str
    description: str = ""

    @property
    def bounds(self):
        return (self.x0, self.y0 - PIXEL_M * self.size_px, self.x0 + PIXEL_M * self.size_px, self.y0)

    def contains(self, xmin, ymin, xmax, ymax) -> bool:
        bx0, by0, bx1, by1 = self.bounds
        return xmin >= bx0 and ymin >= by0 and xmax <= bx1 and ymax <= by1

    def center_latlon(self):
        bx0, by0, bx1, by1 = self.bounds
        lat, lon = polar_stereo_inverse((bx0 + bx1) / 2, (by0 + by1) / 2, south=True)
        return float(lat), float(lon)

    def url(self, suffix: str) -> str:
        return f"{PGDA_BASE}/{self.name}/{self.name}_final_adj_5mpp_{suffix}.tif"


# Read from the GeoTIFF headers of every *_surf.tif linked on the product page
# (ModelTiepoint, ImageWidth/Length, Content-Range total size, Last-Modified).
# Descriptions are those printed on the product page where it gives one.
PGDA_SITES: tuple[PgdaSite, ...] = (
    PgdaSite("Site01", -19000, -4000, 3200, 40980810, "2020-06-05", "Connecting ridge (Shackleton - de Gerlache)"),
    PgdaSite("Site04", -9000, 1000, 3200, 40980806, "2020-06-05", "Shackleton rim"),
    PgdaSite("Site06", 74000, 120000, 4000, 64025603, "2021-02-12", "Nobile rim 1"),
    PgdaSite("Site07", 22000, -12000, 3200, 40980808, "2020-06-05", "Peak near Shackleton"),
    PgdaSite("Site11", -45000, 23000, 3200, 40980806, "2020-06-05", "de Gerlache rim"),
    PgdaSite("Site20", 65000, 126000, 3200, 40980802, "2020-06-12", "Leibnitz beta plateau"),
    PgdaSite("Site20v2", 60000, 131000, 5200, 108192905, "2022-08-03", "Leibnitz beta plateau, extended boundaries"),
    PgdaSite("Site23", -11000, 132000, 4200, 70586804, "2020-06-12", "Malapert massif"),
    PgdaSite("Site42", -123400, -46100, 4000, 64025611, "2021-03-21"),
    PgdaSite("Haworth", -52900, 105400, 5960, 142123767, "2020-11-25", "Haworth"),
    PgdaSite("Shoemaker", 66000, 49000, 4000, 64025605, "2020-11-14", "Shoemaker"),
    PgdaSite("DM1", 154000, 71500, 4000, 64033681, "2021-04-16"),
    PgdaSite("DM2", 147000, 105000, 4000, 64025607, "2021-02-08"),
    PgdaSite("SL2", -58500, 33000, 4000, 64025605, "2021-04-03"),
    PgdaSite("SL3", -38700, 3900, 4000, 64025611, "2021-03-15"),
    PgdaSite("NPA", -98500, 39500, 4000, 64033687, "2021-05-22"),
    PgdaSite("NPB", 175000, 11500, 4000, 64033687, "2021-05-23"),
    PgdaSite("NPC", 122500, -89500, 4000, 64033691, "2021-06-14"),
    PgdaSite("NPD", 13000, 166000, 4000, 64033687, "2021-06-05"),
    PgdaSite("LM1", 2000, 18000, 4000, 64033673, "2021-04-16"),
    PgdaSite("LM2", 2000, 67000, 4000, 64033675, "2021-04-16"),
    PgdaSite("LM3", 4000, 57000, 4000, 64033679, "2021-04-18"),
    PgdaSite("LM4", 9000, 35000, 4000, 64033675, "2021-04-18"),
    PgdaSite("LM5", 30000, 21000, 4000, 64033679, "2021-05-01"),
    PgdaSite("LM6", 49000, 30000, 4000, 64033677, "2021-05-01"),
    PgdaSite("LM7", 54000, 10000, 4000, 64033675, "2021-05-01"),
    PgdaSite("LM8", 60000, 50000, 4000, 64033679, "2021-05-01"),
)

# public layer name -> (file suffix, units, evidence, description)
LAYERS = {
    "elevation": ("surf", "m", Evidence.MEASURED_DERIVED,
                  "LOLA surface-interpolated elevation (height above 1737.4 km sphere). Pixels with "
                  "measurement_density==0 are interpolated, not direct laser returns."),
    "slope": ("slp", "deg", Evidence.MEASURED_DERIVED, "Official PGDA slope map"),
    "measurement_density": ("ldec", "count", Evidence.MEASURED, "Number of LOLA spots in the 5 m pixel"),
    "elevation_uncertainty": ("toterr", "m", Evidence.MODELED, "Total RMS height error (from 100 statistical clones)"),
    "slope_uncertainty": ("slperr", "deg", Evidence.MODELED, "RMS slope error"),
}
DERIVED = {"roughness", "relief", "slope_derived", "measured_mask"}


class LOLAProvider(DataProvider):
    info = DatasetInfo(
        dataset_id="D_LOLA",
        name="LRO LOLA DEM – PGDA 5 m/px south-pole site mosaics",
        body="Moon", provider="NASA GSFC PGDA (Barker et al.)", resolution="5 m/px",
        evidence=Evidence.MEASURED_DERIVED, access=AccessMode.AUTOMATED,
        access_notes="Anonymous HTTPS; uncompressed striped GeoTIFF -> exact HTTP range-request windows. "
                     "Outside the 27 PGDA sites, use search_gdr() for global/polar LOLA GDR products via ODE.",
        endpoints=(PGDA_PRODUCT_PAGE, PGDA_BASE),
        workbook_source_url="https://pds-geosciences.wustl.edu/missions/lro/",
        known_limits="27 south-polar sites only; 5 m grid is interpolated between sparse LOLA tracks "
                     "(check measurement_density); no official roughness layer.",
    )

    # ---------------------------------------------------------------- coverage
    def find_site(self, aoi: AOI) -> Optional[PgdaSite]:
        self.check_body(aoi, (Body.MOON,))
        if aoi.lat > -80:
            return None
        box = aoi.polar_stereo_box()
        for s in PGDA_SITES:
            if s.contains(*box):
                return s
        return None

    def nearest_sites(self, aoi: AOI, n: int = 3):
        x, y = aoi.polar_stereo_center()
        out = []
        for s in PGDA_SITES:
            bx0, by0, bx1, by1 = s.bounds
            dx = max(bx0 - x, 0, x - bx1)
            dy = max(by0 - y, 0, y - by1)
            out.append((math.hypot(dx, dy), s))
        out.sort(key=lambda t: t[0])
        return out[:n]

    def check_coverage(self, aoi: AOI) -> CoverageReport:
        if aoi.body is not Body.MOON or aoi.lat > -80:
            return CoverageReport("D_LOLA", False, "PGDA 5 m products cover south-polar sites only; "
                                  "use search_gdr() for global LOLA GDR grids")
        s = self.find_site(aoi)
        if s:
            return CoverageReport("D_LOLA", True, f"fully inside PGDA {s.name} ({s.description})", [s.name])
        near = ", ".join(f"{s.name} ({d / 1000:.2f} km away)" for d, s in self.nearest_sites(aoi))
        return CoverageReport("D_LOLA", False, f"AOI not fully inside any PGDA site; nearest: {near}")

    def search(self, aoi: AOI, **kw) -> list[ProductRef]:
        s = self.find_site(aoi)
        if not s:
            return []
        return [ProductRef(product_id=s.name, title=s.description,
                           urls={k: s.url(v[0]) for k, v in LAYERS.items()},
                           bbox=s.bounds, properties={"crs": PROJ4_MOON_SOUTH_POLAR_STEREO, "pixel_m": PIXEL_M})]

    def search_gdr(self, aoi: AOI, pt: str = "GDRDEM", limit: int = 20) -> list[ProductRef]:
        """Global / polar LOLA gridded products (shape, slope, roughness maps) via ODE.

        pt: GDRDEM (shape), GDRDSM (slope), GDRDRM (roughness), GDRDEC (counts), SLDEM ...
        Whole-file downloads (no server-side subsetting).
        """
        b = aoi.geographic_bbox(lon_convention="360")
        prods = OdeClient(self.http).product_search(ihid="LRO", iid="LOLA", pt=pt, bbox_lon360=b, limit=limit)
        return [OdeClient.to_product_ref(p) for p in prods]

    # ---------------------------------------------------------------- fetch
    def fetch(self, aoi: AOI, layers=("elevation", "slope", "measurement_density", "elevation_uncertainty"),
              site: Optional[str] = None, mode: str = "window", roughness_window_m: float = 25.0,
              save: bool = True) -> FetchResult:
        """Retrieve the requested layers for ``aoi``.

        mode="window": HTTP range request for just the AOI rows/cols (default).
        mode="full":   download whole site files once (resumable), then read locally.
        Derived layers: "slope_derived" (Horn, from elevation), "roughness"
        (detrended RMS over ``roughness_window_m``), "relief", "measured_mask".
        """
        self.check_body(aoi, (Body.MOON,))
        layers = list(layers)
        unknown = set(layers) - set(LAYERS) - DERIVED
        if unknown:
            raise ProviderError(f"unknown layer(s) {unknown}; available: {sorted(LAYERS) + sorted(DERIVED)}")
        s = next((x for x in PGDA_SITES if x.name == site), None) if site else self.find_site(aoi)
        if s is None:
            raise NotCovered(self.check_coverage(aoi).detail)

        xmin, ymin, xmax, ymax = aoi.polar_stereo_box()
        bx0, by0, bx1, by1 = s.bounds
        col0 = int(math.floor((xmin - bx0) / PIXEL_M))
        col1 = int(math.ceil((xmax - bx0) / PIXEL_M))
        row0 = int(math.floor((by1 - ymax) / PIXEL_M))
        row1 = int(math.ceil((by1 - ymin) / PIXEL_M))
        col0, row0 = max(col0, 0), max(row0, 0)
        col1, row1 = min(col1, s.size_px), min(row1, s.size_px)
        transform = (bx0 + col0 * PIXEL_M, PIXEL_M, 0.0, by1 - row0 * PIXEL_M, 0.0, -PIXEL_M)

        res = FetchResult("D_LOLA", aoi)
        res.metadata.update({
            "site": s.name, "site_description": s.description, "product_page": PGDA_PRODUCT_PAGE,
            "window_rows": [row0, row1], "window_cols": [col0, col1], "crs": PROJ4_MOON_SOUTH_POLAR_STEREO,
            "pixel_m": PIXEL_M, "mode": mode, "reference_frame": "MOON_ME (DE421)",
            "product_last_modified": s.last_modified,
        })

        need_files = {n for n in layers if n in LAYERS}
        if {"slope_derived", "roughness", "relief"} & set(layers):
            need_files.add("elevation")
        if "measured_mask" in layers:
            need_files.add("measurement_density")

        raw_dir = self.store.raw_dir("moon", "D_LOLA", s.name)
        for lname in [n for n in LAYERS if n in need_files]:
            suffix, units, ev, desc = LAYERS[lname]
            url = s.url(suffix)
            tag = f"r{row0}-{row1}_c{col0}-{col1}"
            raw_path = raw_dir / (f"{s.name}_final_adj_5mpp_{suffix}__{tag}.tif" if mode == "window"
                                  else f"{s.name}_final_adj_5mpp_{suffix}.tif")
            if mode == "full":
                expected = s.file_bytes if suffix == "surf" else None
                self.http.download(url, raw_path, expected_size=expected)
                reader = file_reader(raw_path)
                info = read_info(reader)
                arr = read_window(reader, info, row0, row1, col0, col1)
            else:
                cached = self.store.has(raw_path)
                reader = file_reader(raw_path) if cached else http_reader(url, self.http)
                info = read_info(reader)
                if cached:
                    arr = read_window(reader, info, 0, info.height, 0, info.width)
                else:
                    arr = read_window(reader, info, row0, row1, col0, col1)
            # verify georeferencing of the file against the catalogue
            gt = info.geotransform
            if mode == "full" or not self.store.has(raw_path):
                if not (abs(gt[0] - bx0) < 1e-6 and abs(gt[3] - by1) < 1e-6 and abs(gt[1] - PIXEL_M) < 1e-9):
                    raise ProviderError(f"{url}: georeferencing {gt} differs from catalogue {s.bounds}")
            data = arr.astype("float64")
            if info.nodata is not None and not math.isnan(info.nodata):
                data[data == info.nodata] = np.nan
            lyr = Layer(name=lname, data=data, transform=transform, crs=PROJ4_MOON_SOUTH_POLAR_STEREO,
                        units=units, evidence=ev, dataset_id="D_LOLA", description=desc, source_url=url,
                        nodata_original=info.nodata)
            if save and mode == "window" and not self.store.has(raw_path):
                write_geotiff(lyr, raw_path, compress=False)
                self.store.write_metadata(raw_path, self._meta(lyr, s, raw_path, kind="raw window (unmodified pixel values)"))
            res.files.append(str(raw_path))
            if lname in layers:
                res.layers.add(lyr)
            else:
                res.metadata.setdefault("_helper_layers", {})[lname] = lyr

        helpers = res.metadata.pop("_helper_layers", {})
        elev = res.layers.get("elevation") or helpers.get("elevation")
        dens = res.layers.get("measurement_density") or helpers.get("measurement_density")
        if dens is not None:
            measured = np.isfinite(dens.data) & (dens.data > 0)
            frac = float(measured.mean())
            res.metadata["fraction_pixels_with_lola_shot"] = frac
            if elev is not None:
                elev.extra["fraction_pixels_with_lola_shot"] = frac
            if frac < 0.5:
                res.warn(f"only {100 * frac:.1f}% of pixels contain a LOLA spot; the rest of the 5 m "
                         "elevation grid is interpolated between tracks")
            if "measured_mask" in layers:
                res.layers.add(Layer("measured_mask", measured.astype("float64"), transform,
                                     PROJ4_MOON_SOUTH_POLAR_STEREO, "bool", Evidence.MEASURED, "D_LOLA",
                                     "1 where >=1 LOLA spot fell in the pixel, else 0"))
        if elev is not None:
            z = elev.data
            if "slope_derived" in layers:
                res.layers.add(Layer("slope_derived", terrain.slope_horn(z, PIXEL_M, PIXEL_M), transform,
                                     PROJ4_MOON_SOUTH_POLAR_STEREO, "deg", Evidence.DERIVED_HERE, "D_LOLA",
                                     "Horn 3x3 slope computed here from 'elevation' (edges NaN)"))
            n = terrain.window_px_for(roughness_window_m, PIXEL_M)
            if "roughness" in layers:
                res.layers.add(Layer("roughness", terrain.detrended_rms_roughness(z, n, PIXEL_M, PIXEL_M), transform,
                                     PROJ4_MOON_SOUTH_POLAR_STEREO, "m RMS", Evidence.DERIVED_HERE, "D_LOLA",
                                     f"Detrended RMS height residual, {n}x{n} px ({n * PIXEL_M:.0f} m) window. "
                                     "Not an official LOLA product.", extra={"window_m": n * PIXEL_M}))
            if "relief" in layers:
                res.layers.add(Layer("relief", terrain.local_relief(z, n), transform,
                                     PROJ4_MOON_SOUTH_POLAR_STEREO, "m", Evidence.DERIVED_HERE, "D_LOLA",
                                     f"max-min elevation in {n * PIXEL_M:.0f} m window", extra={"window_m": n * PIXEL_M}))
            if save:
                pdir = self.store.processed_dir("moon", "D_LOLA", s.name)
                for name in ("slope_derived", "roughness", "relief"):
                    if name in res.layers:
                        p = pdir / f"{s.name}_{name}__r{row0}-{row1}_c{col0}-{col1}.tif"
                        write_geotiff(res.layers[name], p)
                        self.store.write_metadata(p, self._meta(res.layers[name], s, p, kind="derived"))
                        res.files.append(str(p))

        res.metadata["corners_latlon"] = aoi.polar_stereo_corners_latlon()
        res.metadata["fetched_utc"] = utc_now_iso()
        return res

    def _meta(self, lyr: Layer, s: PgdaSite, path, kind: str) -> dict:
        return {
            "dataset_id": "D_LOLA", "dataset_name": self.info.name, "kind": kind,
            "site": s.name, "source_url": lyr.source_url or PGDA_PRODUCT_PAGE,
            "product_date": s.last_modified, "crs": lyr.crs, "resolution_m": PIXEL_M,
            "units": lyr.units, "evidence": lyr.evidence.value, "download_utc": utc_now_iso(),
            "path": str(path), "transform": list(lyr.transform), "shape": list(lyr.shape),
            "stats": lyr.stats(), "extra": json.loads(json.dumps(lyr.extra, default=str)),
        }


def get_lola_data(latitude: float, longitude: float, width_m: float, height_m: float,
                  layers=("elevation", "slope"), **kw) -> FetchResult:
    """Convenience wrapper matching the interface in the original task description."""
    return LOLAProvider().fetch(AOI(Body.MOON, latitude, longitude, width_m, height_m), layers=layers, **kw)
