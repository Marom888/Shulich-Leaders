"""Predefined lunar targets. Only verified coordinates get a location.

A preset without verified coordinates has ``point = None`` and status
"coordinates_pending_validation"; the UI shows it without a marker and the
discovery job refuses to run until the user enters coordinates.
"""
from __future__ import annotations

ARTEMIS_2024 = ("https://www.nasa.gov/news-release/"
                "nasa-provides-update-on-artemis-iii-moon-landing-regions/")

PRESETS = [
    {
        "id": "mons_mouton_plateau",
        "name": "Mons Mouton Plateau",
        "kind": "Artemis III candidate landing region (NASA, 28 Oct 2024; not a confirmed site)",
        "status": "coordinates_pending_validation",
        "point": None,
        "note": "NASA lists the region by name only; no published centre or boundary was found "
                "(checked 2026-11-15). 'Mons Mouton' is a separate NASA region.",
        "source": ARTEMIS_2024,
    },
    {
        "id": "nobile_rim_2",
        "name": "Nobile Rim 2",
        "kind": "Artemis III candidate landing region (NASA, 28 Oct 2024; not a confirmed site)",
        "status": "coordinates_pending_validation",
        "point": None,
        "note": "NASA lists the region by name only; no published centre or boundary was found "
                "(checked 2026-11-15).",
        "source": ARTEMIS_2024,
    },
    {
        "id": "shackleton_de_gerlache_ridge",
        "name": "Shackleton–de Gerlache ridge (intersection with Shackleton rim)",
        "kind": "Verified point on the Shackleton–de Gerlache connecting ridge",
        "status": "verified_point",
        # LROC caption: "...(portion of NAC mosaic, 750 m wide, 89.684°S, 196.739°E)"
        "point": {"lat": -89.684, "lon": 196.739 - 360.0},
        "suggested_radius_km": 7.0,
        "note": "Point = ridge / Shackleton-rim intersection from the LROC caption, not a ridge "
                "centroid or boundary. Ridgeline is about 14 km long (same source); the suggested "
                "7 km radius is a user-adjustable starting value, not a published extent.",
        "source": "https://lroc.im-ldi.com/images/1247",
        "source_detail": "LROC Featured Image 'Traversing the Shackleton de Gerlache Ridge', "
                         "M. Robinson, 1 April 2022, NAC M1348682369LR",
    },
    {
        "id": "custom",
        "name": "Custom location",
        "kind": "User-defined lunar coordinates",
        "status": "user_defined",
        "point": None,
        "note": "Click the globe or enter latitude/longitude and a radius.",
        "source": "user input",
    },
]


def preset(preset_id: str) -> dict:
    for p in PRESETS:
        if p["id"] == preset_id:
            return p
    raise KeyError(preset_id)
