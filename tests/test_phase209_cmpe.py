# SPDX-License-Identifier: Apache-2.0
"""Phase 209 · INNOV-114 · CMPE — 30-test acceptance suite."""
import json
import pytest
from pathlib import Path

from dorkllm.constitutional_mutation_policy_engine import (
    ConstitutionalMutationPolicyEngine,
    CMPEAuthError, CMPEChainError, CMPEError,
    CMPEImmutError, CMPERuleError,
    EngineMode, PolicyEvalContext, PolicyRule, PolicyVerdict,
    GOVERNOR, INNOV_CODE, PHASE,
)

pytestmark = pytest.mark.cmpe


@pytest.fixture
def eng(tmp_path):
    return ConstitutionalMutationPolicyEngine(
        ledger_path=tmp_path / "cmpe" / "ledger.jsonl",
        hmac_secret=b"test-cmpe-secret",
        health_floor=0.80,
        blast_budget=20,
    )


def _ctx(sid="strat-1", blast=2, health=1.0, vel="CRUISE", v10=False, scope=None):
    return PolicyEvalContext(
        strategy_id=sid, blast_tier=blast,
        invariant_health_ratio=health,
        velocity_state=vel,
        v10_criteria_met=v10,
        scope=scope or ["mod_a"],
    )


# T01: healthy TIER2 CRUISE → ALLOW
def test_01_healthy_cruise_tier2_allowed(eng):
    r = eng.evaluate(_ctx())
    assert r.verdict == PolicyVerdict.ALLOW.value


# T02: HALT velocity → DENY
def test_02_halt_velocity_denied(eng):
    r = eng.evaluate(_ctx(vel="HALT"))
    assert r.verdict == PolicyVerdict.DENY.value
    assert any("HALT" in d for d in r.denial_reasons)


# T03: THROTTLE + TIER1 → DENY
def test_03_throttle_tier1_denied(eng):
    r = eng.evaluate(_ctx(vel="THROTTLE", blast=1))
    assert r.verdict == PolicyVerdict.DENY.value


# T04: THROTTLE + TIER2 → ALLOW (TIER2 is safe under throttle)
def test_04_throttle_tier2_allowed(eng):
    r = eng.evaluate(_ctx(vel="THROTTLE", blast=2))
    assert r.verdict == PolicyVerdict.ALLOW.value


# T05: CMPE-HEALTH-0 — low health → DENY
def test_05_low_health_denied(eng):
    r = eng.evaluate(_ctx(health=0.5))
    assert r.verdict == PolicyVerdict.DENY.value
    assert any("health" in d.lower() for d in r.denial_reasons)


# T06: health exactly at floor → ALLOW
def test_06_health_at_floor_allowed(eng):
    r = eng.evaluate(_ctx(health=0.80))
    assert r.verdict == PolicyVerdict.ALLOW.value


# T07: CMPE-HUMAN0-0 — TIER0 without identity → DENY
def test_07_tier0_no_human0_denied(eng):
    r = eng.evaluate(_ctx(blast=0), human0_identity=None)
    assert r.verdict == PolicyVerdict.DENY.value
    assert any("HUMAN-0" in d for d in r.denial_reasons)


# T08: TIER0 with HUMAN-0 + healthy → ALLOW
def test_08_tier0_with_human0_allowed(eng):
    r = eng.evaluate(_ctx(blast=0), human0_identity="DUSTIN L REID")
    assert r.verdict == PolicyVerdict.ALLOW.value


# T09: CMPE-V10-0 — V10 met → CONVERGENCE_GUARD mode entered
def test_09_v10_triggers_convergence_guard(eng):
    eng.evaluate(_ctx(v10=True))
    assert eng.mode == EngineMode.CONVERGENCE_GUARD.value


# T10: CONVERGENCE_GUARD blocks TIER0/TIER1
def test_10_convergence_guard_blocks_lower_tiers(eng):
    eng.evaluate(_ctx(v10=True))  # enter CONVERGENCE_GUARD
    r = eng.evaluate(_ctx(blast=0, v10=True), human0_identity="DUSTIN L REID")
    assert r.verdict == PolicyVerdict.DENY.value


# T11: CONVERGENCE_GUARD allows TIER2
def test_11_convergence_guard_allows_tier2(eng):
    eng.evaluate(_ctx(v10=True))
    r = eng.evaluate(_ctx(blast=2, v10=True))
    assert r.verdict == PolicyVerdict.ALLOW.value


# T12: CMPE-BUDGET-0 — budget exhausted → DENY
def test_12_budget_exhausted_denied(eng):
    # Each TIER2 costs 1; budget=20; exhaust it
    for i in range(20):
        eng.evaluate(_ctx(sid=f"s{i}"))
    r = eng.evaluate(_ctx(sid="s-overflow"))
    assert r.verdict == PolicyVerdict.DENY.value
    assert any("budget" in d.lower() for d in r.denial_reasons)


# T13: reset_budget restores allocation
def test_13_reset_budget_restores(eng):
    for i in range(20):
        eng.evaluate(_ctx(sid=f"s{i}"))
    eng.reset_budget("DUSTIN L REID")
    r = eng.evaluate(_ctx(sid="post-reset"))
    assert r.verdict == PolicyVerdict.ALLOW.value


# T14: reset_budget requires HUMAN-0
def test_14_reset_budget_requires_human0(eng):
    with pytest.raises(CMPEAuthError):
        eng.reset_budget("")


