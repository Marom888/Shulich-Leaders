import math

import numpy as np
import pytest

from lunarmatch.core.aoi import AOI
from lunarmatch.core.bodies import Body
from lunarmatch.core.projections import polar_stereo_forward, polar_stereo_inverse, polar_stereo_scale_factor
from lunarmatch.providers.moon.lola import PGDA_SITES, LOLAProvider


def test_polar_stereo_roundtrip_south_and_north():
    lat = np.array([-89.9, -89.5, -88.0, -85.0])
    lon = np.array([0.0, 150.0, 222.5, 359.0])
    x, y = polar_stereo_forward(lat, lon, south=True)
    lat2, lon2 = polar_stereo_inverse(x, y, south=True)
    assert np.allclose(lat, lat2, atol=1e-10) and np.allclose(lon % 360, lon2, atol=1e-8)
    x, y = polar_stereo_forward(-lat, lon, south=False)
    lat2, lon2 = polar_stereo_inverse(x, y, south=False)
    assert np.allclose(-lat, lat2, atol=1e-10) and np.allclose(lon % 360, lon2, atol=1e-8)


def test_polar_stereo_radius_matches_spherical_formula():
    # rho = 2 R tan(colat/2); at -89.5 deg colat = 0.5 deg
    x, y = polar_stereo_forward(-89.5, 0.0, south=True)
    assert math.isclose(math.hypot(x, y), 2 * 1737400 * math.tan(math.radians(0.25)), rel_tol=1e-12)
    # PROJ south-polar convention: lon 0 -> +y, lon 90 -> +x
    assert x == pytest.approx(0.0, abs=1e-6) and y > 0
    x, y = polar_stereo_forward(-89.5, 90.0, south=True)
    assert x > 0 and y == pytest.approx(0.0, abs=1e-6)
    assert polar_stereo_scale_factor(-89.5) == pytest.approx(1.0000190, abs=1e-6)


def test_site01_center_is_connecting_ridge():
    s = next(s for s in PGDA_SITES if s.name == "Site01")
    lat, lon = s.center_latlon()
    # Site01 is centred at x=-11 km, y=-12 km -> ~89.46 S, ~222.5 E
    assert lat == pytest.approx(-89.463, abs=0.005)
    assert lon == pytest.approx(222.51, abs=0.05)


def test_user_example_point_not_covered_and_nearest_site_reported():
    p = LOLAProvider()
    aoi = AOI(Body.MOON, -89.5, 150.0, 1000, 1000)
    assert p.find_site(aoi) is None
    d, s = p.nearest_sites(aoi, 1)[0]
    assert s.name == "Site04" and 0 < d < 1500
    cov = p.check_coverage(aoi)
    assert cov.covered is False and "Site04" in cov.detail


def test_aoi_inside_site01():
    s = next(s for s in PGDA_SITES if s.name == "Site01")
    lat, lon = s.center_latlon()
    aoi = AOI(Body.MOON, lat, lon, 1000, 1000)
    assert LOLAProvider().find_site(aoi).name == "Site01"
    xmin, ymin, xmax, ymax = aoi.polar_stereo_box()
    assert xmax - xmin == pytest.approx(1000, rel=1e-4)


def test_geographic_bbox_near_pole_and_earth():
    near_pole = AOI(Body.MOON, -89.5, 150, 1000, 1000).geographic_bbox()
    assert near_pole[2] - near_pole[0] > 3.5  # 1 km spans ~3.9 deg of longitude at -89.5
    full = AOI(Body.MOON, -89.999, 0, 1000, 1000).geographic_bbox()
    assert full[0] == -180 and full[2] == 180 and full[1] == -90
    e = AOI(Body.EARTH, 31.0, 35.0, 1000, 1000).geographic_bbox()
    # 1 km ~ 0.009 deg of latitude, ~0.0105 deg of longitude at 31N
    assert e[3] - e[1] == pytest.approx(0.00902, abs=2e-4)
    assert e[2] - e[0] == pytest.approx(0.01051, abs=2e-4)
