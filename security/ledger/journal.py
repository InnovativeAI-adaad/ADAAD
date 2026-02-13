# SPDX-License-Identifier: Apache-2.0
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Ledger journaling utilities.
"""

import json
import time
import hashlib
from pathlib import Path
from typing import Dict, List, Optional

from runtime import metrics
from security.ledger import LEDGER_ROOT

ELEMENT_ID = "Water"

LEDGER_FILE = LEDGER_ROOT / "lineage.jsonl"
JOURNAL_PATH = LEDGER_ROOT / "cryovant_journal.jsonl"
GENESIS_PATH = LEDGER_ROOT / "cryovant_journal.genesis.jsonl"


def ensure_ledger() -> Path:
    """
    Guarantee the ledger directory and file exist.
    """
    LEDGER_ROOT.mkdir(parents=True, exist_ok=True)
    if not LEDGER_FILE.exists():
        LEDGER_FILE.touch()
    return LEDGER_FILE


def ensure_journal() -> Path:
    """
    Ensure the Cryovant journal exists, seeding from genesis if available.
    """
    LEDGER_ROOT.mkdir(parents=True, exist_ok=True)
    if not JOURNAL_PATH.exists():
        if GENESIS_PATH.exists():
            JOURNAL_PATH.write_text(GENESIS_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            JOURNAL_PATH.touch()
    return JOURNAL_PATH


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


def _hash_line(prev_hash: str, payload: Dict[str, object]) -> str:
    material = (prev_hash + json.dumps(payload, ensure_ascii=False, sort_keys=True)).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _last_hash() -> str:
    ensure_journal()
    last = ""
    with JOURNAL_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                last = line
    if not last:
        return "0" * 64
    try:
        obj = json.loads(last)
        return str(obj.get("hash") or "0" * 64)
    except Exception:
        return "0" * 64


def append_tx(tx_type: str, payload: Dict[str, object], tx_id: Optional[str] = None) -> Dict[str, object]:
    JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    prev = _last_hash()
    entry = {
        "tx": tx_id or f"TX-{tx_type}-{time.strftime('%Y%m%d%H%M%S', time.gmtime())}",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "type": tx_type,
        "payload": payload,
        "prev_hash": prev,
    }
    entry["hash"] = _hash_line(prev, entry)
    with JOURNAL_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def project_from_lineage(event: Dict[str, object]) -> Dict[str, object]:
    """Create a journal projection from a lineage-v2 event."""
    payload = dict(event.get("payload") or {})
    return {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "agent_id": str(payload.get("agent_id") or "system"),
        "action": str(event.get("type") or "lineage_event"),
        "payload": payload,
    }


def record_rotation_event(action: str, payload: Dict[str, object]) -> None:
    """
    Record a rotation event to both the lineage ledger and cryovant journal.
    """
    write_entry(agent_id="system", action=action, payload=payload)
    append_tx(tx_type=action, payload=payload)


def record_rotation_failure(action: str, payload: Dict[str, object]) -> None:
    """
    Record a rotation failure to both the lineage ledger and cryovant journal.
    """
    write_entry(agent_id="system", action=action, payload=payload)
    append_tx(tx_type=action, payload=payload)


__all__ = [
    "write_entry",
    "read_entries",
    "append_tx",
    "ensure_ledger",
    "ensure_journal",
    "record_rotation_event",
    "record_rotation_failure",
    "project_from_lineage",
]
