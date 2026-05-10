# SPDX-License-Identifier: Apache-2.0
"""
Phase 178 — INNOV-83 · CAE — Constitutional Amendment Executor
Acceptance tests: T178-CAE-01 through T178-CAE-30
30/30 required for governance sign-off.

Governor: DUSTIN L REID
"""

from __future__ import annotations

import json
import tempfile
import uuid
from copy import deepcopy
from pathlib import Path

import pytest

from dorkllm.constitutional_amendment_executor import (
    VALID_ACTIONS,
    VALID_DISPOSITIONS,
    ConstitutionalAmendmentExecutor,
    ExecutionCycleResult,
    _GOVERNOR,
    _HMAC_KEY,
    _INNOV_CODE,
    _MODULE_CODE,
    _hmac_hex,
    _sha256,
    _utc_iso,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_proposal(
    invariant_id: str = "TEST-INV-0",
    disposition: str = "ACCEPTED",
    tier: str = "REINFORCE",
    rationale: str = "Strengthen invariant weight",
    governor: str = _GOVERNOR,
    proposal_id: Optional[str] = None,
) -> dict:
    from typing import Optional
    return {
        "proposal_id": proposal_id or str(uuid.uuid4()),
        "invariant_id": invariant_id,
        "disposition": disposition,
        "tier": tier,
        "rationale": rationale,
        "governor": governor,
    }


def _write_rdp_ledger(path: Path, proposals: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for p in proposals:
            fh.write(json.dumps(p) + "\n")


def _make_cae(tmp_path: Path, proposals: list[dict] | None = None) -> tuple:
    rdp_ledger = tmp_path / "rdp" / "disposition_ledger.jsonl"
    if proposals is not None:
        _write_rdp_ledger(rdp_ledger, proposals)
    cae = ConstitutionalAmendmentExecutor(
        rdp_ledger_path=rdp_ledger,
        ledger_dir=tmp_path / "cae",
        constitution_store=tmp_path / "cae" / "live_constitution.json",
    )
    return cae, rdp_ledger


# ── Constants tests ────────────────────────────────────────────────────────────

@pytest.mark.T178_CAE_01
def test_governor_constant():
    """T178-CAE-01: _GOVERNOR must equal 'DUSTIN L REID'."""
    assert _GOVERNOR == "DUSTIN L REID"


@pytest.mark.T178_CAE_02
def test_innov_code():
    """T178-CAE-02: Module identifiers are correct."""
    assert _INNOV_CODE == "INNOV-83"
    assert _MODULE_CODE == "CAE"


@pytest.mark.T178_CAE_03
def test_valid_actions():
    """T178-CAE-03: VALID_ACTIONS contains the five canonical action types."""
    assert VALID_ACTIONS == frozenset({"REINFORCE", "REVIEW", "STABLE", "ADD", "RETIRE"})


@pytest.mark.T178_CAE_04
def test_valid_dispositions():
    """T178-CAE-04: VALID_DISPOSITIONS contains the three canonical disposition types."""
    assert VALID_DISPOSITIONS == frozenset({"ACCEPTED", "DEFERRED", "REJECTED"})


# ── HMAC / crypto helpers ──────────────────────────────────────────────────────

@pytest.mark.T178_CAE_05
def test_hmac_determinism():
    """T178-CAE-05: _hmac_hex is deterministic."""
    h1 = _hmac_hex("payload", "prev")
    h2 = _hmac_hex("payload", "prev")
    assert h1 == h2


@pytest.mark.T178_CAE_06
def test_hmac_sensitivity():
    """T178-CAE-06: _hmac_hex differs for different payloads."""
    h1 = _hmac_hex("payload_a", "prev")
    h2 = _hmac_hex("payload_b", "prev")
    assert h1 != h2


@pytest.mark.T178_CAE_07
def test_sha256_consistency():
    """T178-CAE-07: _sha256 returns consistent hex digest."""
    h = _sha256("test-invariant")
    assert len(h) == 64
    assert _sha256("test-invariant") == h


@pytest.mark.T178_CAE_08
def test_utc_iso_format(tmp_path):
    """T178-CAE-08: _utc_iso() returns a UTC ISO-8601 string."""
    ts = _utc_iso()
    assert "T" in ts
    assert ts.endswith("+00:00")


# ── Instantiation ─────────────────────────────────────────────────────────────

@pytest.mark.T178_CAE_09
def test_cae_instantiation(tmp_path):
    """T178-CAE-09: CAE instantiates without error."""
    cae, _ = _make_cae(tmp_path, [])
    assert cae is not None


@pytest.mark.T178_CAE_10
def test_initial_chain_valid(tmp_path):
    """T178-CAE-10: Fresh CAE reports chain as valid (empty ledger)."""
    cae, _ = _make_cae(tmp_path, [])
    assert cae.verify_chain() is True


# ── CAE-HUMAN0-0: only ACCEPTED proposals execute ─────────────────────────────

@pytest.mark.T178_CAE_11
def test_deferred_not_executed(tmp_path):
    """T178-CAE-11: CAE-HUMAN0-0 — DEFERRED proposals are not executed."""
    proposals = [_make_proposal(disposition="DEFERRED")]
    cae, _ = _make_cae(tmp_path, proposals)
    result = cae.execute()
    assert result.executed == 0


@pytest.mark.T178_CAE_12
def test_rejected_not_executed(tmp_path):
    """T178-CAE-12: CAE-HUMAN0-0 — REJECTED proposals are not executed."""
    proposals = [_make_proposal(disposition="REJECTED")]
    cae, _ = _make_cae(tmp_path, proposals)
    result = cae.execute()
    assert result.executed == 0


@pytest.mark.T178_CAE_13
def test_accepted_executes(tmp_path):
    """T178-CAE-13: CAE-HUMAN0-0 — ACCEPTED proposal executes successfully."""
    proposals = [_make_proposal(disposition="ACCEPTED", tier="REINFORCE")]
    cae, _ = _make_cae(tmp_path, proposals)
    result = cae.execute()
    assert result.executed == 1
    assert result.rejected == 0


# ── CAE-NOSELF-0 ──────────────────────────────────────────────────────────────

@pytest.mark.T178_CAE_14
def test_self_referential_rejected(tmp_path):
    """T178-CAE-14: CAE-NOSELF-0 — CAE- prefixed invariants are rejected."""
    proposals = [_make_proposal(invariant_id="CAE-CHAIN-0", disposition="ACCEPTED")]
    cae, _ = _make_cae(tmp_path, proposals)
    result = cae.execute()
    assert result.executed == 0
    assert result.rejected == 1


# ── CAE-REPLAY-0 ──────────────────────────────────────────────────────────────

@pytest.mark.T178_CAE_15
def test_duplicate_execution_skipped(tmp_path):
    """T178-CAE-15: CAE-REPLAY-0 — duplicate execution_id is skipped."""
    proposal = _make_proposal(disposition="ACCEPTED")
    cae, _ = _make_cae(tmp_path, [proposal])
    cycle_id = str(uuid.uuid4())
    result1 = cae.execute(cycle_id=cycle_id)
    result2 = cae.execute(cycle_id=cycle_id)
    assert result1.executed == 1
    assert result2.skipped == 1
    assert result2.executed == 0


# ── CAE-SNAPSHOT-0 ────────────────────────────────────────────────────────────

@pytest.mark.T178_CAE_16
def test_snapshot_written_after_execute(tmp_path):
    """T178-CAE-16: CAE-SNAPSHOT-0 — snapshot file is written after cycle."""
    proposals = [_make_proposal(disposition="ACCEPTED")]
    cae, _ = _make_cae(tmp_path, proposals)
    cae.execute()
    snap = cae.get_snapshot()
    assert snap is not None
    assert "constitution_hash" in snap


@pytest.mark.T178_CAE_17
def test_snapshot_hash_matches_constitution(tmp_path):
    """T178-CAE-17: CAE-SNAPSHOT-0 — snapshot hash matches constitution content."""
    proposals = [_make_proposal(disposition="ACCEPTED")]
    cae, _ = _make_cae(tmp_path, proposals)
    result = cae.execute()
    snap = cae.get_snapshot()
    constitution = cae.get_constitution()
    expected = _sha256(json.dumps(constitution, sort_keys=True))
    assert snap["constitution_hash"] == expected


# ── CAE-CHAIN-0 ───────────────────────────────────────────────────────────────

@pytest.mark.T178_CAE_18
def test_execution_ledger_chain_valid(tmp_path):
    """T178-CAE-18: CAE-CHAIN-0 — execution ledger chain is valid after writes."""
    proposals = [_make_proposal(disposition="ACCEPTED") for _ in range(3)]
    cae, _ = _make_cae(tmp_path, proposals)
    cae.execute(cycle_id="cycle-a")
    assert cae.verify_chain() is True


@pytest.mark.T178_CAE_19
def test_corrupted_chain_halts(tmp_path):
    """T178-CAE-19: CAE-CHAIN-0 — corrupt chain hash raises RuntimeError."""
    proposals = [_make_proposal(disposition="ACCEPTED")]
    cae, _ = _make_cae(tmp_path, proposals)
    cae.execute()
    # Corrupt the hmac_chain_hash value in the ledger record
    exec_ledger = tmp_path / "cae" / "amendment_execution_ledger.jsonl"
    lines = exec_ledger.read_text().splitlines()
    rec = json.loads(lines[0])
    rec["hmac_chain_hash"] = "deadbeef" * 8  # valid hex, wrong value
    exec_ledger.write_text(json.dumps(rec) + "\n")
    assert cae.verify_chain() is False


# ── CAE-IMMUT-0: ledger grows append-only ────────────────────────────────────

@pytest.mark.T178_CAE_20
def test_ledger_grows_across_cycles(tmp_path):
    """T178-CAE-20: CAE-IMMUT-0 — ledger record count grows across distinct cycles."""
    cae, rdp_ledger = _make_cae(tmp_path, [])
    for i in range(3):
        _write_rdp_ledger(
            rdp_ledger,
            [_make_proposal(
                invariant_id=f"TEST-INV-{i:03d}",
                proposal_id=f"prop-{i}",
                disposition="ACCEPTED",
            )],
        )
        cae.execute(cycle_id=f"cycle-{i}")
    log = cae.get_execution_log()
    assert len(log) == 3


# ── Amendment action coverage ─────────────────────────────────────────────────

@pytest.mark.T178_CAE_21
def test_reinforce_increments_count(tmp_path):
    """T178-CAE-21: REINFORCE action increments reinforcement_count."""
    proposals = [_make_proposal(invariant_id="INV-A", tier="REINFORCE", disposition="ACCEPTED")]
    cae, _ = _make_cae(tmp_path, proposals)
    cae.execute()
    const = cae.get_constitution()
    assert const["invariants"]["INV-A"]["reinforcement_count"] >= 1


@pytest.mark.T178_CAE_22
def test_review_sets_status(tmp_path):
    """T178-CAE-22: REVIEW action sets status to UNDER_REVIEW."""
    proposals = [_make_proposal(invariant_id="INV-B", tier="REVIEW", disposition="ACCEPTED")]
    cae, _ = _make_cae(tmp_path, proposals)
    cae.execute()
    const = cae.get_constitution()
    assert const["invariants"]["INV-B"]["status"] == "UNDER_REVIEW"


@pytest.mark.T178_CAE_23
def test_stable_sets_status(tmp_path):
    """T178-CAE-23: STABLE action sets status to STABLE."""
    proposals = [_make_proposal(invariant_id="INV-C", tier="STABLE", disposition="ACCEPTED")]
    cae, _ = _make_cae(tmp_path, proposals)
    cae.execute()
    const = cae.get_constitution()
    assert const["invariants"]["INV-C"]["status"] == "STABLE"


@pytest.mark.T178_CAE_24
def test_add_creates_new_invariant(tmp_path):
    """T178-CAE-24: ADD action creates a new invariant entry."""
    proposals = [_make_proposal(invariant_id="NEW-INV-0", tier="ADD", disposition="ACCEPTED")]
    cae, _ = _make_cae(tmp_path, proposals)
    cae.execute()
    const = cae.get_constitution()
    assert "NEW-INV-0" in const["invariants"]


@pytest.mark.T178_CAE_25
def test_retire_marks_retired(tmp_path):
    """T178-CAE-25: RETIRE action marks invariant status RETIRED."""
    # First create the invariant
    proposals_add = [_make_proposal(invariant_id="OLD-INV-0", tier="ADD", disposition="ACCEPTED", proposal_id="p-add")]
    cae, rdp_ledger = _make_cae(tmp_path, proposals_add)
    cae.execute(cycle_id="cycle-add")
    # Then retire it
    _write_rdp_ledger(
        rdp_ledger,
        [_make_proposal(invariant_id="OLD-INV-0", tier="RETIRE", disposition="ACCEPTED", proposal_id="p-retire")],
    )
    cae2 = ConstitutionalAmendmentExecutor(
        rdp_ledger_path=rdp_ledger,
        ledger_dir=tmp_path / "cae",
        constitution_store=tmp_path / "cae" / "live_constitution.json",
    )
    cae2.execute(cycle_id="cycle-retire")
    const = cae2.get_constitution()
    assert const["invariants"]["OLD-INV-0"]["status"] == "RETIRED"


# ── CAE-SCOPE-0 ───────────────────────────────────────────────────────────────

@pytest.mark.T178_CAE_26
def test_scope_rdp_ledger_not_modified(tmp_path):
    """T178-CAE-26: CAE-SCOPE-0 — RDP ledger is not written by CAE."""
    proposals = [_make_proposal(disposition="ACCEPTED")]
    cae, rdp_ledger = _make_cae(tmp_path, proposals)
    mtime_before = rdp_ledger.stat().st_mtime
    cae.execute()
    mtime_after = rdp_ledger.stat().st_mtime
    assert mtime_before == mtime_after


# ── ExecutionCycleResult structure ───────────────────────────────────────────

@pytest.mark.T178_CAE_27
def test_cycle_result_fields(tmp_path):
    """T178-CAE-27: ExecutionCycleResult carries all expected fields."""
    proposals = [_make_proposal(disposition="ACCEPTED")]
    cae, _ = _make_cae(tmp_path, proposals)
    result = cae.execute()
    assert isinstance(result, ExecutionCycleResult)
    assert hasattr(result, "cycle_id")
    assert hasattr(result, "proposals_read")
    assert hasattr(result, "executed")
    assert hasattr(result, "rejected")
    assert hasattr(result, "skipped")
    assert hasattr(result, "snapshot_hash")
    assert hasattr(result, "invariant_count")


# ── Summary and metadata ──────────────────────────────────────────────────────

@pytest.mark.T178_CAE_28
def test_execution_summary(tmp_path):
    """T178-CAE-28: execution_summary() returns structured dict with governor."""
    proposals = [_make_proposal(disposition="ACCEPTED")]
    cae, _ = _make_cae(tmp_path, proposals)
    cae.execute()
    summary = cae.execution_summary()
    assert summary["governor"] == _GOVERNOR
    assert summary["total_executions"] >= 1
    assert summary["chain_valid"] is True


# ── Empty / no-op scenarios ───────────────────────────────────────────────────

@pytest.mark.T178_CAE_29
def test_empty_rdp_ledger_no_error(tmp_path):
    """T178-CAE-29: Empty RDP ledger produces a zero-execution result without error."""
    cae, _ = _make_cae(tmp_path, [])
    result = cae.execute()
    assert result.proposals_read == 0
    assert result.executed == 0


@pytest.mark.T178_CAE_30
def test_get_constitution_read_only(tmp_path):
    """T178-CAE-30: get_constitution() returns a deep copy; mutations don't affect store."""
    proposals = [_make_proposal(invariant_id="INV-Z", tier="ADD", disposition="ACCEPTED")]
    cae, _ = _make_cae(tmp_path, proposals)
    cae.execute()
    const1 = cae.get_constitution()
    const1["invariants"]["MUTATED"] = {"hacked": True}
    const2 = cae.get_constitution()
    assert "MUTATED" not in const2.get("invariants", {})
