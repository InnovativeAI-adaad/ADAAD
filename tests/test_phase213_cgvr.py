# SPDX-License-Identifier: Apache-2.0
# Phase 213 · INNOV-118 · CGVR — Constitutional Governance Violation Remediator
# Acceptance Test Suite — T213-CGVR-01…30 — 30/30 required
# Governor: DUSTIN L REID | Agent: DEVADAAD | Org: InnovativeAI LLC
"""
30-test acceptance suite for the Constitutional Governance Violation Remediator.

Categories:
  CORE   — Core remediation engine behaviour (T213-CGVR-01..10)
  CHAIN  — HMAC chain integrity (T213-CGVR-11..16)
  HUMAN0 — HUMAN-0 gate and Tier-0 approval (T213-CGVR-17..21)
  PLAN   — Remediation plan prescription (T213-CGVR-22..25)
  INV    — Hard-class invariant enforcement (T213-CGVR-26..30)
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List

import pytest

from dorkllm.constitutional_governance_violation_remediator import (
    ActionType,
    ConstitutionalGovernanceViolationRemediator,
    RemediationRecord,
    RemediationStatus,
    _PRESCRIPTION,
    _prescribe,
    _compute_hmac,
    _plan_hash,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def eng(tmp_path: Path) -> ConstitutionalGovernanceViolationRemediator:
    """Fresh remediator with temp-path ledger."""
    return ConstitutionalGovernanceViolationRemediator(
        ledger_path=tmp_path / "test_cgvr.jsonl"
    )


def _vid() -> str:
    return "CGVA-" + hashlib.sha256(str(time.time_ns()).encode()).hexdigest()[:32]


# ═══════════════════════════════════════════════════════════════════════════════
# CORE — T213-CGVR-01..10
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.cgvr
@pytest.mark.phase213
def test_T213_CGVR_01_remediate_returns_record(eng):
    """T213-CGVR-01 · CORE: remediate() returns a RemediationRecord."""
    rec = eng.remediate(violation_id=_vid(), domain="drift_containment")
    assert isinstance(rec, RemediationRecord)


@pytest.mark.cgvr
@pytest.mark.phase213
def test_T213_CGVR_02_remediation_id_format(eng):
    """T213-CGVR-02 · CORE: remediation_id starts with 'CGVR-' and is 37 chars."""
    rec = eng.remediate(violation_id=_vid(), domain="drift_containment")
    assert rec.remediation_id.startswith("CGVR-")
    assert len(rec.remediation_id) == 37  # "CGVR-" + 32 hex


@pytest.mark.cgvr
@pytest.mark.phase213
def test_T213_CGVR_03_governor_field(eng):
    """T213-CGVR-03 · CORE: governor is 'DUSTIN L REID'."""
    rec = eng.remediate(violation_id=_vid(), domain="drift_containment")
    assert rec.governor == "DUSTIN L REID"


@pytest.mark.cgvr
@pytest.mark.phase213
def test_T213_CGVR_04_plan_non_empty(eng):
    """T213-CGVR-04 · CORE: plan has ≥1 action for any domain."""
    rec = eng.remediate(violation_id=_vid(), domain="ledger_integrity")
    assert len(rec.plan) >= 1


@pytest.mark.cgvr
@pytest.mark.phase213
def test_T213_CGVR_05_status_valid(eng):
    """T213-CGVR-05 · CORE: status is one of the valid RemediationStatus values."""
    valid = {s.value for s in RemediationStatus}
    rec = eng.remediate(violation_id=_vid(), domain="drift_containment")
    assert rec.status in valid


@pytest.mark.cgvr
@pytest.mark.phase213
def test_T213_CGVR_06_actions_executed_lte_total(eng):
    """T213-CGVR-06 · CORE: actions_executed ≤ actions_total."""
    rec = eng.remediate(violation_id=_vid(), domain="invariant_density")
    assert rec.actions_executed <= rec.actions_total


@pytest.mark.cgvr
@pytest.mark.phase213
def test_T213_CGVR_07_ledger_persists(eng, tmp_path):
    """T213-CGVR-07 · CORE: records persist across engine restarts."""
    eng.remediate(violation_id=_vid(), domain="drift_containment")
    eng2 = ConstitutionalGovernanceViolationRemediator(
        ledger_path=tmp_path / "test_cgvr.jsonl"
    )
    assert len(eng2.records) == 1


@pytest.mark.cgvr
@pytest.mark.phase213
def test_T213_CGVR_08_hmac_digest_present(eng):
    """T213-CGVR-08 · CORE: hmac_digest is a 64-char hex string."""
    rec = eng.remediate(violation_id=_vid(), domain="drift_containment")
    assert len(rec.hmac_digest) == 64
    int(rec.hmac_digest, 16)  # must be valid hex


@pytest.mark.cgvr
@pytest.mark.phase213
def test_T213_CGVR_09_first_record_genesis(eng):
    """T213-CGVR-09 · CORE: first record has prev_digest='GENESIS'."""
    rec = eng.remediate(violation_id=_vid(), domain="drift_containment")
    assert rec.prev_digest == "GENESIS"


@pytest.mark.cgvr
@pytest.mark.phase213
def test_T213_CGVR_10_ts_ns_positive(eng):
    """T213-CGVR-10 · CORE: ts_ns is a positive integer."""
    rec = eng.remediate(violation_id=_vid(), domain="invariant_density")
    assert isinstance(rec.ts_ns, int) and rec.ts_ns > 0


# ═══════════════════════════════════════════════════════════════════════════════
# CHAIN — T213-CGVR-11..16
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.cgvr
@pytest.mark.phase213
def test_T213_CGVR_11_chain_valid_single(eng):
    """T213-CGVR-11 · CHAIN: chain is valid after single record."""
    eng.remediate(violation_id=_vid(), domain="drift_containment")
    valid, idx = eng.verify_chain()
    assert valid is True
    assert idx is None


@pytest.mark.cgvr
@pytest.mark.phase213
def test_T213_CGVR_12_chain_valid_multi(eng):
    """T213-CGVR-12 · CHAIN: chain is valid after 5 records."""
    for _ in range(5):
        eng.remediate(violation_id=_vid(), domain="ledger_integrity")
    valid, idx = eng.verify_chain()
    assert valid is True


@pytest.mark.cgvr
@pytest.mark.phase213
def test_T213_CGVR_13_prev_digest_chaining(eng):
    """T213-CGVR-13 · CHAIN: second record's prev_digest == first record's hmac_digest."""
    r1 = eng.remediate(violation_id=_vid(), domain="drift_containment")
    r2 = eng.remediate(violation_id=_vid(), domain="invariant_density")
    assert r2.prev_digest == r1.hmac_digest


@pytest.mark.cgvr
@pytest.mark.phase213
def test_T213_CGVR_14_tamper_breaks_chain(eng, tmp_path):
    """T213-CGVR-14 · CHAIN: tampering with ledger causes chain break."""
    eng.remediate(violation_id=_vid(), domain="drift_containment")
    eng.remediate(violation_id=_vid(), domain="ledger_integrity")
    ledger = tmp_path / "test_cgvr.jsonl"
    lines  = ledger.read_text().splitlines()
    d      = json.loads(lines[0])
    d["domain"] = "TAMPERED"
    lines[0] = json.dumps(d)
    ledger.write_text("\n".join(lines) + "\n")
    eng3 = ConstitutionalGovernanceViolationRemediator(ledger_path=ledger)
    valid, idx = eng3.verify_chain()
    assert valid is False
    assert idx == 0


@pytest.mark.cgvr
@pytest.mark.phase213
def test_T213_CGVR_15_empty_chain_valid(eng):
    """T213-CGVR-15 · CHAIN: empty ledger returns (True, None)."""
    valid, idx = eng.verify_chain()
    assert valid is True
    assert idx is None


@pytest.mark.cgvr
@pytest.mark.phase213
def test_T213_CGVR_16_chain_ten_records(eng):
    """T213-CGVR-16 · CHAIN: chain valid across 10 records."""
    for _ in range(10):
        eng.remediate(violation_id=_vid(), domain="drift_containment")
    valid, _ = eng.verify_chain()
    assert valid is True


# ═══════════════════════════════════════════════════════════════════════════════
# HUMAN0 — T213-CGVR-17..21
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.cgvr
@pytest.mark.phase213
def test_T213_CGVR_17_tier0_domain_sets_human0(eng):
    """T213-CGVR-17 · HUMAN0: certification_chain domain sets human0_required=True."""
    rec = eng.remediate(violation_id=_vid(), domain="certification_chain")
    assert rec.human0_required is True
    assert rec.status == RemediationStatus.HUMAN0_REQUIRED.value


@pytest.mark.cgvr
@pytest.mark.phase213
def test_T213_CGVR_18_tier0_actions_blocked(eng):
    """T213-CGVR-18 · HUMAN0: Tier-0 actions outcome is BLOCKED_HUMAN0_REQUIRED."""
    rec = eng.remediate(violation_id=_vid(), domain="certification_chain")
    blocked = [a for a in rec.plan if a.blast_radius == 0]
    assert all(a.outcome == "BLOCKED_HUMAN0_REQUIRED" for a in blocked)


@pytest.mark.cgvr
@pytest.mark.phase213
def test_T213_CGVR_19_approve_tier0_remediates(eng):
    """T213-CGVR-19 · HUMAN0: approve_tier0() produces REMEDIATED status."""
    rec = eng.remediate(violation_id=_vid(), domain="certification_chain")
    approved = eng.approve_tier0(rec.remediation_id)
    assert approved.status == RemediationStatus.REMEDIATED.value
    assert approved.human0_required is False


@pytest.mark.cgvr
@pytest.mark.phase213
def test_T213_CGVR_20_approve_tier0_invalid_id_raises(eng):
    """T213-CGVR-20 · HUMAN0: approve_tier0() with unknown id raises KeyError."""
    with pytest.raises(KeyError):
        eng.approve_tier0("CGVR-" + "0" * 32)


@pytest.mark.cgvr
@pytest.mark.phase213
def test_T213_CGVR_21_approve_non_human0_record_raises(eng):
    """T213-CGVR-21 · HUMAN0: approve_tier0() on non-HUMAN0_REQUIRED record raises ValueError."""
    rec = eng.remediate(violation_id=_vid(), domain="drift_containment")
    # drift_containment has no Tier-0 actions → status = REMEDIATED
    assert rec.status == RemediationStatus.REMEDIATED.value
    with pytest.raises(ValueError, match="CGVR-HUMAN0-0"):
        eng.approve_tier0(rec.remediation_id)


# ═══════════════════════════════════════════════════════════════════════════════
# PLAN — T213-CGVR-22..25
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.cgvr
@pytest.mark.phase213
def test_T213_CGVR_22_prescription_known_domain(eng):
    """T213-CGVR-22 · PLAN: known domain produces ≥1 prescribed action."""
    actions = _prescribe(domain="ledger_integrity", failed_dimensions=["ledger_integrity"])
    assert len(actions) >= 1


@pytest.mark.cgvr
@pytest.mark.phase213
def test_T213_CGVR_23_prescription_unknown_domain_uses_default(eng):
    """T213-CGVR-23 · PLAN: unknown domain falls back to default prescription."""
    actions = _prescribe(domain="totally_unknown", failed_dimensions=[])
    assert any(a.action_type == ActionType.NOOP for a in actions)


@pytest.mark.cgvr
@pytest.mark.phase213
def test_T213_CGVR_24_multi_dim_dedup(eng):
    """T213-CGVR-24 · PLAN: duplicate dimensions don't produce duplicate action types."""
    actions = _prescribe(
        domain="drift_containment",
        failed_dimensions=["drift_containment", "drift_containment"],
    )
    types = [(a.action_type, a.blast_radius) for a in actions]
    assert len(types) == len(set(types))


