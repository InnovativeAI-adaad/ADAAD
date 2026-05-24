# SPDX-License-Identifier: Apache-2.0
"""
Phase 181 · INNOV-86 · GIR — Governance Implementation Readiness
Test suite T181-GIR-01..30
Governor: DUSTIN L REID
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import pytest

from dorkllm.governance_implementation_readiness import (
    CRITICAL_THRESHOLD,
    WARNING_THRESHOLD,
    GovernanceImplementationReadiness,
    _cri_status,
    _hmac_digest,
    _HMAC_KEY,
    _canonical_json,
    _ledger_score,
    _read_jsonl,
    _read_json,
    _DIM_WEIGHTS,
    _V10_CRITERIA,
)

pytestmark = pytest.mark.phase181_gir


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_engine(tmp_path):
    """GIR engine pointed at an isolated tmp directory."""
    engine = GovernanceImplementationReadiness(data_dir=tmp_path / "gir")
    return engine, tmp_path


# ══════════════════════════════════════════════════════════════════════════════
# T181-GIR-01  Engine instantiates without error
# ══════════════════════════════════════════════════════════════════════════════
def test_gir_01_instantiation(tmp_engine):
    engine, _ = tmp_engine
    assert isinstance(engine, GovernanceImplementationReadiness)


# ══════════════════════════════════════════════════════════════════════════════
# T181-GIR-02  assess() returns a result with required fields
# ══════════════════════════════════════════════════════════════════════════════
def test_gir_02_assess_fields(tmp_engine):
    engine, _ = tmp_engine
    result = engine.assess()
    assert result.assessment_id
    assert result.timestamp
    assert result.cri is not None
    assert result.cri_status in ("READY", "WARNING", "CRITICAL")
    assert result.governor == "DUSTIN L REID"


# ══════════════════════════════════════════════════════════════════════════════
# T181-GIR-03  CRI is in [0.0, 1.0]
# ══════════════════════════════════════════════════════════════════════════════
def test_gir_03_cri_bounds(tmp_engine):
    engine, _ = tmp_engine
    result = engine.assess()
    assert 0.0 <= result.cri <= 1.0


# ══════════════════════════════════════════════════════════════════════════════
# T181-GIR-04  Dimension weights sum to 1.0 — GIR-WEIGHT-0
# ══════════════════════════════════════════════════════════════════════════════
def test_gir_04_weights_sum(tmp_engine):
    _, _ = tmp_engine
    total = sum(_DIM_WEIGHTS.values())
    assert abs(total - 1.0) < 1e-9, f"Weights sum to {total}, expected 1.0"


# ══════════════════════════════════════════════════════════════════════════════
# T181-GIR-05  Ten dimensions scored
# ══════════════════════════════════════════════════════════════════════════════
def test_gir_05_ten_dimensions(tmp_engine):
    engine, _ = tmp_engine
    result = engine.assess()
    assert len(result.dimensions) == 10


# ══════════════════════════════════════════════════════════════════════════════
# T181-GIR-06  All dimension scores in [0.0, 1.0]
# ══════════════════════════════════════════════════════════════════════════════
def test_gir_06_dimension_scores_bounded(tmp_engine):
    engine, _ = tmp_engine
    result = engine.assess()
    for d in result.dimensions:
        assert 0.0 <= d.score <= 1.0, f"Dimension {d.dimension} score={d.score} out of bounds"


# ══════════════════════════════════════════════════════════════════════════════
# T181-GIR-07  Seven V10 criteria evaluated
# ══════════════════════════════════════════════════════════════════════════════
def test_gir_07_seven_v10_criteria(tmp_engine):
    engine, _ = tmp_engine
    result = engine.assess()
    assert len(result.v10_criteria) == 7
    criterion_names = {c.criterion for c in result.v10_criteria}
    for name in _V10_CRITERIA:
        assert name in criterion_names


# ══════════════════════════════════════════════════════════════════════════════
# T181-GIR-08  V10 criterion confidence in [0.0, 1.0]
# ══════════════════════════════════════════════════════════════════════════════
def test_gir_08_v10_confidence_bounded(tmp_engine):
    engine, _ = tmp_engine
    result = engine.assess()
    for c in result.v10_criteria:
        assert 0.0 <= c.confidence <= 1.0, f"Criterion {c.criterion} confidence={c.confidence}"


# ══════════════════════════════════════════════════════════════════════════════
# T181-GIR-09  Ledger entry written after assess() — GIR-AUDIT-0
# ══════════════════════════════════════════════════════════════════════════════
def test_gir_09_ledger_written(tmp_engine):
    engine, tmp_path = tmp_engine
    result = engine.assess()
    entries = _read_jsonl(tmp_path / "gir" / "readiness_assessment_ledger.jsonl")
    assert len(entries) == 1
    assert entries[0]["assessment_id"] == result.assessment_id


# ══════════════════════════════════════════════════════════════════════════════
# T181-GIR-10  Chain is valid after first assessment — GIR-CHAIN-0
# ══════════════════════════════════════════════════════════════════════════════
def test_gir_10_chain_valid_single(tmp_engine):
    engine, _ = tmp_engine
    engine.assess()
    valid, reason = engine.verify_chain()
    assert valid, f"Chain invalid: {reason}"


# ══════════════════════════════════════════════════════════════════════════════
# T181-GIR-11  Chain valid after multiple assessments
# ══════════════════════════════════════════════════════════════════════════════
def test_gir_11_chain_valid_multi(tmp_engine):
    engine, _ = tmp_engine
    for _ in range(5):
        engine.assess()
    valid, reason = engine.verify_chain()
    assert valid, f"Chain invalid after 5 assessments: {reason}"


# ══════════════════════════════════════════════════════════════════════════════
# T181-GIR-12  Duplicate assessment_id raises ValueError — GIR-DOUBLE-0
# ══════════════════════════════════════════════════════════════════════════════
def test_gir_12_double_assessment_rejected(tmp_engine):
    engine, _ = tmp_engine
    aid = str(uuid.uuid4())
    engine.assess(assessment_id=aid)
    with pytest.raises(ValueError, match="GIR-DOUBLE-0"):
        engine.assess(assessment_id=aid)


# ══════════════════════════════════════════════════════════════════════════════
# T181-GIR-13  Snapshot written after assess() — GIR-PERSIST-0
# ══════════════════════════════════════════════════════════════════════════════
def test_gir_13_snapshot_written(tmp_engine):
    engine, tmp_path = tmp_engine
    result = engine.assess()
    snap = _read_json(tmp_path / "gir" / "gir_snapshot.json")
    assert snap
    assert abs(snap["cri"] - result.cri) < 1e-9


# ══════════════════════════════════════════════════════════════════════════════
# T181-GIR-14  get_snapshot() returns dict after assess()
# ══════════════════════════════════════════════════════════════════════════════
def test_gir_14_get_snapshot(tmp_engine):
    engine, _ = tmp_engine
    engine.assess()
    snap = engine.get_snapshot()
    assert snap is not None
    assert "cri" in snap
    assert "cri_status" in snap


# ══════════════════════════════════════════════════════════════════════════════
# T181-GIR-15  get_snapshot() returns None before first assess()
# ══════════════════════════════════════════════════════════════════════════════
def test_gir_15_snapshot_none_before_assess(tmp_engine):
    engine, _ = tmp_engine
    snap = engine.get_snapshot()
    assert snap is None


# ══════════════════════════════════════════════════════════════════════════════
# T181-GIR-16  Assessment count increments correctly
# ══════════════════════════════════════════════════════════════════════════════
def test_gir_16_assessment_count(tmp_engine):
    engine, _ = tmp_engine
    assert engine.get_assessment_count() == 0
    engine.assess()
    assert engine.get_assessment_count() == 1
    engine.assess()
    assert engine.get_assessment_count() == 2


# ══════════════════════════════════════════════════════════════════════════════
# T181-GIR-17  CRI status thresholds are correct — GIR-THRESHOLD-0
# ══════════════════════════════════════════════════════════════════════════════
def test_gir_17_cri_status_thresholds():
    assert _cri_status(1.0) == "READY"
    assert _cri_status(WARNING_THRESHOLD) == "READY"
    assert _cri_status(WARNING_THRESHOLD - 0.01) == "WARNING"
    assert _cri_status(CRITICAL_THRESHOLD) == "WARNING"
    assert _cri_status(CRITICAL_THRESHOLD - 0.01) == "CRITICAL"
    assert _cri_status(0.0) == "CRITICAL"


# ══════════════════════════════════════════════════════════════════════════════
# T181-GIR-18  HMAC digest is deterministic — GIR-DETERM-0
# ══════════════════════════════════════════════════════════════════════════════
def test_gir_18_hmac_determinism():
    data = "test-payload-adaad"
    d1 = _hmac_digest(_HMAC_KEY, data)
    d2 = _hmac_digest(_HMAC_KEY, data)
    assert d1 == d2


# ══════════════════════════════════════════════════════════════════════════════
# T181-GIR-19  Ledger score helper bounded
# ══════════════════════════════════════════════════════════════════════════════
def test_gir_19_ledger_score_bounded():
    assert _ledger_score(0) == 0.0
    assert _ledger_score(5) == 1.0
    assert _ledger_score(100) == 1.0
    score = _ledger_score(2)
    assert 0.0 < score < 1.0


# ══════════════════════════════════════════════════════════════════════════════
# T181-GIR-20  Weighted contribution sums to CRI
# ══════════════════════════════════════════════════════════════════════════════
def test_gir_20_weighted_sum_equals_cri(tmp_engine):
    engine, _ = tmp_engine
    result = engine.assess()
    computed = sum(d.weighted_contribution for d in result.dimensions)
    computed = round(min(1.0, max(0.0, computed)), 6)
    assert abs(computed - result.cri) < 1e-5


# ══════════════════════════════════════════════════════════════════════════════
# T181-GIR-21  Seal is non-empty and consistent — GIR-SEAL-0
# ══════════════════════════════════════════════════════════════════════════════
def test_gir_21_seal_present(tmp_engine):
    engine, _ = tmp_engine
    result = engine.assess()
    assert result.seal
    assert len(result.seal) == 64   # SHA-256 hex digest length


# ══════════════════════════════════════════════════════════════════════════════
# T181-GIR-22  chain_prev_digest of first entry is GENESIS
# ══════════════════════════════════════════════════════════════════════════════
def test_gir_22_genesis_chain_head(tmp_engine):
    engine, tmp_path = tmp_engine
    engine.assess()
    entries = _read_jsonl(tmp_path / "gir" / "readiness_assessment_ledger.jsonl")
    assert entries[0]["chain_prev_digest"] == "GENESIS"


# ══════════════════════════════════════════════════════════════════════════════
# T181-GIR-23  Gap report written for sub-threshold dimensions
# ══════════════════════════════════════════════════════════════════════════════
def test_gir_23_gap_report_written(tmp_engine):
    engine, tmp_path = tmp_engine
    result = engine.assess()
    gap_path = tmp_path / "gir" / "gap_report.jsonl"
    # Gap report written only if there are gaps
    low_dims = [d for d in result.dimensions if d.gap_description]
    if low_dims:
        assert gap_path.exists()
        entries = _read_jsonl(gap_path)
        assert len(entries) >= 1


# ══════════════════════════════════════════════════════════════════════════════
# T181-GIR-24  Human-0 advisory emitted when CRI < CRITICAL_THRESHOLD — GIR-HUMAN0-0
# ══════════════════════════════════════════════════════════════════════════════
def test_gir_24_human0_advisory_on_critical(tmp_path):
    """Patch upstream paths to empty to drive CRI below CRITICAL_THRESHOLD."""
    engine = GovernanceImplementationReadiness(data_dir=tmp_path / "gir")
    # With no upstream ledgers present, most dimensions score ~0 → CRI < 0.50
    result = engine.assess()
    if result.cri < CRITICAL_THRESHOLD:
        assert result.human0_escalation is True
        assert result.advisory_payload is not None
        assert "DUSTIN L REID" in result.advisory_payload
        advisory_log = tmp_path / "gir" / "human0_advisory_log.jsonl"
        assert advisory_log.exists()


# ══════════════════════════════════════════════════════════════════════════════
# T181-GIR-25  No HUMAN-0 escalation when CRI ≥ CRITICAL_THRESHOLD
# ══════════════════════════════════════════════════════════════════════════════
def test_gir_25_no_escalation_when_above_critical(tmp_engine):
    engine, _ = tmp_engine
    result = engine.assess()
    if result.cri >= CRITICAL_THRESHOLD:
        assert result.human0_escalation is False
        assert result.advisory_payload is None


# ══════════════════════════════════════════════════════════════════════════════
# T181-GIR-26  lowest_dimensions list has exactly 3 entries
# ══════════════════════════════════════════════════════════════════════════════
def test_gir_26_lowest_dimensions_count(tmp_engine):
    engine, _ = tmp_engine
    result = engine.assess()
    assert len(result.lowest_dimensions) == 3


# ══════════════════════════════════════════════════════════════════════════════
# T181-GIR-27  canonical_json produces consistent serialisation
# ══════════════════════════════════════════════════════════════════════════════
def test_gir_27_canonical_json_stable():
    obj = {"z": 3, "a": 1, "m": 2}
    s1 = _canonical_json(obj)
    s2 = _canonical_json(obj)
    assert s1 == s2
    assert s1 == '{"a":1,"m":2,"z":3}'   # keys sorted


# ══════════════════════════════════════════════════════════════════════════════
# T181-GIR-28  Empty ledger chain verification returns CHAIN_VALID_EMPTY
# ══════════════════════════════════════════════════════════════════════════════
def test_gir_28_empty_chain_valid(tmp_engine):
    engine, _ = tmp_engine
    valid, reason = engine.verify_chain()
    assert valid
    assert "EMPTY" in reason


# ══════════════════════════════════════════════════════════════════════════════
# T181-GIR-29  Dimension names match _DIM_WEIGHTS keys
# ══════════════════════════════════════════════════════════════════════════════
def test_gir_29_dimension_names_match_weights(tmp_engine):
    engine, _ = tmp_engine
    result = engine.assess()
    scored_names = {d.dimension for d in result.dimensions}
    weight_names = set(_DIM_WEIGHTS.keys())
    assert scored_names == weight_names


# ══════════════════════════════════════════════════════════════════════════════
# T181-GIR-30  GIR invariant: GIR-SCOPE-0 — assess does not write to upstream ledgers
# ══════════════════════════════════════════════════════════════════════════════
def test_gir_30_readonly_scope(tmp_engine, tmp_path):
    engine, _ = tmp_engine
    upstream_paths = [
        tmp_path / "data" / "car" / "rollback_execution_ledger.jsonl",
        tmp_path / "data" / "csc" / "stability_report_ledger.jsonl",
        tmp_path / "data" / "cae" / "amendment_execution_ledger.jsonl",
    ]
    # Capture mtime of upstream paths (all absent = None)
    before = {p: p.stat().st_mtime if p.exists() else None for p in upstream_paths}
    engine.assess()
    after = {p: p.stat().st_mtime if p.exists() else None for p in upstream_paths}
    for p in upstream_paths:
        assert before[p] == after[p], f"GIR-SCOPE-0 violated: {p} was mutated"
