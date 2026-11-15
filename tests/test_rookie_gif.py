"""GIF validation, still-frame extraction, and Rookie search-animation integration."""
import copy
import json
import re
import subprocess

import pytest

from rookie import build as B
from rookie.gif import GifError, first_frame_gif, inspect_gif

IMG_DATA = b"\x02\x02\x4c\x01\x00"     # LZW min code size + one sub-block + terminator


def make_gif(path, frames=3, delay=22, loop=True, w=4, h=3):
    b = bytearray(b"GIF89a" + w.to_bytes(2, "little") + h.to_bytes(2, "little") + b"\x80\x00\x00")
    b += b"\x00\x00\x00\xff\xff\xff"                                   # 2-colour table
    if loop:
        b += b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00"
    for _ in range(frames):
        b += b"\x21\xf9\x04\x00" + delay.to_bytes(2, "little") + b"\x00\x00"
        b += b"\x2c\x00\x00\x00\x00" + w.to_bytes(2, "little") + h.to_bytes(2, "little") + b"\x00"
        b += IMG_DATA
    b += b"\x3b"
    path.write_bytes(bytes(b))
    return path


def test_inspect_animated_gif(tmp_path):
    info = inspect_gif(make_gif(tmp_path / "a.gif", frames=6, delay=22))
    assert (info.width, info.height, info.frames) == (4, 3, 6)
    assert info.animated and info.loop_count == 0
    assert info.delays_cs == [22] * 6 and info.duration_s == pytest.approx(1.32)


def test_single_frame_without_loop(tmp_path):
    info = inspect_gif(make_gif(tmp_path / "s.gif", frames=1, loop=False))
    assert not info.animated and info.loop_count is None


@pytest.mark.parametrize("data", [b"", b"PNG\x89....", b"GIF89a" + b"\x00" * 7,
                                  b"GIF89a\x04\x00\x03\x00\x00\x00\x00\x3b"])
def test_invalid_gifs_rejected(tmp_path, data):
    p = tmp_path / "bad.gif"
    p.write_bytes(data)
    with pytest.raises(GifError):
        inspect_gif(p)


def test_truncated_gif_rejected(tmp_path):
    p = make_gif(tmp_path / "t.gif")
    p.write_bytes(p.read_bytes()[:-8])
    with pytest.raises(GifError):
        inspect_gif(p)


def test_first_frame_is_valid_single_frame(tmp_path):
    src = make_gif(tmp_path / "a.gif", frames=5)
    still = tmp_path / "still.gif"
    still.write_bytes(first_frame_gif(src))
    info = inspect_gif(still)
    assert info.frames == 1 and (info.width, info.height) == (4, 3)
    assert b"NETSCAPE2.0" not in still.read_bytes()       # no loop extension: cannot animate


# ---------------------------------------------------------------- build integration
def test_prepare_search_animation_copies_and_describes(tmp_path):
    gif = make_gif(tmp_path / "rookie_search.gif", frames=6)
    meta = B.prepare_search_animation(tmp_path / "out", gif)
    assert meta["available"] and meta["frames"] == 6 and meta["duration_s"] == 1.32
    assert (tmp_path / "out" / meta["animated"]).read_bytes() == gif.read_bytes()
    assert inspect_gif(tmp_path / "out" / meta["still"]).frames == 1
    assert meta["alt"] and "guide dog" in meta["alt"]


def test_prepare_search_animation_missing_or_invalid(tmp_path):
    assert B.prepare_search_animation(tmp_path, None)["available"] is False
    bad = tmp_path / "bad.gif"
    bad.write_bytes(b"not a gif")
    meta = B.prepare_search_animation(tmp_path / "out", bad)
    assert meta["available"] is False and "not a valid GIF" in meta["reason"]
    assert not (tmp_path / "out" / "assets").exists()


def test_find_search_gif_accepts_double_extension(tmp_path):
    p = tmp_path / "rookie_search.gif.gif"
    p.write_bytes(b"x")
    assert B.find_search_gif([tmp_path / "rookie_search.gif", p]) == p
    assert B.find_search_gif([tmp_path / "none.gif"]) is None


def test_real_rookie_animation_if_present():
    gif = B.find_search_gif()
    if gif is None:
        pytest.skip("Rookie animation not present")
    info = inspect_gif(gif)
    assert info.animated and info.frames > 1 and info.width > 0
    assert info.size_bytes < 5 * 1024 * 1024               # keeps the app light


# ---------------------------------------------------------------- app + preview pages
from test_rookie import EARTH_OK, _browser, needs_wb  # noqa: E402


@needs_wb
def test_app_and_preview_embed_component(tmp_path):
    gif = make_gif(tmp_path / "rookie_search.gif", frames=6)
    out = B.build(output_dir=tmp_path, earth=copy.deepcopy(EARTH_OK), search_gif=gif)
    html = out.read_text(encoding="utf-8")
    data = json.loads(re.search(r'id="rookie-data">(.*?)</script>', html, re.S).group(1))
    assert data["search_animation"]["available"] is True
    assert "function RookieSearch" in html and '(prefers-reduced-motion: reduce)' in html
    assert "/*__RS_" not in html
    prev = (out.parent / "search_preview.html").read_text(encoding="utf-8")
    assert "Preview only." in prev and "No search is performed" in prev
    assert "/*__RS_" not in prev
    # Missing animation still builds, with an explicit fallback.
    out2 = B.build(output_dir=tmp_path / "b", earth=copy.deepcopy(EARTH_OK), search_gif=None)
    d2 = json.loads(re.search(r'id="rookie-data">(.*?)</script>', out2.read_text(encoding="utf-8"),
                              re.S).group(1))
    assert d2["search_animation"]["available"] is False


@needs_wb
@pytest.mark.skipif(_browser() is None, reason="no headless Chromium-based browser")
def test_animation_only_plays_during_search(tmp_path):
    gif = make_gif(tmp_path / "rookie_search.gif", frames=6)
    out = B.build(output_dir=tmp_path, earth=copy.deepcopy(EARTH_OK), search_gif=gif)

    def dom(url):
        return subprocess.run([_browser(), "--headless=new", "--disable-gpu",
                               f"--user-data-dir={tmp_path / 'profile'}",
                               "--virtual-time-budget=3000", "--dump-dom", url],
                              capture_output=True, text=True, encoding="utf-8", timeout=60).stdout

    app = dom(out.as_uri() + "#target=mons_mouton_plateau&exp=footpad_penetration&step=6")
    fig = re.search(r'<figure class="rs"[^>]*>.*?</figure>', app, re.S).group(0)
    assert 'data-state="unavailable"' in fig and 'aria-busy="false"' in fig
    assert 'src="assets/rookie_search_still.gif"' in fig           # still, not animated
    assert 'src="assets/rookie_search.gif"' not in fig

    prev = dom((out.parent / "search_preview.html").as_uri())
    figs = re.findall(r'<figure class="rs"[^>]*>.*?</figure>', prev, re.S)
    assert len(figs) == 5
    for f in figs:
        animated = 'src="assets/rookie_search.gif"' in f
        assert animated == ('data-state="searching"' in f)
        assert 'media="(prefers-reduced-motion: reduce)"' in f
