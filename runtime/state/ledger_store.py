# SPDX-License-Identifier: Apache-2.0
"""
Module: ledger_store
Purpose: Provide deterministic append-only scoring ledger persistence for JSON/SQLite backends.
Author: ADAAD / InnovativeAI-adaad
Integration points:
  - Imports from: runtime.governance.foundation + deterministic filesystem
  - Consumed by: runtime.evolution.scoring_ledger and migration helpers
  - Governance impact: medium — ledger backend selected by governance policy state_backend
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from runtime.governance.deterministic_filesystem import read_file_deterministic
from runtime.governance.foundation import canonical_json, sha256_prefixed_digest

_ZERO_HASH = "sha256:" + ("0" * 64)


class ScoringLedgerStore:
    def __init__(self, path: Path, *, sqlite_path: Path | None = None, backend: str = "json") -> None:
        if backend not in {"json", "sqlite"}:
            raise ValueError("invalid_state_backend")
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.sqlite_path = sqlite_path or path.with_suffix(".sqlite")
        self.backend = backend
        if self.backend == "json" and not self.path.exists():
            self.path.touch()
        if self.backend == "sqlite":
            self._init_sqlite()

    def _init_sqlite(self) -> None:
        with sqlite3.connect(self.sqlite_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scoring_ledger (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    scoring_result_json TEXT NOT NULL,
                    prev_hash TEXT NOT NULL,
                    record_hash TEXT NOT NULL UNIQUE
                )
                """
            )

    def _iter_json_records(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for line in read_file_deterministic(self.path).splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            if isinstance(payload, dict):
                rows.append(payload)
        return rows

    def iter_records(self) -> list[dict[str, Any]]:
        if self.backend == "sqlite":
            with sqlite3.connect(self.sqlite_path) as conn:
                rows = conn.execute(
                    "SELECT scoring_result_json, prev_hash, record_hash FROM scoring_ledger ORDER BY seq ASC"
                ).fetchall()
            return [
                {
                    "scoring_result": json.loads(scoring_result_json),
                    "prev_hash": prev_hash,
                    "record_hash": record_hash,
                }
                for scoring_result_json, prev_hash, record_hash in rows
            ]
        return self._iter_json_records()

    def last_hash(self) -> str:
        last = _ZERO_HASH
        for record in self.iter_records():
            candidate = record.get("record_hash")
            if isinstance(candidate, str):
                last = candidate
        return last

    def append(self, scoring_result: dict[str, Any]) -> dict[str, Any]:
        prev_hash = self.last_hash()
        record = {
            "scoring_result": dict(scoring_result),
            "prev_hash": prev_hash,
        }
        record["record_hash"] = sha256_prefixed_digest(canonical_json(record))

        if self.backend == "sqlite":
            self._init_sqlite()
            with sqlite3.connect(self.sqlite_path) as conn:
                conn.execute(
                    "INSERT INTO scoring_ledger(scoring_result_json, prev_hash, record_hash) VALUES (?, ?, ?)",
                    (canonical_json(record["scoring_result"]), record["prev_hash"], record["record_hash"]),
                )
            return record

        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
        return record

    def verify_chain(self) -> dict[str, Any]:
        expected_prev = _ZERO_HASH
        records = self.iter_records()
        for index, record in enumerate(records):
            observed_prev = record.get("prev_hash")
            if observed_prev != expected_prev:
                return {"ok": False, "count": index, "error": "prev_hash_mismatch", "index": index}
            computed_record = {
                "scoring_result": dict(record.get("scoring_result") or {}),
                "prev_hash": observed_prev,
            }
            expected_hash = sha256_prefixed_digest(canonical_json(computed_record))
            if record.get("record_hash") != expected_hash:
                return {"ok": False, "count": index, "error": "record_hash_mismatch", "index": index}
            expected_prev = expected_hash
        return {"ok": True, "count": len(records), "tip_hash": expected_prev}
