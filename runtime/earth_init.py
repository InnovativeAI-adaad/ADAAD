# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
"""Earth-layer initialization helpers for ADAAD runtime."""
from __future__ import annotations

import pathlib
from typing import Dict

from app.cryovant import CryovantRegistry

SECURITY_ROOT = pathlib.Path("security")
LEDGER_DIR = SECURITY_ROOT / "ledger"
KEY_DIR = SECURITY_ROOT / "keys"


def init_earth() -> Dict[str, object]:
    registry = CryovantRegistry()
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    return {
        "earth_initialized": True,
        "ledger": str(registry.ledger_path),
        "mirror": str(registry.mirror_path),
    }


__all__ = ["init_earth", "SECURITY_ROOT"]
