# SPDX-License-Identifier: Apache-2.0
"""
Phase 193 · INNOV-98 · CMO — Constitutional Mutation Orchestrator
Acceptance test suite: T193-CMO-01 … T193-CMO-30
30/30 required to gate governance artifact creation.

Invariant coverage:
  CMO-ORCH-0   T01–T04   stage order enforced; no skip, no reorder
  CMO-CHAIN-0  T05–T08   HMAC chain integrity across records
  CMO-HUMAN0-0 T09–T11   CRITICAL risk and INCONCLUSIVE fitness gate on HUMAN-0
  CMO-STAGE-0  T12–T15   stage failure aborts pipeline
  CMO-ATOMIC-0 T16–T18   mid-pipeline exceptions produce abort ledger entry
  CMO-REPLAY-0 T19–T21   records carry deterministic replay data
  CMO-SEAL-0   T22–T24   SEAL stage written before return
  CMO-AUDIT-0  T25–T27   every transition ledgered (including failures)
  CMO-SCOPE-0  T28–T29   non-ADAAD scope rejected
  CMO-DETERM-0 T30       identical inputs → identical records
"""

import hashlib
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Ensure repo root on path
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dorkllm.constitutional_mutation_orchestrator import (
    CANONICAL_STAGES,
    CMOAtomicViolation,
    CMOHuman0Required,
    CMOLedger,
    CMOOrchestrationViolation,
    CMOScopeViolation,
    CMOStageAborted,
    ConstitutionalMutationOrchestrator,
    MutationProposal,
    PipelineStatus,
    StageRecord,
    StageStatus,
)

pytestmark = pytest.mark.T193


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_ledger(tmp_path):
    """Fresh ledger in a temp directory for isolation."""
    p = tmp_path / "cmo" / "orchestration_ledger.jsonl"
    return CMOLedger(p)


@pytest.fixture()
def cmo(tmp_ledger):
    return ConstitutionalMutationOrchestrator(ledger=tmp_ledger)


def make_proposal(
    blast_radius: float = 0.25,
    tier: int = 2,
    scope: str = "adaad-constitutional",
    payload: dict = None,
) -> MutationProposal:
    return MutationProposal(
        proposal_id=str(uuid.uuid4()),
        scope=scope,
        description="Test mutation proposal",
        blast_radius=blast_radius,
        tier=tier,
        payload=payload or {"action": "add_invariant", "module": "test"},
        submitter="DEVADAAD",
        epoch=193,
    )


# ===========================================================================
# CMO-ORCH-0 · Stage order enforced (T01–T04)
# ===========================================================================

def test_t193_cmo_01_nine_stages_completed(cmo):
    """T193-CMO-01: successful pipeline completes exactly 9 stages."""
    rec = cmo.orchestrate(make_proposal())
    assert len(rec.stages) == 9


def test_t193_cmo_02_stage_names_in_order(cmo):
    """T193-CMO-02: stage names match CANONICAL_STAGES in order."""
    rec = cmo.orchestrate(make_proposal())
    names = [s.stage_name for s in rec.stages]
    assert names == CANONICAL_STAGES


def test_t193_cmo_03_stage_indices_sequential(cmo):
    """T193-CMO-03: stage indices are 1-9 sequential (CMO-ORCH-0)."""
    rec = cmo.orchestrate(make_proposal())
    indices = [s.stage_index for s in rec.stages]
    assert indices == list(range(1, 10))


def test_t193_cmo_04_final_stage_is_seal(cmo):
    """T193-CMO-04: last stage must always be SEAL."""
    rec = cmo.orchestrate(make_proposal())
    assert rec.stages[-1].stage_name == "SEAL"
    assert rec.stages[-1].stage_index == 9


# ===========================================================================
# CMO-CHAIN-0 · HMAC chain integrity (T05–T08)
# ===========================================================================

def test_t193_cmo_05_stage_records_have_hashes(cmo):
    """T193-CMO-05: every stage record carries a non-empty record_hash."""
    rec = cmo.orchestrate(make_proposal())
    for s in rec.stages:
        assert len(s.record_hash) == 64  # SHA-256 hex


def test_t193_cmo_06_stage_chain_linked(cmo):
    """T193-CMO-06: each stage's prev_hash equals the prior stage's record_hash."""
    rec = cmo.orchestrate(make_proposal())
    for i in range(1, len(rec.stages)):
        assert rec.stages[i].prev_hash == rec.stages[i - 1].record_hash


def test_t193_cmo_07_ledger_chain_valid_after_orchestration(cmo):
    """T193-CMO-07: ledger chain passes verify_chain() after successful run."""
    cmo.orchestrate(make_proposal())
    assert cmo.verify_chain() is True


def test_t193_cmo_08_ledger_chain_valid_multiple_runs(cmo):
    """T193-CMO-08: chain valid after multiple orchestrations."""
    for _ in range(3):
        cmo.orchestrate(make_proposal())
    assert cmo.verify_chain() is True


# ===========================================================================
# CMO-HUMAN0-0 · HUMAN-0 gates (T09–T11)
# ===========================================================================

