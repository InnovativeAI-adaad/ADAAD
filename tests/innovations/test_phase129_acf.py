# SPDX-License-Identifier: Apache-2.0
"""Phase 129 — INNOV-39 Agent Coalition Formation (ACF) test suite.

Naming convention: T129-ACF-NN
All 30 tests must pass (30/30) for phase acceptance.

Environment: ACSA_HMAC_SECRET (reused as ACF_HMAC_SECRET) injected via
conftest autouse fixture.
"""
from __future__ import annotations

import json
import os
import hashlib
from pathlib import Path

import pytest

from runtime.innovations30.agent_coalition import (
    ACF_MAX_MEMBERS,
    ACF_MIN_MEMBERS,
    AlreadyResolvedError,
    ChainError,
    Coalition,
    CoalitionEngine,
    CoalitionOutcome,
    CoalitionStatus,
    EpochBoundaryError,
    MemberVerdict,
    ShareArithmeticError,
    StakeError,
    CoalitionSizeError,
    UnresolvedCoalitionError,
    requires_coalition,
)

# ────────────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────────────

SECRET = bytes.fromhex(os.environ.get("ACSA_HMAC_SECRET", "b" * 64))

_MEMBERS_3 = [
    {"agent_id": "ARCH-1", "role": "Architect", "stake": 100},
    {"agent_id": "DREAM-1", "role": "Dream",     "stake": 80},
    {"agent_id": "BEAST-1", "role": "Beast",     "stake": 60},
]

_MEMBERS_2 = [
    {"agent_id": "ARCH-2", "role": "Architect", "stake": 50},
    {"agent_id": "DREAM-2", "role": "Dream",     "stake": 50},
]


def _engine(tmp_path: Path) -> CoalitionEngine:
    return CoalitionEngine(
        hmac_secret=SECRET,
        ledger_path=tmp_path / "acf_ledger.jsonl",
    )


def _form(eng: CoalitionEngine, cid: str = "COAL-001", members=None) -> Coalition:
    return eng.form_coalition(
        coalition_id=cid,
        mutation_id="MUT-XYZ",
        complexity_class="HIGH",
        members=members or _MEMBERS_3,
    )


# ────────────────────────────────────────────────────────────────────────────
# T129-ACF-01: Module imports cleanly
# ────────────────────────────────────────────────────────────────────────────
def test_T129_ACF_01_module_import():
    from runtime.innovations30 import agent_coalition  # noqa: F401
    assert True


# ────────────────────────────────────────────────────────────────────────────
# T129-ACF-02: requires_coalition returns True for HIGH
# ────────────────────────────────────────────────────────────────────────────
def test_T129_ACF_02_requires_coalition_high():
    assert requires_coalition("HIGH") is True


# ────────────────────────────────────────────────────────────────────────────
# T129-ACF-03: requires_coalition returns False for MEDIUM
# ────────────────────────────────────────────────────────────────────────────
def test_T129_ACF_03_requires_coalition_medium():
    assert requires_coalition("MEDIUM") is False


# ────────────────────────────────────────────────────────────────────────────
# T129-ACF-04: Engine initialises with zero active coalitions
# ────────────────────────────────────────────────────────────────────────────
def test_T129_ACF_04_engine_init(tmp_path):
    eng = _engine(tmp_path)
    assert eng.active_count() == 0


# ────────────────────────────────────────────────────────────────────────────
# T129-ACF-05: form_coalition seals and records coalition
# ────────────────────────────────────────────────────────────────────────────
def test_T129_ACF_05_form_coalition(tmp_path):
    eng = _engine(tmp_path)
    coal = _form(eng)
    assert coal.status == CoalitionStatus.SEALED
    assert eng.active_count() == 1


# ────────────────────────────────────────────────────────────────────────────
# T129-ACF-06: member_count reflects added members
# ────────────────────────────────────────────────────────────────────────────
def test_T129_ACF_06_member_count(tmp_path):
    eng = _engine(tmp_path)
    coal = _form(eng, members=_MEMBERS_3)
    assert coal.member_count == 3


# ────────────────────────────────────────────────────────────────────────────
# T129-ACF-07: total_stake sums member stakes
# ────────────────────────────────────────────────────────────────────────────
def test_T129_ACF_07_total_stake(tmp_path):
    eng = _engine(tmp_path)
    coal = _form(eng, members=_MEMBERS_3)
    assert coal.total_stake == 240   # 100+80+60


# ────────────────────────────────────────────────────────────────────────────
# T129-ACF-08: ACF-STAKE-0 — zero stake raises StakeError
# ────────────────────────────────────────────────────────────────────────────
def test_T129_ACF_08_zero_stake_raises(tmp_path):
    bad_members = [
        {"agent_id": "ARCH-3", "role": "Architect", "stake": 0},
        {"agent_id": "DREAM-3", "role": "Dream", "stake": 50},
    ]
    eng = _engine(tmp_path)
    with pytest.raises(StakeError):
        eng.form_coalition("COAL-BAD", "MUT-1", "HIGH", bad_members)


