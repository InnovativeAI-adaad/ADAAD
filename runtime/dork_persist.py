# runtime/dork_persist.py
# Phase 133 · INNOV-42 · DORK Fleet Server Bridge
# Constitutional invariant: DFSB-PERSIST-0
# SPDX-License-Identifier: Apache-2.0

"""
DorkLedgerPersistence — append-only JSONL persistence layer for ConversationLedger.

DFSB-PERSIST-0 (Hard):
  The conversation ledger MUST survive server restart with chain continuity
  provable from genesis. Every append MUST be flushed to disk before the
  call returns. Silent write failures are constitutionally prohibited.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

_DEFAULT_LEDGER_PATH = Path(os.getenv(
    "DORK_LEDGER_PATH",
    "data/dork/conversation_ledger.jsonl",
))


class PersistenceWriteError(RuntimeError):
    """DFSB-PERSIST-0: raised when a ledger write cannot be flushed to disk."""


class DorkLedgerPersistence:
    """
    Append-only JSONL persistence for the DORK conversation ledger.

    Each line is a JSON-serialised ledger entry. The file is opened in
    append mode; every write is followed by an explicit flush + fsync so
    the OS page-cache cannot swallow entries on crash.

    Chain continuity: on load, the last entry's entry_hash is used as the
    starting prev_hash for the next append — no re-hashing of the full file
    is required.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _DEFAULT_LEDGER_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._last_hash: str = "0" * 64
        self._seq_offset: int = 0
        self._load_tail()

    # ── Load ──────────────────────────────────────────────────────────────────
    def _load_tail(self) -> None:
        """Scan to the last entry to pick up prev_hash and seq for continuation."""
        if not self._path.exists():
            return
        last_entry = None
        count = 0
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    last_entry = json.loads(line)
                    count += 1
                except json.JSONDecodeError:
                    continue
        if last_entry:
            self._last_hash = last_entry.get("entry_hash", "0" * 64)
            self._seq_offset = last_entry.get("seq", count - 1) + 1

    # ── Append ────────────────────────────────────────────────────────────────
    def append(self, role: str, content: str) -> dict:
        """
        Append a new turn and flush to disk.
        DFSB-PERSIST-0: raises PersistenceWriteError if flush fails.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        content_digest = hashlib.sha256(content.encode()).hexdigest()[:24]
        payload = json.dumps({
            "seq": self._seq_offset,
            "role": role,
            "content_digest": content_digest,
            "timestamp": timestamp,
            "prev_hash": self._last_hash,
        }, sort_keys=True)
        entry_hash = hashlib.sha256(payload.encode()).hexdigest()
        entry = json.loads(payload)
        entry["entry_hash"] = entry_hash

        try:
            with self._path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
                f.flush()
                os.fsync(f.fileno())
        except OSError as exc:
            raise PersistenceWriteError(
                f"DFSB-PERSIST-0 VIOLATION: ledger write failed at seq={self._seq_offset}: {exc}"
            ) from exc

        self._last_hash = entry_hash
        self._seq_offset += 1
        return entry

    # ── Read ──────────────────────────────────────────────────────────────────
    def tail(self, n: int = 20) -> list[dict]:
        """Return the last n entries from the persisted ledger."""
        entries: list[dict] = []
        if not self._path.exists():
            return entries
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return entries[-n:]

    def __iter__(self) -> Iterator[dict]:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue

    def verify(self) -> tuple[bool, str]:
        """Re-derive full chain from genesis. Returns (valid, reason)."""
        prev = "0" * 64
        required_fields = ("seq", "role", "content_digest", "timestamp", "prev_hash", "entry_hash")
        for i, entry in enumerate(self):
            for field in required_fields:
                if field not in entry:
                    return False, f"verify_failed:index={i}:missing_field:{field}"

            actual_seq = entry.get("seq")
            if actual_seq != i:
                return (
                    False,
                    f"verify_failed:index={i}:seq_mismatch:expected={i}:actual={actual_seq}",
                )

            if entry.get("prev_hash") != prev:
                return (
                    False,
                    f"verify_failed:index={i}:prev_hash_mismatch:expected={prev}:actual={entry.get('prev_hash')}",
                )

            payload = json.dumps({
                "seq": entry["seq"],
                "role": entry["role"],
                "content_digest": entry["content_digest"],
                "timestamp": entry["timestamp"],
                "prev_hash": entry["prev_hash"],
            }, sort_keys=True)
            expected_entry_hash = hashlib.sha256(payload.encode()).hexdigest()
            actual_entry_hash = entry.get("entry_hash")
            if actual_entry_hash != expected_entry_hash:
                return (
                    False,
                    f"verify_failed:index={i}:entry_hash_mismatch:expected={expected_entry_hash}:actual={actual_entry_hash}",
                )

            prev = actual_entry_hash
        return True, "chain_valid"

    @property
    def path(self) -> Path:
        return self._path

    @property
    def entry_count(self) -> int:
        return self._seq_offset