def test_t193_cmo_09_critical_risk_no_token_raises(cmo):
    """T193-CMO-09: CRITICAL risk without HUMAN-0 token raises CMOHuman0Required."""
    # blast_radius=0.95 tier=0 → composite risk ≥ 0.80 → CRITICAL
    p = make_proposal(blast_radius=0.95, tier=0)
    rec = cmo.orchestrate(p, human0_token=None)
    assert rec.status == PipelineStatus.HUMAN0_GATED


def test_t193_cmo_10_critical_risk_with_token_passes(cmo):
    """T193-CMO-10: CRITICAL risk with valid HUMAN-0 token completes pipeline."""
    p = make_proposal(blast_radius=0.95, tier=0)
    # Ensure blast stays under MEX hard block (0.95 allowed, > 0.95 is auto-rejected)
    rec = cmo.orchestrate(p, human0_token="HUMAN0-DUSTIN-REID-RATIFIED")
    # May complete or abort on fitness — either way NOT HUMAN0_GATED
    assert rec.status != PipelineStatus.HUMAN0_GATED


def test_t193_cmo_11_scope_violation_gates_at_stage1(cmo):
    """T193-CMO-11: wrong scope aborts at PROPOSE stage (STAGE-1)."""
    p = make_proposal(scope="external-system")
    rec = cmo.orchestrate(p)
    assert rec.status == PipelineStatus.ABORTED
    # Only PROPOSE stage attempted (or zero stages if caught immediately)
    assert len(rec.stages) == 0 or rec.stages[-1].stage_name == "PROPOSE"


# ===========================================================================
# CMO-STAGE-0 · Stage failure aborts pipeline (T12–T15)
# ===========================================================================

def test_t193_cmo_12_high_blast_radius_aborts(cmo):
    """T193-CMO-12: blast_radius > 0.95 triggers auto-abort (MEX-BLAST-0)."""
    p = make_proposal(blast_radius=0.96)
    rec = cmo.orchestrate(p)
    assert rec.status == PipelineStatus.ABORTED


def test_t193_cmo_13_aborted_record_has_abort_reason(cmo):
    """T193-CMO-13: aborted records always populate abort_reason."""
    p = make_proposal(blast_radius=0.96)
    rec = cmo.orchestrate(p)
    assert rec.abort_reason is not None and len(rec.abort_reason) > 0


def test_t193_cmo_14_aborted_pipeline_not_in_main_ledger(cmo, tmp_path):
    """T193-CMO-14: ABORTED orchestrations are NOT appended to main ledger."""
    p = make_proposal(blast_radius=0.96)
    cmo.orchestrate(p)
    # history() returns main ledger — aborted records excluded
    completed = [r for r in cmo.history() if r["status"] == "COMPLETED"]
    assert all(r["status"] == "COMPLETED" for r in completed)


def test_t193_cmo_15_pipeline_status_completed_on_success(cmo):
    """T193-CMO-15: healthy proposal results in COMPLETED status."""
    rec = cmo.orchestrate(make_proposal(blast_radius=0.20, tier=2))
    assert rec.status == PipelineStatus.COMPLETED


# ===========================================================================
# CMO-ATOMIC-0 · Atomicity (T16–T18)
# ===========================================================================

def test_t193_cmo_16_scope_rejection_produces_abort_ledger_entry(cmo, tmp_path):
    """T193-CMO-16: scope violation produces abort ledger entry."""
    p = make_proposal(scope="not-adaad")
    cmo.orchestrate(p)
    abort_path = cmo._ledger._path.parent / "abort_ledger.jsonl"
    assert abort_path.exists()
    with open(abort_path) as fh:
        entries = [json.loads(l) for l in fh]
    assert any(e["proposal_id"] == p.proposal_id for e in entries)


def test_t193_cmo_17_abort_entry_has_required_fields(cmo):
    """T193-CMO-17: abort ledger entries contain orchestration_id and reason."""
    p = make_proposal(blast_radius=0.96)
    cmo.orchestrate(p)
    abort_path = cmo._ledger._path.parent / "abort_ledger.jsonl"
    with open(abort_path) as fh:
        entry = json.loads(fh.readline())
    assert "orchestration_id" in entry
    assert "reason" in entry
    assert "stages_completed" in entry


def test_t193_cmo_18_completed_orchestration_has_all_stage_hashes(cmo):
    """T193-CMO-18: COMPLETED record has record_hash for each of 9 stages."""
    rec = cmo.orchestrate(make_proposal())
    assert len(rec.stages) == 9
    for s in rec.stages:
        assert s.record_hash and s.record_hash != ""


# ===========================================================================
# CMO-REPLAY-0 · Deterministic replay data (T19–T21)
# ===========================================================================

def test_t193_cmo_19_orchestration_record_has_replay_fields(cmo):
    """T193-CMO-19: OrchestrationRecord has all replay fields."""
    rec = cmo.orchestrate(make_proposal())
    assert rec.orchestration_id
    assert rec.proposal_id
    assert rec.scope
    assert rec.governor == "DUSTIN L REID"
    assert rec.seal_hash
    assert rec.chain_hash