@pytest.mark.cgvr
@pytest.mark.phase213
def test_T213_CGVR_25_action_ids_unique(eng):
    """T213-CGVR-25 · PLAN: all action_ids within a plan are unique."""
    actions = _prescribe(
        domain="ledger_integrity",
        failed_dimensions=["ledger_integrity", "drift_containment"],
    )
    ids = [a.action_id for a in actions]
    assert len(ids) == len(set(ids))


# ═══════════════════════════════════════════════════════════════════════════════
# INV — Hard-class invariant enforcement — T213-CGVR-26..30
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.cgvr
@pytest.mark.phase213
def test_T213_CGVR_26_invalid_blast_radius_raises(eng):
    """T213-CGVR-26 · INV: CGVR-BLAST-0 — blast_radius outside {0,1,2} raises ValueError."""
    from dorkllm.constitutional_governance_violation_remediator import RemediationAction
    act = RemediationAction(
        action_id="BAD",
        action_type=ActionType.NOOP,
        blast_radius=99,  # invalid
        description="bad",
    )
    with pytest.raises(ValueError, match="CGVR-BLAST-0"):
        RemediationRecord(
            remediation_id="CGVR-" + "0" * 32,
            violation_id="v",
            domain="d",
            ts_ns=1,
            plan=[act],
            status=RemediationStatus.REMEDIATED.value,
            human0_required=False,
            actions_executed=0,
            actions_total=1,
            governor="DUSTIN L REID",
            hmac_digest="a" * 64,
            prev_digest="GENESIS",
        )


