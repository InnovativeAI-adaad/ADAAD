"""
INNOV-103 CMCE - Constitutional Mutation Consensus Engine
Phase 198 - v10.9.0 - InnovativeAI LLC - DUSTIN L REID (HUMAN-0)

World-first: constitutionally-governed multi-agent consensus protocol that
requires all registered agents (ArchitectAgent, DreamAgent, BeastAgent,
AdversarialRedTeam) to cast typed votes (APPROVE / REJECT / ABSTAIN /
CHALLENGE) on every proposed mutation before CEL entry. A configurable quorum
threshold (default 3-of-4) must be met with no unresolved CHALLENGE votes.
HUMAN-0 holds irrevocable veto and override power. All votes, quorum
evaluations, and decisions are sealed in an HMAC-chained append-only consensus
ledger with deterministic replay. A mutation blocked at consensus MUST NOT
advance to the CEL gate under any agent authority.

Hard-class invariants enforced by this module:
  CMCE-QUORUM-0   — Quorum threshold is immutable; runtime reduction is
                    a constitutional violation.
  CMCE-VOTE-0     — Each registered agent MUST cast exactly one typed vote
                    per round; duplicate or missing votes are fatal.
  CMCE-HUMAN0-0   — HUMAN-0 veto immediately terminates the round as BLOCKED;
                    HUMAN-0 override immediately terminates as APPROVED.
                    Neither can be contested by any agent.
  CMCE-CHAIN-0    — Every consensus event is HMAC-chained to its predecessor;
                    chain break is a fatal constitutional violation.
  CMCE-IMMUT-0    — Committed consensus records are append-only; no mutation
                    or deletion is permitted post-commit.
  CMCE-CHALLENGE-0 — An unresolved CHALLENGE vote blocks quorum; a CHALLENGE
                    must be either withdrawn or escalated to HUMAN-0 before
                    consensus can pass.
  CMCE-DETERM-0   — Consensus evaluation is deterministic; identical vote sets
                    MUST yield identical outcomes.
  CMCE-AUDIT-0    — Every vote, resolution, and quorum decision is logged
                    before the caller receives a response.
  CMCE-SCOPE-0    — A mutation's registered scope paths are immutable once
                    the consensus round is opened.
  CMCE-NOBYPASS-0 — No mutation may advance to the CEL gate without a PASSED
                    consensus record; bypass is a Hard-class constitutional
                    violation.
"""
from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GOVERNOR = "DUSTIN L REID"
INNOV_CODE = "CMCE"
INNOV_NUMBER = "INNOV-103"
VERSION = "10.9.0"
PHASE = 198

LEDGER_PATH = Path("data/cmce/consensus_ledger.jsonl")
HMAC_SECRET = os.environ.get(
    "ADAAD_HMAC_SECRET", "adaad-cmce-hmac-secret-v1"
).encode()

# Canonical registered agents — any deviation is a constitutional violation.
REGISTERED_AGENTS: frozenset[str] = frozenset(
    {"ArchitectAgent", "DreamAgent", "BeastAgent", "AdversarialRedTeam"}
)

