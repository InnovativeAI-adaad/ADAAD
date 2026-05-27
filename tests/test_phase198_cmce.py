"""
Phase 198 — INNOV-103 CMCE — Constitutional Mutation Consensus Engine
30-Test Acceptance Suite · T198-CMCE-01…30
v10.9.0 · InnovativeAI LLC · DUSTIN L REID (HUMAN-0)
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from dorkllm.constitutional_mutation_consensus_engine import (
    ConstitutionalMutationConsensusEngine,
    VoteType,
    ConsensusOutcome,
    RoundStatus,
    CMCEDuplicateVote,
    CMCEUnknownAgent,
    CMCEVoteMissing,
    CMCEHuman0Bypass,
    CMCEChainBroken,
    CMCEChallengeUnresolved,
    CMCERoundNotFound,
    CMCERoundClosed,
    CMCEScopeImmutabilityViolation,
    GOVERNOR,
    REGISTERED_AGENTS,
    DEFAULT_QUORUM,
    LEDGER_PATH,
    _compute_hmac,
    _read_ledger,
)

pytestmark = pytest.mark.phase198


def _mid() -> str:
    return str(uuid.uuid4())


def _iid() -> str:
    return str(uuid.uuid4())


def fresh_engine(tmp_path: Path) -> ConstitutionalMutationConsensusEngine:
    return ConstitutionalMutationConsensusEngine(
        ledger_path=tmp_path / "consensus_ledger.jsonl"
    )


def _all_agents_approve(
    engine: ConstitutionalMutationConsensusEngine, round_id: str
) -> None:
    for agent in REGISTERED_AGENTS:
        engine.cast_vote(round_id, agent, VoteType.APPROVE, "LGTM")


# ===========================================================================
# T198-CMCE-01..05 — Round lifecycle happy path
# ===========================================================================


def test_t198_cmce_01_open_round_returns_round(tmp_path):
    """T198-CMCE-01: open_round returns a round with OPEN status and correct fields."""
    engine = fresh_engine(tmp_path)
    r = engine.open_round(_mid(), _iid(), ["dorkllm/module_x.py"], "ArchitectAgent")
    assert r.status == RoundStatus.OPEN
    assert r.outcome == ConsensusOutcome.PENDING
    assert r.quorum_required == DEFAULT_QUORUM
    assert len(r.scope_paths) == 1


def test_t198_cmce_02_cast_vote_approve(tmp_path):
    """T198-CMCE-02: ArchitectAgent casts APPROVE vote successfully."""
    engine = fresh_engine(tmp_path)
    r = engine.open_round(_mid(), _iid(), ["dorkllm/x.py"], "ArchitectAgent")
    vote = engine.cast_vote(r.round_id, "ArchitectAgent", VoteType.APPROVE, "OK")
    assert vote.agent == "ArchitectAgent"
    assert vote.vote == VoteType.APPROVE


def test_t198_cmce_03_full_quorum_pass(tmp_path):
    """T198-CMCE-03: All 4 agents APPROVE → outcome PASSED."""
    engine = fresh_engine(tmp_path)
    r = engine.open_round(_mid(), _iid(), ["dorkllm/x.py"], "ArchitectAgent")
    _all_agents_approve(engine, r.round_id)
    closed = engine.close_round(r.round_id)
    assert closed.outcome == ConsensusOutcome.PASSED
    assert closed.status == RoundStatus.CLOSED


def test_t198_cmce_04_round_persisted_in_ledger(tmp_path):
    """T198-CMCE-04: Ledger file is written after opening a round."""
    engine = fresh_engine(tmp_path)
    r = engine.open_round(_mid(), _iid(), ["dorkllm/x.py"], "ArchitectAgent")
    records = _read_ledger(engine._ledger_path)
    assert len(records) >= 1
    assert any(rec["event_type"] == "ROUND_OPENED" for rec in records)


def test_t198_cmce_05_votes_persisted_in_ledger(tmp_path):
    """T198-CMCE-05: Every vote is persisted as VOTE_CAST ledger record."""
    engine = fresh_engine(tmp_path)
    r = engine.open_round(_mid(), _iid(), ["dorkllm/x.py"], "ArchitectAgent")
    _all_agents_approve(engine, r.round_id)
    records = _read_ledger(engine._ledger_path)
    vote_records = [rec for rec in records if rec["event_type"] == "VOTE_CAST"]
    assert len(vote_records) == len(REGISTERED_AGENTS)


# ===========================================================================
# T198-CMCE-06..10 — Quorum and blocking logic
# ===========================================================================


def test_t198_cmce_06_quorum_not_met_blocked(tmp_path):
    """T198-CMCE-06: Only 2 APPROVE, 2 REJECT → BLOCKED (quorum=3)."""
    engine = fresh_engine(tmp_path)
    r = engine.open_round(_mid(), _iid(), ["dorkllm/x.py"], "ArchitectAgent")
    agents = sorted(REGISTERED_AGENTS)
    engine.cast_vote(r.round_id, agents[0], VoteType.APPROVE, "Yes")
    engine.cast_vote(r.round_id, agents[1], VoteType.APPROVE, "Yes")
    engine.cast_vote(r.round_id, agents[2], VoteType.REJECT, "No")
    engine.cast_vote(r.round_id, agents[3], VoteType.REJECT, "No")
    closed = engine.close_round(r.round_id)
    assert closed.outcome == ConsensusOutcome.BLOCKED


def test_t198_cmce_07_exactly_quorum_threshold_passes(tmp_path):
    """T198-CMCE-07: Exactly 3 APPROVE, 1 ABSTAIN → PASSED."""
    engine = fresh_engine(tmp_path)
    r = engine.open_round(_mid(), _iid(), ["dorkllm/x.py"], "ArchitectAgent")
    agents = sorted(REGISTERED_AGENTS)
    engine.cast_vote(r.round_id, agents[0], VoteType.APPROVE, "Yes")
    engine.cast_vote(r.round_id, agents[1], VoteType.APPROVE, "Yes")
    engine.cast_vote(r.round_id, agents[2], VoteType.APPROVE, "Yes")
    engine.cast_vote(r.round_id, agents[3], VoteType.ABSTAIN, "No opinion")
    closed = engine.close_round(r.round_id)
    assert closed.outcome == ConsensusOutcome.PASSED


def test_t198_cmce_08_all_reject_blocked(tmp_path):
    """T198-CMCE-08: All 4 REJECT → BLOCKED."""
    engine = fresh_engine(tmp_path)
    r = engine.open_round(_mid(), _iid(), ["dorkllm/x.py"], "ArchitectAgent")
    for agent in REGISTERED_AGENTS:
        engine.cast_vote(r.round_id, agent, VoteType.REJECT, "Reject")
    closed = engine.close_round(r.round_id)
    assert closed.outcome == ConsensusOutcome.BLOCKED


def test_t198_cmce_09_missing_votes_raises(tmp_path):
    """T198-CMCE-09: Closing with missing votes raises CMCEVoteMissing."""
    engine = fresh_engine(tmp_path)
    r = engine.open_round(_mid(), _iid(), ["dorkllm/x.py"], "ArchitectAgent")
    # Only one vote cast
    engine.cast_vote(r.round_id, "ArchitectAgent", VoteType.APPROVE, "Yes")
    with pytest.raises(CMCEVoteMissing):
        engine.close_round(r.round_id)


def test_t198_cmce_10_outcome_deterministic(tmp_path):
    """T198-CMCE-10: Same vote pattern in two engines yields same outcome."""
    engine_a = fresh_engine(tmp_path / "a")
    engine_b = ConstitutionalMutationConsensusEngine(
        ledger_path=tmp_path / "b" / "ledger.jsonl"
    )
    agents = sorted(REGISTERED_AGENTS)
    for engine in (engine_a, engine_b):
        r = engine.open_round(_mid(), _iid(), ["dorkllm/x.py"], "ArchitectAgent")
        engine.cast_vote(r.round_id, agents[0], VoteType.APPROVE, "Yes")
        engine.cast_vote(r.round_id, agents[1], VoteType.APPROVE, "Yes")
        engine.cast_vote(r.round_id, agents[2], VoteType.APPROVE, "Yes")
        engine.cast_vote(r.round_id, agents[3], VoteType.REJECT, "No")
        closed = engine.close_round(r.round_id)
        assert closed.outcome == ConsensusOutcome.PASSED


# ===========================================================================
# T198-CMCE-11..15 — HUMAN-0 authority
# ===========================================================================


def test_t198_cmce_11_human0_veto_blocks_immediately(tmp_path):
    """T198-CMCE-11: HUMAN-0 veto closes round as BLOCKED regardless of votes."""
    engine = fresh_engine(tmp_path)
    r = engine.open_round(_mid(), _iid(), ["dorkllm/x.py"], "ArchitectAgent")
    # All agents approve — but HUMAN-0 vetoes
    _all_agents_approve(engine, r.round_id)
    closed = engine.human0_veto(r.round_id, "Constitutional risk identified by HUMAN-0.")
    # Should be BLOCKED despite unanimous approve
    assert closed.outcome == ConsensusOutcome.BLOCKED
    assert closed.human0_action == "VETO"


def test_t198_cmce_12_human0_override_passes_immediately(tmp_path):
    """T198-CMCE-12: HUMAN-0 override closes round as OVERRIDE regardless of votes."""
    engine = fresh_engine(tmp_path)
    r = engine.open_round(_mid(), _iid(), ["dorkllm/x.py"], "ArchitectAgent")
    # No agent votes — HUMAN-0 overrides
    closed = engine.human0_override(r.round_id, "Emergency production fix authorized.")
    assert closed.outcome == ConsensusOutcome.OVERRIDE
    assert closed.human0_action == "OVERRIDE"
    assert closed.status == RoundStatus.CLOSED


def test_t198_cmce_13_human0_via_cast_vote_rejected(tmp_path):
    """T198-CMCE-13: HUMAN-0 identifier in cast_vote raises CMCEHuman0Bypass."""
    engine = fresh_engine(tmp_path)
    r = engine.open_round(_mid(), _iid(), ["dorkllm/x.py"], "ArchitectAgent")
    with pytest.raises(CMCEHuman0Bypass):
        engine.cast_vote(r.round_id, "HUMAN-0", VoteType.APPROVE, "Try bypass")


def test_t198_cmce_14_human0_veto_logged(tmp_path):
    """T198-CMCE-14: HUMAN-0 veto produces HUMAN0_ACTION and ROUND_CLOSED records."""
    engine = fresh_engine(tmp_path)
    r = engine.open_round(_mid(), _iid(), ["dorkllm/x.py"], "ArchitectAgent")
    engine.human0_veto(r.round_id, "Veto reason.")
    records = _read_ledger(engine._ledger_path)
    event_types = [rec["event_type"] for rec in records]
    assert "HUMAN0_ACTION" in event_types
    assert "ROUND_CLOSED" in event_types


def test_t198_cmce_15_human0_override_round_may_advance(tmp_path):
    """T198-CMCE-15: OVERRIDE outcome is treated as advance-allowed."""
    engine = fresh_engine(tmp_path)
    r = engine.open_round(_mid(), _iid(), ["dorkllm/x.py"], "ArchitectAgent")
    closed = engine.human0_override(r.round_id, "Authorized.")
    assert closed.outcome in (ConsensusOutcome.OVERRIDE, ConsensusOutcome.PASSED)


# ===========================================================================
# T198-CMCE-16..20 — CHALLENGE handling
# ===========================================================================


def test_t198_cmce_16_challenge_blocks_close(tmp_path):
    """T198-CMCE-16: Unresolved CHALLENGE prevents close_round."""
    engine = fresh_engine(tmp_path)
    r = engine.open_round(_mid(), _iid(), ["dorkllm/x.py"], "ArchitectAgent")
    agents = sorted(REGISTERED_AGENTS)
    engine.cast_vote(r.round_id, agents[0], VoteType.APPROVE, "Yes")
    engine.cast_vote(r.round_id, agents[1], VoteType.APPROVE, "Yes")
    engine.cast_vote(r.round_id, agents[2], VoteType.APPROVE, "Yes")
    engine.cast_vote(r.round_id, agents[3], VoteType.CHALLENGE, "Suspicious change.")
    with pytest.raises(CMCEChallengeUnresolved):
        engine.close_round(r.round_id)


def test_t198_cmce_17_challenge_outcome_challenged(tmp_path):
    """T198-CMCE-17: evaluate() returns CHALLENGED when CHALLENGE vote exists."""
    engine = fresh_engine(tmp_path)
    r = engine.open_round(_mid(), _iid(), ["dorkllm/x.py"], "ArchitectAgent")
    agents = sorted(REGISTERED_AGENTS)
    engine.cast_vote(r.round_id, agents[0], VoteType.APPROVE, "Yes")
    engine.cast_vote(r.round_id, agents[1], VoteType.APPROVE, "Yes")
    engine.cast_vote(r.round_id, agents[2], VoteType.APPROVE, "Yes")
    engine.cast_vote(r.round_id, agents[3], VoteType.CHALLENGE, "Suspicious.")
    r2 = engine.get_round(r.round_id)
    outcome, _ = r2.evaluate()
    assert outcome == ConsensusOutcome.CHALLENGED


def test_t198_cmce_18_resolve_challenge_to_approve(tmp_path):
    """T198-CMCE-18: Resolving CHALLENGE to APPROVE allows round to close as PASSED."""
    engine = fresh_engine(tmp_path)
    r = engine.open_round(_mid(), _iid(), ["dorkllm/x.py"], "ArchitectAgent")
    agents = sorted(REGISTERED_AGENTS)
    challenging = agents[3]
    engine.cast_vote(r.round_id, agents[0], VoteType.APPROVE, "Yes")
    engine.cast_vote(r.round_id, agents[1], VoteType.APPROVE, "Yes")
    engine.cast_vote(r.round_id, agents[2], VoteType.APPROVE, "Yes")
    engine.cast_vote(r.round_id, challenging, VoteType.CHALLENGE, "Suspicious.")
    engine.resolve_challenge(r.round_id, challenging, "APPROVE")
    closed = engine.close_round(r.round_id)
    assert closed.outcome == ConsensusOutcome.PASSED


def test_t198_cmce_19_resolve_challenge_to_reject(tmp_path):
    """T198-CMCE-19: Resolving CHALLENGE to REJECT blocks the round (quorum=3, only 3 approve)."""
    engine = fresh_engine(tmp_path)
    r = engine.open_round(_mid(), _iid(), ["dorkllm/x.py"], "ArchitectAgent")
    agents = sorted(REGISTERED_AGENTS)
    engine.cast_vote(r.round_id, agents[0], VoteType.APPROVE, "Yes")
    engine.cast_vote(r.round_id, agents[1], VoteType.APPROVE, "Yes")
    engine.cast_vote(r.round_id, agents[2], VoteType.REJECT, "No")
    engine.cast_vote(r.round_id, agents[3], VoteType.CHALLENGE, "Suspicious.")
    engine.resolve_challenge(r.round_id, agents[3], "REJECT")
    closed = engine.close_round(r.round_id)
    assert closed.outcome == ConsensusOutcome.BLOCKED


def test_t198_cmce_20_challenge_veto_escalation(tmp_path):
    """T198-CMCE-20: CHALLENGE can be escalated to HUMAN-0 veto without resolution."""
    engine = fresh_engine(tmp_path)
    r = engine.open_round(_mid(), _iid(), ["dorkllm/x.py"], "ArchitectAgent")
    for agent in REGISTERED_AGENTS:
        engine.cast_vote(r.round_id, agent, VoteType.CHALLENGE, "All challenge.")
    # HUMAN-0 steps in to veto
    closed = engine.human0_veto(r.round_id, "Escalated from multi-CHALLENGE state.")
    assert closed.outcome == ConsensusOutcome.BLOCKED


# ===========================================================================
# T198-CMCE-21..25 — Invariant enforcement
# ===========================================================================


def test_t198_cmce_21_duplicate_vote_rejected(tmp_path):
    """T198-CMCE-21: Second vote from same agent raises CMCEDuplicateVote."""
    engine = fresh_engine(tmp_path)
    r = engine.open_round(_mid(), _iid(), ["dorkllm/x.py"], "ArchitectAgent")
    engine.cast_vote(r.round_id, "ArchitectAgent", VoteType.APPROVE, "OK")
    with pytest.raises(CMCEDuplicateVote):
        engine.cast_vote(r.round_id, "ArchitectAgent", VoteType.REJECT, "Changed mind")


def test_t198_cmce_22_unknown_agent_rejected(tmp_path):
    """T198-CMCE-22: Vote from non-registered agent raises CMCEUnknownAgent."""
    engine = fresh_engine(tmp_path)
    r = engine.open_round(_mid(), _iid(), ["dorkllm/x.py"], "ArchitectAgent")
    with pytest.raises(CMCEUnknownAgent):
        engine.cast_vote(r.round_id, "RogueAgent", VoteType.APPROVE, "Hack attempt")


def test_t198_cmce_23_vote_on_closed_round_rejected(tmp_path):
    """T198-CMCE-23: Voting on a closed round raises CMCERoundClosed."""
    engine = fresh_engine(tmp_path)
    r = engine.open_round(_mid(), _iid(), ["dorkllm/x.py"], "ArchitectAgent")
    _all_agents_approve(engine, r.round_id)
    engine.close_round(r.round_id)
    with pytest.raises(CMCERoundClosed):
        engine.cast_vote(r.round_id, "ArchitectAgent", VoteType.APPROVE, "Late")


def test_t198_cmce_24_empty_scope_paths_rejected(tmp_path):
    """T198-CMCE-24: Empty scope_paths raises CMCEScopeImmutabilityViolation."""
    engine = fresh_engine(tmp_path)
    with pytest.raises(CMCEScopeImmutabilityViolation):
        engine.open_round(_mid(), _iid(), [], "ArchitectAgent")


def test_t198_cmce_25_get_nonexistent_round_raises(tmp_path):
    """T198-CMCE-25: get_round with unknown ID raises CMCERoundNotFound."""
    engine = fresh_engine(tmp_path)
    with pytest.raises(CMCERoundNotFound):
        engine.get_round(str(uuid.uuid4()))


# ===========================================================================
# T198-CMCE-26..28 — Chain integrity and replay
# ===========================================================================


def test_t198_cmce_26_chain_verify_valid(tmp_path):
    """T198-CMCE-26: verify_chain returns valid=True on untampered ledger."""
    engine = fresh_engine(tmp_path)
    r = engine.open_round(_mid(), _iid(), ["dorkllm/x.py"], "ArchitectAgent")
    _all_agents_approve(engine, r.round_id)
    engine.close_round(r.round_id)
    result = engine.verify_chain()
    assert result["valid"] is True


def test_t198_cmce_27_tampered_ledger_detected(tmp_path):
    """T198-CMCE-27: Tampered ledger record raises CMCEChainBroken on replay."""
    engine = fresh_engine(tmp_path)
    r = engine.open_round(_mid(), _iid(), ["dorkllm/x.py"], "ArchitectAgent")
    _all_agents_approve(engine, r.round_id)
    engine.close_round(r.round_id)

    # Tamper the first ledger record
    ledger_file = engine._ledger_path
    lines = ledger_file.read_text().splitlines()
    rec = json.loads(lines[0])
    rec["data"]["round"]["proposer"] = "TAMPERED"
    lines[0] = json.dumps(rec)
    ledger_file.write_text("\n".join(lines) + "\n")

    with pytest.raises(CMCEChainBroken):
        ConstitutionalMutationConsensusEngine(
            ledger_path=ledger_file
        )


def test_t198_cmce_28_ledger_replay_restores_state(tmp_path):
    """T198-CMCE-28: Replaying the ledger from disk restores round state correctly."""
    ledger_file = tmp_path / "consensus_ledger.jsonl"
    engine = ConstitutionalMutationConsensusEngine(ledger_path=ledger_file)
    r = engine.open_round(_mid(), _iid(), ["dorkllm/x.py"], "ArchitectAgent")
    _all_agents_approve(engine, r.round_id)
    engine.close_round(r.round_id)

    # Replay from disk
    engine2 = ConstitutionalMutationConsensusEngine(ledger_path=ledger_file)
    r2 = engine2.get_round(r.round_id)
    assert r2.outcome == ConsensusOutcome.PASSED
    assert r2.status == RoundStatus.CLOSED


# ===========================================================================
# T198-CMCE-29..30 — Export / governance
# ===========================================================================


def test_t198_cmce_29_export_state_fields(tmp_path):
    """T198-CMCE-29: export_state returns required governance fields."""
    engine = fresh_engine(tmp_path)
    state = engine.export_state()
    required = {
        "innov", "version", "phase", "governor",
        "quorum_required", "registered_agents",
        "total_rounds", "open_rounds", "closed_rounds",
        "outcomes", "chain_tip",
    }
    assert required.issubset(state.keys())
    assert state["governor"] == GOVERNOR
    assert state["innov"] == "INNOV-103"


def test_t198_cmce_30_api_open_and_close_round(tmp_path, monkeypatch):
    """T198-CMCE-30: FastAPI router open + vote + close round returns correct HTTP responses."""
    import dorkllm.constitutional_mutation_consensus_engine as mod
    from app.api.constitutional_mutation_consensus_engine import router

    # Patch the engine to use tmp_path
    test_engine = ConstitutionalMutationConsensusEngine(
        ledger_path=tmp_path / "consensus_ledger.jsonl"
    )
    import app.api.constitutional_mutation_consensus_engine as api_mod
    monkeypatch.setattr(api_mod, "_engine", test_engine)

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    # Open round
    payload = {
        "mutation_id": _mid(),
        "intent_declaration_id": _iid(),
        "scope_paths": ["dorkllm/x.py"],
        "proposer": "ArchitectAgent",
    }
    resp = client.post("/cmce/round/open", json=payload)
    assert resp.status_code == 200
    round_id = resp.json()["round_id"]

    # Cast all votes
    for agent in sorted(REGISTERED_AGENTS):
        resp = client.post(
            f"/cmce/round/{round_id}/vote",
            json={"agent": agent, "vote": "APPROVE", "rationale": "OK"},
        )
        assert resp.status_code == 200

    # Close round
    resp = client.post(f"/cmce/round/{round_id}/close")
    assert resp.status_code == 200
    data = resp.json()
    assert data["outcome"] == "PASSED"
    assert data["may_advance_to_cel"] is True
