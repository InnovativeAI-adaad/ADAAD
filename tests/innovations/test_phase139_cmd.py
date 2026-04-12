# SPDX-License-Identifier: Apache-2.0
# tests/innovations/test_phase139_cmd.py
# Phase 139 · INNOV-46 · Canary Mutation Deployment (CMD)
# 30 tests — must pass 30/30

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from runtime.innovations30.canary_mutation_deployment import (
    CONSTITUTIONAL_INVARIANTS,
    DEFAULT_CANARY_SLICE,
    DEFAULT_MIRROR_THRESHOLD,
    GENESIS_PREV_HASH,
    HIGH_RISK_TIERS,
    INNOV_ID,
    PHASE,
    VERSION,
    WORLD_FIRST,
    CMDAuthorizationViolation,
    CMDChainViolation,
    CMDGateViolation,
    CMDMirrorViolation,
    CanaryDeploymentEngine,
    CanaryStatus,
    CanaryEventType,
    _make_canary_id,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────
@pytest.fixture
def engine(tmp_path):
    return CanaryDeploymentEngine(ledger_path=tmp_path / "canary.jsonl")


@pytest.fixture
def open_canary(engine):
    dep = engine.open_canary("mut-001", tier=0, timestamp="2026-04-11T10:00:00Z")
    return engine, dep


@pytest.fixture
def mirror_checked(open_canary):
    eng, dep = open_canary
    eng.record_mirror_result(dep.canary_id, mirror_score=0.90,
                             timestamp="2026-04-11T10:05:00Z")
    return eng, dep


@pytest.fixture
def failed_mirror(open_canary):
    eng, dep = open_canary
    eng.record_mirror_result(dep.canary_id, mirror_score=0.50,
                             timestamp="2026-04-11T10:05:00Z")
    return eng, dep


# ── Metadata ──────────────────────────────────────────────────────────────────
def test_cmd_01_innov_id():
    assert INNOV_ID == "INNOV-46"


def test_cmd_02_phase():
    assert PHASE == 139


def test_cmd_03_version():
    assert VERSION == "9.72.0"


def test_cmd_04_world_first_nonempty():
    assert len(WORLD_FIRST) > 20


def test_cmd_05_invariants_count():
    assert len(CONSTITUTIONAL_INVARIANTS) == 5


def test_cmd_06_invariants_names():
    expected = {"CMD-GATE-0", "CMD-MIRROR-0", "CMD-ROLLBACK-0",
                "CMD-CHAIN-0", "CMD-HUMAN0-0"}
    assert set(CONSTITUTIONAL_INVARIANTS) == expected


# ── Basic lifecycle ───────────────────────────────────────────────────────────
def test_cmd_07_open_canary_creates_deployment(engine):
    dep = engine.open_canary("mut-A", tier=0, timestamp="2026-04-11T00:00:00Z")
    assert dep.canary_id.startswith("canary-")
    assert dep.mutation_id == "mut-A"
    assert dep.tier == 0
    assert dep.status == CanaryStatus.OPEN


def test_cmd_08_canary_slice_default(engine):
    dep = engine.open_canary("mut-B", tier=0, timestamp="2026-04-11T00:00:00Z")
    assert dep.canary_slice == DEFAULT_CANARY_SLICE


def test_cmd_09_canary_slice_custom(engine):
    dep = engine.open_canary("mut-C", tier=0, canary_slice=0.05,
                              timestamp="2026-04-11T00:00:00Z")
    assert dep.canary_slice == 0.05


def test_cmd_10_record_sample_increments_count(open_canary):
    eng, dep = open_canary
    eng.record_sample(dep.canary_id, success=True, timestamp="2026-04-11T10:01:00Z")
    eng.record_sample(dep.canary_id, success=False, timestamp="2026-04-11T10:02:00Z")
    d = eng.get_deployment(dep.canary_id)
    assert d.sample_count == 2
    assert d.error_count == 1


# ── CMD-MIRROR-0 ──────────────────────────────────────────────────────────────
def test_cmd_11_close_without_mirror_raises(open_canary):
    eng, dep = open_canary
    with pytest.raises(CMDMirrorViolation, match="CMD-MIRROR-0"):
        eng.close_canary(dep.canary_id, timestamp="2026-04-11T10:05:00Z")


def test_cmd_12_record_mirror_sets_status(open_canary):
    eng, dep = open_canary
    eng.record_mirror_result(dep.canary_id, mirror_score=0.85,
                             timestamp="2026-04-11T10:05:00Z")
    d = eng.get_deployment(dep.canary_id)
    assert d.status == CanaryStatus.MIRROR_CHECKED
    assert d.mirror_score == 0.85


# ── CMD-ROLLBACK-0: auto-rollback ─────────────────────────────────────────────
def test_cmd_13_auto_promote_on_passing_mirror(mirror_checked):
    eng, dep = mirror_checked
    result = eng.close_canary(dep.canary_id, timestamp="2026-04-11T10:06:00Z")
    assert result.status == CanaryStatus.PROMOTED


def test_cmd_14_auto_rollback_on_failing_mirror(failed_mirror):
    eng, dep = failed_mirror
    result = eng.close_canary(dep.canary_id, timestamp="2026-04-11T10:06:00Z")
    assert result.status == CanaryStatus.ROLLED_BACK


def test_cmd_15_rollback_sets_closed_at(failed_mirror):
    eng, dep = failed_mirror
    result = eng.close_canary(dep.canary_id, timestamp="2026-04-11T10:06:00Z")
    assert result.closed_at == "2026-04-11T10:06:00Z"


# ── CMD-GATE-0 ────────────────────────────────────────────────────────────────
def test_cmd_16_gate_blocks_high_risk_without_canary(engine):
    with pytest.raises(CMDGateViolation, match="CMD-GATE-0"):
        engine.require_canary_for_high_risk("mut-no-canary", tier=0)


def test_cmd_17_gate_passes_after_canary_opened(engine):
    engine.open_canary("mut-gated", tier=0, timestamp="2026-04-11T00:00:00Z")
    # Should not raise
    engine.require_canary_for_high_risk("mut-gated", tier=0)


def test_cmd_18_gate_passes_for_low_risk_tier(engine):
    # Tier 1 is not high-risk — no canary needed
    engine.require_canary_for_high_risk("mut-tier1", tier=1)


def test_cmd_19_tier0_is_high_risk():
    assert 0 in HIGH_RISK_TIERS


# ── CMD-HUMAN0-0 ──────────────────────────────────────────────────────────────
def test_cmd_20_promote_failed_requires_auth(failed_mirror):
    eng, dep = failed_mirror
    eng.close_canary(dep.canary_id, timestamp="2026-04-11T10:06:00Z")
    with pytest.raises(CMDAuthorizationViolation, match="CMD-HUMAN0-0"):
        eng.promote_failed_canary(dep.canary_id)


def test_cmd_21_promote_failed_with_auth_succeeds(failed_mirror):
    eng, dep = failed_mirror
    eng.close_canary(dep.canary_id, timestamp="2026-04-11T10:06:00Z")
    result = eng.promote_failed_canary(dep.canary_id, human_auth=True,
                                       rationale="approved by HUMAN-0",
                                       timestamp="2026-04-11T10:10:00Z")
    assert result.status == CanaryStatus.PROMOTED
    assert result.human0_override is True


# ── CMD-CHAIN-0: hash chain ───────────────────────────────────────────────────
def test_cmd_22_chain_valid_after_lifecycle(mirror_checked):
    eng, dep = mirror_checked
    eng.close_canary(dep.canary_id, timestamp="2026-04-11T10:06:00Z")
    assert eng.verify_chain() is True


def test_cmd_23_chain_broken_raises(open_canary):
    eng, dep = open_canary
    # Tamper the first event
    eng._events[0].prev_hash = "tampered"
    with pytest.raises(CMDChainViolation, match="CMD-CHAIN-0"):
        eng.verify_chain()


def test_cmd_24_genesis_prev_hash_is_zeros():
    assert GENESIS_PREV_HASH == "0" * 64


def test_cmd_25_ledger_digest_is_sha256_prefixed(engine):
    engine.open_canary("mut-D", tier=0, timestamp="2026-04-11T00:00:00Z")
    assert engine.ledger_digest().startswith("sha256:")


# ── Persistence round-trip ────────────────────────────────────────────────────
def test_cmd_26_persist_roundtrip(tmp_path):
    path = tmp_path / "canary.jsonl"
    e1 = CanaryDeploymentEngine(ledger_path=path)
    dep = e1.open_canary("mut-persist", tier=0, timestamp="2026-04-11T00:00:00Z")
    e1.record_mirror_result(dep.canary_id, mirror_score=0.90,
                             timestamp="2026-04-11T00:01:00Z")
    e1.close_canary(dep.canary_id, timestamp="2026-04-11T00:02:00Z")
    digest1 = e1.ledger_digest()

    e2 = CanaryDeploymentEngine(ledger_path=path)
    assert e2.ledger_digest() == digest1
    reloaded = e2.get_deployment(dep.canary_id)
    assert reloaded.status == CanaryStatus.PROMOTED


# ── Analysis API ──────────────────────────────────────────────────────────────
def test_cmd_27_active_canaries_lists_open(engine):
    engine.open_canary("mut-active", tier=0, timestamp="2026-04-11T00:00:00Z")
    assert len(engine.active_canaries()) == 1


def test_cmd_28_rollback_rate_zero_on_all_pass(tmp_path):
    eng = CanaryDeploymentEngine(ledger_path=tmp_path / "c.jsonl")
    dep = eng.open_canary("mut-pass", tier=0, timestamp="2026-04-11T00:00:00Z")
    eng.record_mirror_result(dep.canary_id, 0.95, timestamp="2026-04-11T00:01:00Z")
    eng.close_canary(dep.canary_id, timestamp="2026-04-11T00:02:00Z")
    assert eng.rollback_rate() == 0.0


def test_cmd_29_rollback_rate_one_on_all_fail(tmp_path):
    eng = CanaryDeploymentEngine(ledger_path=tmp_path / "c.jsonl")
    dep = eng.open_canary("mut-fail", tier=0, timestamp="2026-04-11T00:00:00Z")
    eng.record_mirror_result(dep.canary_id, 0.50, timestamp="2026-04-11T00:01:00Z")
    eng.close_canary(dep.canary_id, timestamp="2026-04-11T00:02:00Z")
    assert eng.rollback_rate() == 1.0


def test_cmd_30_canary_id_deterministic():
    id1 = _make_canary_id("mut-X", "2026-04-11T00:00:00Z")
    id2 = _make_canary_id("mut-X", "2026-04-11T00:00:00Z")
    assert id1 == id2
    assert id1.startswith("canary-")