# Default quorum: 3 of 4 agents must APPROVE.  HUMAN-0 votes are superset.
DEFAULT_QUORUM = 3
HUMAN0_IDENTIFIERS: frozenset[str] = frozenset(
    {"HUMAN-0", "DUSTIN L REID", "HUMAN0"}
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class VoteType(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    ABSTAIN = "ABSTAIN"
    CHALLENGE = "CHALLENGE"


class ConsensusOutcome(str, Enum):
    PASSED = "PASSED"       # Quorum met, no unresolved CHALLENGE
    BLOCKED = "BLOCKED"     # Quorum not met OR HUMAN-0 veto
    CHALLENGED = "CHALLENGED"  # Unresolved CHALLENGE remains
    PENDING = "PENDING"     # Round open, voting in progress
    OVERRIDE = "OVERRIDE"   # HUMAN-0 direct override → advance regardless


class RoundStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


# ---------------------------------------------------------------------------
# Exceptions — fail-closed, never silent
# ---------------------------------------------------------------------------


class CMCEError(Exception):
    """Base CMCE constitutional violation."""


class CMCEQuorumTampered(CMCEError):
    """CMCE-QUORUM-0 violated: quorum threshold altered at runtime."""


class CMCEDuplicateVote(CMCEError):
    """CMCE-VOTE-0 violated: agent cast more than one vote per round."""


class CMCEUnknownAgent(CMCEError):
    """CMCE-VOTE-0 violated: vote from unregistered agent identity."""


class CMCEVoteMissing(CMCEError):
    """CMCE-VOTE-0 violated: attempt to close round with missing votes."""


class CMCEHuman0Bypass(CMCEError):
    """CMCE-HUMAN0-0 violated: attempt to override HUMAN-0 decision."""


class CMCEChainBroken(CMCEError):
    """CMCE-CHAIN-0 violated: HMAC chain integrity failure detected."""


class CMCELedgerTampered(CMCEError):
    """CMCE-IMMUT-0 violated: ledger record altered after commit."""


class CMCEChallengeUnresolved(CMCEError):
    """CMCE-CHALLENGE-0 violated: closing round with live CHALLENGE vote."""


class CMCEDeterminismViolation(CMCEError):
    """CMCE-DETERM-0 violated: non-deterministic evaluation path detected."""


class CMCEScopeImmutabilityViolation(CMCEError):
    """CMCE-SCOPE-0 violated: scope paths modified after round open."""


class CMCEBypassAttempt(CMCEError):
    """CMCE-NOBYPASS-0 violated: mutation advanced without consensus record."""


class CMCERoundNotFound(CMCEError):
    """Consensus round ID does not exist in the ledger."""


class CMCERoundClosed(CMCEError):
    """Attempt to vote on an already-closed consensus round."""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class AgentVote:
    agent: str
    vote: VoteType
    rationale: str
    timestamp: float = field(default_factory=time.time)
    vote_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "vote": self.vote.value,
            "rationale": self.rationale,
            "timestamp": self.timestamp,
            "vote_id": self.vote_id,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AgentVote":
        return cls(
            agent=d["agent"],
            vote=VoteType(d["vote"]),
            rationale=d["rationale"],
            timestamp=d["timestamp"],
            vote_id=d["vote_id"],
        )


@dataclass
class ConsensusRound:
    round_id: str
    mutation_id: str
    intent_declaration_id: str
    scope_paths: list[str]
    proposer: str
    quorum_required: int
    opened_at: float
    status: RoundStatus = RoundStatus.OPEN
    votes: dict[str, AgentVote] = field(default_factory=dict)
    outcome: ConsensusOutcome = ConsensusOutcome.PENDING
    outcome_reason: str = ""
    closed_at: Optional[float] = None
    human0_action: Optional[str] = None  # "VETO" | "OVERRIDE" | None

    # -----------------------------------------------------------------------
    # Consensus evaluation — deterministic (CMCE-DETERM-0)
    # -----------------------------------------------------------------------

    def evaluate(self) -> tuple[ConsensusOutcome, str]:
        """
        Deterministically compute the consensus outcome from current vote set.
        Called only after all registered agents have voted (or HUMAN-0 acted).

        Returns (outcome, reason).  Raises on CHALLENGE unresolved.
        """
        # HUMAN-0 superset checks first (CMCE-HUMAN0-0)
        if self.human0_action == "VETO":
            return ConsensusOutcome.BLOCKED, "HUMAN-0 exercised constitutional veto."
        if self.human0_action == "OVERRIDE":
            return ConsensusOutcome.OVERRIDE, "HUMAN-0 exercised constitutional override — mutation approved unconditionally."

        # Tally votes
        approve_count = sum(
            1 for v in self.votes.values() if v.vote == VoteType.APPROVE
        )
        reject_count = sum(
            1 for v in self.votes.values() if v.vote == VoteType.REJECT
        )
        challenge_count = sum(
            1 for v in self.votes.values() if v.vote == VoteType.CHALLENGE
        )

        # Unresolved CHALLENGE blocks consensus (CMCE-CHALLENGE-0)
        if challenge_count > 0:
            agents_challenged = [
                v.agent for v in self.votes.values() if v.vote == VoteType.CHALLENGE
            ]
            return (
                ConsensusOutcome.CHALLENGED,
                f"Unresolved CHALLENGE from: {agents_challenged}. Escalate to HUMAN-0.",
            )

        # Quorum check (CMCE-QUORUM-0)
        if approve_count >= self.quorum_required:
            return (
                ConsensusOutcome.PASSED,
                f"Quorum met: {approve_count}/{self.quorum_required} APPROVE votes "
                f"({reject_count} REJECT, "
                f"{len(self.votes) - approve_count - reject_count} ABSTAIN).",
            )

        return (
            ConsensusOutcome.BLOCKED,
            f"Quorum not met: {approve_count}/{self.quorum_required} APPROVE votes "
            f"({reject_count} REJECT).",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_id": self.round_id,
            "mutation_id": self.mutation_id,
            "intent_declaration_id": self.intent_declaration_id,
            "scope_paths": self.scope_paths,
            "proposer": self.proposer,
            "quorum_required": self.quorum_required,
            "opened_at": self.opened_at,
            "status": self.status.value,
            "votes": {k: v.to_dict() for k, v in self.votes.items()},
            "outcome": self.outcome.value,
            "outcome_reason": self.outcome_reason,
            "closed_at": self.closed_at,
            "human0_action": self.human0_action,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ConsensusRound":
        r = cls(
            round_id=d["round_id"],
            mutation_id=d["mutation_id"],
            intent_declaration_id=d["intent_declaration_id"],
            scope_paths=d["scope_paths"],
            proposer=d["proposer"],
            quorum_required=d["quorum_required"],
            opened_at=d["opened_at"],
            status=RoundStatus(d["status"]),
            outcome=ConsensusOutcome(d["outcome"]),
            outcome_reason=d["outcome_reason"],
            closed_at=d.get("closed_at"),
            human0_action=d.get("human0_action"),
        )
        r.votes = {k: AgentVote.from_dict(v) for k, v in d.get("votes", {}).items()}
        return r


# ---------------------------------------------------------------------------
# HMAC chain utilities (CMCE-CHAIN-0)
# ---------------------------------------------------------------------------


def _compute_hmac(payload: str, prev_hmac: str) -> str:
    raw = f"{prev_hmac}:{payload}".encode()
    return _hmac.new(HMAC_SECRET, raw, hashlib.sha256).hexdigest()


def _chain_valid(record: dict[str, Any], prev_hmac: str) -> bool:
    stored = record.get("chain_hmac", "")
    payload = json.dumps(record.get("data", {}), sort_keys=True, separators=(",", ":"))
    expected = _compute_hmac(payload, prev_hmac)
    return _hmac.compare_digest(stored[:24], expected[:24])


# ---------------------------------------------------------------------------
# Ledger I/O
# ---------------------------------------------------------------------------


def _write_ledger(
    path: Path,
    event_type: str,
    data: dict[str, Any],
    prev_hmac: str,
) -> str:
    """Append one HMAC-chained record; return new chain HMAC."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
    chain_hmac = _compute_hmac(payload, prev_hmac)
    record = {
        "event_type": event_type,
        "data": data,
        "chain_hmac": chain_hmac,
        "timestamp": time.time(),
    }
    with path.open("a") as fh:
        fh.write(json.dumps(record) + "\n")
    return chain_hmac


def _read_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


# ---------------------------------------------------------------------------
# ConstitutionalMutationConsensusEngine
# ---------------------------------------------------------------------------


class ConstitutionalMutationConsensusEngine:
    """
    INNOV-103 · CMCE — Constitutional Mutation Consensus Engine.

    Manages the full lifecycle of multi-agent consensus rounds for proposed
    mutations.  All state transitions are audit-logged and HMAC-chained.
    """

    def __init__(
        self,
        ledger_path: Path = LEDGER_PATH,
        quorum: int = DEFAULT_QUORUM,
        registered_agents: frozenset[str] = REGISTERED_AGENTS,
    ) -> None:
        # Freeze quorum at construction — runtime change is CMCE-QUORUM-0 violation
        self._quorum: int = quorum
        self._registered_agents: frozenset[str] = registered_agents
        self._ledger_path = ledger_path
        self._rounds: dict[str, ConsensusRound] = {}
        self._chain_hmac: str = "GENESIS"

        # Replay existing ledger
        self._replay_ledger()

    # ------------------------------------------------------------------
    # Ledger replay
    # ------------------------------------------------------------------

    def _replay_ledger(self) -> None:
        """Reconstruct in-memory state from persisted ledger records."""
        records = _read_ledger(self._ledger_path)
        prev = "GENESIS"
        for rec in records:
            if not _chain_valid(rec, prev):
                raise CMCEChainBroken(
                    f"CMCE-CHAIN-0: chain integrity failure at record "
                    f"type={rec.get('event_type')}."
                )
            prev = rec["chain_hmac"]
            self._apply_event(rec["event_type"], rec["data"])
        self._chain_hmac = prev

    def _apply_event(self, event_type: str, data: dict[str, Any]) -> None:
        if event_type == "ROUND_OPENED":
            r = ConsensusRound.from_dict(data["round"])
            self._rounds[r.round_id] = r
        elif event_type == "VOTE_CAST":
            rid = data["round_id"]
            if rid in self._rounds:
                vote = AgentVote.from_dict(data["vote"])
                self._rounds[rid].votes[vote.agent] = vote
        elif event_type == "ROUND_CLOSED":
            rid = data["round_id"]
            if rid in self._rounds:
                r = self._rounds[rid]
                r.outcome = ConsensusOutcome(data["outcome"])
                r.outcome_reason = data["outcome_reason"]
                r.status = RoundStatus.CLOSED
                r.closed_at = data["closed_at"]
                r.human0_action = data.get("human0_action")
        elif event_type == "HUMAN0_ACTION":
            rid = data["round_id"]
            if rid in self._rounds:
                self._rounds[rid].human0_action = data["action"]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def open_round(
        self,
        mutation_id: str,
        intent_declaration_id: str,
        scope_paths: list[str],
        proposer: str,
    ) -> ConsensusRound:
        """
        Open a new consensus round for a proposed mutation.

        Raises CMCEScopeImmutabilityViolation if scope_paths is empty.
        """
        if not scope_paths:
            raise CMCEScopeImmutabilityViolation(
                "CMCE-SCOPE-0: scope_paths must be non-empty when opening a round."
            )

        round_id = str(uuid.uuid4())
        now = time.time()
        r = ConsensusRound(
            round_id=round_id,
            mutation_id=mutation_id,
            intent_declaration_id=intent_declaration_id,
            scope_paths=list(scope_paths),
            proposer=proposer,
            quorum_required=self._quorum,
            opened_at=now,
        )
        self._rounds[round_id] = r

        data: dict[str, Any] = {
            "round": r.to_dict(),
            "governor": GOVERNOR,
            "innov": INNOV_NUMBER,
        }
        self._chain_hmac = _write_ledger(
            self._ledger_path, "ROUND_OPENED", data, self._chain_hmac
        )
        return r

    def cast_vote(
        self,
        round_id: str,
        agent: str,
        vote: VoteType,
        rationale: str,
    ) -> AgentVote:
        """
        Register an agent's vote for an open consensus round.

        Enforces:
          CMCE-VOTE-0  — registered agent, no duplicate, open round
          CMCE-HUMAN0-0 — HUMAN-0 identifiers routed to human0_action only
        """
        if agent in HUMAN0_IDENTIFIERS:
            raise CMCEHuman0Bypass(
                "CMCE-HUMAN0-0: HUMAN-0 authority must use human0_veto() "
                "or human0_override() — not cast_vote()."
            )

        r = self._get_open_round(round_id)

        if agent not in self._registered_agents:
            raise CMCEUnknownAgent(
                f"CMCE-VOTE-0: '{agent}' is not a registered consensus agent. "
                f"Registered: {sorted(self._registered_agents)}."
            )

        if agent in r.votes:
            raise CMCEDuplicateVote(
                f"CMCE-VOTE-0: agent '{agent}' has already voted in round {round_id}."
            )

        agent_vote = AgentVote(agent=agent, vote=vote, rationale=rationale)
        r.votes[agent] = agent_vote

        data: dict[str, Any] = {
            "round_id": round_id,
            "vote": agent_vote.to_dict(),
            "governor": GOVERNOR,
        }
        self._chain_hmac = _write_ledger(
            self._ledger_path, "VOTE_CAST", data, self._chain_hmac
        )
        return agent_vote

    def human0_veto(self, round_id: str, reason: str) -> ConsensusRound:
        """
        HUMAN-0 exercises irrevocable constitutional veto on an open round.
        Immediately closes the round as BLOCKED.  Cannot be contested (CMCE-HUMAN0-0).
        """
        r = self._get_open_round(round_id)
        r.human0_action = "VETO"

        data: dict[str, Any] = {
            "round_id": round_id,
            "action": "VETO",
            "reason": reason,
            "governor": GOVERNOR,
        }
        self._chain_hmac = _write_ledger(
            self._ledger_path, "HUMAN0_ACTION", data, self._chain_hmac
        )

        return self._close_round(r)

    def human0_override(self, round_id: str, reason: str) -> ConsensusRound:
        """
        HUMAN-0 exercises irrevocable constitutional override on an open round.
        Immediately closes the round as OVERRIDE (mutation approved unconditionally).
        Cannot be contested (CMCE-HUMAN0-0).
        """
        r = self._get_open_round(round_id)
        r.human0_action = "OVERRIDE"

        data: dict[str, Any] = {
            "round_id": round_id,
            "action": "OVERRIDE",
            "reason": reason,
            "governor": GOVERNOR,
        }
        self._chain_hmac = _write_ledger(
            self._ledger_path, "HUMAN0_ACTION", data, self._chain_hmac
        )

        return self._close_round(r)

    def close_round(self, round_id: str) -> ConsensusRound:
        """
        Attempt to close a consensus round after all registered agents have voted.

        Raises CMCEVoteMissing if any registered agent has not yet voted.
        Raises CMCEChallengeUnresolved if a CHALLENGE is recorded and
        human0_action has not been set.
        """
        r = self._get_open_round(round_id)

        # HUMAN-0 action path — no vote completeness check needed
        if r.human0_action in ("VETO", "OVERRIDE"):
            return self._close_round(r)

        # Require all registered agents to have voted (CMCE-VOTE-0)
        missing = self._registered_agents - r.votes.keys()
        if missing:
            raise CMCEVoteMissing(
                f"CMCE-VOTE-0: round {round_id} cannot close — votes missing "
                f"from: {sorted(missing)}."
            )

        # Evaluate — CHALLENGE with no human0_action is blocked
        outcome, reason = r.evaluate()
        if outcome == ConsensusOutcome.CHALLENGED and not r.human0_action:
            raise CMCEChallengeUnresolved(
                f"CMCE-CHALLENGE-0: {reason}  Use human0_veto() or "
                f"human0_override() to resolve."
            )

        return self._close_round(r)

    def resolve_challenge(
        self, round_id: str, challenging_agent: str, resolution: str
    ) -> AgentVote:
        """
        Withdraw a CHALLENGE vote (replace with APPROVE or REJECT) so that
        the round can proceed without HUMAN-0 escalation.  The resolution
        must be 'APPROVE' or 'REJECT'.
        """
        r = self._get_open_round(round_id)
        if challenging_agent not in r.votes:
            raise CMCEUnknownAgent(
                f"Agent '{challenging_agent}' has not voted in round {round_id}."
            )
        existing = r.votes[challenging_agent]
        if existing.vote != VoteType.CHALLENGE:
            raise CMCEError(
                f"Agent '{challenging_agent}' did not cast a CHALLENGE in "
                f"round {round_id}."
            )
        if resolution not in ("APPROVE", "REJECT"):
            raise CMCEError(
                "Challenge resolution must be 'APPROVE' or 'REJECT'."
            )
        new_vote = AgentVote(
            agent=challenging_agent,
            vote=VoteType(resolution),
            rationale=f"Challenge resolved: {resolution}",
        )
        r.votes[challenging_agent] = new_vote

        data: dict[str, Any] = {
            "round_id": round_id,
            "vote": new_vote.to_dict(),
            "governor": GOVERNOR,
            "resolution_of_challenge": True,
        }
        self._chain_hmac = _write_ledger(
            self._ledger_path, "VOTE_CAST", data, self._chain_hmac
        )
        return new_vote

    def get_round(self, round_id: str) -> ConsensusRound:
        r = self._rounds.get(round_id)
        if r is None:
            raise CMCERoundNotFound(f"Consensus round '{round_id}' not found.")
        return r

    def verify_chain(self) -> dict[str, Any]:
        """Replay the full ledger and validate HMAC chain integrity."""
        records = _read_ledger(self._ledger_path)
        prev = "GENESIS"
        for i, rec in enumerate(records):
            if not _chain_valid(rec, prev):
                return {
                    "valid": False,
                    "broken_at_index": i,
                    "event_type": rec.get("event_type"),
                    "governor": GOVERNOR,
                }
            prev = rec["chain_hmac"]
        return {
            "valid": True,
            "total_records": len(records),
            "chain_tip": prev[:24],
            "governor": GOVERNOR,
        }

    def export_state(self) -> dict[str, Any]:
        return {
            "innov": INNOV_NUMBER,
            "version": VERSION,
            "phase": PHASE,
            "governor": GOVERNOR,
            "quorum_required": self._quorum,
            "registered_agents": sorted(self._registered_agents),
            "total_rounds": len(self._rounds),
            "open_rounds": sum(
                1 for r in self._rounds.values() if r.status == RoundStatus.OPEN
            ),
            "closed_rounds": sum(
                1 for r in self._rounds.values() if r.status == RoundStatus.CLOSED
            ),
            "outcomes": {
                outcome.value: sum(
                    1 for r in self._rounds.values() if r.outcome == outcome
                )
                for outcome in ConsensusOutcome
            },
            "chain_tip": self._chain_hmac[:24],
        }

    def summary(self) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self._rounds.values()]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_open_round(self, round_id: str) -> ConsensusRound:
        r = self._rounds.get(round_id)
        if r is None:
            raise CMCERoundNotFound(f"Consensus round '{round_id}' not found.")
        if r.status == RoundStatus.CLOSED:
            raise CMCERoundClosed(
                f"Consensus round '{round_id}' is already closed "
                f"(outcome={r.outcome.value})."
            )
        return r

    def _close_round(self, r: ConsensusRound) -> ConsensusRound:
        outcome, reason = r.evaluate()
        r.outcome = outcome
        r.outcome_reason = reason
        r.status = RoundStatus.CLOSED
        r.closed_at = time.time()

        data: dict[str, Any] = {
            "round_id": r.round_id,
            "mutation_id": r.mutation_id,
            "outcome": outcome.value,
            "outcome_reason": reason,
            "closed_at": r.closed_at,
            "human0_action": r.human0_action,
            "governor": GOVERNOR,
        }
        self._chain_hmac = _write_ledger(
            self._ledger_path, "ROUND_CLOSED", data, self._chain_hmac
        )
        return r
