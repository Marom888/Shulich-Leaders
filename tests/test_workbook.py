"""Planning-workbook reader: synthetic .xlsx fixtures plus the real workbook (if present)."""
import hashlib
import zipfile

import pytest

from lunarmatch.knowledge import workbook as wbm

NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
RNS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def make_xlsx(path, sheets: dict[str, list[list]]):
    """Minimal .xlsx: strings go to sharedStrings (or inline for '!'-prefixed)."""
    shared, sheet_xml, rels, entries = [], {}, [], []
    for i, (name, rows) in enumerate(sheets.items(), start=1):
        rows_xml = []
        for r, row in enumerate(rows, start=1):
            cells = []
            for c, v in enumerate(row):
                if v is None:
                    continue
                ref = f"{chr(65 + c)}{r}"
                if isinstance(v, (int, float)):
                    cells.append(f'<c r="{ref}"><v>{v}</v></c>')
                elif v.startswith("!"):
                    cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{v[1:]}</t></is></c>')
                else:
                    shared.append(v)
                    cells.append(f'<c r="{ref}" t="s"><v>{len(shared) - 1}</v></c>')
            rows_xml.append(f'<row r="{r}">{"".join(cells)}</row>')
        sheet_xml[f"xl/worksheets/sheet{i}.xml"] = (
            f'<worksheet {NS}><sheetData>{"".join(rows_xml)}</sheetData></worksheet>')
        rels.append(f'<Relationship Id="rId{i}" Target="worksheets/sheet{i}.xml" Type="x"/>')
        entries.append(f'<sheet name="{name}" sheetId="{i}" r:id="rId{i}"/>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook {NS} {RNS}><sheets>{"".join(entries)}</sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   f'{"".join(rels)}</Relationships>')
        z.writestr("xl/sharedStrings.xml",
                   f'<sst {NS}>' + "".join(f"<si><t>{s}</t></si>" for s in shared) + "</sst>")
        for k, v in sheet_xml.items():
            z.writestr(k, v)
    return path


SRC_HEADER = list(wbm.COLUMNS["sources"].values())


def test_read_sheets_shared_inline_numeric_and_gaps(tmp_path):
    p = make_xlsx(tmp_path / "w.xlsx", {"S": [["a", None, "!inline"], [1.5, "b"]]})
    rows = wbm.read_sheets(p)["S"]
    assert rows == [["a", "", "inline"], ["1.5", "b"]]


def test_records_by_english_keys_and_skips_blank_ids(tmp_path):
    p = make_xlsx(tmp_path / "w.xlsx", {wbm.SHEETS["sources"]: [
        SRC_HEADER, ["SRC-01", "Name", "https://x", "Earth", "DEM", "caveat"], [None, "orphan"]]})
    recs = wbm.records(wbm.read_sheets(p), "sources")
    assert recs == [{"id": "SRC-01", "name": "Name", "url": "https://x", "body": "Earth",
                     "provides": "DEM", "caveat": "caveat"}]


def test_missing_sheet_column_file_and_bad_zip(tmp_path):
    p = make_xlsx(tmp_path / "w.xlsx", {wbm.SHEETS["sources"]: [["ID", "URL"], ["SRC-01", "u"]]})
    with pytest.raises(wbm.WorkbookError, match="missing columns"):
        wbm.records(wbm.read_sheets(p), "sources")
    with pytest.raises(wbm.WorkbookError, match="not found"):
        wbm.records(wbm.read_sheets(p), "parameters")
    with pytest.raises(wbm.WorkbookError):
        wbm.read_sheets(tmp_path / "nope.xlsx")
    bad = tmp_path / "bad.xlsx"
    bad.write_bytes(b"not a zip")
    with pytest.raises(wbm.WorkbookError):
        wbm.read_sheets(bad)


PARAMS = [
    {"id": "TOP-02", "symbol": "θ", "name_en": "Slope"},
    {"id": "TOP-03", "symbol": "R", "name_en": "Terrain roughness"},
    {"id": "SOIL-11", "symbol": "q_c / F(z)", "name_en": "Penetration resistance"},
    {"id": "SOIL-02", "symbol": "c", "name_en": "Cohesion"},
]


def test_resolve_tokens_symbols_names_and_unresolved():
    ids, unresolved = wbm.resolve_parameter_tokens("Slope; c; roughness; F(z); E_abs; c", PARAMS)
    assert ids == ["TOP-02", "SOIL-02", "TOP-03", "SOIL-11"]       # deduplicated, in order
    assert unresolved == ["E_abs"]                                 # reported, never guessed
    assert wbm.resolve_parameter_tokens("rough", PARAMS) == ([], ["rough"])   # no partial words


# ---------------------------------------------------------------- real workbook
REAL = wbm.WORKBOOK_PATH
needs_real = pytest.mark.skipif(not REAL.is_file(), reason="team workbook not present")


@needs_real
def test_real_workbook_structure_and_read_only():
    before = hashlib.sha256(REAL.read_bytes()).hexdigest()
    wb = wbm.load_workbook()
    assert hashlib.sha256(REAL.read_bytes()).hexdigest() == before
    assert len(wb.parameters) == 28 and len(wb.experiments) == 12 and len(wb.sources) == 18
    domains = {p["id"].split("-")[0] for p in wb.parameters}
    assert domains == {"TOP", "GEO", "SOIL"}
    assert len({p["id"] for p in wb.parameters}) == 28


@needs_real
@pytest.mark.parametrize("eid,expected,unresolved", [
    ("EXP-01", ["SOIL-01", "SOIL-02", "SOIL-03", "SOIL-04", "SOIL-11"], []),
    ("EXP-04", ["TOP-02", "SOIL-03", "SOIL-02", "TOP-03"], []),
    ("EXP-05", ["SOIL-01", "SOIL-11", "TOP-02", "TOP-04"], []),
    ("EXP-07", ["SOIL-01", "SOIL-11"], ["E_abs"]),
    ("EXP-09", ["SOIL-03", "SOIL-02"], ["moisture"]),
])
def test_real_experiment_parameter_mapping(eid, expected, unresolved):
    wb = wbm.load_workbook()
    assert wbm.resolve_parameter_tokens(wb.experiment(eid)["parameters"], wb.parameters) == (
        expected, unresolved)