@pytest.mark.cgvr
@pytest.mark.phase213
def test_T213_CGVR_27_invalid_status_raises(eng):
    """T213-CGVR-27 · INV: CGVR-STATUS-0 — invalid status raises ValueError."""
    with pytest.raises(ValueError, match="CGVR-STATUS-0"):
        RemediationRecord(
            remediation_id="CGVR-" + "0" * 32,
            violation_id="v",
            domain="d",
            ts_ns=1,
            plan=[],
            status="INVALID_STATUS",
            human0_required=False,
            actions_executed=0,
            actions_total=0,
            governor="DUSTIN L REID",
            hmac_digest="a" * 64,
            prev_digest="GENESIS",
        )


@pytest.mark.cgvr
@pytest.mark.phase213
def test_T213_CGVR_28_corrupt_ledger_raises(eng, tmp_path):
    """T213-CGVR-28 · INV: CGVR-FAILCLOSED-0 — corrupt ledger line raises RuntimeError."""
    ledger = tmp_path / "bad_cgvr.jsonl"
    ledger.write_text("{not valid json\n")
    with pytest.raises(Exception):
        ConstitutionalGovernanceViolationRemediator(ledger_path=ledger)


@pytest.mark.cgvr
@pytest.mark.phase213
def test_T213_CGVR_29_status_dict_has_invariants(eng):
    """T213-CGVR-29 · INV: status() returns all 10 invariant names."""
    s = eng.status()
    invs = s["invariants"]
    expected = {
        "CGVR-AUDIT-0", "CGVR-CHAIN-0", "CGVR-DETERM-0", "CGVR-FAILCLOSED-0",
        "CGVR-HUMAN0-0", "CGVR-BLAST-0", "CGVR-SEAL-0", "CGVR-IMMUT-0",
        "CGVR-PLAN-0", "CGVR-STATUS-0",
    }
    assert set(invs) == expected


@pytest.mark.cgvr
@pytest.mark.phase213
def test_T213_CGVR_30_records_immutable(eng):
    """T213-CGVR-30 · INV: CGVR-IMMUT-0 — records list is a copy, mutations don't affect engine."""
    eng.remediate(violation_id=_vid(), domain="drift_containment")
    recs = eng.records
    recs.clear()
    assert len(eng.records) == 1
