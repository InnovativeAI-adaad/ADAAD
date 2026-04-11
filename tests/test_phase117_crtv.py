# SPDX-License-Identifier: Apache-2.0
"""
test_phase117_crtv.py — Phase 117 · INNOV-32 · Constitutional Rollback & Temporal Versioning
Tests: T117-CRTV-01 through T117-CRTV-30 (30/30)

Hard-class invariants under test
---------------------------------
CRTV-0        Append-only snapshots
CRTV-CHAIN-0  Chain linkage integrity
CRTV-DETERM-0 Deterministic digests
CRTV-GATE-0   Fail-closed guard
CRTV-AUDIT-0  Ledger persistence before return
"""

import hashlib
import json
import os
import tempfile

import pytest

# ---------------------------------------------------------------------------
# Test isolation: override ledger path via env
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def tmp_ledger(tmp_path, monkeypatch):
    ledger = str(tmp_path / "crtv_test.jsonl")
    monkeypatch.setenv("ADAAD_CRTV_LEDGER", ledger)
    return ledger


@pytest.fixture()
def engine(tmp_ledger):
    """Fresh engine per test, isolated to tmp_ledger path."""
    from runtime.innovations30.constitutional_rollback import (
        ConstitutionalRollbackEngine,
    )
    return ConstitutionalRollbackEngine(ledger_path=tmp_ledger)


@pytest.fixture()
def rules_v1():
    return {"RULE-A": "no_silent_failures", "RULE-B": "human_override_required"}


@pytest.fixture()
def rules_v2():
    return {
        "RULE-A": "no_silent_failures",
        "RULE-B": "human_override_required",
        "RULE-C": "append_only_ledger",
    }


@pytest.fixture()
def rules_v3():
    return {
        "RULE-A": "no_silent_failures_v2",
        "RULE-C": "append_only_ledger",
        "RULE-D": "deterministic_digests",
    }


RATIFY = "DUSTIN L REID — 2026-04-04 ratified"

# ===========================================================================
# T117-CRTV-01 — Engine instantiates without error
# ===========================================================================
def test_T117_CRTV_01_engine_instantiates(engine):
    assert engine is not None
    assert engine.snapshot_count == 0
    assert engine.head is None


# ===========================================================================
# T117-CRTV-02 — Snapshot returns ConstitutionalSnapshot
# ===========================================================================
def test_T117_CRTV_02_snapshot_returns_object(engine, rules_v1):
    from runtime.innovations30.constitutional_rollback import ConstitutionalSnapshot
    snap = engine.snapshot("E-001", rules_v1, "genesis", "DEVADAAD")
    assert isinstance(snap, ConstitutionalSnapshot)


# ===========================================================================
# T117-CRTV-03 — Snapshot count increments
# ===========================================================================
def test_T117_CRTV_03_snapshot_count_increments(engine, rules_v1, rules_v2):
    engine.snapshot("E-001", rules_v1, "genesis")
    engine.snapshot("E-002", rules_v2, "add rule-c")
    assert engine.snapshot_count == 2


# ===========================================================================
# T117-CRTV-04 — Head reflects latest snapshot
# ===========================================================================
def test_T117_CRTV_04_head_reflects_latest(engine, rules_v1, rules_v2):
    engine.snapshot("E-001", rules_v1, "genesis")
    snap2 = engine.snapshot("E-002", rules_v2, "second")
    assert engine.head.snapshot_id == snap2.snapshot_id


# ===========================================================================
# T117-CRTV-05 — Genesis snapshot prev_hash is GENESIS constant (CRTV-CHAIN-0)
# ===========================================================================
def test_T117_CRTV_05_genesis_prev_hash(engine, rules_v1):
    from runtime.innovations30.constitutional_rollback import GENESIS_HASH
    snap = engine.snapshot("E-001", rules_v1, "genesis")
    assert snap.prev_hash == GENESIS_HASH


# ===========================================================================
# T117-CRTV-06 — Second snapshot prev_hash matches first digest (CRTV-CHAIN-0)
# ===========================================================================
def test_T117_CRTV_06_chain_link(engine, rules_v1, rules_v2):
    snap1 = engine.snapshot("E-001", rules_v1, "genesis")
    snap2 = engine.snapshot("E-002", rules_v2, "second")
    assert snap2.prev_hash == snap1.snapshot_digest


# ===========================================================================
# T117-CRTV-07 — verify_chain passes on clean ledger
# ===========================================================================
def test_T117_CRTV_07_verify_chain_clean(engine, rules_v1, rules_v2, rules_v3):
    engine.snapshot("E-001", rules_v1, "genesis")
    engine.snapshot("E-002", rules_v2, "second")
    engine.snapshot("E-003", rules_v3, "third")
    assert engine.verify_chain() is True


