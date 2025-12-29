# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from pathlib import Path
from security.ledger import journal


def test_journal_hash_chaining(tmp_path: Path) -> None:
    original_path = journal.JOURNAL_PATH
    original_genesis = journal.GENESIS_PATH
    journal.JOURNAL_PATH = tmp_path / "cryovant_journal.jsonl"  # type: ignore
    journal.GENESIS_PATH = tmp_path / "cryovant_journal.genesis.jsonl"  # type: ignore
    try:
        first = journal.append_tx("test", {"i": 1}, tx_id="TX-1")
        second = journal.append_tx("test", {"i": 2}, tx_id="TX-2")
        assert second["prev_hash"] == first["hash"]
    finally:
        journal.JOURNAL_PATH = original_path  # type: ignore
        journal.GENESIS_PATH = original_genesis  # type: ignore