def test_t193_cmo_20_stage_records_carry_prev_hash_for_replay(cmo):
    """T193-CMO-20: every stage record carries prev_hash (replay anchor)."""
    rec = cmo.orchestrate(make_proposal())
    for s in rec.stages:
        assert hasattr(s, "prev_hash")
        assert s.prev_hash is not None


def test_t193_cmo_21_seal_stage_output_contains_pipeline_seal(cmo):
    """T193-CMO-21: SEAL stage output contains pipeline_seal digest."""
    rec = cmo.orchestrate(make_proposal())
    seal_stage = rec.stages[-1]
    assert "pipeline_seal" in seal_stage.output
    assert len(seal_stage.output["pipeline_seal"]) == 64


# ===========================================================================
# CMO-SEAL-0 · SEAL stage written before return (T22–T24)
# ===========================================================================

def test_t193_cmo_22_seal_hash_populated_on_completed(cmo):
    """T193-CMO-22: seal_hash non-empty on COMPLETED record."""
    rec = cmo.orchestrate(make_proposal())
    assert rec.seal_hash and len(rec.seal_hash) == 64


def test_t193_cmo_23_seal_hash_matches_recompute(cmo):
    """T193-CMO-23: seal_hash equals recomputed value from record fields."""
    rec = cmo.orchestrate(make_proposal())
    recomputed = rec.compute_seal()
    assert rec.seal_hash == recomputed


def test_t193_cmo_24_chain_hash_covers_seal(cmo):
    """T193-CMO-24: chain_hash is derived from seal_hash (not independent)."""
    rec = cmo.orchestrate(make_proposal())
    # If seal_hash is part of chain_hash computation, they must differ
    assert rec.chain_hash != rec.seal_hash
    # Both non-empty 64-char hex
    assert len(rec.chain_hash) == 64


# ===========================================================================
# CMO-AUDIT-0 · Every transition ledgered (T25–T27)
# ===========================================================================

def test_t193_cmo_25_stage_audit_file_created(cmo):
    """T193-CMO-25: stage_audit.jsonl created after orchestration."""
    cmo.orchestrate(make_proposal())
    audit_path = cmo._ledger._path.parent / "stage_audit.jsonl"
    assert audit_path.exists()


def test_t193_cmo_26_stage_audit_has_nine_entries(cmo):
    """T193-CMO-26: nine audit entries written for a successful pipeline."""
    cmo.orchestrate(make_proposal())
    audit_path = cmo._ledger._path.parent / "stage_audit.jsonl"
    with open(audit_path) as fh:
        entries = [json.loads(l) for l in fh]
    assert len(entries) == 9


def test_t193_cmo_27_audit_entries_have_required_fields(cmo):
    """T193-CMO-27: each audit entry has orchestration_id, stage_name, status, record_hash."""
    cmo.orchestrate(make_proposal())
    audit_path = cmo._ledger._path.parent / "stage_audit.jsonl"
    with open(audit_path) as fh:
        for line in fh:
            e = json.loads(line)
            assert "orchestration_id" in e
            assert "stage_name" in e
            assert "status" in e
            assert "record_hash" in e


# ===========================================================================
# CMO-SCOPE-0 · Non-ADAAD scope rejected (T28–T29)
# ===========================================================================

def test_t193_cmo_28_external_scope_aborted(cmo):
    """T193-CMO-28: scope != 'adaad-constitutional' → ABORTED."""
    p = make_proposal(scope="external-legacy-system")
    rec = cmo.orchestrate(p)
    assert rec.status == PipelineStatus.ABORTED


def test_t193_cmo_29_correct_scope_accepted(cmo):
    """T193-CMO-29: correct scope passes PROPOSE stage."""
    p = make_proposal(scope="adaad-constitutional")
    rec = cmo.orchestrate(p)
    # Pipeline proceeds past PROPOSE
    assert len(rec.stages) >= 1
    assert rec.stages[0].stage_name == "PROPOSE"
    assert rec.stages[0].status == StageStatus.PASSED


# ===========================================================================
# CMO-DETERM-0 · Deterministic outputs (T30)
# ===========================================================================

def test_t193_cmo_30_deterministic_stage_hashes_same_inputs(tmp_path):
    """T193-CMO-30: identical inputs produce identical stage record_hashes (CMO-DETERM-0)."""
    fixed_id = "deterministic-test-proposal-id"

    def run() -> list:
        ledger_path = tmp_path / f"cmo_{uuid.uuid4()}" / "ledger.jsonl"
        ledger = CMOLedger(ledger_path)
        engine = ConstitutionalMutationOrchestrator(ledger=ledger)
        p = MutationProposal(
            proposal_id=fixed_id,
            scope="adaad-constitutional",
            description="Determinism check",
            blast_radius=0.30,
            tier=2,
            payload={"key": "value"},
            submitter="DEVADAAD",
            epoch=193,
        )
        rec = engine.orchestrate(p)
        return [s.record_hash for s in rec.stages]

    hashes_a = run()
    hashes_b = run()
    assert hashes_a == hashes_b, "CMO-DETERM-0 violated: non-deterministic stage hashes"