# ===========================================================================
# T117-CRTV-08 — verify_chain raises on tampered snapshot (CRTV-CHAIN-0)
# ===========================================================================
def test_T117_CRTV_08_verify_chain_tamper(engine, rules_v1, rules_v2):
    from runtime.innovations30.constitutional_rollback import ConstitutionalRollbackError
    engine.snapshot("E-001", rules_v1, "genesis")
    engine.snapshot("E-002", rules_v2, "second")
    # Tamper in-memory
    engine._snapshots[0].prev_hash = "TAMPERED"
    with pytest.raises(ConstitutionalRollbackError, match="CRTV-CHAIN-0"):
        engine.verify_chain()


# ===========================================================================
# T117-CRTV-09 — Snapshot digest is deterministic (CRTV-DETERM-0)
# ===========================================================================
def test_T117_CRTV_09_digest_deterministic(rules_v1):
    from runtime.innovations30.constitutional_rollback import (
        ConstitutionalRollbackEngine,
        GENESIS_HASH,
        ConstitutionalDiff,
        ConstitutionalSnapshot,
        _DeterminismProvider,
    )
    diff = ConstitutionalDiff(added=["RULE-A", "RULE-B"])
    payload = {
        "snapshot_id": "SNAP-E-001-0000",
        "epoch_id": "E-001",
        "rules": rules_v1,
        "amendment_reason": "genesis",
        "author": "DEVADAAD",
        "timestamp": "2026-04-04T00:00:00Z",
        "prev_hash": GENESIS_HASH,
        "diff": diff.to_dict(),
    }
    expected = _DeterminismProvider.digest(payload)
    snap = ConstitutionalSnapshot(
        snapshot_id="SNAP-E-001-0000",
        epoch_id="E-001",
        rules=rules_v1,
        amendment_reason="genesis",
        author="DEVADAAD",
        timestamp="2026-04-04T00:00:00Z",
        prev_hash=GENESIS_HASH,
        diff=diff,
    )
    assert snap.snapshot_digest == expected


# ===========================================================================
# T117-CRTV-10 — Snapshot is appended to JSONL ledger (CRTV-AUDIT-0)
# ===========================================================================
def test_T117_CRTV_10_ledger_written(engine, rules_v1, tmp_ledger):
    engine.snapshot("E-001", rules_v1, "genesis")
    assert os.path.exists(tmp_ledger)
    with open(tmp_ledger) as fh:
        lines = [l for l in fh if l.strip()]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["action"] == "snapshot"


# ===========================================================================
# T117-CRTV-11 — Multiple snapshots produce multiple ledger entries
# ===========================================================================
def test_T117_CRTV_11_multiple_ledger_entries(engine, rules_v1, rules_v2, rules_v3, tmp_ledger):
    engine.snapshot("E-001", rules_v1, "genesis")
    engine.snapshot("E-002", rules_v2, "second")
    engine.snapshot("E-003", rules_v3, "third")
    with open(tmp_ledger) as fh:
        lines = [l for l in fh if l.strip()]
    assert len(lines) == 3


# ===========================================================================
# T117-CRTV-12 — Diff: added rules detected
# ===========================================================================
def test_T117_CRTV_12_diff_added(engine, rules_v1, rules_v2):
    snap1 = engine.snapshot("E-001", rules_v1, "genesis")
    snap2 = engine.snapshot("E-002", rules_v2, "add rule-c")
    diff = engine.diff(snap1.snapshot_id, snap2.snapshot_id)
    assert "RULE-C" in diff.added


# ===========================================================================
# T117-CRTV-13 — Diff: removed rules detected
# ===========================================================================
def test_T117_CRTV_13_diff_removed(engine, rules_v2, rules_v3):
    snap2 = engine.snapshot("E-002", rules_v2, "v2")
    snap3 = engine.snapshot("E-003", rules_v3, "v3")
    diff = engine.diff(snap2.snapshot_id, snap3.snapshot_id)
    assert "RULE-B" in diff.removed


# ===========================================================================
# T117-CRTV-14 — Diff: modified rules detected
# ===========================================================================
def test_T117_CRTV_14_diff_modified(engine, rules_v2, rules_v3):
    snap2 = engine.snapshot("E-002", rules_v2, "v2")
    snap3 = engine.snapshot("E-003", rules_v3, "v3")
    diff = engine.diff(snap2.snapshot_id, snap3.snapshot_id)
    assert "RULE-A" in diff.modified


