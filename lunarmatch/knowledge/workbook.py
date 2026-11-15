"""Standard-library reader for the engineering planning workbook (.xlsx).

Read-only: the file is opened as a zip archive and never written. Cached
formula results are returned as values. Sheet and column names are the
workbook's own (Hebrew) headers; :data:`SHEETS` and :data:`COLUMNS` give
English keys for the ones the code uses.
"""
from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from lunarmatch.config import PROJECT_ROOT

WORKBOOK_PATH = PROJECT_ROOT / "data" / "reference" / "LunarMatch_database_hackathon.xlsx"

# English key -> sheet name in the workbook
SHEETS = {
    "parameters": "פרמטרים",
    "experiments": "ניסויים",
    "skills": "סקילים",
    "pipeline": "פייפליין",
    "sources": "מקורות",
    "reference_sites": "אתרי ייחוס",
    "control": "בקרה",
}

# English key -> column header, per sheet
COLUMNS = {
    "parameters": {
        "id": "ID", "domain": "תחום", "name_he": "שם הפרמטר", "name_en": "English",
        "symbol": "סימון", "units": "יחידות", "lunar_source": "מקור ירחי",
        "earth_source": "מקור ארצי", "lunar_status": "מצב ירח", "earth_status": "מצב ארץ",
        "importance": "חשיבות", "priority": "עדיפות", "landing_use": "שימוש לנחיתה",
        "limitations": "מגבלות / הערות", "info_type": "סוג מידע",
    },
    "experiments": {
        "id": "ID", "name_he": "ניסוי פיזי / חישובי", "name_en": "English",
        "objective": "מטרה", "parameters": "פרמטרים קשורים", "equipment": "כלים / ציוד",
        "deliverable": "תוצר מדיד", "priority": "עדיפות", "why": "למה חשוב",
        "controls": "בקרות / מגבלות", "owner": "אחראי מוצע", "status": "סטטוס",
        "duration": "משך משוער", "dependencies": "תלויות",
    },
    "sources": {
        "id": "ID", "name": "מאגר / מקור", "url": "URL", "body": "גוף / עולם",
        "provides": "מה מקבלים", "caveat": "הסתייגות",
    },
}


class WorkbookError(RuntimeError):
    """The workbook is missing or does not have the expected structure."""


def _tag(el) -> str:
    return el.tag.rsplit("}", 1)[-1]


def _text(el) -> str:
    return "".join(t.text or "" for t in el.iter() if _tag(t) == "t")


def _col_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref).group(0)
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def read_sheets(path: Path = WORKBOOK_PATH) -> dict[str, list[list[str]]]:
    """Return {sheet name: rows}, each row a list of cell strings ('' if empty)."""
    path = Path(path)
    if not path.is_file():
        raise WorkbookError(f"Workbook not found: {path}")
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile as e:
        raise WorkbookError(f"Not a valid .xlsx: {path}") from e
    with z:
        names = set(z.namelist())
        shared = []
        if "xl/sharedStrings.xml" in names:
            shared = [_text(si) for si in ET.fromstring(z.read("xl/sharedStrings.xml"))
                      if _tag(si) == "si"]
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = {r.get("Id"): r.get("Target")
                for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        out: dict[str, list[list[str]]] = {}
        for s in wb.iter():
            if _tag(s) != "sheet":
                continue
            rid = next(v for k, v in s.attrib.items() if k.endswith("}id"))
            target = rels[rid].lstrip("/")
            part = target if target.startswith("xl/") else "xl/" + target
            rows = []
            for row in ET.fromstring(z.read(part)).iter():
                if _tag(row) != "row":
                    continue
                cells: dict[int, str] = {}
                for c in row:
                    if _tag(c) != "c":
                        continue
                    v = None
                    for ch in c:
                        if _tag(ch) == "v":
                            v = ch.text
                        elif _tag(ch) == "is":
                            v = _text(ch)
                    if v is None:
                        continue
                    if c.get("t") == "s":
                        v = shared[int(v)]
                    cells[_col_index(c.get("r"))] = v.strip()
                if cells:
                    rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
            out[s.get("name")] = rows
    return out


def records(sheets: dict, key: str) -> list[dict]:
    """Rows of a table sheet as dicts keyed by English column keys."""
    name = SHEETS[key]
    if name not in sheets:
        raise WorkbookError(f"Sheet {name!r} ({key}) not found")
    rows = sheets[name]
    header = rows[0]
    cols = COLUMNS[key]
    missing = [h for h in cols.values() if h not in header]
    if missing:
        raise WorkbookError(f"Sheet {key}: missing columns {missing}")
    idx = {k: header.index(h) for k, h in cols.items()}
    out = []
    for r in rows[1:]:
        rec = {k: (r[i] if i < len(r) else "") for k, i in idx.items()}
        if rec.get("id"):
            out.append(rec)
    return out


@dataclass
class PlanningWorkbook:
    """Parsed workbook content used by the application."""

    path: Path
    parameters: list[dict]
    experiments: list[dict]
    sources: list[dict]

    def parameter(self, pid: str) -> dict:
        for p in self.parameters:
            if p["id"] == pid:
                return p
        raise KeyError(pid)

    def experiment(self, eid: str) -> dict:
        for e in self.experiments:
            if e["id"] == eid:
                return e
        raise KeyError(eid)

    def source(self, sid: str) -> dict:
        for s in self.sources:
            if s["id"] == sid:
                return s
        raise KeyError(sid)


def load_workbook(path: Path = WORKBOOK_PATH) -> PlanningWorkbook:
    sheets = read_sheets(path)
    return PlanningWorkbook(
        path=Path(path),
        parameters=records(sheets, "parameters"),
        experiments=records(sheets, "experiments"),
        sources=records(sheets, "sources"),
    )


def resolve_parameter_tokens(text: str, parameters: list[dict]) -> tuple[list[str], list[str]]:
    """Map an experiment's parameter list (e.g. 'ρ_d; c; φ; PSD; q_c') to IDs.

    A token matches a parameter by symbol (each alternative in 'q_c / F(z)'),
    exact English name, or as a whole word inside the English name (so
    'roughness' matches 'Terrain roughness'). Returns (ids, unresolved tokens).
    Unresolved tokens are reported, never guessed.
    """
    ids, unresolved = [], []
    for tok in [t.strip() for t in re.split(r"[;,]", text) if t.strip()]:
        low = tok.lower()
        hit = None
        for p in parameters:
            symbols = [s.strip() for s in re.split(r"[/,]", p["symbol"]) if s.strip()]
            if tok in symbols:
                hit = p["id"]
                break
        if hit is None:
            for p in parameters:
                en = p["name_en"].lower()
                if en == low or re.search(rf"\b{re.escape(low)}\b", en):
                    hit = p["id"]
                    break
        if hit is None:
            unresolved.append(tok)
        elif hit not in ids:
            ids.append(hit)
    return ids, unresolved
