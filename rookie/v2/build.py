"""Build the Rookie 2.0 static bundle into outputs/rookie2/.

The bundle works offline for screens 1-2 (config embedded). Searches need the
local engine (``python run_rookie.py --serve``); without it the app shows an
explicit "engine not running" state instead of results.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from lunarmatch.config import OUTPUT_DIR
from lunarmatch.terrain.registry import default_registry
from rookie.build import find_search_gif, prepare_search_animation
from rookie.v2.config import build_config

SRC = Path(__file__).resolve().parent / "web"
OUT = OUTPUT_DIR / "rookie2"


def build(out_dir: Path = OUT, registry=None, search_gif="auto") -> Path:
    from plotly.offline import get_plotlyjs

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = build_config(registry or default_registry())
    gif = find_search_gif() if search_gif == "auto" else search_gif
    cfg["animation"] = prepare_search_animation(out_dir, gif)
    html = (SRC / "index.html").read_text(encoding="utf-8")
    data = json.dumps(cfg, ensure_ascii=False).replace("</", "<\\/")
    (out_dir / "index.html").write_text(html.replace("/*__CONFIG__*/", data), encoding="utf-8")
    for f in ("app.css", "app.js"):
        shutil.copyfile(SRC / f, out_dir / f)
    plotly_js = out_dir / "plotly.min.js"
    if not plotly_js.is_file():
        plotly_js.write_text(get_plotlyjs(), encoding="utf-8")
    return out_dir / "index.html"
