"""Makes civlint importable without relying on an installed package or on
pytest's rootdir-based sys.path insertion."""

import sys
from pathlib import Path

root = str(Path(__file__).resolve().parent.parent)
if root not in sys.path:
    sys.path.insert(0, root)
