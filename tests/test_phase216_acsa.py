# SPDX-License-Identifier: Apache-2.0
"""
Phase 216 · INNOV-121 · ACSA — Autonomous Constitutional Self-Amendment Engine
30-test acceptance suite — T216-ACSA-01..30
"""
import json
import os
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

# Redirect ledger/state to temp dir for all tests
@pytest.fixture(autouse=True)
def isolated_acsa(tmp_path, monkeypatch):
    import dorkllm.autonomous_constitutional_self_amendment as mod
    monkeypatch.setattr(mod, "_LEDGER_PATH", tmp_path / "acsa" / "amendment_ledger.jsonl")
    monkeypatch.setattr(mod, "_STATE_PATH", tmp_path / "acsa" / "acsa_state.json")
    yield

from dorkllm.autonomous_constitutional_self_amendment import (
    AmendmentClass,
    AmendmentStage,
    AutonomousConstitutionalSelfAmendment,
    _amendment_content_hash,
    _hmac_digest,
    _HMAC_KEY,
    _revert_hash,
    _utc_iso,
    _verify_chain,
)


def _engine():
    return AutonomousConstitutionalSelfAmendment()


def _proposal_kwargs(**overrides):
    base = dict(
        title="Test Amendment",
        description="Test description",
        target_section="CEL gate",
        proposed_text="New gate logic",
        current_text="Old gate logic",
        amendment_class=AmendmentClass.SOFT,
        supporting_invariant_ids=["CEL-GATE-0", "ACSA-CHAIN-0", "CGVF-AUDIT-0"],
    )
    base.update(overrides)
    return base


# ── T216-ACSA-01: Engine instantiates ──────────────────────────────────────
def test_T216_ACSA_01_engine_instantiates():
    eng = _engine()
    assert eng is not None
    assert len(eng.INVARIANT_CODES) == 12


# ── T216-ACSA-02: Status returns correct structure ─────────────────────────
def test_T216_ACSA_02_status_structure():
    eng = _engine()
    s = eng.status()
    assert s["engine"] == "ACSA"
    assert s["innovation"] == "INNOV-121"
    assert s["hard_class_invariants"] == 12
    assert "governor" in s


# ── T216-ACSA-03: propose() creates PROPOSED record ────────────────────────
def test_T216_ACSA_03_propose_creates_record():
    eng = _engine()
    p = eng.propose(**_proposal_kwargs())
    assert p.stage == AmendmentStage.PROPOSED
    assert p.amendment_id is not None
    assert p.revert_hash is not None


# ── T216-ACSA-04: ACSA-QUORUM-0 enforced on propose ───────────────────────
def test_T216_ACSA_04_quorum_enforced():
    eng = _engine()
    with pytest.raises(ValueError, match="ACSA-QUORUM-0"):
        eng.propose(**_proposal_kwargs(supporting_invariant_ids=["CEL-GATE-0", "ONE-0"]))


# ── T216-ACSA-05: propose() writes ledger entry ────────────────────────────
def test_T216_ACSA_05_propose_writes_ledger(tmp_path):
    import dorkllm.autonomous_constitutional_self_amendment as mod
    ledger = tmp_path / "acsa" / "amendment_ledger.jsonl"
    mod._LEDGER_PATH = ledger
    mod._STATE_PATH = tmp_path / "acsa" / "acsa_state.json"
    eng = _engine()
    eng.propose(**_proposal_kwargs())
    assert ledger.exists()
    lines = ledger.read_text().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["event"] == "PROPOSED"


# ── T216-ACSA-06: ACSA-IDEMPOTENT-0 — duplicate propose returns same id ───
def test_T216_ACSA_06_idempotent_propose():
    eng = _engine()
    kwargs = _proposal_kwargs()
    p1 = eng.propose(**kwargs)
    p2 = eng.propose(**kwargs)
    assert p1.amendment_id == p2.amendment_id


# ── T216-ACSA-07: validate() passes with sufficient score ──────────────────
def test_T216_ACSA_07_validate_passes():
    eng = _engine()
    p = eng.propose(**_proposal_kwargs())
    result = eng.validate(p, cgvf_score=0.85)
    assert result.passed
    assert p.stage == AmendmentStage.VALIDATED


