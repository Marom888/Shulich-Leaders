"""D_LROC_NAC – LROC Narrow Angle Camera images.

Discovery: ODE REST ``ihid=LRO iid=LROC pt=CDRNAC4`` (calibrated, PDS4).
Verified file layout (2026-11-15): ``<ID>.IMG`` ≈ 500 MB, PDS label ``.xml``,
and a browse pyramid ``<ID>_pyr.tif`` (~45 MB).

Important limitation: CDR images are **not map-projected**. Turning them
into an orthoimage that can be compared with a DEM requires USGS ISIS
(``lronac2isis``, ``spiceinit``, ``cam2map``) or NASA Ames Stereo Pipeline.
For map-projected NAC imagery use the orthophotos shipped inside the NAC
DTM products (see :mod:`lroc_dtm`, files "ORTHOPHOTO IN PDS FORMAT").

This provider therefore: searches by AOI, returns observation geometry
(incidence/emission/phase, resolution, time — the inputs for illumination
matching in EXP_SHADOW / EXP_10) and downloads selected files on request.
"""
from __future__ import annotations

from typing import Iterable, Optional

from ...core.aoi import AOI
from ...core.base import CoverageReport, DataProvider, DatasetInfo, FetchResult, ProductRef
from ...core.bodies import Body
from ...core.evidence import AccessMode, Evidence
from ...core.ode import OdeClient
from ...core.storage import utc_now_iso

GEOMETRY_KEYS = ("Observation_time", "UTC_start_time", "Incidence_angle", "Emission_angle", "Phase_angle",
                 "Map_resolution", "Solar_longitude", "Center_latitude", "Center_longitude")


class LROCNACProvider(DataProvider):
    info = DatasetInfo(
        dataset_id="D_LROC_NAC", name="LROC NAC images (CDR)", body="Moon", provider="LROC/ASU via PDS (ODE)",
        resolution="~0.5-2 m/px", evidence=Evidence.MEASURED, access=AccessMode.SEARCH_AND_DOWNLOAD,
        access_notes="ODE search (pt=CDRNAC4); IMG files ~0.5 GB each, not map-projected (ISIS/ASP needed).",
        endpoints=("https://oderest.rsl.wustl.edu/live2/",),
        workbook_source_url="https://www.lroc.asu.edu/data/support/downloads/LROC_NAC_Processing_Guide.pdf",
        known_limits="Lighting/projection affect comparisons; raw CDR not orthorectified.",
    )

    def search(self, aoi: AOI, limit: int = 100, pt: str = "CDRNAC4", **kw) -> list[ProductRef]:
        self.check_body(aoi, (Body.MOON,))
        b = aoi.geographic_bbox(lon_convention="360")
        prods = OdeClient(self.http).product_search(ihid="LRO", iid="LROC", pt=pt, bbox_lon360=b, limit=limit)
        return [OdeClient.to_product_ref(p) for p in prods]

    def check_coverage(self, aoi: AOI) -> CoverageReport:
        refs = self.search(aoi, limit=20)
        return CoverageReport(self.info.dataset_id, bool(refs),
                              f"{len(refs)}+ NAC observations intersect the AOI" if refs else "no NAC observation found",
                              [r.product_id for r in refs])

    def fetch(self, aoi: AOI, download: Iterable[str] = (), file_kinds=("BROWSE IMAGE",),
              max_bytes: Optional[int] = 100_000_000, limit: int = 100, **kw) -> FetchResult:
        """Return an observation table; optionally download files for chosen product ids.

        download:   product ids to download.
        file_kinds: description substrings of files to fetch, e.g. "BROWSE IMAGE" or
                    "PRODUCT DATA FILE" (the full ~500 MB calibrated IMG).
        """
        refs = self.search(aoi, limit=limit)
        res = FetchResult(self.info.dataset_id, aoi)
        rows = []
        for r in refs:
            row = {"product_id": r.product_id, **{k: r.properties.get(k) for k in GEOMETRY_KEYS}}
            rows.append(row)
        res.tables["observations"] = rows
        res.metadata["evidence"] = Evidence.MEASURED.value
        res.metadata["note"] = "CDR images are not map-projected; see module docstring."
        for pid in download:
            ref = next((r for r in refs if r.product_id == pid), None)
            if ref is None:
                res.warn(f"{pid} not among search results")
                continue
            for kind in file_kinds:
                picked = OdeClient.pick_file(ref, kind)
                if not picked:
                    res.warn(f"{pid}: no file matching '{kind}'")
                    continue
                fname, url, size = picked
                if max_bytes and size > max_bytes:
                    res.warn(f"{fname} is {size / 1e6:.0f} MB; raise max_bytes to download")
                    continue
                dest = self.store.raw_dir("moon", self.info.dataset_id, pid) / fname
                self.http.download(url, dest)
                self.store.write_metadata(dest, {"dataset_id": self.info.dataset_id, "product_id": pid,
                                                 "source_url": url, "download_utc": utc_now_iso(),
                                                 "evidence": Evidence.MEASURED.value, "path": str(dest),
                                                 "geometry": {k: ref.properties.get(k) for k in GEOMETRY_KEYS}})
                res.files.append(str(dest))
        return res
