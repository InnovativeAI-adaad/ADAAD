from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

LEDGER_FILE = "events.jsonl"


class LedgerWriteForbidden(RuntimeError):
    """Raised when a direct ledger write is attempted outside Cryovant."""


def ensure_ledger(_: Path) -> Path:
    raise LedgerWriteForbidden("Direct ledger writes are forbidden; use security.cryovant.Cryovant")


def append_record(_: Path, __: Dict[str, Any]) -> Path:
    raise LedgerWriteForbidden("Direct ledger writes are forbidden; use security.cryovant.Cryovant")


__all__ = ["LedgerWriteForbidden", "append_record", "ensure_ledger", "LEDGER_FILE"]
