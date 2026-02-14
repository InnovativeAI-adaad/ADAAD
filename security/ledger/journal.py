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
import os
import threading
from pathlib import Path
from contextlib import contextmanager
from typing import Dict, List, Optional, Protocol

from runtime import metrics
from security.ledger import LEDGER_ROOT

ELEMENT_ID = "Water"

LEDGER_FILE = LEDGER_ROOT / "lineage.jsonl"
JOURNAL_PATH = LEDGER_ROOT / "cryovant_journal.jsonl"
GENESIS_PATH = LEDGER_ROOT / "cryovant_journal.genesis.jsonl"
TAIL_STATE_PATH = LEDGER_ROOT / "cryovant_journal.tail.json"
LOCK_PATH = LEDGER_ROOT / "cryovant_journal.lock"

_THREAD_APPEND_LOCK = threading.Lock()


class JournalIntegrityError(RuntimeError):
    """Raised when the Cryovant journal integrity verification fails."""


class JournalRecoveryHook(Protocol):
    """Interface for invoking journal recovery workflows after integrity failures."""

    def on_journal_integrity_failure(self, *, journal_path: Path, error: JournalIntegrityError) -> None:
        """Handle a journal integrity failure (for example, snapshot restore)."""


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
    last_hash, _ = _validated_last_hash()
    return last_hash


def _raise_integrity_error(
    message: str,
    *,
    path: Path,
    recovery_hook: JournalRecoveryHook | None,
    cause: Exception | None = None,
) -> None:
    error = JournalIntegrityError(message)
    if recovery_hook is not None:
        recovery_hook.on_journal_integrity_failure(journal_path=path, error=error)
    if cause is not None:
        raise error from cause
    raise error


def _scan_chain(
    *,
    path: Path,
    recovery_hook: JournalRecoveryHook | None,
    start_offset: int,
    expected_prev_hash: str,
) -> tuple[str, int]:
    prev_hash = expected_prev_hash
    with path.open("r", encoding="utf-8") as handle:
        if start_offset:
            handle.seek(start_offset)
        for line_no, line in enumerate(handle, start=1):
            entry_text = line.strip()
            if not entry_text:
                continue
            try:
                entry = json.loads(entry_text)
            except json.JSONDecodeError as exc:
                _raise_integrity_error(
                    f"journal_invalid_json:line{line_no}:{exc}",
                    path=path,
                    recovery_hook=recovery_hook,
                    cause=exc,
                )
            if not isinstance(entry, dict):
                _raise_integrity_error(
                    f"journal_malformed_entry:line{line_no}",
                    path=path,
                    recovery_hook=recovery_hook,
                )
            entry_prev_hash = str(entry.get("prev_hash") or "")
            entry_hash = str(entry.get("hash") or "")
            if entry_prev_hash != prev_hash:
                _raise_integrity_error(
                    f"journal_prev_hash_mismatch:line{line_no}",
                    path=path,
                    recovery_hook=recovery_hook,
                )
            payload = {key: value for key, value in entry.items() if key != "hash"}
            computed_hash = _hash_line(prev_hash, payload)
            if entry_hash != computed_hash:
                _raise_integrity_error(
                    f"journal_hash_mismatch:line{line_no}",
                    path=path,
                    recovery_hook=recovery_hook,
                )
            prev_hash = entry_hash
        return prev_hash, handle.tell()


def _read_tail_state(path: Path) -> tuple[str, int] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    last_hash = str(data.get("last_hash") or "")
    offset = data.get("offset")
    if len(last_hash) != 64 or not isinstance(offset, int) or offset < 0:
        return None
    return last_hash, offset


def _write_tail_state(path: Path, *, last_hash: str, offset: int) -> None:
    payload = {"last_hash": last_hash, "offset": offset}
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(path)


def _validated_last_hash(
    recovery_hook: JournalRecoveryHook | None = None,
    *,
    journal_path: Path | None = None,
) -> tuple[str, int]:
    if journal_path is None:
        ensure_journal()
        path = JOURNAL_PATH
        tail_path = TAIL_STATE_PATH
    else:
        path = journal_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.touch()
        tail_path = path.with_suffix(path.suffix + ".tail")

    default_hash = "0" * 64
    tail_state = _read_tail_state(tail_path)
    if tail_state is not None:
        state_hash, state_offset = tail_state
        try:
            if path.stat().st_size > state_offset:
                last_hash, offset = _scan_chain(
                    path=path,
                    recovery_hook=recovery_hook,
                    start_offset=state_offset,
                    expected_prev_hash=state_hash,
                )
                _write_tail_state(tail_path, last_hash=last_hash, offset=offset)
                return last_hash, offset
        except JournalIntegrityError:
            # Cached tail state is inconsistent with the current journal; fall back
            # to a full rescan from offset 0 below to rebuild a valid tail state.
            metrics.counter("ledger_journal_tail_recovery_errors").inc()

    last_hash, offset = _scan_chain(
        path=path,
        recovery_hook=recovery_hook,
        start_offset=0,
        expected_prev_hash=default_hash,
    )
    _write_tail_state(tail_path, last_hash=last_hash, offset=offset)
    return last_hash, offset


@contextmanager
def _journal_append_lock(path: Path):
    lock_path = LOCK_PATH if path == JOURNAL_PATH else path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with _THREAD_APPEND_LOCK:
        with lock_path.open("a+", encoding="utf-8") as handle:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def verify_journal_integrity(
    recovery_hook: JournalRecoveryHook | None = None,
    *,
    journal_path: Path | None = None,
) -> None:
    """Recompute the chain from genesis and validate every stored hash."""
    _validated_last_hash(recovery_hook=recovery_hook, journal_path=journal_path)


def append_tx(tx_type: str, payload: Dict[str, object], tx_id: Optional[str] = None) -> Dict[str, object]:
    JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _journal_append_lock(JOURNAL_PATH):
        prev, offset = _validated_last_hash()
        entry = {
            "tx": tx_id or f"TX-{tx_type}-{time.strftime('%Y%m%d%H%M%S', time.gmtime())}",
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "type": tx_type,
            "payload": payload,
            "prev_hash": prev,
        }
        entry["hash"] = _hash_line(prev, entry)
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with JOURNAL_PATH.open("a", encoding="utf-8") as f:
            f.write(line)
        _write_tail_state(TAIL_STATE_PATH, last_hash=entry["hash"], offset=offset + len(line.encode("utf-8")))
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
    "verify_journal_integrity",
    "JournalIntegrityError",
    "JournalRecoveryHook",
]