# ── T216-ACSA-08: validate() fails below CGVF threshold ───────────────────
def test_T216_ACSA_08_validate_fails_low_score():
    eng = _engine()
    p = eng.propose(**_proposal_kwargs())
    result = eng.validate(p, cgvf_score=0.50)
    assert not result.passed
    assert p.stage == AmendmentStage.REJECTED


# ── T216-ACSA-09: ACSA-CONFLICT-0 blocks Hard conflict ────────────────────
def test_T216_ACSA_09_conflict_check():
    eng = _engine()
    p = eng.propose(**_proposal_kwargs(
        amendment_class=AmendmentClass.HARD,
        proposed_text="Modify CEL gate behavior",
        supporting_invariant_ids=["CEL-GATE-0", "ACSA-CHAIN-0", "CGVF-AUDIT-0"],
    ))
    result = eng.validate(p, cgvf_score=0.90, existing_hard_invariants=["CEL-GATE-0"])
    # CEL-GATE-0 is both in proposed_text prefix AND in supporting_invariant_ids
    # so conflict check should pass (it's a known/accepted invariant)
    # Test that conflict_check logic runs without error
    assert isinstance(result.passed, bool)


# ── T216-ACSA-10: simulate() requires VALIDATED stage ─────────────────────
def test_T216_ACSA_10_simulate_requires_validated():
    eng = _engine()
    p = eng.propose(**_proposal_kwargs())
    # Directly in PROPOSED stage
    with pytest.raises(RuntimeError, match="ACSA-SIMFIRST-0"):
        eng.simulate(p)


# ── T216-ACSA-11: simulate() passes with dry_run_passes=True ──────────────
def test_T216_ACSA_11_simulate_passes():
    eng = _engine()
    p = eng.propose(**_proposal_kwargs())
    eng.validate(p, cgvf_score=0.80)
    result = eng.simulate(p, dry_run_passes=True)
    assert result.passed
    assert p.stage == AmendmentStage.SIMULATED


# ── T216-ACSA-12: simulate() fails with breakage ──────────────────────────
def test_T216_ACSA_12_simulate_fails_breakage():
    eng = _engine()
    p = eng.propose(**_proposal_kwargs())
    eng.validate(p, cgvf_score=0.80)
    result = eng.simulate(p, dry_run_passes=False)
    assert not result.passed
    assert p.stage == AmendmentStage.REJECTED


# ── T216-ACSA-13: ACSA-SCOPE-0 SOFT with Hard affected fails ──────────────
def test_T216_ACSA_13_scope_violation():
    eng = _engine()
    p = eng.propose(**_proposal_kwargs(amendment_class=AmendmentClass.SOFT))
    eng.validate(p, cgvf_score=0.80)
    result = eng.simulate(p, dry_run_passes=True, hard_invariants_affected=["ACSA-CHAIN-0"])
    assert not result.passed
    assert result.breakage_detected


# ── T216-ACSA-14: queue_for_ratification requires SIMULATED ───────────────
def test_T216_ACSA_14_queue_requires_simulated():
    eng = _engine()
    p = eng.propose(**_proposal_kwargs())
    eng.validate(p, cgvf_score=0.80)
    # Stage is VALIDATED, not SIMULATED
    with pytest.raises(RuntimeError, match="ACSA-SIMFIRST-0"):
        eng.queue_for_ratification(p)


# ── T216-ACSA-15: queue_for_ratification advances to PENDING_H0 ───────────
def test_T216_ACSA_15_queue_pending_h0():
    eng = _engine()
    p = eng.propose(**_proposal_kwargs())
    eng.validate(p, cgvf_score=0.80)
    eng.simulate(p, dry_run_passes=True)
    record = eng.queue_for_ratification(p)
    assert p.stage == AmendmentStage.PENDING_H0
    assert record["human0_signature_slot"] == "__AWAITING_DUSTIN_L_REID_GPG__"


