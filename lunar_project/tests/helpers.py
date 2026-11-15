"""Test-only fixtures.  The arrays written here are synthetic *test fixtures*
(clearly not lunar data) used to check byte-level reading logic."""
import numpy as np
import tifffile


def write_pgda_like_tiff(path, data: np.ndarray, x0: float, y0: float, pixel: float = 5.0, tile=None):
    """Write a float32 GeoTIFF with the same tag layout as the PGDA LOLA files
    (uncompressed, rows-per-strip = 1, south polar stereographic GeoKeys, NaN nodata)."""
    geokeys = (1, 1, 0, 8,
               1024, 0, 1, 1,          # GTModelType = projected
               1025, 0, 1, 1,          # PixelIsArea
               1026, 34737, 8, 0,
               2048, 0, 1, 32767,
               2054, 0, 1, 9102,
               3072, 0, 1, 32767,
               3075, 0, 1, 15,         # polar stereographic
               3095, 34736, 1, 0)      # latitude of origin -> doubles[0]
    extratags = [
        (33550, "d", 3, (pixel, pixel, 0.0), False),
        (33922, "d", 6, (0.0, 0.0, 0.0, x0, y0, 0.0), False),
        (34735, "H", len(geokeys), geokeys, False),
        (34736, "d", 8, (-90.0, 0.0, 1.0, 0.0, 0.0, 1737400.0, 1737400.0, 0.0), False),
        (34737, "s", 0, "unnamed|", False),
        (42113, "s", 0, "nan", False),
    ]
    kw = {"tile": tile} if tile else {"rowsperstrip": 1}
    tifffile.imwrite(path, data.astype("<f4"), extratags=extratags, compression=None, **kw)
