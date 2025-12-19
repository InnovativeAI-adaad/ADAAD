import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for candidate in [ROOT, ROOT / "User-ready-ADAAD"]:
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))
