# SPDX-License-Identifier: Apache-2.0
"""
Phase 6 — Autonomous Roadmap Self-Amendment Engine
===================================================

Enables the mutation pipeline to propose, score, and submit governed amendments
to ROADMAP.md. All proposals are constitutional-gated, human-approvable, and
deterministically replayable.

Authority invariant:
  This engine PROPOSES amendments only. No roadmap change is committed without:
    1. GovernanceGate constitutional evaluation
    2. Human-approval-gate sign-off (authority_level = "governor-review")
    3. Deterministic replay proof before merge

Acceptance criteria (Phase 6):
  - roadmap_diff_score ∈ [0.0, 1.0] on every valid proposal
  - All proposals stored with full SHA-256 lineage chain
  - AmendmentProposal round-trips to/from JSON deterministically
  - RoadmapAmendmentEngine raises GovernanceViolation on authority breach
  - ≥85% test pass rate across replay scenarios
"""

from __future__ import annotations

import hashlib
import json
import re
import textwrap
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Sequence

from runtime import ROOT_DIR
from runtime.governance.foundation.determinism import (
    RuntimeDeterminismProvider,
    default_provider,
    require_replay_safe_provider,
)
from security.ledger import journal


# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

_ROADMAP_PATH = ROOT_DIR / "ROADMAP.md"
_PROPOSALS_DIR = ROOT_DIR / "runtime" / "governance" / "roadmap_proposals"

_MIN_RATIONALE_WORDS = 10
_MAX_PROPOSAL_TITLE_LEN = 120
_AUTHORITY_LEVEL = "governor-review"

# Milestone states permitted in a roadmap amendment
_VALID_MILESTONE_STATES = frozenset(["proposed", "active", "deferred", "cancelled", "shipped"])


# ──────────────────────────────────────────────────────────────────────────────
# Exceptions
# ──────────────────────────────────────────────────────────────────────────────


class GovernanceViolation(RuntimeError):
    """Raised when a roadmap amendment violates a constitutional invariant."""


class DeterminismViolation(RuntimeError):
    """Raised when replay produces a divergent roadmap diff hash."""


# ──────────────────────────────────────────────────────────────────────────────
# Value objects
# ──────────────────────────────────────────────────────────────────────────────


class ProposalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


@dataclass(frozen=True)
class MilestoneEntry:
    """
    Structured representation of a single roadmap milestone.

    Attributes
    ----------
    phase_id:   Numeric phase identifier (e.g. 6).
    title:      Short human-readable label.
    status:     One of _VALID_MILESTONE_STATES.
    target_ver: Semver string the milestone targets (e.g. "3.1.0").
    description: Free-form detail — subject to rationale-length gate.
    """

    phase_id: int
    title: str
    status: str
    target_ver: str
    description: str

    def __post_init__(self) -> None:
        if self.status not in _VALID_MILESTONE_STATES:
            raise GovernanceViolation(
                f"Milestone status '{self.status}' not in {sorted(_VALID_MILESTONE_STATES)}"
            )
        if len(self.title) > _MAX_PROPOSAL_TITLE_LEN:
            raise GovernanceViolation(
                f"Milestone title exceeds {_MAX_PROPOSAL_TITLE_LEN} chars: {self.title!r}"
            )


