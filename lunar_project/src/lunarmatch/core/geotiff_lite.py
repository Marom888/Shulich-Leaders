"""Minimal GeoTIFF reader with windowed reads over HTTP range requests.

Why this exists: the NASA PGDA 5 m/px LOLA products are *uncompressed*,
float32, one-row-per-strip GeoTIFFs (verified from the file headers).
For such files the byte offset of any pixel is known exactly, so a window
can be fetched with a single HTTP Range request – no GDAL needed and no
need to download the 41–142 MB files.

Supported: baseline little/big-endian TIFF, single band, uncompressed
(Compression=1), strips or tiles, integer/float sample formats, and the
GeoTIFF tags ModelPixelScale / ModelTiepoint / ModelTransformation,
GeoKeyDirectory (+ double/ascii params) and GDAL_NODATA / GDAL_METADATA.
Compressed files raise :class:`UnsupportedTiff` – use rasterio for those.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np

_TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 16: 8, 17: 8, 18: 8}
_TYPE_FMT = {1: "B", 3: "H", 4: "I", 6: "b", 8: "h", 9: "i", 11: "f", 12: "d", 16: "Q", 17: "q"}

TAG_IMAGE_WIDTH, TAG_IMAGE_LENGTH, TAG_BITS = 256, 257, 258
TAG_COMPRESSION, TAG_STRIP_OFFSETS, TAG_SPP = 259, 273, 277
TAG_ROWS_PER_STRIP, TAG_STRIP_BYTES, TAG_PLANAR = 278, 279, 284
TAG_TILE_W, TAG_TILE_H, TAG_TILE_OFFSETS, TAG_TILE_BYTES = 322, 323, 324, 325
TAG_SAMPLE_FORMAT = 339
TAG_PIXEL_SCALE, TAG_TIEPOINT, TAG_TRANSFORM = 33550, 33922, 34264
TAG_GEOKEYS, TAG_GEO_DOUBLES, TAG_GEO_ASCII = 34735, 34736, 34737
TAG_GDAL_METADATA, TAG_GDAL_NODATA = 42112, 42113


class UnsupportedTiff(ValueError):
    pass


ByteReader = Callable[[int, int], bytes]  # (offset, length) -> bytes


def file_reader(path) -> ByteReader:
    path = Path(path)

    def read(offset: int, length: int) -> bytes:
        with open(path, "rb") as fh:
            fh.seek(offset)
            return fh.read(length)

    return read


def http_reader(url: str, client=None) -> ByteReader:
    from .http import default_client

    c = client or default_client()

    def read(offset: int, length: int) -> bytes:
        return c.read_range(url, offset, offset + length - 1)

    return read


@dataclass
class TiffInfo:
    width: int
    height: int
    dtype: np.dtype
    compression: int
    tiled: bool
    block_w: int
    block_h: int
    offsets: np.ndarray
    byte_counts: np.ndarray
    pixel_scale: Optional[tuple] = None
    tiepoint: Optional[tuple] = None
    model_transform: Optional[tuple] = None
    geokeys: dict = field(default_factory=dict)
    geo_doubles: tuple = ()
    geo_ascii: str = ""
    nodata: Optional[float] = None
    gdal_metadata: str = ""

    @property
    def geotransform(self) -> tuple[float, float, float, float, float, float]:
        """GDAL-style (x0, dx, rot, y0, rot, dy) of the *pixel corner* grid."""
        if self.model_transform:
            m = self.model_transform
            return (m[3], m[0], m[1], m[7], m[4], m[5])
        if not (self.pixel_scale and self.tiepoint):
            raise UnsupportedTiff("file has no georeferencing tags")
        sx, sy = self.pixel_scale[0], self.pixel_scale[1]
        i, j, _, x, y, _ = self.tiepoint[:6]
        raster_is_point = self.geokeys.get(1025) == 2  # GTRasterTypeGeoKey = PixelIsPoint
        x0 = x - i * sx
        y0 = y + j * sy
        if raster_is_point:
            x0 -= sx / 2.0
            y0 += sy / 2.0
        return (x0, sx, 0.0, y0, 0.0, -sy)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        x0, dx, _, y0, _, dy = self.geotransform
        x1 = x0 + dx * self.width
        y1 = y0 + dy * self.height
        return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def _parse_ifd(read: ByteReader, prefetch: int = 65536) -> tuple[dict, str]:
    head = read(0, prefetch)
    if len(head) < 8:
        raise UnsupportedTiff("file too small")
    bo = {b"II": "<", b"MM": ">"}.get(head[:2])
    if bo is None:
        raise UnsupportedTiff("not a TIFF file")
    magic = struct.unpack(bo + "H", head[2:4])[0]
    if magic != 42:
        raise UnsupportedTiff("BigTIFF / unknown magic not supported")
    ifd = struct.unpack(bo + "I", head[4:8])[0]

    buf = {"data": head, "start": 0}

    def get(off: int, n: int) -> bytes:
        s = buf["start"]
        if off >= s and off + n <= s + len(buf["data"]):
            return buf["data"][off - s: off - s + n]
        return read(off, n)

    n_entries = struct.unpack(bo + "H", get(ifd, 2))[0]
    entries = get(ifd + 2, 12 * n_entries)
    tags: dict[int, object] = {}
    for k in range(n_entries):
        e = entries[12 * k: 12 * k + 12]
        tag, typ, cnt = struct.unpack(bo + "HHI", e[:8])
        size = _TYPE_SIZES.get(typ, 1) * cnt
        raw = e[8: 8 + size] if size <= 4 else get(struct.unpack(bo + "I", e[8:12])[0], size)
        if typ == 2:
            tags[tag] = raw.split(b"\x00")[0].decode("latin-1")
        elif typ in (5, 10):
            vals = struct.unpack(bo + ("I" if typ == 5 else "i") * (2 * cnt), raw)
            tags[tag] = tuple(vals[i] / vals[i + 1] for i in range(0, len(vals), 2))
        elif typ in _TYPE_FMT:
            tags[tag] = struct.unpack(bo + _TYPE_FMT[typ] * cnt, raw)
        else:
            tags[tag] = raw
    return tags, bo


def read_info(read: ByteReader) -> TiffInfo:
    tags, bo = _parse_ifd(read)

    def one(tag, default=None):
        v = tags.get(tag, default)
        return v[0] if isinstance(v, tuple) else v

    spp = one(TAG_SPP, 1)
    if spp != 1:
        raise UnsupportedTiff(f"only single-band TIFFs supported (SamplesPerPixel={spp})")
    bits = one(TAG_BITS, 1)
    fmt = one(TAG_SAMPLE_FORMAT, 1)
    kind = {1: "u", 2: "i", 3: "f"}.get(fmt)
    if kind is None:
        raise UnsupportedTiff(f"unsupported SampleFormat {fmt}")
    dtype = np.dtype(f"{bo}{kind}{bits // 8}")

    tiled = TAG_TILE_W in tags
    width, height = one(TAG_IMAGE_WIDTH), one(TAG_IMAGE_LENGTH)
    if tiled:
        bw, bh = one(TAG_TILE_W), one(TAG_TILE_H)
        offsets, counts = tags[TAG_TILE_OFFSETS], tags[TAG_TILE_BYTES]
    else:
        bw, bh = width, one(TAG_ROWS_PER_STRIP, height)
        offsets, counts = tags[TAG_STRIP_OFFSETS], tags[TAG_STRIP_BYTES]

    geokeys = {}
    gk = tags.get(TAG_GEOKEYS)
    if gk:
        for i in range(4, 4 + 4 * gk[3], 4):
            key, loc, cnt, val = gk[i: i + 4]
            geokeys[key] = val if loc == 0 else (loc, cnt, val)

    nodata = None
    if TAG_GDAL_NODATA in tags:
        try:
            nodata = float(str(tags[TAG_GDAL_NODATA]).strip())
        except ValueError:
            nodata = None

    return TiffInfo(
        width=width, height=height, dtype=dtype, compression=one(TAG_COMPRESSION, 1),
        tiled=tiled, block_w=bw, block_h=bh,
        offsets=np.asarray(offsets, dtype=np.int64), byte_counts=np.asarray(counts, dtype=np.int64),
        pixel_scale=tags.get(TAG_PIXEL_SCALE), tiepoint=tags.get(TAG_TIEPOINT),
        model_transform=tags.get(TAG_TRANSFORM), geokeys=geokeys,
        geo_doubles=tuple(tags.get(TAG_GEO_DOUBLES, ())), geo_ascii=str(tags.get(TAG_GEO_ASCII, "")),
        nodata=nodata, gdal_metadata=str(tags.get(TAG_GDAL_METADATA, "")),
    )


def _merge_ranges(ranges: list[tuple[int, int]], max_gap: int) -> list[tuple[int, int]]:
    """Merge (offset, length) ranges whose gap is <= max_gap bytes."""
    if not ranges:
        return []
    ranges = sorted(ranges)
    out = [list(ranges[0])]
    for off, ln in ranges[1:]:
        last = out[-1]
        if off <= last[0] + last[1] + max_gap:
            last[1] = max(last[1], off + ln - last[0])
        else:
            out.append([off, ln])
    return [tuple(r) for r in out]


def read_window(read: ByteReader, info: TiffInfo, row0: int, row1: int, col0: int, col1: int,
                max_gap: int = 1 << 20) -> np.ndarray:
    """Read rows [row0,row1) x cols [col0,col1) as a native-endian array.

    Byte ranges of neighbouring rows/blocks are merged (gaps up to
    ``max_gap`` bytes are over-read) so a window over a contiguous striped
    file costs a single HTTP request.
    """
    if info.compression != 1:
        raise UnsupportedTiff(f"compressed TIFF (Compression={info.compression}); use rasterio instead")
    row0, col0 = max(0, row0), max(0, col0)
    row1, col1 = min(info.height, row1), min(info.width, col1)
    if row1 <= row0 or col1 <= col0:
        raise ValueError("empty window after clipping to raster extent")
    isz = info.dtype.itemsize
    out = np.empty((row1 - row0, col1 - col0), dtype=info.dtype.newbyteorder("="))

    # Work out which byte ranges we need: (block_index, row_in_block, col_start, col_end)
    pieces = []
    if not info.tiled:
        for r in range(row0, row1):
            s = r // info.block_h
            rib = r % info.block_h
            off = int(info.offsets[s]) + (rib * info.width + col0) * isz
            pieces.append((off, (col1 - col0) * isz, r - row0, 0))
    else:
        tiles_across = -(-info.width // info.block_w)
        for r in range(row0, row1):
            tr, rit = divmod(r, info.block_h)
            for tc in range(col0 // info.block_w, (col1 - 1) // info.block_w + 1):
                c_start = max(col0, tc * info.block_w)
                c_end = min(col1, (tc + 1) * info.block_w)
                t = tr * tiles_across + tc
                off = int(info.offsets[t]) + (rit * info.block_w + (c_start - tc * info.block_w)) * isz
                pieces.append((off, (c_end - c_start) * isz, r - row0, c_start - col0))

    merged = _merge_ranges([(p[0], p[1]) for p in pieces], max_gap)
    blobs = {}
    for off, ln in merged:
        blobs[off] = read(off, ln)
    starts = np.array(sorted(blobs))
    for off, ln, orow, ocol in pieces:
        base = int(starts[np.searchsorted(starts, off, side="right") - 1])
        b = blobs[base][off - base: off - base + ln]
        out[orow, ocol: ocol + ln // isz] = np.frombuffer(b, dtype=info.dtype)
    return out
