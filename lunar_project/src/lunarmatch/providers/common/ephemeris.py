"""D_EPHEM – Sun position for the Moon and for Earth (never interchangeable).

Earth: NOAA solar-position equations (Meeus-based; ~0.01° accuracy for
1800–2100), pure numpy, no downloads.  Elevation is geometric (no refraction)
unless ``refraction=True``.

Moon: requires ``skyfield`` and NAIF kernels (downloaded once by skyfield's
loader into ``data/raw/common/D_EPHEM``): ``de421.bsp``, ``moon_080317.tf``,
``pck00008.tpc``, ``moon_pa_de421_1900-2050.bpc``.  The site is placed in the
``MOON_ME_DE421`` frame – the same frame as the PGDA LOLA products.

Also provides :func:`find_earth_times` to search an Earth date window for
times when the Sun's elevation/azimuth at a field site matches a lunar
landing illumination (input for EXP_SHADOW / F_SUN).
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

import numpy as np

from ...core.aoi import AOI
from ...core.base import CoverageReport, DataProvider, DatasetInfo, FetchResult
from ...core.bodies import Body
from ...core.evidence import AccessMode, Evidence


def _julian_day(dt: datetime) -> float:
    if dt.tzinfo is None:
        raise ValueError("datetime must be timezone-aware (use UTC)")
    dt = dt.astimezone(timezone.utc)
    return dt.timestamp() / 86400.0 + 2440587.5


def earth_sun_position(lat: float, lon: float, when: datetime, refraction: bool = False) -> dict:
    """Solar elevation/azimuth (deg, azimuth clockwise from true north) – NOAA algorithm."""
    jd = _julian_day(when)
    jc = (jd - 2451545.0) / 36525.0
    l0 = (280.46646 + jc * (36000.76983 + jc * 0.0003032)) % 360.0
    m = 357.52911 + jc * (35999.05029 - 0.0001537 * jc)
    ecc = 0.016708634 - jc * (0.000042037 + 0.0000001267 * jc)
    mr = math.radians(m)
    c = (math.sin(mr) * (1.914602 - jc * (0.004817 + 0.000014 * jc))
         + math.sin(2 * mr) * (0.019993 - 0.000101 * jc) + math.sin(3 * mr) * 0.000289)
    omega = math.radians(125.04 - 1934.136 * jc)
    app_long = l0 + c - 0.00569 - 0.00478 * math.sin(omega)
    mean_obliq = 23.0 + (26.0 + (21.448 - jc * (46.815 + jc * (0.00059 - jc * 0.001813))) / 60.0) / 60.0
    obliq = mean_obliq + 0.00256 * math.cos(omega)
    decl = math.asin(math.sin(math.radians(obliq)) * math.sin(math.radians(app_long)))
    y = math.tan(math.radians(obliq / 2.0)) ** 2
    l0r = math.radians(l0)
    eq_time = 4.0 * math.degrees(y * math.sin(2 * l0r) - 2 * ecc * math.sin(mr)
                                 + 4 * ecc * y * math.sin(mr) * math.cos(2 * l0r)
                                 - 0.5 * y * y * math.sin(4 * l0r) - 1.25 * ecc * ecc * math.sin(2 * mr))
    utc = when.astimezone(timezone.utc)
    minutes = utc.hour * 60 + utc.minute + utc.second / 60.0 + utc.microsecond / 6e7
    tst = (minutes + eq_time + 4.0 * lon) % 1440.0
    ha = tst / 4.0 + 180.0 if tst / 4.0 < 0 else tst / 4.0 - 180.0
    latr, har = math.radians(lat), math.radians(ha)
    cos_zen = math.sin(latr) * math.sin(decl) + math.cos(latr) * math.cos(decl) * math.cos(har)
    zen = math.acos(max(-1.0, min(1.0, cos_zen)))
    denom = math.cos(latr) * math.sin(zen)
    if abs(denom) < 1e-12:
        az = 180.0 if lat > math.degrees(decl) else 0.0
    else:
        a = math.degrees(math.acos(max(-1.0, min(1.0, (math.sin(latr) * math.cos(zen) - math.sin(decl)) / denom))))
        az = (a + 180.0) % 360.0 if ha > 0 else (540.0 - a) % 360.0
    elev = 90.0 - math.degrees(zen)
    if refraction:
        elev += _refraction_deg(elev)
    return {"elevation_deg": elev, "azimuth_deg": az, "declination_deg": math.degrees(decl),
            "equation_of_time_min": eq_time, "body": "earth", "method": "NOAA", "utc": utc.isoformat()}


def _refraction_deg(e: float) -> float:
    if e > 85:
        return 0.0
    te = math.tan(math.radians(e))
    if e > 5:
        r = 58.1 / te - 0.07 / te ** 3 + 0.000086 / te ** 5
    elif e > -0.575:
        r = 1735 + e * (-518.2 + e * (103.4 + e * (-12.79 + e * 0.711)))
    else:
        r = -20.772 / te
    return r / 3600.0


_SKY = {}


def moon_sun_position(lat: float, lon: float, when: datetime, kernel_dir: Optional[str] = None) -> dict:
    """Solar elevation/azimuth at a lunar surface point (MOON_ME_DE421 frame) using skyfield."""
    try:
        from skyfield.api import Loader, PlanetaryConstants
    except ImportError as exc:  # pragma: no cover
        raise ImportError("Lunar sun geometry needs skyfield: pip install skyfield") from exc
    if not _SKY:
        from ...core.storage import DataStore

        load = Loader(kernel_dir or str(DataStore().raw_dir("common", "D_EPHEM")))
        eph = load("de421.bsp")
        pc = PlanetaryConstants()
        pc.read_text(load("moon_080317.tf"))
        pc.read_text(load("pck00008.tpc"))
        pc.read_binary(load("moon_pa_de421_1900-2050.bpc"))
        _SKY.update(ts=load.timescale(), eph=eph, pc=pc, frame=pc.build_frame_named("MOON_ME_DE421"))
    ts, eph, pc, frame = _SKY["ts"], _SKY["eph"], _SKY["pc"], _SKY["frame"]
    t = ts.from_datetime(when.astimezone(timezone.utc))
    site = eph["moon"] + pc.build_latlon_degrees(frame, lat, lon)
    alt, az, dist = site.at(t).observe(eph["sun"]).apparent().altaz()
    return {"elevation_deg": alt.degrees, "azimuth_deg": az.degrees, "sun_distance_au": dist.au,
            "body": "moon", "method": "skyfield DE421 + MOON_ME_DE421", "utc": when.astimezone(timezone.utc).isoformat()}


def find_earth_times(lat: float, lon: float, target_elev: float, target_az: Optional[float],
                     start: datetime, end: datetime, step_min: int = 10, elev_tol: float = 1.0,
                     az_tol: float = 10.0) -> list[dict]:
    """All times in [start, end) where the Earth Sun matches the target geometry within tolerances."""
    out, t = [], start
    while t < end:
        p = earth_sun_position(lat, lon, t)
        de = abs(p["elevation_deg"] - target_elev)
        da = 0.0 if target_az is None else abs((p["azimuth_deg"] - target_az + 180) % 360 - 180)
        if de <= elev_tol and da <= az_tol:
            out.append({**p, "d_elev": de, "d_az": da})
        t += timedelta(minutes=step_min)
    return out


class EphemerisProvider(DataProvider):
    info = DatasetInfo(
        dataset_id="D_EPHEM", name="Solar ephemeris / sun geometry", body="Both", provider="Computed",
        resolution="time/geolocation based", evidence=Evidence.CALCULATED, access=AccessMode.COMPUTED,
        access_notes="Earth: NOAA equations (no download). Moon: skyfield + NAIF DE421 kernels (auto-download once).",
        endpoints=("https://naif.jpl.nasa.gov/pub/naif/generic_kernels/",),
        workbook_source_url="https://www.nasa.gov/reference/moonbase-environment/",
        known_limits="Body, datetime (UTC) and frame must be explicit; Moon and Earth not interchangeable.",
    )

    def check_coverage(self, aoi: AOI) -> CoverageReport:
        return CoverageReport(self.info.dataset_id, True, "computed for any location/time")

    def fetch(self, aoi: AOI, times: Iterable[datetime] = (), **kw) -> FetchResult:
        fn = moon_sun_position if aoi.body is Body.MOON else earth_sun_position
        rows = [fn(aoi.lat, aoi.lon, t) for t in times]
        for r in rows:
            r["evidence"] = Evidence.CALCULATED.value
        res = FetchResult(self.info.dataset_id, aoi)
        res.tables["sun"] = rows
        return res
