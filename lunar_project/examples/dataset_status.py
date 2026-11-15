"""Print every dataset of the workbook with its access path – and, with --check,
query live coverage for a Moon AOI and an Earth AOI.

    python examples/dataset_status.py            # offline description only
    python examples/dataset_status.py --check    # also asks each service about coverage
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lunarmatch import AOI, Body  # noqa: E402
from lunarmatch.registry import status_table  # noqa: E402

MOON = AOI(Body.MOON, -89.46311, 222.51, 1000, 1000, name="Shackleton connecting ridge")
EARTH = AOI(Body.EARTH, 36.10, -112.10, 1000, 1000, name="Arizona test AOI")  # US: 3DEP/NAIP/CPT apply


def main():
    check = "--check" in sys.argv
    for aoi in ((MOON, EARTH) if check else (None,)):
        if aoi:
            print(f"\n##### {aoi.name} ({aoi.body.value} {aoi.lat}, {aoi.lon}) #####")
        for r in status_table(aoi):
            line = f"{r['dataset_id']:13s} {r['body']:11s} {r['access']:20s} {r['resolution'][:34]:34s}"
            if aoi:
                line += f" {r.get('coverage', '')[:110]}"
            print(line)


if __name__ == "__main__":
    main()
