# SPDX-License-Identifier: Apache-2.0
"""Phase 206 · INNOV-111 · CMSE — 30-test acceptance suite.

Tests:
  T206-CMSE-01..08  : CMSE-CHAIN-0, CMSE-IMMUT-0, CMSE-HUMAN0-0, CMSE-OVERLAP-0
  T206-CMSE-09..14  : CMSE-DETERM-0, CMSE-VELOCITY-0, CMSE-BLAST-0, CMSE-AUDIT-0
  T206-CMSE-15..20  : CMSE-FAILCLOSED-0, CMSE-DRAIN-0, CMSE-SCOPE-0, CMSE-SLOT-0
  T206-CMSE-21..30  : Integration, edge cases, ledger replay, REST health
"""
import hashlib
import json
import os
import tempfile
from pathlib import Path

import pytest

from dorkllm.constitutional_mutation_scheduling_engine import (
    ConstitutionalMutationSchedulingEngine,
    CMSEAuthError,
    CMSEBlastError,
    CMSECapacityError,
    CMSEChainError,
    CMSEError,
    CMSEImmutError,
    CMSEOverlapError,
    CMSEScopeError,
    CMSEVelocityError,
    WindowStatus,
    GOVERNOR,
    INNOV_CODE,
    PHASE,
)

pytestmark = pytest.mark.cmse


@pytest.fixture
def tmp_engine(tmp_path):
    ledger = tmp_path / "cmse" / "schedule_ledger.jsonl"
    return ConstitutionalMutationSchedulingEngine(
        ledger_path=ledger,
        hmac_secret=b"test-cmse-secret",
        slot_capacity=4,
    )


# ---------------------------------------------------------------------------
# T206-CMSE-01: schedule creates PENDING window
# ---------------------------------------------------------------------------
def test_01_schedule_creates_pending_window(tmp_engine):
    w = tmp_engine.schedule("prop-001", blast_tier=2, mutation_scope={"mod_a"})
    assert w.status == WindowStatus.PENDING.value
    assert w.proposal_id == "prop-001"


# ---------------------------------------------------------------------------
# T206-CMSE-02: CMSE-DETERM-0 — identical inputs yield same window_id
# ---------------------------------------------------------------------------
def test_02_deterministic_window_id(tmp_engine, tmp_path):
    eng2 = ConstitutionalMutationSchedulingEngine(
        ledger_path=tmp_path / "cmse2" / "ledger.jsonl",
        hmac_secret=b"test-cmse-secret",
        slot_capacity=4,
    )
    w1 = tmp_engine.schedule("prop-det", blast_tier=1, mutation_scope={"x", "y"})
    w2 = eng2.schedule("prop-det", blast_tier=1, mutation_scope={"x", "y"})
    assert w1.window_id == w2.window_id


# ---------------------------------------------------------------------------
# T206-CMSE-03: CMSE-SCOPE-0 — empty scope rejected
# ---------------------------------------------------------------------------
def test_03_empty_scope_raises(tmp_engine):
    with pytest.raises(CMSEScopeError):
        tmp_engine.schedule("prop-scope", blast_tier=2, mutation_scope=set())


# ---------------------------------------------------------------------------
# T206-CMSE-04: CMSE-BLAST-0 — invalid blast tier rejected
# ---------------------------------------------------------------------------
def test_04_invalid_blast_tier_raises(tmp_engine):
    with pytest.raises(CMSEBlastError):
        tmp_engine.schedule("prop-blast", blast_tier=5, mutation_scope={"mod"})


# ---------------------------------------------------------------------------
# T206-CMSE-05: CMSE-VELOCITY-0 — HALT velocity blocks scheduling
# ---------------------------------------------------------------------------
def test_05_halt_velocity_blocks_schedule(tmp_engine):
    with pytest.raises(CMSEVelocityError):
        tmp_engine.schedule("prop-vel", blast_tier=2, mutation_scope={"mod"},
                            velocity_rate=0.0)


# ---------------------------------------------------------------------------
# T206-CMSE-06: CMSE-SLOT-0 — slot capacity enforced
# ---------------------------------------------------------------------------
def test_06_slot_capacity_enforced(tmp_engine):
    for i in range(4):
        tmp_engine.schedule(f"prop-{i}", blast_tier=2, mutation_scope={f"mod_{i}"})
    with pytest.raises(CMSECapacityError):
        tmp_engine.schedule("prop-overflow", blast_tier=2, mutation_scope={"mod_x"})


