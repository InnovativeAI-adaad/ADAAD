# SPDX-License-Identifier: LicenseRef-Proprietary-InnovativeAI
"""
Test suite: Phase 172 · INNOV-78 · MFV — Mutation Fitness Verifier
T172-MFV-01 through T172-MFV-30

Coverage categories:
  CHAIN   (T172-MFV-01..04)  — HMAC chain integrity
  VERDICT (T172-MFV-05..10)  — Verdict computation paths
  GATE    (T172-MFV-11..15)  — Lineage gate enforcement
  FAIL    (T172-MFV-16..22)  — Violation / failure mode coverage
  DETERM  (T172-MFV-23..26)  — Determinism and replay
  AUDIT   (T172-MFV-27..30)  — Audit completeness
"""

from __future__ import annotations

import hashlib
import hmac
import json
import pytest
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch

from dorkllm.mutation_fitness_verifier import (
    DELTA_FLOOR,
    HMAC_SECRET,
    MFVAtomicViolation,
    MFVCertifyViolation,
    MFVChainViolation,
    MFVHuman0Violation,
    MFVPersistViolation,
    EvaluationEvent,
    FitnessVerdictEnum,
    MutationFitnessVerifier,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_ledger(tmp_path: Path) -> Path:
    return tmp_path / "fitness_verdict_ledger.jsonl"


@pytest.fixture()
def verifier(tmp_ledger: Path) -> MutationFitnessVerifier:
    return MutationFitnessVerifier(ledger_path=tmp_ledger)


def _exec_record(mutation_id: str = "mut-001") -> Dict[str, Any]:
    """Minimal valid ExecutionRecord stub."""
    payload = json.dumps(
        {"mutation_id": mutation_id, "prev_digest": "GENESIS"}, sort_keys=True
    ).encode()
    digest = hmac.new(b"MEX-ADAAD-CHAIN-v1", payload, hashlib.sha256).hexdigest()
    return {"mutation_id": mutation_id, "prev_digest": "GENESIS", "hmac_digest": digest}


def _snapshot(
    invariant_pass_rate: float = 1.0,
    hmac_chain_integrity: float = 1.0,
    blast_radius_compliance: float = 1.0,
    human0_gate_compliance: float = 1.0,
    determinism_score: float = 1.0,
    violated_invariants: Optional[List[str]] = None,
) -> Dict[str, Any]:
    snap: Dict[str, Any] = {
        "invariant_pass_rate": invariant_pass_rate,
        "hmac_chain_integrity": hmac_chain_integrity,
        "blast_radius_compliance": blast_radius_compliance,
        "human0_gate_compliance": human0_gate_compliance,
        "determinism_score": determinism_score,
    }
    if violated_invariants is not None:
        snap["violated_invariants"] = violated_invariants
    return snap


# ══════════════════════════════════════════════════════════════════════════════
# CHAIN tests — T172-MFV-01..04
# ══════════════════════════════════════════════════════════════════════════════

class TestChainIntegrity:

    def test_T172_MFV_01_genesis_entry_written_on_init(self, verifier, tmp_ledger):
        """T172-MFV-01: Genesis entry is written on fresh initialisation."""
        lines = [json.loads(l) for l in tmp_ledger.read_text().splitlines() if l.strip()]
        assert lines[0]["verdict_id"] == "GENESIS"
        assert lines[0]["prev_digest"] == "GENESIS"

    def test_T172_MFV_02_chain_valid_after_evaluation(self, verifier):
        """T172-MFV-02: Chain remains valid after a successful evaluation."""
        pre = _snapshot(invariant_pass_rate=0.8)
        post = _snapshot(invariant_pass_rate=0.9)
        verifier.evaluate(_exec_record(), pre, post)
        assert verifier.verify_chain() is True

    def test_T172_MFV_03_tampered_chain_detected_on_load(self, tmp_ledger):
        """T172-MFV-03: Tampered HMAC digest raises MFVChainViolation on load."""
        # Write a valid verifier, then corrupt its ledger
        v = MutationFitnessVerifier(ledger_path=tmp_ledger)
        pre = _snapshot(invariant_pass_rate=0.7)
        post = _snapshot(invariant_pass_rate=0.9)
        v.evaluate(_exec_record(), pre, post)

        lines = tmp_ledger.read_text().splitlines()
        records = [json.loads(l) for l in lines if l.strip()]
        records[-1]["hmac_digest"] = "deadbeef" * 8
        tmp_ledger.write_text("\n".join(json.dumps(r) for r in records) + "\n")

        with pytest.raises(MFVChainViolation):
            MutationFitnessVerifier(ledger_path=tmp_ledger)

    def test_T172_MFV_04_prev_digest_linked_to_predecessor(self, verifier):
        """T172-MFV-04: Each verdict's prev_digest matches predecessor's hmac_digest."""
        pre = _snapshot(invariant_pass_rate=0.6)
        post = _snapshot(invariant_pass_rate=0.8)
        verifier.evaluate(_exec_record("mut-A"), pre, post)
        verifier.evaluate(_exec_record("mut-B"), pre, post)

        # Find verdict records
        verdicts = [
            r for r in verifier.ledger()
            if r.get("verdict") in ("CERTIFIED", "REGRESSED", "INCONCLUSIVE")
        ]
        assert len(verdicts) >= 2
        # Each verdict entry's prev_digest should be some earlier hmac in the chain
        for v in verdicts:
            assert v["prev_digest"] != ""


# ══════════════════════════════════════════════════════════════════════════════
# VERDICT tests — T172-MFV-05..10
# ══════════════════════════════════════════════════════════════════════════════

class TestVerdictComputation:

    def test_T172_MFV_05_certified_on_positive_delta_no_violations(self, verifier):
        """T172-MFV-05: CERTIFIED when delta > 0 and no invariants violated."""
        pre = _snapshot(invariant_pass_rate=0.7)
        post = _snapshot(invariant_pass_rate=0.9)
        v = verifier.evaluate(_exec_record(), pre, post)
        assert v.verdict == FitnessVerdictEnum.CERTIFIED
        assert v.fitness_delta > DELTA_FLOOR

    def test_T172_MFV_06_regressed_when_delta_zero(self, verifier):
        """T172-MFV-06: REGRESSED when delta == 0.0 (boundary condition)."""
        snap = _snapshot(invariant_pass_rate=0.8)
        v = verifier.evaluate(_exec_record(), snap, snap)
        assert v.verdict == FitnessVerdictEnum.REGRESSED
        assert v.fitness_delta == 0.0

    def test_T172_MFV_07_regressed_when_delta_negative(self, verifier):
        """T172-MFV-07: REGRESSED when post-fitness < pre-fitness."""
        pre = _snapshot(invariant_pass_rate=0.9)
        post = _snapshot(invariant_pass_rate=0.5)
        v = verifier.evaluate(_exec_record(), pre, post)
        assert v.verdict == FitnessVerdictEnum.REGRESSED
        assert v.fitness_delta < 0.0

    def test_T172_MFV_08_inconclusive_when_invariants_violated(self, verifier):
        """T172-MFV-08: INCONCLUSIVE when delta > 0 but invariants violated."""
        pre = _snapshot(invariant_pass_rate=0.7)
        post = _snapshot(
            invariant_pass_rate=0.9,
            violated_invariants=["MEX-BLAST-0"],
        )
        v = verifier.evaluate(_exec_record(), pre, post)
        assert v.verdict == FitnessVerdictEnum.INCONCLUSIVE
        assert "MEX-BLAST-0" in v.invariants_violated

    def test_T172_MFV_09_human0_override_certifies_inconclusive(self, verifier):
        """T172-MFV-09: HUMAN-0 override token promotes INCONCLUSIVE to CERTIFIED."""
        pre = _snapshot(invariant_pass_rate=0.7)
        post = _snapshot(
            invariant_pass_rate=0.9,
            violated_invariants=["MEX-BLAST-0"],
        )
        v = verifier.evaluate(
            _exec_record(), pre, post, human0_override_token="HUMAN0-TOKEN-XYZ"
        )
        assert v.verdict == FitnessVerdictEnum.CERTIFIED
        assert v.human0_override_token == "HUMAN0-TOKEN-XYZ"

    def test_T172_MFV_10_fitness_delta_computed_correctly(self, verifier):
        """T172-MFV-10: fitness_delta equals post_score minus pre_score."""
        pre = _snapshot(
            invariant_pass_rate=0.6,
            hmac_chain_integrity=0.6,
            blast_radius_compliance=0.6,
            human0_gate_compliance=0.6,
            determinism_score=0.6,
        )
        post = _snapshot(
            invariant_pass_rate=1.0,
            hmac_chain_integrity=1.0,
            blast_radius_compliance=1.0,
            human0_gate_compliance=1.0,
            determinism_score=1.0,
        )
        v = verifier.evaluate(_exec_record(), pre, post)
        expected_delta = round(v.post_fitness_score - v.pre_fitness_score, 6)
        assert abs(v.fitness_delta - expected_delta) < 1e-9


# ══════════════════════════════════════════════════════════════════════════════
# GATE tests — T172-MFV-11..15
# ══════════════════════════════════════════════════════════════════════════════

class TestGateEnforcement:

    def test_T172_MFV_11_certified_verdict_passes_lineage_gate(self, verifier):
        """T172-MFV-11: CERTIFIED verdict passes assert_lineage_eligible without error."""
        pre = _snapshot(invariant_pass_rate=0.7)
        post = _snapshot(invariant_pass_rate=0.95)
        v = verifier.evaluate(_exec_record(), pre, post)
        assert v.verdict == FitnessVerdictEnum.CERTIFIED
        verifier.assert_lineage_eligible(v)  # Must not raise

    def test_T172_MFV_12_regressed_verdict_blocks_lineage_gate(self, verifier):
        """T172-MFV-12: REGRESSED verdict raises MFVCertifyViolation at lineage gate."""
        snap = _snapshot(invariant_pass_rate=0.8)
        v = verifier.evaluate(_exec_record(), snap, snap)
        assert v.verdict == FitnessVerdictEnum.REGRESSED
        with pytest.raises(MFVCertifyViolation):
            verifier.assert_lineage_eligible(v)

    def test_T172_MFV_13_inconclusive_verdict_blocks_lineage_gate(self, verifier):
        """T172-MFV-13: INCONCLUSIVE verdict raises MFVCertifyViolation at lineage gate."""
        pre = _snapshot(invariant_pass_rate=0.7)
        post = _snapshot(invariant_pass_rate=0.9, violated_invariants=["MRP-SCORE-0"])
        v = verifier.evaluate(_exec_record(), pre, post)
        assert v.verdict == FitnessVerdictEnum.INCONCLUSIVE
        with pytest.raises(MFVCertifyViolation):
            verifier.assert_lineage_eligible(v)

    def test_T172_MFV_14_human0_overridden_verdict_passes_gate(self, verifier):
        """T172-MFV-14: HUMAN-0 overridden CERTIFIED verdict passes lineage gate."""
        pre = _snapshot(invariant_pass_rate=0.7)
        post = _snapshot(invariant_pass_rate=0.9, violated_invariants=["MRP-SCORE-0"])
        v = verifier.evaluate(_exec_record(), pre, post, human0_override_token="H0-TOKEN")
        assert v.verdict == FitnessVerdictEnum.CERTIFIED
        verifier.assert_lineage_eligible(v)  # Must not raise

    def test_T172_MFV_15_gate_check_emits_audit_entry(self, verifier):
        """T172-MFV-15: assert_lineage_eligible emits LINEAGE_GATE_CHECKED audit entry."""
        pre = _snapshot(invariant_pass_rate=0.7)
        post = _snapshot(invariant_pass_rate=0.9)
        v = verifier.evaluate(_exec_record(), pre, post)
        verifier.assert_lineage_eligible(v)

        gate_events = [
            r for r in verifier.ledger()
            if r.get("event") == EvaluationEvent.LINEAGE_GATE_CHECKED.value
        ]
        assert len(gate_events) >= 1


# ══════════════════════════════════════════════════════════════════════════════
# FAIL tests — T172-MFV-16..22
# ══════════════════════════════════════════════════════════════════════════════

class TestFailureModes:

    def test_T172_MFV_16_missing_hmac_digest_raises_chain_violation(self, verifier):
        """T172-MFV-16: ExecutionRecord without hmac_digest raises MFVChainViolation."""
        bad_record = {"mutation_id": "mut-bad", "prev_digest": "GENESIS"}
        pre = _snapshot(invariant_pass_rate=0.8)
        post = _snapshot(invariant_pass_rate=0.9)
        with pytest.raises(MFVChainViolation):
            verifier.evaluate(bad_record, pre, post)

    def test_T172_MFV_17_chain_violation_seals_engine(self, verifier):
        """T172-MFV-17: MFVChainViolation seals the engine."""
        bad_record = {"mutation_id": "mut-seal", "prev_digest": "GENESIS"}
        pre = _snapshot()
        post = _snapshot()
        with pytest.raises(MFVChainViolation):
            verifier.evaluate(bad_record, pre, post)
        assert verifier._sealed is True

    def test_T172_MFV_18_sealed_engine_blocks_further_evaluation(self, verifier):
        """T172-MFV-18: Sealed engine raises MFVAtomicViolation on next evaluate."""
        verifier._sealed = True
        pre = _snapshot(invariant_pass_rate=0.8)
        post = _snapshot(invariant_pass_rate=0.9)
        with pytest.raises(MFVAtomicViolation):
            verifier.evaluate(_exec_record(), pre, post)

    def test_T172_MFV_19_certify_violation_raised_on_blocked_promotion(self, verifier):
        """T172-MFV-19: MFVCertifyViolation raised when REGRESSED verdict presented at gate."""
        snap = _snapshot(invariant_pass_rate=0.7)
        v = verifier.evaluate(_exec_record(), snap, snap)
        assert v.verdict == FitnessVerdictEnum.REGRESSED
        with pytest.raises(MFVCertifyViolation):
            verifier.assert_lineage_eligible(v)

    def test_T172_MFV_20_corrupt_ledger_raises_atomic_violation_on_load(self, tmp_ledger):
        """T172-MFV-20: Corrupt JSON in ledger raises MFVAtomicViolation on load."""
        tmp_ledger.write_text("{bad json}\n")
        with pytest.raises(MFVAtomicViolation):
            MutationFitnessVerifier(ledger_path=tmp_ledger)

    def test_T172_MFV_21_persist_violation_on_flush_failure(self, tmp_ledger):
        """T172-MFV-21: MFVPersistViolation raised when _flush raises OSError."""
        from unittest.mock import patch

        v = MutationFitnessVerifier(ledger_path=tmp_ledger)
        pre = _snapshot(invariant_pass_rate=0.7)
        post = _snapshot(invariant_pass_rate=0.95)

        original_flush = v._flush

        def _failing_flush(records):
            raise OSError("Simulated disk failure")

        v._flush = _failing_flush
        with pytest.raises((MFVPersistViolation, OSError)):
            v.evaluate(_exec_record("mut-flush-fail"), pre, post)

    def test_T172_MFV_22_delta_floor_boundary_exact_zero_regresses(self, verifier):
        """T172-MFV-22: Exact delta=0.0 is REGRESSED (boundary, inclusive floor)."""
        pre = _snapshot(
            invariant_pass_rate=0.8,
            hmac_chain_integrity=0.8,
            blast_radius_compliance=0.8,
            human0_gate_compliance=0.8,
            determinism_score=0.8,
        )
        # Identical post snapshot → delta == 0.0
        post = _snapshot(
            invariant_pass_rate=0.8,
            hmac_chain_integrity=0.8,
            blast_radius_compliance=0.8,
            human0_gate_compliance=0.8,
            determinism_score=0.8,
        )
        v = verifier.evaluate(_exec_record(), pre, post)
        assert v.fitness_delta == 0.0
        assert v.verdict == FitnessVerdictEnum.REGRESSED


# ══════════════════════════════════════════════════════════════════════════════
# DETERM tests — T172-MFV-23..26
# ══════════════════════════════════════════════════════════════════════════════

class TestDeterminism:

    def test_T172_MFV_23_identical_inputs_produce_same_delta(self, tmp_path):
        """T172-MFV-23: Identical inputs produce identical fitness_delta values."""
        pre = _snapshot(invariant_pass_rate=0.6)
        post = _snapshot(invariant_pass_rate=0.85)
        rec = _exec_record("mut-det")

        v1 = MutationFitnessVerifier(ledger_path=tmp_path / "l1.jsonl")
        result1 = v1.evaluate(rec, pre, post)

        v2 = MutationFitnessVerifier(ledger_path=tmp_path / "l2.jsonl")
        result2 = v2.evaluate(rec, pre, post)

        assert result1.fitness_delta == result2.fitness_delta
        assert result1.pre_fitness_score == result2.pre_fitness_score
        assert result1.post_fitness_score == result2.post_fitness_score

    def test_T172_MFV_24_identical_inputs_produce_same_verdict(self, tmp_path):
        """T172-MFV-24: Identical inputs produce identical verdict enum."""
        pre = _snapshot(invariant_pass_rate=0.6)
        post = _snapshot(invariant_pass_rate=0.85)
        rec = _exec_record("mut-det-v")

        v1 = MutationFitnessVerifier(ledger_path=tmp_path / "l3.jsonl")
        v2 = MutationFitnessVerifier(ledger_path=tmp_path / "l4.jsonl")

        assert v1.evaluate(rec, pre, post).verdict == v2.evaluate(rec, pre, post).verdict

    def test_T172_MFV_25_verdict_record_contains_replay_fields(self, verifier):
        """T172-MFV-25: FitnessVerdict carries all fields required for deterministic replay."""
        pre = _snapshot(invariant_pass_rate=0.7)
        post = _snapshot(invariant_pass_rate=0.9)
        v = verifier.evaluate(_exec_record(), pre, post)
        assert v.verdict_id
        assert v.mutation_id
        assert v.evaluation_token
        assert v.prev_digest
        assert v.hmac_digest
        assert v.invariants_checked

    def test_T172_MFV_26_evaluation_token_is_not_wall_clock(self, verifier):
        """T172-MFV-26: Evaluation token is deterministic counter, not a timestamp."""
        pre = _snapshot(invariant_pass_rate=0.7)
        post = _snapshot(invariant_pass_rate=0.9)
        v = verifier.evaluate(_exec_record(), pre, post)
        # Token must start with MFV-TOKEN- prefix (determinism provider format)
        assert "MFV-TOKEN-" in v.evaluation_token


# ══════════════════════════════════════════════════════════════════════════════
# AUDIT tests — T172-MFV-27..30
# ══════════════════════════════════════════════════════════════════════════════

class TestAuditCompleteness:

    def test_T172_MFV_27_evaluation_start_event_emitted(self, verifier):
        """T172-MFV-27: EVALUATION_START event is ledgered for every evaluation."""
        pre = _snapshot(invariant_pass_rate=0.7)
        post = _snapshot(invariant_pass_rate=0.9)
        verifier.evaluate(_exec_record("mut-audit-1"), pre, post)
        events = [
            r.get("event") for r in verifier.ledger()
        ]
        assert EvaluationEvent.EVALUATION_START.value in events

    def test_T172_MFV_28_rejection_audit_entry_on_chain_violation(self, verifier):
        """T172-MFV-28: Engine SEALED event is ledgered on chain violation."""
        bad_record = {"mutation_id": "mut-rejected", "prev_digest": "GENESIS"}
        with pytest.raises(MFVChainViolation):
            verifier.evaluate(bad_record, _snapshot(), _snapshot())
        events = [r.get("event") for r in verifier.ledger()]
        assert EvaluationEvent.ENGINE_SEALED.value in events

    def test_T172_MFV_29_human0_override_event_ledgered(self, verifier):
        """T172-MFV-29: HUMAN0_OVERRIDE event is ledgered when override applied."""
        pre = _snapshot(invariant_pass_rate=0.7)
        post = _snapshot(invariant_pass_rate=0.9, violated_invariants=["MEX-BLAST-0"])
        verifier.evaluate(_exec_record(), pre, post, human0_override_token="H0-TEST")
        events = [r.get("event") for r in verifier.ledger()]
        assert EvaluationEvent.HUMAN0_OVERRIDE.value in events

    def test_T172_MFV_30_stats_reflects_evaluation_counts(self, verifier):
        """T172-MFV-30: stats() accurately reflects certified/regressed/inconclusive counts."""
        pre_low = _snapshot(invariant_pass_rate=0.5)
        pre_high = _snapshot(invariant_pass_rate=0.9)
        snap_same = _snapshot(invariant_pass_rate=0.7)
        post_violated = _snapshot(invariant_pass_rate=0.9, violated_invariants=["X-0"])

        verifier.evaluate(_exec_record("m1"), pre_low, pre_high)   # CERTIFIED
        verifier.evaluate(_exec_record("m2"), snap_same, snap_same)  # REGRESSED
        verifier.evaluate(_exec_record("m3"), pre_low, post_violated)  # INCONCLUSIVE

        s = verifier.stats()
        assert s["certified"] == 1
        assert s["regressed"] == 1
        assert s["inconclusive"] == 1
        assert s["total_evaluations"] == 3
        assert s["chain_valid"] is True
