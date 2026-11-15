"""Standard-library GIF inspection and still-frame extraction.

``inspect_gif`` walks the GIF block structure (no pixel decoding) and
validates it. ``first_frame_gif`` copies the header, colour table and the
first image's blocks into a new single-frame GIF, used as the static poster
for users who prefer reduced motion.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


class GifError(ValueError):
    """Not a valid GIF file."""


@dataclass
class GifInfo:
    width: int
    height: int
    frames: int
    delays_cs: list[int] = field(default_factory=list)   # per frame, 1/100 s
    loop_count: int | None = None                          # 0 = forever; None = no loop ext
    size_bytes: int = 0

    @property
    def animated(self) -> bool:
        return self.frames > 1

    @property
    def duration_s(self) -> float:
        return sum(self.delays_cs) / 100.0


def _skip_sub_blocks(b: bytes, i: int) -> int:
    while True:
        if i >= len(b):
            raise GifError("truncated data sub-blocks")
        n = b[i]
        i += 1
        if n == 0:
            return i
        i += n


def _walk(b: bytes):
    """Yield (kind, start, end, extra) for each block after the header."""
    if len(b) < 13 or b[:6] not in (b"GIF87a", b"GIF89a"):
        raise GifError("missing GIF87a/GIF89a signature")
    flags = b[10]
    i = 13 + (3 * 2 ** ((flags & 7) + 1) if flags & 0x80 else 0)
    yield "header", 0, i, None
    while True:
        if i >= len(b):
            raise GifError("missing trailer")
        t = b[i]
        if t == 0x3B:
            yield "trailer", i, i + 1, None
            return
        if t == 0x21:
            if i + 2 > len(b):
                raise GifError("truncated extension")
            label = b[i + 1]
            end = _skip_sub_blocks(b, i + 2)
            yield "ext", i, end, (label, b[i + 2:end])
            i = end
        elif t == 0x2C:
            if i + 10 > len(b):
                raise GifError("truncated image descriptor")
            f = b[i + 9]
            j = i + 10 + (3 * 2 ** ((f & 7) + 1) if f & 0x80 else 0)
            end = _skip_sub_blocks(b, j + 1)          # +1: LZW minimum code size
            yield "image", i, end, None
            i = end
        else:
            raise GifError(f"unexpected block 0x{t:02X} at byte {i}")


def inspect_gif(path: Path) -> GifInfo:
    b = Path(path).read_bytes()
    info = GifInfo(width=int.from_bytes(b[6:8], "little") if len(b) >= 10 else 0,
                   height=int.from_bytes(b[8:10], "little") if len(b) >= 10 else 0,
                   frames=0, size_bytes=len(b))
    pending_delay = 0
    for kind, s, e, extra in _walk(b):
        if kind == "ext":
            label, data = extra
            if label == 0xF9 and len(data) >= 5:       # graphic control extension
                pending_delay = int.from_bytes(data[2:4], "little")
            elif label == 0xFF and data[1:12] == b"NETSCAPE2.0" and len(data) >= 16:
                info.loop_count = int.from_bytes(data[14:16], "little")
        elif kind == "image":
            info.frames += 1
            info.delays_cs.append(pending_delay)
            pending_delay = 0
    if info.frames == 0:
        raise GifError("no image frames")
    if info.width <= 0 or info.height <= 0:
        raise GifError("invalid logical screen size")
    return info


def first_frame_gif(path: Path) -> bytes:
    """A valid single-frame GIF containing only the first frame."""
    b = Path(path).read_bytes()
    out, gce = bytearray(), None
    for kind, s, e, extra in _walk(b):
        if kind == "header":
            out += b[s:e]
        elif kind == "ext" and extra[0] == 0xF9:
            gce = b[s:e]
        elif kind == "image":
            if gce:
                out += gce
            out += b[s:e]
            out += b"\x3B"
            return bytes(out)
    raise GifError("no image frames")
