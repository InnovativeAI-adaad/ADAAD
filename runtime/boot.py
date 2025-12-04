# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
"""Health-first boot sequencing for ADAAD runtime."""
from __future__ import annotations

import json
import pathlib
from typing import Dict, List

REQUIRED_DIRS = ["reports", "security", "ui", "app"]
REPORTS = pathlib.Path("reports")
HEALTH_FIRST = True


def _missing_dirs(required: List[str]) -> List[str]:
    return [d for d in required if not pathlib.Path(d).exists()]


def write_health(status: Dict[str, object]) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "health.json").write_text(json.dumps(status, indent=2), encoding="utf-8")


def boot_sequence() -> Dict[str, object]:
    missing = _missing_dirs(REQUIRED_DIRS)
    status: Dict[str, object] = {
        "structure_ok": not missing,
        "missing": missing,
        "cryovant_ledger_writable": True,
    }
    status["mutation_enabled"] = not (HEALTH_FIRST and bool(missing))
    write_health(status)
    return status


__all__ = ["boot_sequence", "write_health", "HEALTH_FIRST"]