# ────────────────────────────────────────────────────────────────────────────
# T129-ACF-09: ACF-FORM-0 — one member raises CoalitionSizeError
# ────────────────────────────────────────────────────────────────────────────
def test_T129_ACF_09_under_min_raises(tmp_path):
    eng = _engine(tmp_path)
    with pytest.raises(CoalitionSizeError):
        eng.form_coalition(
            "COAL-SMALL", "MUT-1", "HIGH",
            [{"agent_id": "A1", "role": "Architect", "stake": 10}]
        )


# ────────────────────────────────────────────────────────────────────────────
# T129-ACF-10: ACF-FORM-0 — eight members raises CoalitionSizeError
# ────────────────────────────────────────────────────────────────────────────
def test_T129_ACF_10_over_max_raises(tmp_path):
    eng = _engine(tmp_path)
    members = [{"agent_id": f"A{i}", "role": "Architect", "stake": 10} for i in range(8)]
    with pytest.raises(CoalitionSizeError):
        eng.form_coalition("COAL-BIG", "MUT-1", "HIGH", members)


# ────────────────────────────────────────────────────────────────────────────
# T129-ACF-11: Majority APPROVE → outcome APPROVED
# ────────────────────────────────────────────────────────────────────────────
def test_T129_ACF_11_majority_approve(tmp_path):
    eng = _engine(tmp_path)
    _form(eng, "COAL-A", _MEMBERS_3)
    verdicts = {"ARCH-1": "APPROVE", "DREAM-1": "APPROVE", "BEAST-1": "REJECT"}
    outcome, _ = eng.resolve_coalition("COAL-A", verdicts)
    assert outcome == CoalitionOutcome.APPROVED


# ────────────────────────────────────────────────────────────────────────────
# T129-ACF-12: Majority REJECT → outcome REJECTED
# ────────────────────────────────────────────────────────────────────────────
def test_T129_ACF_12_majority_reject(tmp_path):
    eng = _engine(tmp_path)
    _form(eng, "COAL-B", _MEMBERS_3)
    verdicts = {"ARCH-1": "REJECT", "DREAM-1": "REJECT", "BEAST-1": "APPROVE"}
    outcome, _ = eng.resolve_coalition("COAL-B", verdicts)
    assert outcome == CoalitionOutcome.REJECTED


# ────────────────────────────────────────────────────────────────────────────
# T129-ACF-13: Tie → outcome ESCALATED
# ────────────────────────────────────────────────────────────────────────────
def test_T129_ACF_13_tie_escalated(tmp_path):
    eng = _engine(tmp_path)
    _form(eng, "COAL-C", _MEMBERS_2)
    verdicts = {"ARCH-2": "APPROVE", "DREAM-2": "REJECT"}
    outcome, _ = eng.resolve_coalition("COAL-C", verdicts)
    assert outcome == CoalitionOutcome.ESCALATED


# ────────────────────────────────────────────────────────────────────────────
# T129-ACF-14: ACF-SHARE-0 — total distributed == total pool
# ────────────────────────────────────────────────────────────────────────────
def test_T129_ACF_14_stake_balance(tmp_path):
    eng = _engine(tmp_path)
    _form(eng, "COAL-D", _MEMBERS_3)
    verdicts = {"ARCH-1": "APPROVE", "DREAM-1": "APPROVE", "BEAST-1": "REJECT"}
    _, dist = eng.resolve_coalition("COAL-D", verdicts)
    dist.validate()  # raises ShareArithmeticError if unbalanced
    total_out = sum(dist.distributions.values()) + dist.remainder
    assert total_out == dist.total_pool


# ────────────────────────────────────────────────────────────────────────────
# T129-ACF-15: ESCALATED outcome — all stakes returned in full
# ────────────────────────────────────────────────────────────────────────────
def test_T129_ACF_15_escalated_full_return(tmp_path):
    eng = _engine(tmp_path)
    _form(eng, "COAL-E", _MEMBERS_2)
    verdicts = {"ARCH-2": "APPROVE", "DREAM-2": "REJECT"}
    _, dist = eng.resolve_coalition("COAL-E", verdicts)
    assert dist.remainder == 0
    for m in _MEMBERS_2:
        assert dist.distributions[m["agent_id"]] == m["stake"]


