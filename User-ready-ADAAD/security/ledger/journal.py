# SPDX-License-Identifier: Apache-2.0
"""
Ledger journaling utilities.
"""

import json
import time
from pathlib import Path
from typing import Dict, List

from runtime import metrics
from security.ledger import LEDGER_ROOT

ELEMENT_ID = "Water"

LEDGER_FILE = LEDGER_ROOT / "lineage.jsonl"


def ensure_ledger() -> Path:
    """
    Guarantee the ledger directory and file exist.
    """
    LEDGER_ROOT.mkdir(parents=True, exist_ok=True)
    if not LEDGER_FILE.exists():
        LEDGER_FILE.touch()
    return LEDGER_FILE


def write_entry(agent_id: str, action: str, payload: Dict[str, str] | None = None) -> None:
    ensure_ledger()
    record = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "agent_id": agent_id,
        "action": action,
        "payload": payload or {},
    }
    with LEDGER_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    metrics.log(event_type="ledger_write", payload=record, level="INFO", element_id=ELEMENT_ID)


def read_entries(limit: int = 50) -> List[Dict[str, str]]:
    ensure_ledger()
    lines = LEDGER_FILE.read_text(encoding="utf-8").splitlines()
    entries: List[Dict[str, str]] = []
    for line in lines[-limit:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def last_issued_at(agent_id: str) -> str | None:
    """
    Return the most recent issued_at for the given agent based on certificate_evolved entries.
    """
    entries = read_entries(limit=5000)
    for entry in reversed(entries):
        if entry.get("agent_id") != agent_id:
            continue
        if entry.get("action") != "certificate_evolved":
            continue
        payload = entry.get("payload") or {}
        issued_at = payload.get("issued_at")
        if issued_at:
            return issued_at
    return None
