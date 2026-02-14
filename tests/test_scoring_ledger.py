# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from runtime.evolution.scoring_ledger import ScoringLedger


def test_scoring_ledger_hash_chain(tmp_path: Path) -> None:
    ledger = ScoringLedger(tmp_path / "scoring.jsonl")
    first = ledger.append({"mutation_id": "m1", "score": 1})
    second = ledger.append({"mutation_id": "m2", "score": 2})

    assert first["prev_hash"] == "sha256:" + ("0" * 64)
    assert second["prev_hash"] == first["record_hash"]
    assert ledger.last_hash() == second["record_hash"]