# ────────────────────────────────────────────────────────────────────────────
# T129-ACF-16: Winners receive their own stake back
# ────────────────────────────────────────────────────────────────────────────
def test_T129_ACF_16_winners_recover_stake(tmp_path):
    eng = _engine(tmp_path)
    _form(eng, "COAL-F", _MEMBERS_3)
    verdicts = {"ARCH-1": "APPROVE", "DREAM-1": "APPROVE", "BEAST-1": "REJECT"}
    _, dist = eng.resolve_coalition("COAL-F", verdicts)
    # Both winners must receive at least their original stake
    assert dist.distributions["ARCH-1"]  >= 100
    assert dist.distributions["DREAM-1"] >= 80


# ────────────────────────────────────────────────────────────────────────────
# T129-ACF-17: ACF-RESOLVE-0 — resolving twice raises AlreadyResolvedError
# ────────────────────────────────────────────────────────────────────────────
def test_T129_ACF_17_double_resolve_raises(tmp_path):
    eng = _engine(tmp_path)
    _form(eng, "COAL-G", _MEMBERS_2)
    verdicts = {"ARCH-2": "APPROVE", "DREAM-2": "APPROVE"}
    eng.resolve_coalition("COAL-G", verdicts)
    with pytest.raises(AlreadyResolvedError):
        eng.resolve_coalition("COAL-G", verdicts)


# ────────────────────────────────────────────────────────────────────────────
# T129-ACF-18: dissolve_coalition moves coalition out of active set
# ────────────────────────────────────────────────────────────────────────────
def test_T129_ACF_18_dissolve_removes_active(tmp_path):
    eng = _engine(tmp_path)
    _form(eng, "COAL-H", _MEMBERS_2)
    eng.resolve_coalition("COAL-H", {"ARCH-2": "APPROVE", "DREAM-2": "APPROVE"})
    assert eng.active_count() == 1
    eng.dissolve_coalition("COAL-H")
    assert eng.active_count() == 0


# ────────────────────────────────────────────────────────────────────────────
# T129-ACF-19: ACF-DISSOLVE-0 — dissolve unresolved coalition raises
# ────────────────────────────────────────────────────────────────────────────
def test_T129_ACF_19_dissolve_unresolved_raises(tmp_path):
    eng = _engine(tmp_path)
    _form(eng, "COAL-I", _MEMBERS_2)
    with pytest.raises(EpochBoundaryError):
        eng.dissolve_coalition("COAL-I")


# ────────────────────────────────────────────────────────────────────────────
# T129-ACF-20: ACF-0 — assert_epoch_clear raises for sealed coalition
# ────────────────────────────────────────────────────────────────────────────
def test_T129_ACF_20_epoch_clear_blocks_sealed(tmp_path):
    eng = _engine(tmp_path)
    _form(eng, "COAL-J", _MEMBERS_2)
    with pytest.raises(UnresolvedCoalitionError):
        eng.assert_epoch_clear()


# ────────────────────────────────────────────────────────────────────────────
# T129-ACF-21: ACF-DISSOLVE-0 — assert_epoch_clear raises for resolved coalition
# ────────────────────────────────────────────────────────────────────────────
def test_T129_ACF_21_epoch_clear_blocks_resolved(tmp_path):
    eng = _engine(tmp_path)
    _form(eng, "COAL-K", _MEMBERS_2)
    eng.resolve_coalition("COAL-K", {"ARCH-2": "APPROVE", "DREAM-2": "APPROVE"})
    with pytest.raises(EpochBoundaryError):
        eng.assert_epoch_clear()


# ────────────────────────────────────────────────────────────────────────────
# T129-ACF-22: assert_epoch_clear passes after full lifecycle
# ────────────────────────────────────────────────────────────────────────────
def test_T129_ACF_22_epoch_clear_passes_after_dissolve(tmp_path):
    eng = _engine(tmp_path)
    _form(eng, "COAL-L", _MEMBERS_2)
    eng.resolve_coalition("COAL-L", {"ARCH-2": "APPROVE", "DREAM-2": "APPROVE"})
    eng.dissolve_coalition("COAL-L")
    eng.assert_epoch_clear()   # must not raise


# ────────────────────────────────────────────────────────────────────────────
# T129-ACF-23: Ledger written to disk after formation
# ────────────────────────────────────────────────────────────────────────────
def test_T129_ACF_23_ledger_written(tmp_path):
    eng = _engine(tmp_path)
    _form(eng, "COAL-M", _MEMBERS_2)
    assert (tmp_path / "acf_ledger.jsonl").exists()


# ────────────────────────────────────────────────────────────────────────────
# T129-ACF-24: Ledger lines are valid JSON
# ────────────────────────────────────────────────────────────────────────────
def test_T129_ACF_24_ledger_valid_json(tmp_path):
    eng = _engine(tmp_path)
    _form(eng, "COAL-N", _MEMBERS_2)
    eng.resolve_coalition("COAL-N", {"ARCH-2": "APPROVE", "DREAM-2": "APPROVE"})
    eng.dissolve_coalition("COAL-N")
    for line in (tmp_path / "acf_ledger.jsonl").read_text().splitlines():
        json.loads(line)  # must not raise


