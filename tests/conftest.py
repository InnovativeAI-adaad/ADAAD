import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / "User-ready-ADAAD"
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
