"""Public release metadata shared by the API, frontend build and host updater."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCAL = json.loads((ROOT / "release.json").read_text())
TAG = re.compile(r"v(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})")
REPO = "Anning01/novelvids"


def version_key(version):
    match = TAG.fullmatch("v" + version)
    if match is None:
        raise ValueError("Invalid release version")
    return tuple(map(int, match.groups()))
