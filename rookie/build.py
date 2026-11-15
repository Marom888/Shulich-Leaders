"""Render the Rookie static app to outputs/rookie/.

Writes index.html (the guided app), search_preview.html (design preview of the
RookieSearch component states) and assets/ (the Rookie animation and its
still first frame for reduced-motion users).
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from lunarmatch.config import OUTPUT_DIR, PROJECT_ROOT
from lunarmatch.knowledge.workbook import WORKBOOK_PATH, load_workbook
from rookie.earth import earth_summary
from rookie.gif import GifError, first_frame_gif, inspect_gif
from rookie.journey import build_payload

TEMPLATES = Path(__file__).resolve().parent / "templates"
TEMPLATE = TEMPLATES / "index.html"
PREVIEW_TEMPLATE = TEMPLATES / "search_preview.html"
PLACEHOLDER = "/*__ROOKIE_DATA__*/"

# The team's animation. Windows can hide a doubled extension, so both names are accepted.
SEARCH_GIF_CANDIDATES = [
    PROJECT_ROOT / "assets" / "animations" / "rookie_search.gif",
    PROJECT_ROOT / "assets" / "animations" / "rookie_search.gif.gif",
]
SEARCH_GIF_ALT = ("Rookie, an orange voxel-style guide dog in a blue harness, walking across "
                  "Earth and sniffing for terrestrial test sites")
SEARCH_GIF_CREDIT = "Rookie is based on a real Labrador guide dog our team is training."


def _json_for_script(obj) -> str:
    # Escape "</" so text can never close the surrounding <script> element.
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def _inline_component(html: str) -> str:
    css = (TEMPLATES / "rookie_search.css").read_text(encoding="utf-8")
    js = (TEMPLATES / "rookie_search.js").read_text(encoding="utf-8")
    return html.replace("/*__RS_CSS__*/", css).replace("/*__RS_JS__*/", js)


def render_html(payload: dict, template: Path = TEMPLATE) -> str:
    html = template.read_text(encoding="utf-8")
    if PLACEHOLDER not in html:
        raise RuntimeError("template is missing the data placeholder")
    return _inline_component(html.replace(PLACEHOLDER, _json_for_script(payload)))


def find_search_gif(candidates=None) -> Path | None:
    for p in (candidates or SEARCH_GIF_CANDIDATES):
        if Path(p).is_file():
            return Path(p)
    return None


def prepare_search_animation(out_dir: Path, gif_path: Path | None) -> dict:
    """Validate the GIF, copy it next to the app and write its still frame.

    Returns the ``search_animation`` entry for the payload. Paths are
    relative to out_dir (outputs/rookie/).
    """
    if gif_path is None:
        return {"available": False,
                "reason": "Rookie animation not found at assets/animations/rookie_search.gif."}
    try:
        info = inspect_gif(gif_path)
    except GifError as e:
        return {"available": False, "reason": f"Rookie animation is not a valid GIF: {e}"}
    assets = Path(out_dir) / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(gif_path, assets / "rookie_search.gif")
    (assets / "rookie_search_still.gif").write_bytes(first_frame_gif(gif_path))
    return {
        "available": True, "animated": "assets/rookie_search.gif",
        "still": "assets/rookie_search_still.gif", "alt": SEARCH_GIF_ALT,
        "credit": SEARCH_GIF_CREDIT, "width": info.width, "height": info.height,
        "frames": info.frames, "duration_s": round(info.duration_s, 2),
        "source_file": Path(gif_path).name,
    }


def discovery_summary(path: Path) -> dict | None:
    """Summary of the latest real discovery run (no per-window data, no scores)."""
    from lunarmatch.discovery.store import read_result

    if not Path(path).is_file():
        return None
    r = read_result(path)
    ws = r["windows"]
    return {
        "created_at": r["created_at"],
        "bbox_wsen": r["request"]["bbox"],
        "window_km": r["request"]["window_m"] / 1000,
        "coverage": r["coverage"],
        "windows": len(ws),
        "windows_ok": sum(w["status"] == "ok" for w in ws),
        "windows_insufficient": sum(w["status"] == "insufficient_data" for w in ws),
        "constraints": r["filters"]["constraints"],
        "passed": len(r["filters"]["passed"]),
        "sources": r["sources"],
        "governance": r["governance"],
        "limitations": r["limitations"],
    }


MAX_COMPARISON_ROWS = 600


def comparison_summary(path: Path) -> dict | None:
    """Compact view of the latest comparison run for the app (no scores exist to show)."""
    from lunarmatch.discovery.comparison_run import COMPARISON_SCHEMA

    if not Path(path).is_file():
        return None
    r = json.loads(Path(path).read_text(encoding="utf-8"))
    if r.get("schema") != COMPARISON_SCHEMA:
        return None

    def feat(c, name):
        f = c["features"][name]
        if f["status"] != "computed":
            return {"status": f["status"]}
        return {"status": "computed", "earth_p50": f["earth"]["p50"], "earth_p90": f["earth"]["p90"],
                "d_p50": f["delta"]["p50"], "d_p90": f["delta"]["p90"], "w1": f["w1"]}

    earth_mock = bool(r["earth"]["contains_mock_data"])
    rows = [{"id": c["window_id"], "centre": c["centre_lat_lon"], "earth_mock": earth_mock,
             "passes_filters": c["passes_filters"], "slope": feat(c, "slope_deg"),
             "rough": feat(c, "roughness_m")} for c in r["comparisons"][:MAX_COMPARISON_ROWS]]
    m = r["moon"]
    strip = (lambda d: None if d is None else {k: v for k, v in d.items() if k != "q"})
    return {
        "created_at": r["created_at"], "contains_mock_data": r["contains_mock_data"],
        "request": r["request"],
        "moon": {"status": m["status"], "dataset_id": m["dataset_id"], "is_mock": m["is_mock"],
                 "region": m["region"], "spacing_m": m.get("spacing_m"),
                 "n_samples": m.get("n_samples"), "slope_deg": strip(m.get("slope_deg")),
                 "roughness_m": strip(m.get("roughness_m")),
                 "processing": [p["processing"] for p in m.get("provenance", [])]},
        "earth": {"dataset_id": r["earth"]["dataset_id"], "is_mock": r["earth"]["contains_mock_data"],
                  "coverage": r["earth"]["coverage"], "constraints": r["earth"]["filters"]["constraints"]},
        "rows": rows, "rows_total": len(r["comparisons"]),
        "experiments_draft": [{k: d[k] for k in ("experiment_id", "name", "label", "status",
                                                  "missing_required", "note")}
                              for d in r["experiments_draft"]],
        "governance": r["governance"], "limitations": r["limitations"],
    }


def build(output_dir: Path = OUTPUT_DIR, workbook_path: Path = WORKBOOK_PATH,
          tile_path: Path | None = None, earth: dict | None = None,
          search_gif: Path | None | str = "auto",
          discovery_path: Path | None = None, comparison_path: Path | None = None) -> Path:
    wb = load_workbook(workbook_path)
    earth = earth if earth is not None else earth_summary(tile_path, output_dir)
    payload = build_payload(wb, earth)
    payload["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    payload["discovery"] = discovery_summary(
        discovery_path or Path(output_dir) / "discovery" / "latest.json")
    payload["comparison"] = comparison_summary(
        comparison_path or Path(output_dir) / "discovery" / "latest_comparison.json")

    out_dir = Path(output_dir) / "rookie"
    out_dir.mkdir(parents=True, exist_ok=True)
    gif = find_search_gif() if search_gif == "auto" else search_gif
    payload["search_animation"] = prepare_search_animation(out_dir, gif)

    out = out_dir / "index.html"
    out.write_text(render_html(payload), encoding="utf-8")
    preview = PREVIEW_TEMPLATE.read_text(encoding="utf-8").replace(
        "/*__RS_DATA__*/", _json_for_script(payload["search_animation"]))
    (out_dir / "search_preview.html").write_text(_inline_component(preview), encoding="utf-8")
    return out
