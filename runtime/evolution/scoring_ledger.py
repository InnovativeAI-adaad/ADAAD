# SPDX-License-Identifier: Apache-2.0
"""Append-only deterministic scoring ledger helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from runtime.governance.foundation import canonical_json, sha256_prefixed_digest


class ScoringLedger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def append(self, scoring_result: Dict[str, Any]) -> Dict[str, Any]:
        prev_hash = self.last_hash()
        record = {
            "scoring_result": dict(scoring_result),
            "prev_hash": prev_hash,
        }
        record["record_hash"] = sha256_prefixed_digest(canonical_json(record))
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
        return record

    def last_hash(self) -> str:
        last = "sha256:" + ("0" * 64)
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                row = line.strip()
                if not row:
                    continue
                try:
                    payload = json.loads(row)
                except json.JSONDecodeError:
                    continue
                value = payload.get("record_hash")
                if isinstance(value, str):
                    last = value
        return last


__all__ = ["ScoringLedger"]