# T15: EMERGENCY_FREEZE blocks all
def test_15_emergency_freeze_blocks_all(eng):
    eng.set_emergency_freeze("DUSTIN L REID", freeze=True)
    r = eng.evaluate(_ctx())
    assert r.verdict == PolicyVerdict.DENY.value
    assert any("EMERGENCY_FREEZE" in d for d in r.denial_reasons)


# T16: set_emergency_freeze requires HUMAN-0
def test_16_freeze_requires_human0(eng):
    with pytest.raises(CMPEAuthError):
        eng.set_emergency_freeze("", freeze=True)


# T17: unfreeze restores normal operation
def test_17_unfreeze_restores(eng):
    eng.set_emergency_freeze("DUSTIN L REID", freeze=True)
    eng.set_emergency_freeze("DUSTIN L REID", freeze=False)
    r = eng.evaluate(_ctx())
    assert r.verdict == PolicyVerdict.ALLOW.value


# T18: amend adds new rule
def test_18_amend_adds_rule(eng):
    rule = PolicyRule("CUSTOM-R1", "custom rule", 2, 0.9, False)
    eng.amend(rule)
    assert "CUSTOM-R1" in eng.rules


# T19: CMPE-AMEND-0 — invalid blast_tier_max rejected
def test_19_amend_invalid_blast_tier(eng):
    with pytest.raises(CMPERuleError):
        eng.amend(PolicyRule("BAD-R", "bad", 5, 0.5, False))


# T20: CMPE-IMMUT-0 — HUMAN-0-locked rule requires HUMAN-0 to replace
def test_20_locked_rule_requires_human0(eng):
    locked = PolicyRule("LOCKED-R", "locked", 0, 0.95, True)
    eng.amend(locked, human0_identity="DUSTIN L REID")
    with pytest.raises((CMPEImmutError, CMPEAuthError)):
        eng.amend(PolicyRule("LOCKED-R", "override attempt", 2, 0.5, False))


# T21: CMPE-CHAIN-0 — ledger verifies clean
def test_21_ledger_verifies_clean(eng):
    eng.evaluate(_ctx())
    assert eng.verify_ledger() is True


# T22: CMPE-CHAIN-0 — tampered ledger detected
def test_22_tampered_ledger_detected(eng):
    eng.evaluate(_ctx())
    lines = eng._ledger_path.read_text().splitlines()
    r = json.loads(lines[0])
    r["blast_tier"] = 99   # mutate a field — changes HMAC payload
    lines[0] = json.dumps(r)
    eng._ledger_path.write_text("\n".join(lines) + "\n")
    assert eng.verify_ledger() is False


# T23: CMPE-AUDIT-0 — every evaluate appends record
def test_23_evaluate_appended_to_ledger(eng):
    eng.evaluate(_ctx("s1"))
    eng.evaluate(_ctx("s2"))
    records = [json.loads(l) for l in eng._ledger_path.read_text().splitlines() if l.strip()]
    assert len([r for r in records if r.get("action") == "EVALUATE"]) >= 2


# T24: CMPE-DETERM-0 — same input same record_id
def test_24_deterministic_record_id(tmp_path):
    def make(sub):
        return ConstitutionalMutationPolicyEngine(
            ledger_path=tmp_path / sub / "l.jsonl",
            hmac_secret=b"det", health_floor=0.8, blast_budget=100)
    e1, e2 = make("e1"), make("e2")
    e1.evaluate(_ctx("det-strat"))
    e2.evaluate(_ctx("det-strat"))
    r1 = json.loads(e1._ledger_path.read_text().splitlines()[0])
    r2 = json.loads(e2._ledger_path.read_text().splitlines()[0])
    assert r1["record_id"] == r2["record_id"]


# T25: governor field correct in all records
def test_25_governor_correct(eng):
    eng.evaluate(_ctx())
    records = [json.loads(l) for l in eng._ledger_path.read_text().splitlines() if l.strip()]
    assert all(r["governor"] == GOVERNOR for r in records)


# T26: innov_code correct
def test_26_innov_code_correct(eng):
    eng.evaluate(_ctx())
    records = [json.loads(l) for l in eng._ledger_path.read_text().splitlines() if l.strip()]
    assert all(r["innov_code"] == INNOV_CODE for r in records)


# T27: phase correct
def test_27_phase_correct(eng):
    eng.evaluate(_ctx())
    records = [json.loads(l) for l in eng._ledger_path.read_text().splitlines() if l.strip()]
    assert all(r["phase"] == PHASE for r in records)


# T28: blast_budget_remaining decrements correctly
def test_28_budget_decrements(eng):
    initial = eng.blast_budget_remaining
    eng.evaluate(_ctx(blast=2))  # cost = 1
    assert eng.blast_budget_remaining == initial - 1


# T29: ACCELERATE velocity does not block TIER2
def test_29_accelerate_allows_tier2(eng):
    r = eng.evaluate(_ctx(vel="ACCELERATE", blast=2))
    assert r.verdict == PolicyVerdict.ALLOW.value


# T30: full policy lifecycle — evaluate → freeze → unfreeze → reset → evaluate
def test_30_full_lifecycle(eng):
    r1 = eng.evaluate(_ctx("lifecycle"))
    assert r1.verdict == PolicyVerdict.ALLOW.value
    eng.set_emergency_freeze("DUSTIN L REID", freeze=True)
    r2 = eng.evaluate(_ctx("lifecycle-frozen"))
    assert r2.verdict == PolicyVerdict.DENY.value
    eng.set_emergency_freeze("DUSTIN L REID", freeze=False)
    eng.reset_budget("DUSTIN L REID")
    r3 = eng.evaluate(_ctx("lifecycle-restored"))
    assert r3.verdict == PolicyVerdict.ALLOW.value
    assert eng.verify_ledger() is True