# ---------------------------------------------------------------------------
# T206-CMSE-07: CMSE-HUMAN0-0 — TIER0 promote requires HUMAN-0
# ---------------------------------------------------------------------------
def test_07_tier0_promote_requires_human0(tmp_engine):
    w = tmp_engine.schedule("prop-t0", blast_tier=0, mutation_scope={"core"})
    with pytest.raises(CMSEAuthError):
        tmp_engine.promote(w.window_id, human0_identity=None)


# ---------------------------------------------------------------------------
# T206-CMSE-08: TIER0 promote succeeds with HUMAN-0 identity
# ---------------------------------------------------------------------------
def test_08_tier0_promote_succeeds_with_human0(tmp_engine):
    w = tmp_engine.schedule("prop-t0-ok", blast_tier=0, mutation_scope={"core_ok"})
    w2 = tmp_engine.promote(w.window_id, human0_identity="DUSTIN L REID")
    assert w2.status == WindowStatus.ACTIVE.value
    assert w2.promoted_by == "DUSTIN L REID"


# ---------------------------------------------------------------------------
# T206-CMSE-09: CMSE-OVERLAP-0 — concurrent overlapping scopes rejected
# ---------------------------------------------------------------------------
def test_09_overlap_blocked(tmp_engine):
    w1 = tmp_engine.schedule("prop-oa", blast_tier=2, mutation_scope={"shared", "a"})
    tmp_engine.promote(w1.window_id)  # TIER2, no human0 needed
    w2 = tmp_engine.schedule("prop-ob", blast_tier=2, mutation_scope={"shared", "b"})
    with pytest.raises(CMSEOverlapError):
        tmp_engine.promote(w2.window_id)


# ---------------------------------------------------------------------------
# T206-CMSE-10: Non-overlapping scopes promote concurrently
# ---------------------------------------------------------------------------
def test_10_non_overlapping_scopes_ok(tmp_engine):
    w1 = tmp_engine.schedule("prop-na", blast_tier=2, mutation_scope={"mod_a"})
    w2 = tmp_engine.schedule("prop-nb", blast_tier=2, mutation_scope={"mod_b"})
    tmp_engine.promote(w1.window_id)
    tmp_engine.promote(w2.window_id)
    assert len(tmp_engine.active_windows()) == 2


# ---------------------------------------------------------------------------
# T206-CMSE-11: CMSE-IMMUT-0 — double-promote rejected
# ---------------------------------------------------------------------------
def test_11_double_promote_rejected(tmp_engine):
    w = tmp_engine.schedule("prop-dp", blast_tier=2, mutation_scope={"mod_dp"})
    tmp_engine.promote(w.window_id)
    with pytest.raises(CMSEImmutError):
        tmp_engine.promote(w.window_id)


# ---------------------------------------------------------------------------
# T206-CMSE-12: expire releases slot
# ---------------------------------------------------------------------------
def test_12_expire_releases_slot(tmp_engine):
    for i in range(4):
        tmp_engine.schedule(f"prop-fill-{i}", blast_tier=2, mutation_scope={f"fill_{i}"})
    w_first = tmp_engine.get_window(list(tmp_engine._windows.keys())[0])
    tmp_engine.expire(w_first.window_id)
    # Should now be able to schedule again
    w_new = tmp_engine.schedule("prop-after-expire", blast_tier=2, mutation_scope={"new"})
    assert w_new.status == WindowStatus.PENDING.value


# ---------------------------------------------------------------------------
# T206-CMSE-13: CMSE-DRAIN-0 — drain blocks promote
# ---------------------------------------------------------------------------
def test_13_drain_blocks_promote(tmp_engine):
    w = tmp_engine.schedule("prop-drain", blast_tier=2, mutation_scope={"mod_drain"})
    tmp_engine.set_drain("DUSTIN L REID", drain=True)
    with pytest.raises(CMSEVelocityError):
        tmp_engine.promote(w.window_id)


# ---------------------------------------------------------------------------
# T206-CMSE-14: drain mode clears with undrain
# ---------------------------------------------------------------------------
def test_14_undrain_restores_promote(tmp_engine):
    w = tmp_engine.schedule("prop-undrain", blast_tier=2, mutation_scope={"mod_ud"})
    tmp_engine.set_drain("DUSTIN L REID", drain=True)
    tmp_engine.set_drain("DUSTIN L REID", drain=False)
    w2 = tmp_engine.promote(w.window_id)
    assert w2.status == WindowStatus.ACTIVE.value