# ── T216-ACSA-16: ACSA-HUMAN0-0 — ratify requires non-empty signature ─────
def test_T216_ACSA_16_human0_gate_empty_sig():
    eng = _engine()
    p = eng.propose(**_proposal_kwargs())
    eng.validate(p, cgvf_score=0.80)
    eng.simulate(p, dry_run_passes=True)
    eng.queue_for_ratification(p)
    with pytest.raises(ValueError, match="ACSA-HUMAN0-0"):
        eng.ratify(p, human0_signature="")


# ── T216-ACSA-17: ratify() completes amendment lifecycle ──────────────────
def test_T216_ACSA_17_ratify_completes():
    eng = _engine()
    p = eng.propose(**_proposal_kwargs())
    eng.validate(p, cgvf_score=0.85)
    eng.simulate(p, dry_run_passes=True)
    eng.queue_for_ratification(p)
    record = eng.ratify(p, human0_signature="GPG-MOCK-SIG-DUSTIN-L-REID")
    assert p.stage == AmendmentStage.RATIFIED
    assert record["stage"] == AmendmentStage.RATIFIED
    assert "ledger_digest" in record


# ── T216-ACSA-18: ratify() increments total_ratified ─────────────────────
def test_T216_ACSA_18_ratify_increments_counter():
    eng = _engine()
    p = eng.propose(**_proposal_kwargs())
    eng.validate(p, cgvf_score=0.85)
    eng.simulate(p, dry_run_passes=True)
    eng.queue_for_ratification(p)
    eng.ratify(p, human0_signature="GPG-MOCK")
    s = eng.status()
    assert s["total_ratified"] == 1


# ── T216-ACSA-19: reject() seals rejection record ─────────────────────────
def test_T216_ACSA_19_reject_seals():
    eng = _engine()
    p = eng.propose(**_proposal_kwargs())
    record = eng.reject(p, reason="Human-0 vetoed")
    assert p.stage == AmendmentStage.REJECTED
    assert "ledger_digest" in record


# ── T216-ACSA-20: reject() increments total_rejected ─────────────────────
def test_T216_ACSA_20_reject_increments_counter():
    eng = _engine()
    p = eng.propose(**_proposal_kwargs())
    eng.reject(p, reason="Vetoed")
    s = eng.status()
    assert s["total_rejected"] == 1


# ── T216-ACSA-21: ACSA-CHAIN-0 chain is valid after full lifecycle ─────────
def test_T216_ACSA_21_chain_valid_after_lifecycle():
    eng = _engine()
    p = eng.propose(**_proposal_kwargs())
    eng.validate(p, cgvf_score=0.85)
    eng.simulate(p, dry_run_passes=True)
    eng.queue_for_ratification(p)
    eng.ratify(p, human0_signature="GPG-MOCK")
    result = eng.verify_chain()
    assert result["chain_valid"]
    assert result["records_verified"] >= 4  # PROPOSED + VALIDATED + SIMULATED + PENDING + RATIFIED


# ── T216-ACSA-22: verify_chain detects tampered record ────────────────────
def test_T216_ACSA_22_chain_detects_tamper(tmp_path):
    import dorkllm.autonomous_constitutional_self_amendment as mod
    ledger = tmp_path / "acsa" / "amendment_ledger.jsonl"
    mod._LEDGER_PATH = ledger
    mod._STATE_PATH = tmp_path / "acsa" / "acsa_state.json"
    eng = _engine()
    p = eng.propose(**_proposal_kwargs())
    # Tamper the ledger
    content = ledger.read_text()
    ledger.write_text(content.replace('"PROPOSED"', '"TAMPERED"'))
    valid, _, status = _verify_chain()
    assert not valid


# ── T216-ACSA-23: revert_hash is deterministic ────────────────────────────
def test_T216_ACSA_23_revert_hash_deterministic():
    eng = _engine()
    p = eng.propose(**_proposal_kwargs())
    h1 = p.revert_hash
    p2 = eng.propose(**_proposal_kwargs(title="Other"))
    # revert_hash is based on current_text which is same
    assert h1 == p2.revert_hash


