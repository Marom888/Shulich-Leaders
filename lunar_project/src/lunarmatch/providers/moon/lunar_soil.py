"""D_LUNAR_SOIL – lunar regolith mechanical reference records.

There is **no** machine API and no map of lunar friction/cohesion/density.
The workbook (sheet ``Lunar_Mechanical_References``) lists the sources and
intentionally leaves numerical values blank until verified.

This provider:
* loads those reference rows (from ``config/lunar_mechanical_references.csv``),
* loads *verified* observations the team adds to
  ``data/raw/moon/D_LUNAR_SOIL/observations.csv`` (one row per measured value,
  with source, page/station, depth, method), and
* never produces a number that is not present in such a file.

Every returned record is labelled ``Evidence.REFERENCE`` – it is NOT a
site-specific measurement of the selected lunar landing polygon.
"""
from __future__ import annotations

import csv
from pathlib import Path

from ...core.aoi import AOI
from ...core.base import CoverageReport, DataProvider, DatasetInfo, FetchResult
from ...core.evidence import AccessMode, Evidence
from ...core.storage import PROJECT_ROOT

REFERENCES_CSV = PROJECT_ROOT / "config" / "lunar_mechanical_references.csv"
OBS_COLUMNS = ["reference_id", "property", "value", "units", "depth_cm_top", "depth_cm_bottom", "site",
               "lat", "lon", "method", "source_citation", "source_page_or_table", "verified_by", "notes"]


class LunarSoilProvider(DataProvider):
    info = DatasetInfo(
        dataset_id="D_LUNAR_SOIL", name="Lunar Regolith Properties (reference records)", body="Moon",
        provider="Peer-reviewed / mission reports", resolution="point / heterogeneous",
        evidence=Evidence.REFERENCE, access=AccessMode.LOCAL_FILES,
        access_notes="No API. Reference list from workbook + team-verified observations CSV.",
        workbook_source_url="https://doi.org/10.1002/nag.70432",
        known_limits="Apollo/Luna samples are not south-pole site measurements; mixed provenance.",
    )

    @property
    def observations_csv(self) -> Path:
        return self.store.raw_dir("moon", "D_LUNAR_SOIL") / "observations.csv"

    def ensure_template(self) -> Path:
        p = self.observations_csv
        if not p.exists():
            with open(p, "w", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerow(OBS_COLUMNS)
        return p

    def check_coverage(self, aoi: AOI) -> CoverageReport:
        return CoverageReport(self.info.dataset_id, None,
                              "Reference data only – no site-specific lunar soil map exists for any AOI")

    def fetch(self, aoi: AOI = None, **kw) -> FetchResult:
        res = FetchResult(self.info.dataset_id, aoi)
        refs = []
        if REFERENCES_CSV.exists():
            with open(REFERENCES_CSV, newline="", encoding="utf-8") as fh:
                refs = list(csv.DictReader(fh))
        res.tables["references"] = refs
        obs_path = self.ensure_template()
        with open(obs_path, newline="", encoding="utf-8") as fh:
            obs = [r for r in csv.DictReader(fh) if (r.get("value") or "").strip()]
        bad = [r for r in obs if not (r.get("source_citation") and r.get("units") and r.get("method"))]
        if bad:
            res.warn(f"{len(bad)} observation rows lack source_citation/units/method and were dropped")
        obs = [dict(r, evidence=Evidence.REFERENCE.value) for r in obs if r not in bad]
        res.tables["observations"] = obs
        if not obs:
            res.warn(f"no verified lunar soil values loaded yet – add rows to {obs_path}")
        res.files.append(str(obs_path))
        return res
