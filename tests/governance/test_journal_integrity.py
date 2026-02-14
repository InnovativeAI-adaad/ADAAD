# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
from pathlib import Path

import pytest

from security.ledger import journal


def _with_temp_journal(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path, Path]:
    original_path = journal.JOURNAL_PATH
    original_genesis = journal.GENESIS_PATH
    original_tail = journal.TAIL_STATE_PATH
    original_lock = journal.LOCK_PATH
    temp_journal = tmp_path / "cryovant_journal.jsonl"
    temp_genesis = tmp_path / "cryovant_journal.genesis.jsonl"
    temp_tail = tmp_path / "cryovant_journal.tail.json"
    temp_lock = tmp_path / "cryovant_journal.lock"
    journal.JOURNAL_PATH = temp_journal  # type: ignore
    journal.GENESIS_PATH = temp_genesis  # type: ignore
    journal.TAIL_STATE_PATH = temp_tail  # type: ignore
    journal.LOCK_PATH = temp_lock  # type: ignore
    return original_path, original_genesis, original_tail, original_lock, temp_journal, temp_genesis


def _restore_journal(original_path: Path, original_genesis: Path, original_tail: Path, original_lock: Path) -> None:
    journal.JOURNAL_PATH = original_path  # type: ignore
    journal.GENESIS_PATH = original_genesis  # type: ignore
    journal.TAIL_STATE_PATH = original_tail  # type: ignore
    journal.LOCK_PATH = original_lock  # type: ignore


def test_verify_journal_integrity_valid_chain(tmp_path: Path) -> None:
    original_path, original_genesis, original_tail, original_lock, _, _ = _with_temp_journal(tmp_path)
    try:
        journal.append_tx("test", {"i": 1}, tx_id="TX-1")
        journal.append_tx("test", {"i": 2}, tx_id="TX-2")
        journal.verify_journal_integrity()
    finally:
        _restore_journal(original_path, original_genesis, original_tail, original_lock)


def test_verify_journal_integrity_detects_tamper(tmp_path: Path) -> None:
    original_path, original_genesis, original_tail, original_lock, temp_journal, _ = _with_temp_journal(tmp_path)
    try:
        journal.append_tx("test", {"i": 1}, tx_id="TX-1")
        entry = json.loads(temp_journal.read_text(encoding="utf-8").splitlines()[0])
        entry["payload"]["i"] = 999
        temp_journal.write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")

        with pytest.raises(journal.JournalIntegrityError, match="journal_hash_mismatch"):
            journal.verify_journal_integrity()
    finally:
        _restore_journal(original_path, original_genesis, original_tail, original_lock)


def test_verify_journal_integrity_detects_malformed_json(tmp_path: Path) -> None:
    original_path, original_genesis, original_tail, original_lock, temp_journal, _ = _with_temp_journal(tmp_path)
    try:
        temp_journal.write_text('{"tx":"oops"\n', encoding="utf-8")
        with pytest.raises(journal.JournalIntegrityError, match="journal_invalid_json"):
            journal.verify_journal_integrity()
    finally:
        _restore_journal(original_path, original_genesis, original_tail, original_lock)


def test_append_tx_blocked_after_corruption(tmp_path: Path) -> None:
    original_path, original_genesis, original_tail, original_lock, temp_journal, _ = _with_temp_journal(tmp_path)
    try:
        journal.append_tx("test", {"i": 1}, tx_id="TX-1")
        entry = json.loads(temp_journal.read_text(encoding="utf-8").splitlines()[0])
        entry["prev_hash"] = "f" * 64
        temp_journal.write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")

        with pytest.raises(journal.JournalIntegrityError, match="journal_prev_hash_mismatch"):
            journal.append_tx("test", {"i": 2}, tx_id="TX-2")
    finally:
        _restore_journal(original_path, original_genesis, original_tail, original_lock)
