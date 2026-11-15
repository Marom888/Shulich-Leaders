"""Datasets that the workbook lists but that have no confirmed data API.

* D_SCALPSS  – NASA SCALPSS descent imaging (IM-1, Blue Ghost). Public pages
  describe the experiment; downloadable images/3-D reconstructions are not
  confirmed (workbook: VERIFY_PRODUCT_RELEASE_AND_REUSABILITY).
* D_PSI_TEST – NASA Langley plume–surface interaction vacuum-chamber tests
  (workbook: DATA_ACCESS_UNCONFIRMED).

The providers record provenance and let the team *register* files obtained
by request (papers, image sets) so they are tracked like every other raw
dataset.  They never fabricate measurements.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from ..core.aoi import AOI
from ..core.base import CoverageReport, DataProvider, DatasetInfo, FetchResult, NotAvailable
from ..core.evidence import AccessMode, Evidence
from ..core.storage import utc_now_iso


class _ReferenceOnly(DataProvider):
    status: str = "DATA_ACCESS_UNCONFIRMED"

    def check_coverage(self, aoi: AOI) -> CoverageReport:
        return CoverageReport(self.info.dataset_id, None,
                              f"{self.status}: not a geographic layer; validation reference only")

    def register_file(self, path, *, source_url: str, description: str, evidence: Evidence = Evidence.MEASURED) -> Path:
        """Copy a manually obtained file into data/raw and write its provenance sidecar."""
        src = Path(path)
        dest = self.store.raw_dir(self.body_dir, self.info.dataset_id) / src.name
        if src.resolve() != dest.resolve():
            shutil.copy2(src, dest)
        self.store.write_metadata(dest, {"dataset_id": self.info.dataset_id, "source_url": source_url,
                                         "description": description, "evidence": evidence.value,
                                         "registered_utc": utc_now_iso(), "path": str(dest)})
        return dest

    def fetch(self, aoi: AOI = None, **kw) -> FetchResult:
        d = self.store.raw_dir(self.body_dir, self.info.dataset_id)
        files = sorted(str(p) for p in d.iterdir() if not p.name.endswith(".meta.json"))
        if not files:
            raise NotAvailable(f"{self.info.dataset_id}: {self.status}. {self.info.access_notes} "
                               f"Register obtained files with register_file(); folder: {d}")
        res = FetchResult(self.info.dataset_id, aoi, files=files)
        res.metadata["records"] = [self.store.read_metadata(f) for f in files]
        return res


class SCALPSSProvider(_ReferenceOnly):
    status = "VERIFY_PRODUCT_RELEASE_AND_REUSABILITY"
    info = DatasetInfo(
        dataset_id="D_SCALPSS", name="NASA SCALPSS lunar descent imaging / photogrammetry", body="Moon",
        provider="NASA Langley / CLPS", resolution="mission- and reconstruction-dependent",
        evidence=Evidence.MEASURED, access=AccessMode.REFERENCE_ONLY,
        access_notes="No public download API confirmed; obtain products by request and register them.",
        workbook_source_url="https://www.nasa.gov/lunar-surface-technology/",
        known_limits="IM-1 and Blue Ghost sites only; validation reference, not a matching raster.",
    )


class PSITestProvider(_ReferenceOnly):
    status = "DATA_ACCESS_UNCONFIRMED"
    info = DatasetInfo(
        dataset_id="D_PSI_TEST", name="NASA Langley Plume-Surface Interaction vacuum testing", body="Earth / lab",
        provider="NASA Langley", resolution="experiment-specific", evidence=Evidence.MEASURED,
        access=AccessMode.REFERENCE_ONLY,
        access_notes="Published test descriptions only; register datasets/papers once obtained.",
        workbook_source_url="https://www.nasa.gov/missions/artemis/nasa-begins-moon-mission-plume-surface-interaction-tests/",
        known_limits="Not an Earth-site raster; calibrates erosion models only if data are published.",
    )