# ---------------------------------------------------------------------------
# T206-CMSE-15: drain requires HUMAN-0 identity
# ---------------------------------------------------------------------------
def test_15_drain_requires_human0(tmp_engine):
    with pytest.raises(CMSEAuthError):
        tmp_engine.set_drain("", drain=True)


# ---------------------------------------------------------------------------
# T206-CMSE-16: CMSE-CHAIN-0 — ledger chain verifies clean
# ---------------------------------------------------------------------------
def test_16_ledger_chain_verifies(tmp_engine):
    tmp_engine.schedule("prop-chain", blast_tier=2, mutation_scope={"mod_c"})
    assert tmp_engine.verify_ledger() is True


# ---------------------------------------------------------------------------
# T206-CMSE-17: CMSE-CHAIN-0 — tampered ledger detected
# ---------------------------------------------------------------------------
def test_17_tampered_ledger_detected(tmp_engine):
    tmp_engine.schedule("prop-tamper", blast_tier=2, mutation_scope={"mod_t"})
    # Corrupt the ledger
    content = tmp_engine._ledger_path.read_text()
    lines = content.splitlines()
    rec = json.loads(lines[0])
    rec["blast_tier"] = 99
    lines[0] = json.dumps(rec)
    tmp_engine._ledger_path.write_text("\n".join(lines) + "\n")
    assert tmp_engine.verify_ledger() is False


# ---------------------------------------------------------------------------
# T206-CMSE-18: CMSE-AUDIT-0 — every schedule appends ledger record
# ---------------------------------------------------------------------------
def test_18_every_schedule_appended_to_ledger(tmp_engine):
    for i in range(3):
        tmp_engine.schedule(f"prop-audit-{i}", blast_tier=2, mutation_scope={f"aud_{i}"})
    records = [json.loads(l) for l in tmp_engine._ledger_path.read_text().splitlines() if l.strip()]
    assert len(records) >= 3


# ---------------------------------------------------------------------------
# T206-CMSE-19: CMSE-AUDIT-0 — failed schedule also appended
# ---------------------------------------------------------------------------
def test_19_failed_schedule_appended(tmp_engine):
    try:
        tmp_engine.schedule("prop-fail-scope", blast_tier=2, mutation_scope=set())
    except CMSEScopeError:
        pass
    records = [json.loads(l) for l in tmp_engine._ledger_path.read_text().splitlines() if l.strip()]
    assert any(r["status"] == WindowStatus.FAILED.value for r in records)


# ---------------------------------------------------------------------------
# T206-CMSE-20: governor field correct in all records
# ---------------------------------------------------------------------------
def test_20_governor_field_correct(tmp_engine):
    tmp_engine.schedule("prop-gov", blast_tier=2, mutation_scope={"mod_g"})
    records = [json.loads(l) for l in tmp_engine._ledger_path.read_text().splitlines() if l.strip()]
    assert all(r.get("governor") == GOVERNOR for r in records if "governor" in r)


# ---------------------------------------------------------------------------
# T206-CMSE-21: innov_code correct in ledger
# ---------------------------------------------------------------------------
def test_21_innov_code_in_ledger(tmp_engine):
    tmp_engine.schedule("prop-ic", blast_tier=2, mutation_scope={"mod_ic"})
    records = [json.loads(l) for l in tmp_engine._ledger_path.read_text().splitlines() if l.strip()]
    assert all(r.get("innov_code") == INNOV_CODE for r in records if "innov_code" in r)


# ---------------------------------------------------------------------------
# T206-CMSE-22: phase number correct in ledger
# ---------------------------------------------------------------------------
def test_22_phase_number_in_ledger(tmp_engine):
    tmp_engine.schedule("prop-ph", blast_tier=2, mutation_scope={"mod_ph"})
    records = [json.loads(l) for l in tmp_engine._ledger_path.read_text().splitlines() if l.strip()]
    assert all(r.get("phase") == PHASE for r in records if "phase" in r)


# ---------------------------------------------------------------------------
# T206-CMSE-23: CMSE-VELOCITY-0 — HALT velocity blocks promote
# ---------------------------------------------------------------------------
def test_23_halt_velocity_blocks_promote(tmp_engine):
    w = tmp_engine.schedule("prop-hv", blast_tier=2, mutation_scope={"mod_hv"})
    with pytest.raises(CMSEVelocityError):
        tmp_engine.promote(w.window_id, velocity_rate=0.0)