@dataclass
class RoadmapAmendmentProposal:
    """
    Immutable (post-creation) proposal record for a roadmap amendment.

    Fields
    ------
    proposal_id:       Deterministic ID derived from timestamp + content hash.
    proposer_agent:    Agent ID that authored the amendment (e.g. "ArchitectAgent").
    timestamp:         ISO-8601 UTC creation time.
    prior_roadmap_hash: SHA-256 of ROADMAP.md before this amendment.
    amended_milestones: Ordered list of milestones being changed.
    rationale:         Human-readable justification (≥10 words).
    diff_score:        Float in [0, 1] estimating fitness improvement.
    authority_level:   Always "governor-review" — cannot be overridden.
    lineage_chain_hash: SHA-256 of (prior_roadmap_hash + proposal content).
    approvals:         List of governor IDs who approved.
    rejections:        List of governor IDs who rejected.
    status:            ProposalStatus.
    phase_transitions: Audit log of status changes.
    """

    proposal_id: str
    proposer_agent: str
    timestamp: str
    prior_roadmap_hash: str
    amended_milestones: list[dict[str, Any]]
    rationale: str
    diff_score: float
    authority_level: str
    lineage_chain_hash: str
    approvals: list[str] = field(default_factory=list)
    rejections: list[str] = field(default_factory=list)
    status: str = ProposalStatus.PENDING
    phase_transitions: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, raw: str) -> "RoadmapAmendmentProposal":
        data = json.loads(raw)
        return cls(**data)

    def content_hash(self) -> str:
        payload = json.dumps(
            {
                "proposer_agent": self.proposer_agent,
                "prior_roadmap_hash": self.prior_roadmap_hash,
                "amended_milestones": self.amended_milestones,
                "rationale": self.rationale,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ──────────────────────────────────────────────────────────────────────────────
# Scoring
# ──────────────────────────────────────────────────────────────────────────────


def _score_amendment(milestones: Sequence[MilestoneEntry], rationale: str) -> float:
    """
    Heuristic diff_score ∈ [0.0, 1.0].

    Scoring axes:
      +0.30 — milestone moves from proposed → active (execution momentum)
      +0.20 — milestone moves from active → shipped (delivery evidence)
      -0.15 — milestone moves to deferred or cancelled (regression signal)
      +0.10 — each word in rationale beyond minimum (capped at +0.20)
      -0.35 — duplicate phase_id in proposal (structural incoherence)

    Clamped to [0.0, 1.0].
    """
    score = 0.0
    seen_phases: set[int] = set()

    for m in milestones:
        if m.status == "active":
            score += 0.30
        elif m.status == "shipped":
            score += 0.20
        elif m.status in ("deferred", "cancelled"):
            score -= 0.15
        if m.phase_id in seen_phases:
            score -= 0.35
        seen_phases.add(m.phase_id)

    word_count = len(rationale.split())
    bonus = min(0.20, max(0.0, (word_count - _MIN_RATIONALE_WORDS) * 0.01))
    score += bonus

    return round(max(0.0, min(1.0, score)), 4)


# ──────────────────────────────────────────────────────────────────────────────
# Roadmap hash utilities
# ──────────────────────────────────────────────────────────────────────────────


def hash_roadmap(path: Path = _ROADMAP_PATH) -> str:
    """Return SHA-256 hex digest of ROADMAP.md contents (UTF-8, normalised line endings)."""
    text = path.read_text("utf-8").replace("\r\n", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _lineage_hash(prior_hash: str, content_hash: str) -> str:
    return hashlib.sha256(f"{prior_hash}:{content_hash}".encode("utf-8")).hexdigest()


# ──────────────────────────────────────────────────────────────────────────────
# Engine
# ──────────────────────────────────────────────────────────────────────────────


class RoadmapAmendmentEngine:
    """
    Governed interface for autonomous roadmap self-amendment (Phase 6).

    All write paths are:
      propose() → persisted as JSON in roadmap_proposals/
      approve() → status transition, journal entry, authority_level enforced
      reject()  → status transition, journal entry

    Nothing modifies ROADMAP.md directly — that is the responsibility of the
    human-approval gate after all approvals are received.

    Parameters
    ----------
    proposals_dir:    Override for proposal storage path (default: runtime/).
    required_approvals: Number of governor approvals needed to transition to
                        ProposalStatus.APPROVED (default: 2).
    provider:         Determinism provider for time injection in tests.
    replay_mode:      Passed to require_replay_safe_provider().
    roadmap_path:     Override for ROADMAP.md location (tests).
    """

    def __init__(
        self,
        *,
        proposals_dir: Path | None = None,
        required_approvals: int = 2,
        provider: RuntimeDeterminismProvider | None = None,
        replay_mode: str = "off",
        roadmap_path: Path | None = None,
    ) -> None:
        self.proposals_dir = proposals_dir or _PROPOSALS_DIR
        self.proposals_dir.mkdir(parents=True, exist_ok=True)
        self.required_approvals = required_approvals
        self.provider = provider or default_provider()
        self.roadmap_path = roadmap_path or _ROADMAP_PATH
        require_replay_safe_provider(self.provider, replay_mode=replay_mode)

    # ── Public API ─────────────────────────────────────────────────────────

    def propose(
        self,
        proposer_agent: str,
        *,
        milestones: Sequence[MilestoneEntry],
        rationale: str,
    ) -> RoadmapAmendmentProposal:
        """
        Create and persist a governed roadmap amendment proposal.

        Governance checks (fail-closed):
          1. rationale word count ≥ _MIN_RATIONALE_WORDS
          2. All milestone statuses valid
          3. authority_level is hardcoded to "governor-review" — cannot be injected
          4. diff_score ∈ [0.0, 1.0]
          5. Lineage chain hash computed and stored

        Returns the persisted proposal.
        """
        self._validate_rationale(rationale)
        milestone_dicts = [asdict(m) for m in milestones]
        diff_score = _score_amendment(milestones, rationale)

        prior_hash = hash_roadmap(self.roadmap_path)
        timestamp = self.provider.iso_now()
        ts_slug = self.provider.format_utc("%Y%m%dT%H%M%SZ")
        proposal_seed = json.dumps(
            {
                "proposer_agent": proposer_agent,
                "prior_roadmap_hash": prior_hash,
                "amended_milestones": milestone_dicts,
                "rationale": rationale,
            },
            sort_keys=True,
        )
        proposal_hash = hashlib.sha256(proposal_seed.encode("utf-8")).hexdigest()
        proposal_id = f"rmap-amendment-{ts_slug}-{prior_hash[:8]}-{proposal_hash[:8]}"

        proposal = RoadmapAmendmentProposal(
            proposal_id=proposal_id,
            proposer_agent=proposer_agent,
            timestamp=timestamp,
            prior_roadmap_hash=prior_hash,
            amended_milestones=milestone_dicts,
            rationale=rationale,
            diff_score=diff_score,
            authority_level=_AUTHORITY_LEVEL,  # immutable
            lineage_chain_hash="",  # computed after content_hash
            approvals=[],
            rejections=[],
            status=ProposalStatus.PENDING,
            phase_transitions=[
                {
                    "from": None,
                    "to": ProposalStatus.PENDING,
                    "at": timestamp,
                    "actor": proposer_agent,
                }
            ],
        )
        # Compute lineage after all fields are set
        chain = _lineage_hash(prior_hash, proposal.content_hash())
        proposal.lineage_chain_hash = chain

        self._persist(proposal)

        journal.write_entry(
            agent_id=proposer_agent,
            action="roadmap_amendment_proposed",
            payload={
                "proposal_id": proposal_id,
                "prior_roadmap_hash": prior_hash[:16],
                "lineage_chain_hash": chain[:16],
                "milestone_count": len(milestones),
                "diff_score": diff_score,
            },
        )
        return proposal

    def approve(
        self,
        proposal_id: str,
        *,
        governor_id: str,
        human_signoff_token: str | None = None,
    ) -> RoadmapAmendmentProposal:
        """
        Record a governor approval after a human signoff ledger event.

        Governance invariants:
          - INVARIANT PHASE6-HUMAN-0 requires a non-empty human_signoff_token.
          - The roadmap_amendment_human_signoff ledger event is written before
            any approval mutation is persisted.
          - A governor may not approve the same proposal twice.
          - Once rejected, a proposal cannot be re-approved (status = REJECTED).
          - authority_level remains "governor-review" through all transitions.
        """
        proposal = self._load(proposal_id)
        self._validate_proposal_payload(proposal)
        self._assert_human_signoff_token(
            proposal_id,
            governor_id=governor_id,
            human_signoff_token=human_signoff_token,
        )
        self.verify_replay(proposal_id)
        self._assert_approval_allowed(proposal_id, governor_id=governor_id)
        self._record_human_signoff(
            proposal_id,
            governor_id=governor_id,
            human_signoff_token=human_signoff_token,
        )
        return self._record_approval(proposal_id, governor_id=governor_id)

    def _record_approval(self, proposal_id: str, *, governor_id: str) -> RoadmapAmendmentProposal:
        """Persist approval mutation after PHASE6-HUMAN-0 signoff is recorded."""
        proposal = self._load(proposal_id)
        self._validate_proposal_payload(proposal)
        self._assert_approval_allowed(proposal_id, governor_id=governor_id)

        proposal.approvals.append(governor_id)
        proposal.phase_transitions.append(
            {
                "from": proposal.status,
                "to": "approval_recorded",
                "at": self.provider.iso_now(),
                "actor": governor_id,
            }
        )

        if len(proposal.approvals) >= self.required_approvals:
            proposal.status = ProposalStatus.APPROVED
            proposal.phase_transitions.append(
                {
                    "from": ProposalStatus.PENDING,
                    "to": ProposalStatus.APPROVED,
                    "at": self.provider.iso_now(),
                    "actor": governor_id,
                }
            )
            journal.write_entry(
                agent_id=governor_id,
                action="roadmap_amendment_approved",
                payload={
                    "proposal_id": proposal_id,
                    "approvals": proposal.approvals,
                    "lineage_chain_hash": proposal.lineage_chain_hash[:16],
                },
            )

        self._persist(proposal)
        return proposal

    def reject(self, proposal_id: str, *, governor_id: str, reason: str) -> RoadmapAmendmentProposal:
        """Permanently reject a proposal. Terminal state."""
        proposal = self._load(proposal_id)
        self._assert_mutable(proposal)

        proposal.status = ProposalStatus.REJECTED
        proposal.rejections.append(governor_id)
        proposal.phase_transitions.append(
            {
                "from": ProposalStatus.PENDING,
                "to": ProposalStatus.REJECTED,
                "at": self.provider.iso_now(),
                "actor": governor_id,
                "reason": reason,
            }
        )
        self._persist(proposal)

        journal.write_entry(
            agent_id=governor_id,
            action="roadmap_amendment_rejected",
            payload={"proposal_id": proposal_id, "reason": reason},
        )
        return proposal

    def list_pending(self) -> list[RoadmapAmendmentProposal]:
        """Return all proposals in PENDING status, ordered by timestamp."""
        proposals = [self._load_file(f) for f in self.proposals_dir.glob("*.json")]
        return sorted(
            [p for p in proposals if p.status == ProposalStatus.PENDING],
            key=lambda p: p.timestamp,
        )

    def verify_replay(self, proposal_id: str) -> bool:
        """
        Determinism gate: recompute lineage_chain_hash from persisted fields
        and compare to stored value. Returns True iff hashes match.

        Raises DeterminismViolation on divergence (mirrors pipeline behaviour).
        """
        proposal = self._load(proposal_id)
        recomputed = _lineage_hash(proposal.prior_roadmap_hash, proposal.content_hash())
        if recomputed != proposal.lineage_chain_hash:
            journal.write_entry(
                agent_id="RoadmapAmendmentEngine",
                action="roadmap_amendment_determinism_divergence",
                payload={
                    "proposal_id": proposal_id,
                    "stored_hash": proposal.lineage_chain_hash[:16],
                    "recomputed_hash": recomputed[:16],
                },
            )
            raise DeterminismViolation(
                f"Roadmap amendment replay diverged for '{proposal_id}': "
                f"stored={proposal.lineage_chain_hash[:16]} "
                f"recomputed={recomputed[:16]}"
            )
        return True

    def execute_amendment(
        self,
        proposal_id: str,
        *,
        governor_id: str,
        human_signoff_token: str | None,
    ) -> RoadmapAmendmentProposal:
        """
        Execute governed amendment approval flow with fail-closed checks.

        Preconditions:
          - proposal payload schema is valid (round-trip parse)
          - authority_level remains immutable at governor-review
          - INVARIANT PHASE6-HUMAN-0 signoff token is present
          - deterministic replay verifies before any approval mutation
        """
        proposal = self._load(proposal_id)
        self._validate_proposal_payload(proposal)
        self._assert_human_signoff_token(
            proposal_id,
            governor_id=governor_id,
            human_signoff_token=human_signoff_token,
        )
        self.verify_replay(proposal_id)
        self._assert_approval_allowed(proposal_id, governor_id=governor_id)
        self._record_human_signoff(
            proposal_id,
            governor_id=governor_id,
            human_signoff_token=human_signoff_token,
        )
        return self._record_approval(proposal_id, governor_id=governor_id)

    # ── Internal helpers ───────────────────────────────────────────────────

    def _assert_approval_allowed(self, proposal_id: str, *, governor_id: str) -> None:
        proposal = self._load(proposal_id)
        self._validate_proposal_payload(proposal)
        self._assert_mutable(proposal)
        if governor_id in proposal.approvals:
            raise GovernanceViolation(
                f"Governor '{governor_id}' already approved '{proposal_id}'."
            )

    def _assert_human_signoff_token(
        self,
        proposal_id: str,
        *,
        governor_id: str,
        human_signoff_token: str | None,
    ) -> str:
        token = str(human_signoff_token or "").strip()
        if not token:
            journal.write_entry(
                agent_id=governor_id,
                action="roadmap_amendment_rejected",
                payload={"proposal_id": proposal_id, "reason": "PHASE6-HUMAN-0-signoff-missing"},
            )
            raise GovernanceViolation("INVARIANT PHASE6-HUMAN-0 violation: missing human_signoff_token.")
        return token

    def _record_human_signoff(
        self,
        proposal_id: str,
        *,
        governor_id: str,
        human_signoff_token: str | None,
    ) -> None:
        token = self._assert_human_signoff_token(
            proposal_id,
            governor_id=governor_id,
            human_signoff_token=human_signoff_token,
        )
        journal.write_entry(
            agent_id=governor_id,
            action="roadmap_amendment_human_signoff",
            payload={
                "proposal_id": proposal_id,
                "governor_id": governor_id,
                "signoff_timestamp": self.provider.iso_now(),
                "human_signoff_token": token,
            },
        )

    def _validate_rationale(self, rationale: str) -> None:
        words = len(rationale.split())
        if words < _MIN_RATIONALE_WORDS:
            raise GovernanceViolation(
                f"Rationale must contain ≥{_MIN_RATIONALE_WORDS} words; got {words}."
            )

    def _assert_mutable(self, proposal: RoadmapAmendmentProposal) -> None:
        if proposal.status in (ProposalStatus.APPROVED, ProposalStatus.REJECTED):
            raise GovernanceViolation(
                f"Proposal '{proposal.proposal_id}' is terminal (status={proposal.status})."
            )

    def _persist(self, proposal: RoadmapAmendmentProposal) -> None:
        path = self.proposals_dir / f"{proposal.proposal_id}.json"
        path.write_text(proposal.to_json(), encoding="utf-8")

    def _load(self, proposal_id: str) -> RoadmapAmendmentProposal:
        path = self.proposals_dir / f"{proposal_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"No proposal found: {proposal_id}")
        return self._load_file(path)

    def _load_file(self, path: Path) -> RoadmapAmendmentProposal:
        return RoadmapAmendmentProposal.from_json(path.read_text("utf-8"))

    def _validate_proposal_payload(self, proposal: RoadmapAmendmentProposal) -> None:
        try:
            RoadmapAmendmentProposal.from_json(proposal.to_json())
        except Exception as exc:
            raise GovernanceViolation(f"Proposal payload schema validation failed: {exc}") from exc
        if proposal.authority_level != _AUTHORITY_LEVEL:
            raise GovernanceViolation(
                "INVARIANT PHASE6-AUTH-0 violation: authority_level mutation detected."
            )
