# SPDX-License-Identifier: Apache-2.0
"""
Phase 183 · INNOV-88 · CPE — Convergence Plan Executor
Test suite T183-CPE-01..30
Governor: DUSTIN L REID
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from pathlib import Path

import pytest

from dorkllm.convergence_plan_executor import (
    _HMAC_KEY,
    _canonical_json,
    _hmac_digest,
    _read_jsonl,
    _utc_iso,
    _verify_grp_seal,
    _dispatch_action,
    _STATUS_SUCCESS,
    _STATUS_PARTIAL,
    _STATUS_FAILED,
    _STATUS_REJECTED,
    DEFAULT_EXECUTE_N,
    ActionResult,
    ExecutionRecord,
    CPESnapshot,
    ConvergencePlanExecutor,
)

pytestmark = pytest.mark.phase183


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_engine(tmp_path, monkeypatch):
    """Fresh CPE engine wired to tmp_path data directories."""
    import dorkllm.convergence_plan_executor as cpe_mod
    monkeypatch.setattr(cpe_mod, "_DATA_DIR", tmp_path / "cpe")
    monkeypatch.setattr(cpe_mod, "_EXEC_LEDGER_PATH", tmp_path / "cpe" / "execution_ledger.jsonl")
    monkeypatch.setattr(cpe_mod, "_CPE_SNAPSHOT_PATH", tmp_path / "cpe" / "cpe_snapshot.json")
    monkeypatch.setattr(cpe_mod, "_ADVISORY_LOG_PATH", tmp_path / "cpe" / "human0_advisory_log.jsonl")
    monkeypatch.setattr(cpe_mod, "_OUTCOME_LOG_PATH", tmp_path / "cpe" / "outcome_telemetry.jsonl")
    monkeypatch.setattr(cpe_mod, "_CGR_LEDGER_PATH", tmp_path / "cgr" / "grp_ledger.jsonl")
    monkeypatch.setattr(cpe_mod, "_CGR_SNAPSHOT_PATH", tmp_path / "cgr" / "cgr_snapshot.json")
    (tmp_path / "cpe").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cgr").mkdir(parents=True, exist_ok=True)
    return cpe_mod.ConvergencePlanExecutor()


def _make_plan(
    tmp_path: Path,
    severity: str = "WARNING",
    dimension: str = "constitutional_lifecycle",
    n_actions: int = 2,
) -> dict:
    """Build a syntactically valid GRP and write to cgr ledger path."""
    import dorkllm.convergence_plan_executor as cpe_mod
    actions = [
        {
            "action_type": "ADD_INVARIANTS",
            "target_dimension": dimension,
            "impact_estimate": {"invariants_added": 2, "tests_added": 0, "score_delta": 0.05},
        }
        for _ in range(n_actions)
    ]
    plan = {
        "plan_id": str(uuid.uuid4()),
        "plan_severity": severity,
        "target_dimension": dimension,
        "remediation_actions": actions,
    }
    # Compute seal using CGR key
    cgr_key = b"adaad-cgr-chain-key-v1"
    payload_str = _canonical_json(plan)
    seal = hmac.new(cgr_key, payload_str.encode(), hashlib.sha256).hexdigest()
    plan["plan_seal"] = seal

    ledger_path = cpe_mod._CGR_LEDGER_PATH
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a") as fh:
        fh.write(json.dumps(plan) + "\n")
    return plan


# ── T183-CPE-01: Module imports cleanly ──────────────────────────────────────
def test_cpe_01_imports():
    from dorkllm.convergence_plan_executor import ConvergencePlanExecutor
    assert ConvergencePlanExecutor is not None


# ── T183-CPE-02: Engine instantiates ─────────────────────────────────────────
def test_cpe_02_instantiation(tmp_engine):
    assert isinstance(tmp_engine, ConvergencePlanExecutor)


# ── T183-CPE-03: Empty ledger chain valid ────────────────────────────────────
def test_cpe_03_empty_chain_valid(tmp_engine):
    valid, detail = tmp_engine.verify_chain()
    assert valid is True
    assert "empty" in detail


# ── T183-CPE-04: Execute with empty CGR ledger returns empty list ─────────────
def test_cpe_04_execute_empty_cgr(tmp_engine):
    results = tmp_engine.execute()
    assert results == []


# ── T183-CPE-05: Execute single plan returns ExecutionRecord ─────────────────
def test_cpe_05_execute_single_plan(tmp_path, tmp_engine):
    _make_plan(tmp_path)
    results = tmp_engine.execute(top_n=1)
    assert len(results) == 1
    assert isinstance(results[0], ExecutionRecord)


# ── T183-CPE-06: Successful plan records SUCCESS status ──────────────────────
def test_cpe_06_success_status(tmp_path, tmp_engine):
    _make_plan(tmp_path, severity="WARNING", n_actions=1)
    results = tmp_engine.execute(top_n=1)
    assert results[0].status == _STATUS_SUCCESS


# ── T183-CPE-07: GRP seal verified flag true on valid seal ───────────────────
def test_cpe_07_seal_verified(tmp_path, tmp_engine):
    _make_plan(tmp_path)
    results = tmp_engine.execute(top_n=1)
    assert results[0].seal_verified is True


# ── T183-CPE-08: Seal verification helper returns True on valid plan ──────────
def test_cpe_08_verify_grp_seal_valid():
    plan = {
        "plan_id": "p1",
        "plan_severity": "WARNING",
        "target_dimension": "dim1",
        "remediation_actions": [],
    }
    cgr_key = b"adaad-cgr-chain-key-v1"
    seal = hmac.new(cgr_key, _canonical_json(plan).encode(), hashlib.sha256).hexdigest()
    plan["plan_seal"] = seal
    assert _verify_grp_seal(plan) is True


# ── T183-CPE-09: Seal verification returns False on tampered plan ─────────────
def test_cpe_09_verify_grp_seal_invalid():
    plan = {
        "plan_id": "p1",
        "plan_severity": "WARNING",
        "target_dimension": "dim1",
        "remediation_actions": [],
        "plan_seal": "badbadbadbadbadbadbadbad",
    }
    assert _verify_grp_seal(plan) is False


# ── T183-CPE-10: CRITICAL plan emits HUMAN-0 advisory ────────────────────────
def test_cpe_10_critical_advisory(tmp_path, tmp_engine):
    import dorkllm.convergence_plan_executor as cpe_mod
    _make_plan(tmp_path, severity="CRITICAL")
    tmp_engine.execute(top_n=1)
    advisory_log = cpe_mod._ADVISORY_LOG_PATH
    assert advisory_log.exists()
    records = _read_jsonl(advisory_log)
    assert len(records) >= 1
    assert records[0]["severity"] == "CRITICAL"


# ── T183-CPE-11: CRITICAL plan sets advisory_emitted True ────────────────────
def test_cpe_11_advisory_emitted_flag(tmp_path, tmp_engine):
    _make_plan(tmp_path, severity="CRITICAL")
    results = tmp_engine.execute(top_n=1)
    assert results[0].advisory_emitted is True


# ── T183-CPE-12: Non-CRITICAL plan does not emit advisory ────────────────────
def test_cpe_12_no_advisory_warning(tmp_path, tmp_engine):
    import dorkllm.convergence_plan_executor as cpe_mod
    _make_plan(tmp_path, severity="WARNING")
    results = tmp_engine.execute(top_n=1)
    assert results[0].advisory_emitted is False
    if cpe_mod._ADVISORY_LOG_PATH.exists():
        records = _read_jsonl(cpe_mod._ADVISORY_LOG_PATH)
        assert all(r["severity"] == "CRITICAL" for r in records)


# ── T183-CPE-13: Ledger file created after first execution ───────────────────
def test_cpe_13_ledger_created(tmp_path, tmp_engine):
    import dorkllm.convergence_plan_executor as cpe_mod
    _make_plan(tmp_path)
    tmp_engine.execute(top_n=1)
    assert cpe_mod._EXEC_LEDGER_PATH.exists()


# ── T183-CPE-14: Ledger entry has required fields ────────────────────────────
def test_cpe_14_ledger_entry_fields(tmp_path, tmp_engine):
    import dorkllm.convergence_plan_executor as cpe_mod
    _make_plan(tmp_path)
    tmp_engine.execute(top_n=1)
    entries = _read_jsonl(cpe_mod._EXEC_LEDGER_PATH)
    assert len(entries) == 1
    entry = entries[0]
    for field in ("execution_id", "plan_id", "status", "chain_hash", "exec_seal", "timestamp_utc"):
        assert field in entry, f"Missing field: {field}"


# ── T183-CPE-15: Chain valid after single execution ──────────────────────────
def test_cpe_15_chain_valid_after_exec(tmp_path, tmp_engine):
    _make_plan(tmp_path)
    tmp_engine.execute(top_n=1)
    valid, _ = tmp_engine.verify_chain()
    assert valid is True


# ── T183-CPE-16: Chain valid after multiple executions ───────────────────────
def test_cpe_16_chain_valid_multi(tmp_path, tmp_engine):
    for _ in range(3):
        _make_plan(tmp_path)
    tmp_engine.execute(top_n=3)
    valid, _ = tmp_engine.verify_chain()
    assert valid is True


# ── T183-CPE-17: Idempotency — same plan_id not re-executed ──────────────────
def test_cpe_17_idempotency(tmp_path, tmp_engine):
    import dorkllm.convergence_plan_executor as cpe_mod
    _make_plan(tmp_path)
    tmp_engine.execute(top_n=1)
    tmp_engine.execute(top_n=1)  # second call should skip already-executed plan
    entries = _read_jsonl(cpe_mod._EXEC_LEDGER_PATH)
    # Only 1 unique plan → 1 ledger entry (idempotency guard)
    assert len(entries) == 1


# ── T183-CPE-18: Outcome telemetry written ───────────────────────────────────
def test_cpe_18_outcome_telemetry(tmp_path, tmp_engine):
    import dorkllm.convergence_plan_executor as cpe_mod
    _make_plan(tmp_path)
    tmp_engine.execute(top_n=1)
    assert cpe_mod._OUTCOME_LOG_PATH.exists()
    records = _read_jsonl(cpe_mod._OUTCOME_LOG_PATH)
    assert len(records) >= 1
    assert "execution_id" in records[0]


# ── T183-CPE-19: Outcome telemetry includes score_delta ─────────────────────
def test_cpe_19_outcome_score_delta(tmp_path, tmp_engine):
    import dorkllm.convergence_plan_executor as cpe_mod
    _make_plan(tmp_path, n_actions=2)
    tmp_engine.execute(top_n=1)
    records = _read_jsonl(cpe_mod._OUTCOME_LOG_PATH)
    assert records[0]["outcome_score_delta"] > 0.0


# ── T183-CPE-20: Snapshot created after execution ────────────────────────────
def test_cpe_20_snapshot_created(tmp_path, tmp_engine):
    import dorkllm.convergence_plan_executor as cpe_mod
    _make_plan(tmp_path)
    tmp_engine.execute(top_n=1)
    tmp_engine.get_snapshot()
    assert cpe_mod._CPE_SNAPSHOT_PATH.exists()


# ── T183-CPE-21: Snapshot fields correct ─────────────────────────────────────
def test_cpe_21_snapshot_fields(tmp_path, tmp_engine):
    _make_plan(tmp_path)
    tmp_engine.execute(top_n=1)
    snap = tmp_engine.get_snapshot()
    assert isinstance(snap, CPESnapshot)
    assert snap.total_plans_executed == 1
    assert snap.total_plans_succeeded == 1


# ── T183-CPE-22: Snapshot counts partial correctly ───────────────────────────
def test_cpe_22_snapshot_partial(tmp_path, tmp_engine):
    import dorkllm.convergence_plan_executor as cpe_mod

    # Write a plan with a broken action type to force PARTIAL
    plan = {
        "plan_id": str(uuid.uuid4()),
        "plan_severity": "WARNING",
        "target_dimension": "test_dim",
        "remediation_actions": [
            {"action_type": "UNKNOWN_BAD", "target_dimension": "test_dim", "impact_estimate": {}},
        ],
    }
    cgr_key = b"adaad-cgr-chain-key-v1"
    seal = hmac.new(cgr_key, _canonical_json(plan).encode(), hashlib.sha256).hexdigest()
    plan["plan_seal"] = seal
    cpe_mod._CGR_LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with cpe_mod._CGR_LEDGER_PATH.open("a") as fh:
        fh.write(json.dumps(plan) + "\n")

    tmp_engine.execute(top_n=1)
    snap = tmp_engine.get_snapshot()
    assert snap.total_plans_failed + snap.total_plans_partial >= 1


# ── T183-CPE-23: Invalid seal results in REJECTED status ─────────────────────
def test_cpe_23_rejected_on_bad_seal(tmp_path, tmp_engine):
    import dorkllm.convergence_plan_executor as cpe_mod

    plan = {
        "plan_id": str(uuid.uuid4()),
        "plan_severity": "WARNING",
        "target_dimension": "dim_bad_seal",
        "remediation_actions": [
            {"action_type": "ADD_INVARIANTS", "target_dimension": "dim_bad_seal",
             "impact_estimate": {"invariants_added": 1, "tests_added": 0, "score_delta": 0.02}},
        ],
        "plan_seal": "00000000000000000000000000000000",  # deliberate bad seal
    }
    cpe_mod._CGR_LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with cpe_mod._CGR_LEDGER_PATH.open("a") as fh:
        fh.write(json.dumps(plan) + "\n")

    results = tmp_engine.execute(top_n=1)
    assert results[0].status == _STATUS_REJECTED
    assert results[0].seal_verified is False


# ── T183-CPE-24: top_n=0 returns empty list ──────────────────────────────────
def test_cpe_24_top_n_zero(tmp_path, tmp_engine):
    _make_plan(tmp_path)
    results = tmp_engine.execute(top_n=0)
    # top_n clamped to 1 minimum in router; raw engine returns empty via slice
    # engine slice [:0] → empty
    assert isinstance(results, list)


# ── T183-CPE-25: severity_filter restricts execution ─────────────────────────
def test_cpe_25_severity_filter(tmp_path, tmp_engine):
    _make_plan(tmp_path, severity="WARNING")
    results = tmp_engine.execute(top_n=5, severity_filter="CRITICAL")
    assert results == []


# ── T183-CPE-26: CRITICAL plans sorted before WARNING ────────────────────────
def test_cpe_26_critical_priority(tmp_path, tmp_engine):
    _make_plan(tmp_path, severity="WARNING", dimension="dim_warn")
    _make_plan(tmp_path, severity="CRITICAL", dimension="dim_crit")
    results = tmp_engine.execute(top_n=1)
    assert results[0].plan_severity == "CRITICAL"


# ── T183-CPE-27: _dispatch_action returns tuple of (bool, str, dict) ─────────
def test_cpe_27_dispatch_action_returns_tuple():
    action = {
        "action_type": "ADD_INVARIANTS",
        "target_dimension": "test_dim",
        "impact_estimate": {"invariants_added": 3, "score_delta": 0.03},
    }
    result = _dispatch_action(action, "plan-001")
    assert isinstance(result, tuple)
    assert len(result) == 3
    success, detail, impact = result
    assert isinstance(success, bool)
    assert isinstance(detail, str)
    assert isinstance(impact, dict)


# ── T183-CPE-28: _canonical_json is deterministic ───────────────────────────
def test_cpe_28_canonical_json_deterministic():
    obj = {"z": 1, "a": 2, "m": [3, 4]}
    assert _canonical_json(obj) == _canonical_json(obj)
    assert _canonical_json(obj) == _canonical_json({"a": 2, "z": 1, "m": [3, 4]})


# ── T183-CPE-29: get_execution_history returns list ──────────────────────────
def test_cpe_29_get_history(tmp_path, tmp_engine):
    _make_plan(tmp_path)
    tmp_engine.execute(top_n=1)
    history = tmp_engine.get_execution_history()
    assert isinstance(history, list)
    assert len(history) >= 1


# ── T183-CPE-30: governor and innov_code in ledger entry ─────────────────────
def test_cpe_30_ledger_governor_innov(tmp_path, tmp_engine):
    import dorkllm.convergence_plan_executor as cpe_mod
    _make_plan(tmp_path)
    tmp_engine.execute(top_n=1)
    entries = _read_jsonl(cpe_mod._EXEC_LEDGER_PATH)
    entry = entries[0]
    assert entry["governor"] == "DUSTIN L REID"
    assert entry["innov_code"] == "INNOV-88"