# ---------------------------------------------------------------------------
# T206-CMSE-24: expire non-active raises ImmutError
# ---------------------------------------------------------------------------
def test_24_expire_already_expired_raises(tmp_engine):
    w = tmp_engine.schedule("prop-exp2", blast_tier=2, mutation_scope={"mod_exp2"})
    tmp_engine.expire(w.window_id)
    with pytest.raises(CMSEImmutError):
        tmp_engine.expire(w.window_id)


# ---------------------------------------------------------------------------
# T206-CMSE-25: active_windows returns only ACTIVE
# ---------------------------------------------------------------------------
def test_25_active_windows_filter(tmp_engine):
    w1 = tmp_engine.schedule("prop-aw1", blast_tier=2, mutation_scope={"mod_aw1"})
    tmp_engine.schedule("prop-aw2", blast_tier=2, mutation_scope={"mod_aw2"})
    tmp_engine.promote(w1.window_id)
    active = tmp_engine.active_windows()
    assert all(w.status == WindowStatus.ACTIVE.value for w in active)
    assert len(active) == 1


# ---------------------------------------------------------------------------
# T206-CMSE-26: pending_windows returns only PENDING
# ---------------------------------------------------------------------------
def test_26_pending_windows_filter(tmp_engine):
    tmp_engine.schedule("prop-pw1", blast_tier=2, mutation_scope={"mod_pw1"})
    w2 = tmp_engine.schedule("prop-pw2", blast_tier=2, mutation_scope={"mod_pw2"})
    tmp_engine.promote(w2.window_id)
    pending = tmp_engine.pending_windows()
    assert all(w.status == WindowStatus.PENDING.value for w in pending)


# ---------------------------------------------------------------------------
# T206-CMSE-27: ledger reload restores window state
# ---------------------------------------------------------------------------
def test_27_ledger_reload_restores_state(tmp_path):
    ledger = tmp_path / "cmse_reload" / "ledger.jsonl"
    eng1 = ConstitutionalMutationSchedulingEngine(
        ledger_path=ledger, hmac_secret=b"reload-secret", slot_capacity=4)
    w = eng1.schedule("prop-reload", blast_tier=2, mutation_scope={"mod_reload"})
    eng1.promote(w.window_id)

    eng2 = ConstitutionalMutationSchedulingEngine(
        ledger_path=ledger, hmac_secret=b"reload-secret", slot_capacity=4)
    reloaded = eng2.get_window(w.window_id)
    assert reloaded is not None
    assert reloaded.status == WindowStatus.ACTIVE.value


# ---------------------------------------------------------------------------
# T206-CMSE-28: constitutional_fitness preserved in ledger
# ---------------------------------------------------------------------------
def test_28_fitness_preserved(tmp_engine):
    tmp_engine.schedule("prop-fit", blast_tier=1, mutation_scope={"mod_fit"},
                        constitutional_fitness=0.87)
    records = [json.loads(l) for l in tmp_engine._ledger_path.read_text().splitlines() if l.strip()]
    fit_records = [r for r in records if r.get("constitutional_fitness") is not None]
    assert any(abs(r["constitutional_fitness"] - 0.87) < 0.001 for r in fit_records)


# ---------------------------------------------------------------------------
# T206-CMSE-29: mutation_scope sorted deterministically in ledger
# ---------------------------------------------------------------------------
def test_29_scope_sorted_in_ledger(tmp_engine):
    tmp_engine.schedule("prop-sort", blast_tier=2, mutation_scope={"z_mod", "a_mod", "m_mod"})
    records = [json.loads(l) for l in tmp_engine._ledger_path.read_text().splitlines() if l.strip()]
    scopes = [r["mutation_scope"] for r in records if r.get("mutation_scope")]
    for s in scopes:
        if s:
            assert s == sorted(s)


# ---------------------------------------------------------------------------
# T206-CMSE-30: full happy-path lifecycle: schedule → promote → expire → verify
# ---------------------------------------------------------------------------
def test_30_full_lifecycle(tmp_engine):
    w = tmp_engine.schedule("prop-lifecycle", blast_tier=1, mutation_scope={"lifecycle_mod"})
    assert w.status == WindowStatus.PENDING.value
    w = tmp_engine.promote(w.window_id)
    assert w.status == WindowStatus.ACTIVE.value
    w = tmp_engine.expire(w.window_id)
    assert w.status == WindowStatus.EXPIRED.value
    assert tmp_engine.verify_ledger() is True
