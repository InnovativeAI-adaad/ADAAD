from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

LEDGER_FILE = "events.jsonl"


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_ledger(ledger_dir: Path) -> Path:
    ledger_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = ledger_dir / LEDGER_FILE
    if not ledger_path.exists():
        ledger_path.touch()
    return ledger_path


def append_record(ledger_dir: Path, record: Dict[str, Any]) -> Path:
    ledger_path = ensure_ledger(ledger_dir)
    payload = {"ts": _ts(), **record}
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return ledger_path
