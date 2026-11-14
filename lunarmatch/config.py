"""Project paths and the reference test region.

All paths derive from this file's location, never from the terminal's
current working directory.
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "nasa_data"
EXTRACT_DIR = DATA_DIR / "extracted"
OUTPUT_DIR = PROJECT_ROOT / "outputs"

# Atacama Desert test region, (west, south, east, north) in degrees.
ATACAMA_BBOX = (-69.6, -23.7, -69.2, -23.3)
ATACAMA_TILE = "S24W070"

SRTM_SHORT_NAME = "SRTMGL1"
SRTM_VERSION = "003"
