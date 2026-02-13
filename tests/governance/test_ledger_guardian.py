# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.evolution.lineage_v2 import LineageIntegrityError, LineageLedgerV2
from runtime.recovery.ledger_guardian import AutoRecoveryHook, SnapshotManager
from security.ledger.journal import JournalIntegrityError, append_tx, verify_journal_integrity


def test_lineage_auto_recovery_from_snapshot(tmp_path: Path) -> None:
    ledger_path = tmp_path / "lineage_v2.jsonl"
    ledger = LineageLedgerV2(ledger_path)
    ledger.append_event("EpochStartEvent", {"epoch_id": "ep-1"})

    snapshots = SnapshotManager(tmp_path / "snaps")
    snapshots.create_snapshot(ledger_path)

    entry = json.loads(ledger_path.read_text(encoding="utf-8").splitlines()[0])
    entry["prev_hash"] = "x" * 64
    ledger_path.write_text(json.dumps(entry) + "\n", encoding="utf-8")

    hook = AutoRecoveryHook(snapshots)
    with pytest.raises(LineageIntegrityError):
        ledger.verify_integrity(recovery_hook=hook)

    # run verify again post-recovery
    ledger.verify_integrity()
    assert hook.recovery_log


def test_journal_auto_recovery_from_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from security.ledger import journal

    temp_journal = tmp_path / "cryovant_journal.jsonl"
    temp_genesis = tmp_path / "cryovant_journal.genesis.jsonl"
    monkeypatch.setattr(journal, "JOURNAL_PATH", temp_journal)
    monkeypatch.setattr(journal, "GENESIS_PATH", temp_genesis)

    append_tx("test", {"i": 1}, tx_id="TX-1")

    snapshots = SnapshotManager(tmp_path / "snaps")
    snapshots.create_snapshot(temp_journal)

    entry = json.loads(temp_journal.read_text(encoding="utf-8").splitlines()[0])
    entry["hash"] = "bad"
    temp_journal.write_text(json.dumps(entry) + "\n", encoding="utf-8")

    hook = AutoRecoveryHook(snapshots)
    with pytest.raises(JournalIntegrityError):
        verify_journal_integrity(recovery_hook=hook)

    verify_journal_integrity()
    assert hook.recovery_log


def test_snapshot_manager_list_restore_and_latest(tmp_path: Path) -> None:
    lineage = tmp_path / "lineage_v2.jsonl"
    journal = tmp_path / "cryovant_journal.jsonl"
    lineage.write_text('{"type":"EpochStartEvent"}\n', encoding="utf-8")
    journal.write_text('{"tx":"ok"}\n', encoding="utf-8")

    snapshots = SnapshotManager(tmp_path / "snaps")
    snapshots.create_snapshot(lineage, journal, "epoch-1")

    all_snaps = snapshots.list_snapshots()
    assert all_snaps
    latest = snapshots.get_latest_snapshot()
    assert latest is not None
    assert latest.epoch_id == "epoch-1"

    lineage.write_text("corrupt\n", encoding="utf-8")
    journal.write_text("corrupt\n", encoding="utf-8")
    restored = snapshots.restore_snapshot(latest.snapshot_id, lineage, journal)
    assert restored
    assert "EpochStartEvent" in lineage.read_text(encoding="utf-8")