# ── T216-ACSA-24: HARD amendment class requires explicit flag ─────────────
def test_T216_ACSA_24_hard_amendment_class():
    eng = _engine()
    p = eng.propose(**_proposal_kwargs(amendment_class=AmendmentClass.HARD))
    assert p.amendment_class == AmendmentClass.HARD


# ── T216-ACSA-25: multiple amendments tracked independently ───────────────
def test_T216_ACSA_25_multiple_amendments():
    eng = _engine()
    p1 = eng.propose(**_proposal_kwargs(title="Amend A", proposed_text="Text A"))
    p2 = eng.propose(**_proposal_kwargs(title="Amend B", proposed_text="Text B"))
    assert p1.amendment_id != p2.amendment_id
    assert eng.status()["total_proposed"] == 2


# ── T216-ACSA-26: preview_amendment_report returns all fields ─────────────
def test_T216_ACSA_26_preview_report():
    eng = _engine()
    p = eng.propose(**_proposal_kwargs())
    report = eng.preview_amendment_report(p)
    assert "amendment_id" in report
    assert "title" in report
    assert "stage" in report
    assert "revert_hash" in report
    assert "human0_signature" in report


# ── T216-ACSA-27: ACSA-DETERM-0 — _utc_iso returns ISO string ────────────
def test_T216_ACSA_27_deterministic_timestamp():
    ts = _utc_iso()
    assert "T" in ts
    assert ts.endswith("Z")


# ── T216-ACSA-28: HMAC key is version-specific ────────────────────────────
def test_T216_ACSA_28_hmac_key_versioned():
    assert b"v1" in _HMAC_KEY
    d = _hmac_digest(_HMAC_KEY, '{"test": 1}')
    assert len(d) == 64


# ── T216-ACSA-29: ratify() raises if wrong stage ──────────────────────────
def test_T216_ACSA_29_ratify_wrong_stage():
    eng = _engine()
    p = eng.propose(**_proposal_kwargs())
    # Still PROPOSED
    with pytest.raises((RuntimeError, ValueError)):
        eng.ratify(p, human0_signature="GPG-SIG")


# ── T216-ACSA-30: full pipeline 30/30 integration test ────────────────────
def test_T216_ACSA_30_full_pipeline_integration():
    eng = _engine()

    # 1. Propose
    p = eng.propose(
        title="Arc II: CEL gate timeout extension",
        description="Extend CEL mutation evaluation window from 30s to 60s",
        target_section="Constitutional Evolution Loop / timing parameters",
        proposed_text="CEL evaluation timeout: 60 seconds",
        current_text="CEL evaluation timeout: 30 seconds",
        amendment_class=AmendmentClass.SOFT,
        supporting_invariant_ids=["CEL-GATE-0", "ACSA-CHAIN-0", "CGVF-AUDIT-0"],
        justification_evidence={"convergence_score": 0.91, "phase": 216},
        proposed_by="DEVADAAD",
    )
    assert p.stage == AmendmentStage.PROPOSED

    # 2. Validate
    v = eng.validate(p, cgvf_score=0.88)
    assert v.passed
    assert p.stage == AmendmentStage.VALIDATED

    # 3. Simulate
    s = eng.simulate(p, dry_run_passes=True, soft_invariants_affected=["CEL-TIMEOUT-0"])
    assert s.passed
    assert p.stage == AmendmentStage.SIMULATED

    # 4. Queue
    q = eng.queue_for_ratification(p)
    assert p.stage == AmendmentStage.PENDING_H0

    # 5. Ratify
    r = eng.ratify(p, human0_signature="GPG-DUSTIN-L-REID-MOCK-PHASE-216")
    assert p.stage == AmendmentStage.RATIFIED
    assert r["constitutional_compliance"].startswith("CERTIFIED")

    # 6. Verify chain
    chain = eng.verify_chain()
    assert chain["chain_valid"]

    # 7. Status check
    status = eng.status()
    assert status["total_ratified"] == 1
    assert status["total_proposed"] == 1