# ===========================================================================
# T117-CRTV-15 — Diff on identical rules produces zero changes
# ===========================================================================
def test_T117_CRTV_15_diff_identical(engine, rules_v1):
    snap1 = engine.snapshot("E-001", rules_v1, "genesis")
    snap2 = engine.snapshot("E-002", rules_v1, "no change")
    diff = engine.diff(snap1.snapshot_id, snap2.snapshot_id)
    assert diff.change_count == 0


# ===========================================================================
# T117-CRTV-16 — Rollback requires HUMAN-0 token (CRTV-GATE-0)
# ===========================================================================
def test_T117_CRTV_16_rollback_requires_human0(engine, rules_v1, rules_v2):
    from runtime.innovations30.constitutional_rollback import ConstitutionalRollbackError
    snap1 = engine.snapshot("E-001", rules_v1, "genesis")
    engine.snapshot("E-002", rules_v2, "second")
    with pytest.raises(ConstitutionalRollbackError, match="CRTV-GATE-0"):
        engine.rollback(snap1.snapshot_id, "E-003", "reason", "UNAUTHORIZED TOKEN")


# ===========================================================================
# T117-CRTV-17 — Rollback with valid token succeeds
# ===========================================================================
def test_T117_CRTV_17_rollback_succeeds(engine, rules_v1, rules_v2):
    from runtime.innovations30.constitutional_rollback import RollbackEvent
    snap1 = engine.snapshot("E-001", rules_v1, "genesis")
    engine.snapshot("E-002", rules_v2, "second")
    evt = engine.rollback(snap1.snapshot_id, "E-003", "drift detected", RATIFY)
    assert isinstance(evt, RollbackEvent)
    assert evt.target_snapshot_id == snap1.snapshot_id


# ===========================================================================
# T117-CRTV-18 — Rollback restores rules to target state
# ===========================================================================
def test_T117_CRTV_18_rollback_restores_rules(engine, rules_v1, rules_v2):
    snap1 = engine.snapshot("E-001", rules_v1, "genesis")
    engine.snapshot("E-002", rules_v2, "second")
    evt = engine.rollback(snap1.snapshot_id, "E-003", "drift", RATIFY)
    assert evt.restored_rules == rules_v1


# ===========================================================================
# T117-CRTV-19 — Rollback trims in-memory chain to target
# ===========================================================================
def test_T117_CRTV_19_rollback_trims_chain(engine, rules_v1, rules_v2, rules_v3):
    snap1 = engine.snapshot("E-001", rules_v1, "genesis")
    engine.snapshot("E-002", rules_v2, "second")
    engine.snapshot("E-003", rules_v3, "third")
    engine.rollback(snap1.snapshot_id, "E-004", "revert", RATIFY)
    assert engine.snapshot_count == 1
    assert engine.head.snapshot_id == snap1.snapshot_id


# ===========================================================================
# T117-CRTV-20 — Rollback event written to ledger (CRTV-AUDIT-0)
# ===========================================================================
def test_T117_CRTV_20_rollback_ledger_entry(engine, rules_v1, rules_v2, tmp_ledger):
    snap1 = engine.snapshot("E-001", rules_v1, "genesis")
    engine.snapshot("E-002", rules_v2, "second")
    engine.rollback(snap1.snapshot_id, "E-003", "reason", RATIFY)
    with open(tmp_ledger) as fh:
        records = [json.loads(l) for l in fh if l.strip()]
    rollbacks = [r for r in records if r["action"] == "rollback"]
    assert len(rollbacks) == 1
    assert rollbacks[0]["target_snapshot_id"] == snap1.snapshot_id


# ===========================================================================
# T117-CRTV-21 — Rollback to non-existent snapshot raises (CRTV-GATE-0)
# ===========================================================================
def test_T117_CRTV_21_rollback_missing_raises(engine, rules_v1):
    from runtime.innovations30.constitutional_rollback import ConstitutionalRollbackError
    engine.snapshot("E-001", rules_v1, "genesis")
    with pytest.raises(ConstitutionalRollbackError, match="CRTV-GATE-0"):
        engine.rollback("SNAP-NONEXISTENT", "E-002", "reason", RATIFY)


# ===========================================================================
# T117-CRTV-22 — Snapshot with empty epoch_id raises (CRTV-GATE-0)
# ===========================================================================
def test_T117_CRTV_22_snapshot_empty_epoch_raises(engine, rules_v1):
    from runtime.innovations30.constitutional_rollback import ConstitutionalRollbackError
    with pytest.raises(ConstitutionalRollbackError):
        engine.snapshot("", rules_v1, "should fail")


