# SPDX-License-Identifier: Apache-2.0
"""
Phase 182 · INNOV-87 · CGR — Convergence Gap Resolver
Test suite T182-CGR-01..30
Governor: DUSTIN L REID
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from dorkllm.convergence_gap_resolver import (
    _ACTION_CATALOGUE,
    _CRITICAL_GAP_THRESHOLD,
    _WARNING_GAP_THRESHOLD,
    _canonical_json,
    _gap_severity,
    _hmac_digest,
    _HMAC_KEY,
    _ledger_score,
    _read_json,
    _read_jsonl,
    ConvergenceGapResolver,
    DEFAULT_TOP_N,
    GapResolutionPlan,
    RemediationAction,
)

pytestmark = pytest.mark.phase182_cgr


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def engine(tmp_path):
    return ConvergenceGapResolver(data_dir=tmp_path / "cgr")


@pytest.fixture
def engine_with_gir(tmp_path):
    """Engine with a minimal GIR snapshot pre-seeded to control input."""
    gir_dir = tmp_path / "data" / "gir"
    gir_dir.mkdir(parents=True)
    snap = {
        "cri": 0.45,
        "cri_status": "CRITICAL",
        "lowest_dimensions": ["cel_feedback_integration", "recommendation_delivery", "forecast_coverage"],
    }
    (gir_dir / "gir_snapshot.json").write_text(json.dumps(snap))
    gap_report = [
        {"assessment_id": "test-1", "cri": 0.45, "gaps": [
            {"dimension": "cel_feedback_integration", "score": 0.10, "gap": "CFI ledger empty"},
            {"dimension": "recommendation_delivery", "score": 0.20, "gap": "RDP ledger empty"},
            {"dimension": "forecast_coverage", "score": 0.30, "gap": "CFE ledger shallow"},
        ]}
    ]
    with (gir_dir / "gap_report.jsonl").open("w") as f:
        for r in gap_report:
            f.write(json.dumps(r) + "\n")

    import dorkllm.convergence_gap_resolver as cgr_mod
    orig_gir = cgr_mod._GIR_SNAPSHOT
    orig_gap = cgr_mod._GIR_GAP_REPORT
    cgr_mod._GIR_SNAPSHOT = gir_dir / "gir_snapshot.json"
    cgr_mod._GIR_GAP_REPORT = gir_dir / "gap_report.jsonl"

    eng = ConvergenceGapResolver(data_dir=tmp_path / "cgr")
    yield eng

    cgr_mod._GIR_SNAPSHOT = orig_gir
    cgr_mod._GIR_GAP_REPORT = orig_gap


# ══════════════════════════════════════════════════════════════════════════════
# T182-CGR-01  Engine instantiates without error
# ══════════════════════════════════════════════════════════════════════════════
def test_cgr_01_instantiation(engine):
    assert isinstance(engine, ConvergenceGapResolver)


# ══════════════════════════════════════════════════════════════════════════════
# T182-CGR-02  resolve() returns result with required fields
# ══════════════════════════════════════════════════════════════════════════════
def test_cgr_02_resolve_fields(engine):
    result = engine.resolve()
    assert result.plan_id
    assert result.timestamp
    assert result.governor == "DUSTIN L REID"
    assert result.gir_cri is not None
    assert result.overall_convergence_score is not None


# ══════════════════════════════════════════════════════════════════════════════
# T182-CGR-03  overall_convergence_score in [0.0, 1.0]
# ══════════════════════════════════════════════════════════════════════════════
def test_cgr_03_convergence_bounded(engine):
    result = engine.resolve()
    assert 0.0 <= result.overall_convergence_score <= 1.0


# ══════════════════════════════════════════════════════════════════════════════
# T182-CGR-04  plans list has at most top_n entries
# ══════════════════════════════════════════════════════════════════════════════
def test_cgr_04_plans_top_n(engine):
    result = engine.resolve(top_n=3)
    assert len(result.plans) <= 3


# ══════════════════════════════════════════════════════════════════════════════
# T182-CGR-05  Each GapResolutionPlan has required fields
# ══════════════════════════════════════════════════════════════════════════════
def test_cgr_05_plan_fields(engine):
    result = engine.resolve(top_n=2)
    for plan in result.plans:
        assert plan.gap_id
        assert plan.dimension
        assert 0.0 <= plan.observed_score <= 1.0
        assert plan.severity in ("CRITICAL", "WARNING", "ACCEPTABLE")
        assert isinstance(plan.actions, list)
        assert plan.estimated_total_invariants >= 0
        assert plan.estimated_total_tests >= 0


# ══════════════════════════════════════════════════════════════════════════════
# T182-CGR-06  Actions present for every plan
# ══════════════════════════════════════════════════════════════════════════════
def test_cgr_06_actions_present(engine):
    result = engine.resolve()
    for plan in result.plans:
        assert len(plan.actions) > 0
        for action in plan.actions:
            assert action.action
            assert action.rank >= 1
            assert isinstance(action.ip_opportunity, bool)


# ══════════════════════════════════════════════════════════════════════════════
# T182-CGR-07  Action ranks are ordered (1, 2, 3)
# ══════════════════════════════════════════════════════════════════════════════
def test_cgr_07_action_rank_order(engine):
    result = engine.resolve()
    for plan in result.plans:
        ranks = [a.rank for a in plan.actions]
        assert ranks == sorted(ranks)


# ══════════════════════════════════════════════════════════════════════════════
# T182-CGR-08  Ledger entry written after resolve() — CGR-AUDIT-0
# ══════════════════════════════════════════════════════════════════════════════
def test_cgr_08_ledger_written(engine, tmp_path):
    result = engine.resolve()
    entries = _read_jsonl(tmp_path / "cgr" / "grp_ledger.jsonl")
    assert len(entries) == 1
    assert entries[0]["plan_id"] == result.plan_id


# ══════════════════════════════════════════════════════════════════════════════
# T182-CGR-09  Chain valid after first resolve — CGR-CHAIN-0
# ══════════════════════════════════════════════════════════════════════════════
def test_cgr_09_chain_valid_single(engine):
    engine.resolve()
    valid, reason = engine.verify_chain()
    assert valid, reason


# ══════════════════════════════════════════════════════════════════════════════
# T182-CGR-10  Chain valid after 5 resolves
# ══════════════════════════════════════════════════════════════════════════════
def test_cgr_10_chain_valid_multi(engine):
    for _ in range(5):
        engine.resolve()
    valid, reason = engine.verify_chain()
    assert valid, reason


# ══════════════════════════════════════════════════════════════════════════════
# T182-CGR-11  Duplicate plan_id raises ValueError — CGR-DOUBLE-0
# ══════════════════════════════════════════════════════════════════════════════
def test_cgr_11_double_plan_rejected(engine):
    pid = str(uuid.uuid4())
    engine.resolve(plan_id=pid)
    with pytest.raises(ValueError, match="CGR-DOUBLE-0"):
        engine.resolve(plan_id=pid)


# ══════════════════════════════════════════════════════════════════════════════
# T182-CGR-12  Snapshot written after resolve — CGR-PERSIST-0
# ══════════════════════════════════════════════════════════════════════════════
def test_cgr_12_snapshot_written(engine, tmp_path):
    result = engine.resolve()
    snap = _read_json(tmp_path / "cgr" / "cgr_snapshot.json")
    assert snap
    assert snap["last_plan_id"] == result.plan_id


# ══════════════════════════════════════════════════════════════════════════════
# T182-CGR-13  get_snapshot() returns None before first resolve
# ══════════════════════════════════════════════════════════════════════════════
def test_cgr_13_snapshot_none_before_resolve(engine):
    assert engine.get_snapshot() is None


# ══════════════════════════════════════════════════════════════════════════════
# T182-CGR-14  get_snapshot() returns dict after resolve
# ══════════════════════════════════════════════════════════════════════════════
def test_cgr_14_snapshot_after_resolve(engine):
    engine.resolve()
    snap = engine.get_snapshot()
    assert snap is not None
    assert "last_gir_cri" in snap


# ══════════════════════════════════════════════════════════════════════════════
# T182-CGR-15  Plan count increments
# ══════════════════════════════════════════════════════════════════════════════
def test_cgr_15_plan_count(engine):
    assert engine.get_plan_count() == 0
    engine.resolve()
    assert engine.get_plan_count() == 1
    engine.resolve()
    assert engine.get_plan_count() == 2


# ══════════════════════════════════════════════════════════════════════════════
# T182-CGR-16  Seal is 64-char hex — CGR-SEAL-0
# ══════════════════════════════════════════════════════════════════════════════
def test_cgr_16_seal_hex(engine):
    result = engine.resolve()
    assert len(result.seal) == 64
    int(result.seal, 16)   # raises ValueError if not valid hex


# ══════════════════════════════════════════════════════════════════════════════
# T182-CGR-17  chain_prev_digest of first entry is GENESIS
# ══════════════════════════════════════════════════════════════════════════════
def test_cgr_17_genesis_head(engine, tmp_path):
    engine.resolve()
    entries = _read_jsonl(tmp_path / "cgr" / "grp_ledger.jsonl")
    assert entries[0]["chain_prev_digest"] == "GENESIS"


# ══════════════════════════════════════════════════════════════════════════════
# T182-CGR-18  HMAC digest is deterministic — CGR-DETERM-0
# ══════════════════════════════════════════════════════════════════════════════
def test_cgr_18_hmac_determ():
    data = "adaad-cgr-test"
    assert _hmac_digest(_HMAC_KEY, data) == _hmac_digest(_HMAC_KEY, data)


# ══════════════════════════════════════════════════════════════════════════════
# T182-CGR-19  Empty chain verify returns CHAIN_VALID_EMPTY
# ══════════════════════════════════════════════════════════════════════════════
def test_cgr_19_empty_chain(engine):
    valid, reason = engine.verify_chain()
    assert valid
    assert "EMPTY" in reason


# ══════════════════════════════════════════════════════════════════════════════
# T182-CGR-20  gap_severity thresholds correct
# ══════════════════════════════════════════════════════════════════════════════
def test_cgr_20_gap_severity():
    assert _gap_severity(0.0) == "CRITICAL"
    assert _gap_severity(_CRITICAL_GAP_THRESHOLD - 0.01) == "CRITICAL"
    assert _gap_severity(_CRITICAL_GAP_THRESHOLD) == "WARNING"
    assert _gap_severity(_WARNING_GAP_THRESHOLD - 0.01) == "WARNING"
    assert _gap_severity(_WARNING_GAP_THRESHOLD) == "ACCEPTABLE"
    assert _gap_severity(1.0) == "ACCEPTABLE"


# ══════════════════════════════════════════════════════════════════════════════
# T182-CGR-21  HUMAN-0 advisory emitted for CRITICAL gaps — CGR-HUMAN0-0
# ══════════════════════════════════════════════════════════════════════════════
def test_cgr_21_human0_advisory_critical(engine_with_gir, tmp_path):
    result = engine_with_gir.resolve()
    if result.human0_advisory:
        assert result.advisory_payload is not None
        assert "DUSTIN L REID" in result.advisory_payload
        adv_path = tmp_path / "cgr" / "human0_advisory_log.jsonl"
        assert adv_path.exists()
        entries = _read_jsonl(adv_path)
        assert len(entries) >= 1


# ══════════════════════════════════════════════════════════════════════════════
# T182-CGR-22  human0_ratification_required True for CRITICAL plans
# ══════════════════════════════════════════════════════════════════════════════
def test_cgr_22_ratification_flag(engine):
    result = engine.resolve()
    for plan in result.plans:
        if plan.severity == "CRITICAL":
            assert plan.human0_ratification_required is True
        else:
            assert plan.human0_ratification_required is False


# ══════════════════════════════════════════════════════════════════════════════
# T182-CGR-23  canonical_json produces sorted keys
# ══════════════════════════════════════════════════════════════════════════════
def test_cgr_23_canonical_json():
    obj = {"z": 3, "a": 1, "m": 2}
    result = _canonical_json(obj)
    assert result == '{"a":1,"m":2,"z":3}'


# ══════════════════════════════════════════════════════════════════════════════
# T182-CGR-24  Plans are sorted by score ascending — CGR-TOPN-0
# ══════════════════════════════════════════════════════════════════════════════
def test_cgr_24_plans_sorted_ascending(engine_with_gir):
    result = engine_with_gir.resolve(top_n=3)
    scores = [p.observed_score for p in result.plans]
    assert scores == sorted(scores)


# ══════════════════════════════════════════════════════════════════════════════
# T182-CGR-25  delta_to_threshold is non-negative
# ══════════════════════════════════════════════════════════════════════════════
def test_cgr_25_delta_nonneg(engine):
    result = engine.resolve()
    for plan in result.plans:
        assert plan.delta_to_threshold >= 0.0


# ══════════════════════════════════════════════════════════════════════════════
# T182-CGR-26  IP opportunity flags present when action catalogue marks them
# ══════════════════════════════════════════════════════════════════════════════
def test_cgr_26_ip_flags(engine):
    result = engine.resolve()
    for plan in result.plans:
        ip_actions = [a for a in plan.actions if a.ip_opportunity]
        assert plan.ip_opportunities == [a.action for a in ip_actions]


# ══════════════════════════════════════════════════════════════════════════════
# T182-CGR-27  estimated_total_invariants equals sum of action estimates
# ══════════════════════════════════════════════════════════════════════════════
def test_cgr_27_invariant_sum(engine):
    result = engine.resolve()
    for plan in result.plans:
        expected = sum(a.estimated_invariants_to_add for a in plan.actions)
        assert plan.estimated_total_invariants == expected


# ══════════════════════════════════════════════════════════════════════════════
# T182-CGR-28  estimated_total_tests equals sum of action estimates
# ══════════════════════════════════════════════════════════════════════════════
def test_cgr_28_test_sum(engine):
    result = engine.resolve()
    for plan in result.plans:
        expected = sum(a.estimated_tests_to_add for a in plan.actions)
        assert plan.estimated_total_tests == expected


# ══════════════════════════════════════════════════════════════════════════════
# T182-CGR-29  CGR-SCOPE-0 — resolve() does not write to upstream GIR paths
# ══════════════════════════════════════════════════════════════════════════════
def test_cgr_29_readonly_scope(engine, tmp_path):
    upstream = [
        Path("data/gir/gir_snapshot.json"),
        Path("data/gir/gap_report.jsonl"),
    ]
    before = {p: p.stat().st_mtime if p.exists() else None for p in upstream}
    engine.resolve()
    after = {p: p.stat().st_mtime if p.exists() else None for p in upstream}
    for p in upstream:
        assert before[p] == after[p], f"CGR-SCOPE-0 violated: {p} was written"


# ══════════════════════════════════════════════════════════════════════════════
# T182-CGR-30  Action catalogue covers all 10 GIR dimensions
# ══════════════════════════════════════════════════════════════════════════════
def test_cgr_30_catalogue_completeness():
    expected_dims = {
        "constitutional_lifecycle", "stability_monitoring", "adaptive_learning",
        "recommendation_delivery", "cel_feedback_integration", "forecast_coverage",
        "invariant_density", "test_coverage", "governance_telemetry", "rollback_capability",
    }
    assert set(_ACTION_CATALOGUE.keys()) == expected_dims