# ────────────────────────────────────────────────────────────────────────────
# T129-ACF-25: First ledger record carries prev_digest="genesis"
# ────────────────────────────────────────────────────────────────────────────
def test_T129_ACF_25_first_record_genesis(tmp_path):
    eng = _engine(tmp_path)
    _form(eng, "COAL-O", _MEMBERS_2)
    line = (tmp_path / "acf_ledger.jsonl").read_text().splitlines()[0]
    rec = json.loads(line)
    assert rec["prev_digest"] == "genesis"


# ────────────────────────────────────────────────────────────────────────────
# T129-ACF-26: ACF-CHAIN-0 — chain is intact after full lifecycle
# ────────────────────────────────────────────────────────────────────────────
def test_T129_ACF_26_chain_intact(tmp_path):
    eng = _engine(tmp_path)
    for i in range(3):
        cid = f"COAL-{i:03d}"
        _form(eng, cid, _MEMBERS_2)
        eng.resolve_coalition(cid, {"ARCH-2": "APPROVE", "DREAM-2": "APPROVE"})
        eng.dissolve_coalition(cid)
    assert eng.verify_chain() is True


# ────────────────────────────────────────────────────────────────────────────
# T129-ACF-27: ACF-CHAIN-0 — tampered prev_digest raises ChainError
# ────────────────────────────────────────────────────────────────────────────
def test_T129_ACF_27_chain_tamper_detected(tmp_path):
    eng = _engine(tmp_path)
    _form(eng, "COAL-P", _MEMBERS_2)
    eng.resolve_coalition("COAL-P", {"ARCH-2": "APPROVE", "DREAM-2": "APPROVE"})
    ledger = tmp_path / "acf_ledger.jsonl"
    lines = ledger.read_text().splitlines()
    rec = json.loads(lines[1])
    rec["prev_digest"] = "tampered"
    lines[1] = json.dumps(rec)
    ledger.write_text("\n".join(lines) + "\n")
    eng2 = CoalitionEngine(SECRET, ledger)
    with pytest.raises(ChainError):
        eng2.verify_chain()


# ────────────────────────────────────────────────────────────────────────────
# T129-ACF-28: ACF-DETERM-0 — coalition_digest is deterministic
# ────────────────────────────────────────────────────────────────────────────
def test_T129_ACF_28_digest_deterministic(tmp_path):
    eng = _engine(tmp_path)
    coal = _form(eng, "COAL-Q", _MEMBERS_3)
    # read digest from ledger line
    line = (tmp_path / "acf_ledger.jsonl").read_text().splitlines()[0]
    rec = json.loads(line)
    d1 = rec["coalition_digest"]
    # Re-form identical coalition on new engine → same digest
    eng2 = CoalitionEngine(SECRET, tmp_path / "acf_ledger2.jsonl")
    _form(eng2, "COAL-Q", _MEMBERS_3)
    line2 = (tmp_path / "acf_ledger2.jsonl").read_text().splitlines()[0]
    rec2 = json.loads(line2)
    assert rec2["coalition_digest"] == d1


# ────────────────────────────────────────────────────────────────────────────
# T129-ACF-29: Engine reloads record_counter from ledger on restart
# ────────────────────────────────────────────────────────────────────────────
def test_T129_ACF_29_reload_record_counter(tmp_path):
    eng = _engine(tmp_path)
    _form(eng, "COAL-R", _MEMBERS_2)
    eng.resolve_coalition("COAL-R", {"ARCH-2": "APPROVE", "DREAM-2": "APPROVE"})
    eng2 = CoalitionEngine(SECRET, tmp_path / "acf_ledger.jsonl")
    assert eng2.record_count() == 2   # SEALED + RESOLVED records


# ────────────────────────────────────────────────────────────────────────────
# T129-ACF-30: Multiple concurrent coalitions all tracked independently
# ────────────────────────────────────────────────────────────────────────────
def test_T129_ACF_30_concurrent_coalitions(tmp_path):
    eng = _engine(tmp_path)
    _form(eng, "COAL-S1", _MEMBERS_2)
    _form(eng, "COAL-S2", _MEMBERS_3)
    assert eng.active_count() == 2
    eng.resolve_coalition("COAL-S1", {"ARCH-2": "APPROVE", "DREAM-2": "REJECT"})
    eng.resolve_coalition("COAL-S2", {"ARCH-1": "REJECT", "DREAM-1": "REJECT", "BEAST-1": "APPROVE"})
    eng.dissolve_coalition("COAL-S1")
    eng.dissolve_coalition("COAL-S2")
    assert eng.active_count() == 0
    eng.assert_epoch_clear()
