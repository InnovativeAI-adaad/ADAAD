# SPDX-License-Identifier: Apache-2.0
"""
Phase 180 · INNOV-85 · CAR — Constitutional Amendment Rollback
Acceptance tests: T180-CAR-01 … T180-CAR-30  (30/30 required)
"""
from __future__ import annotations

import json
import tempfile
from copy import deepcopy
from pathlib import Path

import pytest

from dorkllm.constitutional_amendment_rollback import (
    CRITICAL_SCSI_THRESHOLD,
    HUMAN0_TRIGGER_TOKEN_PREFIX,
    ConstitutionalAmendmentRollback,
    _hmac_hex,
    _HMAC_KEY,
    _INVERSE_ACTIONS,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_cae_record(
    execution_id: str = "CAE-TEST-001",
    invariant_id: str = "STABLE-INV-0",
    action: str = "REINFORCE",
    status: str = "EXECUTED",
    timestamp: str = "2026-05-10T00:00:00+00:00",
    snapshot_before: dict | None = None,
) -> dict:
    return {
        "execution_id": execution_id,
        "invariant_id": invariant_id,
        "action": action,
        "status": status,
        "timestamp": timestamp,
        "snapshot_before": snapshot_before or {invariant_id: {"weight": 0.5, "status": "active"}},
    }


def _make_constitution(invariants: dict | None = None) -> dict:
    return {
        "invariants": invariants or {"STABLE-INV-0": {"weight": 0.9, "status": "active"}},
        "schema_version": "1.0",
    }


def _make_scsi_snapshot(scsi: float = 0.30, status: str = "CRITICAL") -> dict:
    return {"scsi": scsi, "scsi_status": status}


@pytest.fixture
def tmp_engine(tmp_path):
    cae_ledger = tmp_path / "cae" / "amendment_execution_ledger.jsonl"
    cae_ledger.parent.mkdir(parents=True)
    csc_snapshot = tmp_path / "csc" / "scsi_snapshot.json"
    csc_snapshot.parent.mkdir(parents=True)
    constitution = tmp_path / "cae" / "live_constitution.json"
    constitution.write_text(json.dumps(_make_constitution()), encoding="utf-8")

    engine = ConstitutionalAmendmentRollback(
        data_dir=tmp_path / "car",
        cae_ledger_path=cae_ledger,
        csc_snapshot_path=csc_snapshot,
        constitution_path=constitution,
    )
    return engine, tmp_path, cae_ledger, csc_snapshot, constitution


# ── T180-CAR-01: Module imports without error ─────────────────────────────────
def test_01_module_import():
    from dorkllm.constitutional_amendment_rollback import ConstitutionalAmendmentRollback
    assert ConstitutionalAmendmentRollback is not None


# ── T180-CAR-02: Engine instantiates and creates data dir ─────────────────────
def test_02_instantiation(tmp_engine):
    engine, tmp_path, *_ = tmp_engine
    assert (tmp_path / "car").is_dir()


# ── T180-CAR-03: run_auto returns no-op when SCSI is OK ──────────────────────
def test_03_auto_noop_when_ok(tmp_engine):
    engine, tmp_path, cae_ledger, csc_snapshot, _ = tmp_engine
    csc_snapshot.write_text(json.dumps({"scsi": 0.85, "scsi_status": "OK"}))
    result = engine.run_auto()
    assert result.rolled_back == 0
    assert "no rollback triggered" in result.trigger_detail


# ── T180-CAR-04: run_auto returns no-op when SCSI is WARNING ─────────────────
def test_04_auto_noop_when_warning(tmp_engine):
    engine, tmp_path, cae_ledger, csc_snapshot, _ = tmp_engine
    csc_snapshot.write_text(json.dumps({"scsi": 0.65, "scsi_status": "WARNING"}))
    result = engine.run_auto()
    assert result.rolled_back == 0


# ── T180-CAR-05: run_auto triggers on CRITICAL SCSI ──────────────────────────
def test_05_auto_triggers_on_critical(tmp_engine):
    engine, tmp_path, cae_ledger, csc_snapshot, _ = tmp_engine
    cae_ledger.write_text(json.dumps(_make_cae_record()) + "\n")
    csc_snapshot.write_text(json.dumps(_make_scsi_snapshot(0.30, "CRITICAL")))
    result = engine.run_auto()
    assert result.rolled_back == 1


# ── T180-CAR-06: CAR-SCOPE-0 — only EXECUTED amendments are eligible ─────────
def test_06_scope_only_executed(tmp_engine):
    engine, tmp_path, cae_ledger, csc_snapshot, _ = tmp_engine
    cae_ledger.write_text(json.dumps(_make_cae_record(status="REJECTED")) + "\n")
    csc_snapshot.write_text(json.dumps(_make_scsi_snapshot()))
    result = engine.run_auto()
    assert result.rolled_back == 0
    assert result.candidates_found == 0


# ── T180-CAR-07: CAR-DOUBLE-0 — no duplicate rollbacks ───────────────────────
def test_07_double_rollback_blocked(tmp_engine):
    engine, tmp_path, cae_ledger, csc_snapshot, _ = tmp_engine
    rec = _make_cae_record()
    cae_ledger.write_text(json.dumps(rec) + "\n")
    csc_snapshot.write_text(json.dumps(_make_scsi_snapshot()))

    result1 = engine.run_auto()
    assert result1.rolled_back == 1

    csc_snapshot.write_text(json.dumps(_make_scsi_snapshot()))
    result2 = engine.run_auto()
    assert result2.rolled_back == 0
    assert result2.skipped == 1


# ── T180-CAR-08: CAR-CHAIN-0 — ledger chain is valid after writes ────────────
def test_08_chain_integrity_after_rollback(tmp_engine):
    engine, tmp_path, cae_ledger, csc_snapshot, _ = tmp_engine
    cae_ledger.write_text(json.dumps(_make_cae_record()) + "\n")
    csc_snapshot.write_text(json.dumps(_make_scsi_snapshot()))
    engine.run_auto()
    assert engine.verify_chain_integrity() is True


# ── T180-CAR-09: CAR-CHAIN-0 — tampered digest fails chain verify ────────────
def test_09_tampered_digest_fails_chain(tmp_engine):
    engine, tmp_path, cae_ledger, csc_snapshot, _ = tmp_engine
    cae_ledger.write_text(json.dumps(_make_cae_record()) + "\n")
    csc_snapshot.write_text(json.dumps(_make_scsi_snapshot()))
    engine.run_auto()

    ledger_path = tmp_path / "car" / "rollback_execution_ledger.jsonl"
    content = ledger_path.read_text()
    tampered = content.replace('"ROLLED_BACK"', '"TAMPERED"')
    ledger_path.write_text(tampered)
    assert engine.verify_chain_integrity() is False


# ── T180-CAR-10: CAR-IMMUT-0 — empty ledger passes chain verify ──────────────
def test_10_empty_ledger_chain_ok(tmp_engine):
    engine, *_ = tmp_engine
    assert engine.verify_chain_integrity() is True


# ── T180-CAR-11: CAR-HUMAN0-0 — manual rollback requires valid token ─────────
def test_11_manual_requires_valid_token(tmp_engine):
    engine, tmp_path, cae_ledger, *_ = tmp_engine
    cae_ledger.write_text(json.dumps(_make_cae_record()) + "\n")
    result = engine.run_manual("CAE-TEST-001", "INVALID-TOKEN")
    assert result.rolled_back == 0
    assert result.rejected == 1
    assert "CAR-HUMAN0-0" in result.errors[0]


# ── T180-CAR-12: CAR-HUMAN0-0 — valid token allows manual rollback ───────────
def test_12_manual_valid_token_succeeds(tmp_engine):
    engine, tmp_path, cae_ledger, csc_snapshot, _ = tmp_engine
    cae_ledger.write_text(json.dumps(_make_cae_record()) + "\n")
    token = f"{HUMAN0_TRIGGER_TOKEN_PREFIX}DUSTIN-2026-05-10"
    result = engine.run_manual("CAE-TEST-001", token)
    assert result.rolled_back == 1


# ── T180-CAR-13: CAR-HUMAN0-0 — empty token rejected ────────────────────────
def test_13_empty_token_rejected(tmp_engine):
    engine, tmp_path, cae_ledger, *_ = tmp_engine
    cae_ledger.write_text(json.dumps(_make_cae_record()) + "\n")
    result = engine.run_manual("CAE-TEST-001", "")
    assert result.rejected == 1


# ── T180-CAR-14: CAR-AUDIT-0 — ledger entry written for SKIPPED ──────────────
def test_14_skipped_entry_in_ledger(tmp_engine):
    engine, tmp_path, cae_ledger, csc_snapshot, _ = tmp_engine
    cae_ledger.write_text(json.dumps(_make_cae_record()) + "\n")
    csc_snapshot.write_text(json.dumps(_make_scsi_snapshot()))
    engine.run_auto()
    csc_snapshot.write_text(json.dumps(_make_scsi_snapshot()))
    engine.run_auto()  # triggers SKIPPED
    entries = engine.get_ledger_entries()
    statuses = [e["status"] for e in entries]
    assert "SKIPPED" in statuses


# ── T180-CAR-15: CAR-PERSIST-0 — rollback state survives reload ──────────────
def test_15_state_persists(tmp_engine):
    engine, tmp_path, cae_ledger, csc_snapshot, constitution = tmp_engine
    cae_ledger.write_text(json.dumps(_make_cae_record()) + "\n")
    csc_snapshot.write_text(json.dumps(_make_scsi_snapshot()))
    engine.run_auto()

    engine2 = ConstitutionalAmendmentRollback(
        data_dir=tmp_path / "car",
        cae_ledger_path=cae_ledger,
        csc_snapshot_path=csc_snapshot,
        constitution_path=constitution,
    )
    state = engine2.get_rollback_state()
    assert state["total_rolled_back"] == 1


# ── T180-CAR-16: CAR-DETERM-0 — no datetime.now() at call sites ──────────────
def test_16_no_datetime_now_in_source():
    import ast
    source = Path("dorkllm/constitutional_amendment_rollback.py").read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "now":
            if isinstance(node.value, ast.Attribute) and node.value.attr == "datetime":
                # Only allowed in _utc_iso
                pytest.fail("datetime.now() called outside _utc_iso()")


# ── T180-CAR-17: REINFORCE inverse restores prior weight ─────────────────────
def test_17_reinforce_inverse_restores_weight(tmp_engine):
    engine, tmp_path, cae_ledger, csc_snapshot, constitution = tmp_engine
    constitution.write_text(json.dumps({
        "invariants": {"STABLE-INV-0": {"weight": 0.9, "status": "active"}},
        "schema_version": "1.0",
    }))
    rec = _make_cae_record(
        action="REINFORCE",
        snapshot_before={"STABLE-INV-0": {"weight": 0.5, "status": "active"}},
    )
    cae_ledger.write_text(json.dumps(rec) + "\n")
    csc_snapshot.write_text(json.dumps(_make_scsi_snapshot()))
    engine.run_auto()
    updated = json.loads(constitution.read_text())
    assert updated["invariants"]["STABLE-INV-0"]["weight"] == 0.5


# ── T180-CAR-18: ADD inverse removes the added invariant ─────────────────────
def test_18_add_inverse_removes_invariant(tmp_engine):
    engine, tmp_path, cae_ledger, csc_snapshot, constitution = tmp_engine
    constitution.write_text(json.dumps({
        "invariants": {"NEW-INV-0": {"weight": 0.8, "status": "active"}},
        "schema_version": "1.0",
    }))
    rec = _make_cae_record(invariant_id="NEW-INV-0", action="ADD")
    cae_ledger.write_text(json.dumps(rec) + "\n")
    csc_snapshot.write_text(json.dumps(_make_scsi_snapshot()))
    engine.run_auto()
    updated = json.loads(constitution.read_text())
    assert "NEW-INV-0" not in updated["invariants"]


# ── T180-CAR-19: RETIRE inverse un-retires the invariant ─────────────────────
def test_19_retire_inverse_unretires(tmp_engine):
    engine, tmp_path, cae_ledger, csc_snapshot, constitution = tmp_engine
    constitution.write_text(json.dumps({
        "invariants": {"OLD-INV-0": {"weight": 0.7, "status": "retired", "retired": True}},
        "schema_version": "1.0",
    }))
    rec = _make_cae_record(
        invariant_id="OLD-INV-0",
        action="RETIRE",
        snapshot_before={"OLD-INV-0": {"weight": 0.7, "status": "active", "retired": False}},
    )
    cae_ledger.write_text(json.dumps(rec) + "\n")
    csc_snapshot.write_text(json.dumps(_make_scsi_snapshot()))
    engine.run_auto()
    updated = json.loads(constitution.read_text())
    assert updated["invariants"]["OLD-INV-0"]["status"] == "active"
    assert updated["invariants"]["OLD-INV-0"]["retired"] is False


# ── T180-CAR-20: Manual rollback on non-existent execution_id ────────────────
def test_20_manual_nonexistent_execution_id(tmp_engine):
    engine, tmp_path, cae_ledger, *_ = tmp_engine
    cae_ledger.write_text(json.dumps(_make_cae_record()) + "\n")
    result = engine.run_manual("CAE-DOES-NOT-EXIST", f"{HUMAN0_TRIGGER_TOKEN_PREFIX}TEST")
    assert result.rolled_back == 0
    assert result.candidates_found == 0


# ── T180-CAR-21: Multiple CAE records — only most recent rolled back ──────────
def test_21_only_most_recent_rolled_back(tmp_engine):
    engine, tmp_path, cae_ledger, csc_snapshot, _ = tmp_engine
    rec1 = _make_cae_record("CAE-001", timestamp="2026-05-10T01:00:00+00:00")
    rec2 = _make_cae_record("CAE-002", timestamp="2026-05-10T02:00:00+00:00")
    cae_ledger.write_text(
        json.dumps(rec1) + "\n" + json.dumps(rec2) + "\n"
    )
    csc_snapshot.write_text(json.dumps(_make_scsi_snapshot()))
    result = engine.run_auto()
    assert result.rolled_back == 1
    # Verify it was the newest (CAE-002)
    entries = engine.get_ledger_entries()
    assert entries[0]["execution_id"] == "CAE-002"


# ── T180-CAR-22: get_ledger_entries returns all records ──────────────────────
def test_22_get_ledger_entries(tmp_engine):
    engine, tmp_path, cae_ledger, csc_snapshot, _ = tmp_engine
    cae_ledger.write_text(json.dumps(_make_cae_record()) + "\n")
    csc_snapshot.write_text(json.dumps(_make_scsi_snapshot()))
    engine.run_auto()
    entries = engine.get_ledger_entries()
    assert len(entries) == 1
    assert entries[0]["status"] == "ROLLED_BACK"


# ── T180-CAR-23: CAR-SEAL-0 — digest field is non-empty ──────────────────────
def test_23_digest_non_empty(tmp_engine):
    engine, tmp_path, cae_ledger, csc_snapshot, _ = tmp_engine
    cae_ledger.write_text(json.dumps(_make_cae_record()) + "\n")
    csc_snapshot.write_text(json.dumps(_make_scsi_snapshot()))
    engine.run_auto()
    entries = engine.get_ledger_entries()
    assert entries[0]["digest"] != ""
    assert len(entries[0]["digest"]) == 64  # SHA-256 hex


# ── T180-CAR-24: CAR-CHAIN-0 — genesis digest is deterministic ───────────────
def test_24_genesis_digest_deterministic():
    d1 = _hmac_hex(_HMAC_KEY, "CAR-GENESIS-180")
    d2 = _hmac_hex(_HMAC_KEY, "CAR-GENESIS-180")
    assert d1 == d2
    assert len(d1) == 64


# ── T180-CAR-25: INNOV-85 module constant set correctly ──────────────────────
def test_25_innov_constant():
    from dorkllm.constitutional_amendment_rollback import _INNOV_CODE, _MODULE_CODE
    assert _INNOV_CODE == "INNOV-85"
    assert _MODULE_CODE == "CAR"


# ── T180-CAR-26: SPDX header present ────────────────────────────────────────
def test_26_spdx_header():
    src = Path("dorkllm/constitutional_amendment_rollback.py").read_text()
    assert "SPDX-License-Identifier: Apache-2.0" in src


# ── T180-CAR-27: CAR-TRIGGER-0 constant is 0.50 ─────────────────────────────
def test_27_critical_threshold_constant():
    assert CRITICAL_SCSI_THRESHOLD == 0.50


# ── T180-CAR-28: Inverse actions cover all CAE action types ──────────────────
def test_28_inverse_actions_complete():
    cae_actions = {"REINFORCE", "ADD", "RETIRE", "REVIEW", "STABLE"}
    for action in cae_actions:
        assert action in _INVERSE_ACTIONS, f"Missing inverse for {action}"


# ── T180-CAR-29: Auto rollback absent snapshot is safe no-op ─────────────────
def test_29_missing_snapshot_is_safe(tmp_engine):
    engine, tmp_path, cae_ledger, csc_snapshot, _ = tmp_engine
    # Do NOT write snapshot file — engine should default to OK
    cae_ledger.write_text(json.dumps(_make_cae_record()) + "\n")
    result = engine.run_auto()
    assert result.rolled_back == 0


# ── T180-CAR-30: CAR-PERSIST-0 — ledger dir created on init ──────────────────
def test_30_data_dir_created(tmp_path):
    car_dir = tmp_path / "car_new_dir"
    assert not car_dir.exists()
    engine = ConstitutionalAmendmentRollback(
        data_dir=car_dir,
        cae_ledger_path=tmp_path / "cae.jsonl",
        csc_snapshot_path=tmp_path / "scsi.json",
        constitution_path=tmp_path / "constitution.json",
    )
    assert car_dir.is_dir()