# ===========================================================================
# T117-CRTV-23 — Snapshot with non-dict rules raises (CRTV-GATE-0)
# ===========================================================================
def test_T117_CRTV_23_snapshot_invalid_rules_raises(engine):
    from runtime.innovations30.constitutional_rollback import ConstitutionalRollbackError
    with pytest.raises(ConstitutionalRollbackError):
        engine.snapshot("E-001", ["not", "a", "dict"], "should fail")  # type: ignore


# ===========================================================================
# T117-CRTV-24 — list_snapshots returns all snapshot IDs
# ===========================================================================
def test_T117_CRTV_24_list_snapshots(engine, rules_v1, rules_v2, rules_v3):
    engine.snapshot("E-001", rules_v1, "genesis")
    engine.snapshot("E-002", rules_v2, "second")
    engine.snapshot("E-003", rules_v3, "third")
    ids = engine.list_snapshots()
    assert len(ids) == 3
    assert all(isinstance(i, str) for i in ids)


# ===========================================================================
# T117-CRTV-25 — get_snapshot retrieves by ID
# ===========================================================================
def test_T117_CRTV_25_get_snapshot_by_id(engine, rules_v1, rules_v2):
    snap1 = engine.snapshot("E-001", rules_v1, "genesis")
    engine.snapshot("E-002", rules_v2, "second")
    retrieved = engine.get_snapshot(snap1.snapshot_id)
    assert retrieved is not None
    assert retrieved.rules == rules_v1


# ===========================================================================
# T117-CRTV-26 — get_snapshot returns None for unknown ID
# ===========================================================================
def test_T117_CRTV_26_get_snapshot_unknown(engine, rules_v1):
    engine.snapshot("E-001", rules_v1, "genesis")
    assert engine.get_snapshot("UNKNOWN") is None


# ===========================================================================
# T117-CRTV-27 — Engine reloads from ledger (persistence across instances)
# ===========================================================================
def test_T117_CRTV_27_persistence_across_instances(tmp_ledger, rules_v1, rules_v2):
    from runtime.innovations30.constitutional_rollback import ConstitutionalRollbackEngine
    e1 = ConstitutionalRollbackEngine(ledger_path=tmp_ledger)
    e1.snapshot("E-001", rules_v1, "genesis")
    e1.snapshot("E-002", rules_v2, "second")

    e2 = ConstitutionalRollbackEngine(ledger_path=tmp_ledger)
    assert e2.snapshot_count == 2
    assert e2.head.rules == rules_v2


# ===========================================================================
# T117-CRTV-28 — Reloaded engine passes verify_chain (CRTV-CHAIN-0)
# ===========================================================================
def test_T117_CRTV_28_reloaded_chain_verify(tmp_ledger, rules_v1, rules_v2, rules_v3):
    from runtime.innovations30.constitutional_rollback import ConstitutionalRollbackEngine
    e1 = ConstitutionalRollbackEngine(ledger_path=tmp_ledger)
    e1.snapshot("E-001", rules_v1, "genesis")
    e1.snapshot("E-002", rules_v2, "second")
    e1.snapshot("E-003", rules_v3, "third")

    e2 = ConstitutionalRollbackEngine(ledger_path=tmp_ledger)
    assert e2.verify_chain() is True


# ===========================================================================
# T117-CRTV-29 — RollbackEvent digest is deterministic (CRTV-DETERM-0)
# ===========================================================================
def test_T117_CRTV_29_rollback_event_digest(engine, rules_v1, rules_v2):
    snap1 = engine.snapshot("E-001", rules_v1, "genesis")
    engine.snapshot("E-002", rules_v2, "second")
    evt = engine.rollback(snap1.snapshot_id, "E-003", "test", RATIFY)
    # Digest should be a valid sha256 hex string
    assert len(evt.event_digest) == 64
    assert all(c in "0123456789abcdef" for c in evt.event_digest)


# ===========================================================================
# T117-CRTV-30 — ConstitutionalDiff change_count reflects total changes
# ===========================================================================
def test_T117_CRTV_30_diff_change_count(engine, rules_v1, rules_v3):
    snap1 = engine.snapshot("E-001", rules_v1, "genesis")
    snap3 = engine.snapshot("E-003", rules_v3, "third")
    diff = engine.diff(snap1.snapshot_id, snap3.snapshot_id)
    # rules_v1: A, B  →  rules_v3: A(modified), C(added), D(added), B(removed)
    assert diff.change_count == len(diff.added) + len(diff.removed) + len(diff.modified)
    assert diff.change_count > 0
