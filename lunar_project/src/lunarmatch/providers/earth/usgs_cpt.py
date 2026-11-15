"""D_USGS_CPT – USGS "An Open Repository of U.S. Cone Penetration Test (CPT) data".

Data release: Bennett, Holzer, Noce & Grant (2025), doi:10.5066/P13M3WVY,
ScienceBase item 67ffc46ed4be024303209582.  1822 soundings, 14 US states.
Format (from the FGDC metadata, verified 2026-11-15):
* index CSV:   ID, Location, County, State, Date, Latitude, Longitude,
               Elevation (-999 = n/a), Total_Depth, WT_Depth (-999 = n/a), WT_Notes, Operator, Cone
* per sounding ``<ID>.csv``: z [m], tip [MPa] (qc), sleeve [kPa] (fs, may be empty)

Access: the ScienceBase JSON API (``?format=json``) lists the attached files;
ScienceBase sits behind a bot-protection layer that sometimes blocks
scripts, so a local-folder mode is provided: download the release once in a
browser and point ``local_dir`` to the extracted folder.
"""
from __future__ import annotations

import csv
import io
import math
import zipfile
from pathlib import Path
from typing import Optional

from ...core.aoi import AOI
from ...core.base import CoverageReport, DataProvider, DatasetInfo, FetchResult, NotAvailable
from ...core.bodies import Body
from ...core.evidence import AccessMode, Evidence
from ...core.storage import utc_now_iso
from .wosis import _haversine_km

SCIENCEBASE_ITEM = "https://www.sciencebase.gov/catalog/item/67ffc46ed4be024303209582"
DOI = "https://doi.org/10.5066/P13M3WVY"
BBOX = (-125.1563, 25.6415, -79.2773, 49.6107)


class USGSCPTProvider(DataProvider):
    info = DatasetInfo(
        dataset_id="D_USGS_CPT", name="USGS CPT 1822 soundings", body="Earth", provider="USGS",
        resolution="point and depth profile", evidence=Evidence.MEASURED, access=AccessMode.AUTOMATED,
        access_notes="ScienceBase JSON file listing + CSV download; local-folder fallback.",
        endpoints=(SCIENCEBASE_ITEM + "?format=json", DOI),
        workbook_source_url="https://www.usgs.gov/data/open-repository-us-cone-penetration-test-cpt-data",
        known_limits="US only, points; nearby CPT not representative without spatial correlation (EXP_04).",
    )

    def __init__(self, *a, local_dir: Optional[str] = None, **kw):
        super().__init__(*a, **kw)
        self.local_dir = Path(local_dir) if local_dir else self.store.raw_dir("earth", "D_USGS_CPT")

    # ------------------------------------------------------------------ files
    def list_remote_files(self) -> dict[str, str]:
        j = self.http.get_json(SCIENCEBASE_ITEM, params={"format": "json"})
        files = {f["name"]: f.get("url") or f.get("downloadUri") for f in j.get("files", [])}
        for ext in j.get("facets", []) or []:
            for f in ext.get("files", []):
                files[f["name"]] = f.get("url") or f.get("downloadUri")
        return {k: v for k, v in files.items() if v}

    def _index_path(self) -> Optional[Path]:
        cands = [p for p in self.local_dir.rglob("*.csv") if "index" in p.name.lower()]
        return cands[0] if cands else None

    def ensure_local(self) -> Path:
        """Make sure the index CSV (and data zip if any) are present locally."""
        idx = self._index_path()
        if idx:
            return idx
        try:
            files = self.list_remote_files()
        except Exception as exc:  # bot protection, offline...
            raise NotAvailable(
                f"Could not list ScienceBase files ({exc}). Download the data release manually from {DOI} "
                f"and extract it into {self.local_dir}") from exc
        for name, url in files.items():
            if name.lower().endswith((".csv", ".zip")) and "legacy" not in name.lower():
                dest = self.local_dir / name
                self.http.download(url, dest)
                self.store.write_metadata(dest, {"dataset_id": "D_USGS_CPT", "source_url": url, "doi": DOI,
                                                 "download_utc": utc_now_iso(), "evidence": "MEASURED"})
                if name.lower().endswith(".zip"):
                    with zipfile.ZipFile(dest) as z:
                        z.extractall(self.local_dir / dest.stem)
        idx = self._index_path()
        if not idx:
            raise NotAvailable(f"index CSV not found in {self.local_dir}")
        return idx

    def read_index(self) -> list[dict]:
        idx = self.ensure_local()
        with open(idx, newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
        for r in rows:
            for k in ("Latitude", "Longitude", "Elevation", "Total_Depth", "WT_Depth"):
                try:
                    v = float(r.get(k, "nan"))
                    r[k] = None if v == -999 else v
                except ValueError:
                    r[k] = None
        return rows

    def read_sounding(self, cpt_id: str) -> list[dict]:
        hits = list(self.local_dir.rglob(f"{cpt_id}.csv"))
        if not hits:
            raise NotAvailable(f"sounding file {cpt_id}.csv not found under {self.local_dir}")
        text = hits[0].read_text(encoding="utf-8-sig")
        out = []
        for r in csv.DictReader(io.StringIO(text)):
            def f(key):
                v = (r.get(key) or "").strip()
                return float(v) if v else None
            out.append({"z_m": f("z"), "qc_MPa": f("tip"), "fs_kPa": f("sleeve")})
        return out

    # ------------------------------------------------------------------ interface
    def check_coverage(self, aoi: AOI) -> CoverageReport:
        self.check_body(aoi, (Body.EARTH,))
        w, s, e, n = BBOX
        inside = w <= aoi.lon <= e and s <= aoi.lat <= n
        return CoverageReport(self.info.dataset_id, None if inside else False,
                              "inside the release bounding box (point data – use fetch to find distances)"
                              if inside else "outside the conterminous-US extent of the release")

    def fetch(self, aoi: AOI, max_distance_km: float = 25.0, max_soundings: int = 10, profiles: bool = True,
              **kw) -> FetchResult:
        self.check_body(aoi, (Body.EARTH,))
        idx = self.read_index()
        for r in idx:
            r["distance_km"] = (_haversine_km(aoi.lat, aoi.lon, r["Latitude"], r["Longitude"])
                                if r["Latitude"] is not None else math.inf)
        near = sorted([r for r in idx if r["distance_km"] <= max_distance_km], key=lambda r: r["distance_km"])
        near = near[:max_soundings]
        res = FetchResult(self.info.dataset_id, aoi, metadata={"doi": DOI, "evidence": "MEASURED",
                                                               "max_distance_km": max_distance_km})
        res.tables["soundings"] = near
        if not near:
            res.warn(f"no CPT sounding within {max_distance_km} km")
        if profiles:
            for r in near:
                try:
                    res.tables[f"profile_{r['ID']}"] = self.read_sounding(r["ID"])
                except NotAvailable as exc:
                    res.warn(str(exc))
        res.warn("CPT qc is an Earth field-verification measurement, not a lunar-equivalent metric (workbook F_CPT)")
        return res
