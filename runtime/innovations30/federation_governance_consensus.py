# SPDX-License-Identifier: Apache-2.0
"""Innovation #34 — Federation Governance Consensus (FGCON).

Formal consensus protocol for federation-wide constitutional amendments.
Requires a strict majority quorum of registered federated ADAAD instances
to ratify any federation-level invariant change.  No single instance can
amend federation-level invariants unilaterally.

Constitutional invariants enforced by this module
  FGCON-0           Any federation-level constitutional amendment MUST collect
                    a strict majority quorum before ratification.
                    Fail-closed: FGCONQuorumError on insufficient votes.
  FGCON-DETERM-0    Proposal IDs derived solely from epoch_id + instance_id +
                    amendment_id via SHA-256; no datetime.now(), no random.
  FGCON-PERSIST-0   Every vote record MUST be flushed to the append-only JSONL
                    ledger before the vote() method returns.
  FGCON-CHAIN-0     Each ledger record is chain-linked to its predecessor via
                    HMAC-SHA256 over (record_id + prev_digest + proposal_id).
  FGCON-GATE-0      Federation amendments require human0_acknowledged=True;
                    fail-closed otherwise.
  FGCON-UNILATERAL-0 A single instance_id MAY NOT cast more than one ratifying
                    vote per proposal, regardless of how many times vote() is
                    called with the same instance_id.
  FGCON-QUORUM-0    Quorum threshold = floor(N / 2) + 1 where N is the count
                    of registered federation members at proposal creation time.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import hashlib
import hmac

# Hardening scaffold — injected by fix/senior-deep-dive-hardening
FEGOCO_INV_CHAIN: str = "FEGOCO-INV-CHAIN"


class FederationGovernanceConsensusViolation(RuntimeError):
    """Raised when a Federation Governance Consensus constitutional invariant is breached."""



# ── module-level constants ─────────────────────────────────────────────────
_FGCON_VERSION: str = "1.0"
_FGCON_LEDGER: str = "data/fgcon_consensus_ledger.jsonl"
_FGCON_HMAC_KEY: str = "fgcon-chain-key-v1"  # environment-injectable in production


# ── exceptions ────────────────────────────────────────────────────────────

class FGCONQuorumError(Exception):
    """FGCON-0 / FGCON-QUORUM-0: amendment ratified without reaching quorum."""


class FGCONChainError(Exception):
    """FGCON-CHAIN-0: ledger chain integrity violation detected."""


class FGCONGateError(Exception):
    """FGCON-GATE-0: federation amendment attempted without HUMAN-0 acknowledgement."""


class FGCONPersistError(Exception):
    """FGCON-PERSIST-0: ledger write failed before method return."""


class FGCONUnilateralError(Exception):
    """FGCON-UNILATERAL-0: single instance cast duplicate ratifying vote."""


class FGCONDeterminismError(Exception):
    """FGCON-DETERM-0: non-deterministic ID generation detected."""


# ── guard helper ──────────────────────────────────────────────────────────

def fgcon_guard(condition: bool, invariant: str, msg: str) -> None:
    """Fail-closed enforcement helper for all FGCON Hard-class invariants."""
    if not condition:
        raise FGCONQuorumError(f"[{invariant}] {msg}")


# ── data structures ───────────────────────────────────────────────────────

@dataclass
class FederationMember:
    """A registered member of the ADAAD federation.

    instance_id  — unique identifier for this ADAAD deployment
    weight       — voting weight (default 1; constitutional equality)
    """
    instance_id: str
    weight: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {"instance_id": self.instance_id, "weight": self.weight}


@dataclass
class AmendmentProposal:
    """A federation-level constitutional amendment awaiting consensus.

    proposal_id    — FGCON-DETERM-0: sha256(epoch_id + instance_id + amendment_id)
    quorum_required — FGCON-QUORUM-0: floor(N/2) + 1 at creation time
    status         — 'pending' | 'ratified' | 'rejected'
    """
    proposal_id: str
    epoch_id: str
    proposing_instance: str
    amendment_id: str
    amendment_text: str
    federation_size: int
    quorum_required: int
    status: str = "pending"
    votes_for: list[str] = field(default_factory=list)
    votes_against: list[str] = field(default_factory=list)
    human0_acknowledged: bool = False

    @classmethod
    def create(
        cls,
        epoch_id: str,
        proposing_instance: str,
        amendment_id: str,
        amendment_text: str,
        federation_size: int,
        human0_acknowledged: bool = False,
    ) -> "AmendmentProposal":
        """FGCON-DETERM-0: deterministic proposal_id, no datetime/random."""
        id_src = f"{epoch_id}:{proposing_instance}:{amendment_id}"
        proposal_id = "fgcon:" + hashlib.sha256(id_src.encode()).hexdigest()[:16]
        quorum_required = (federation_size // 2) + 1
        return cls(
            proposal_id=proposal_id,
            epoch_id=epoch_id,
            proposing_instance=proposing_instance,
            amendment_id=amendment_id,
            amendment_text=amendment_text,
            federation_size=federation_size,
            quorum_required=quorum_required,
            human0_acknowledged=human0_acknowledged,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "epoch_id": self.epoch_id,
            "proposing_instance": self.proposing_instance,
            "amendment_id": self.amendment_id,
            "amendment_text": self.amendment_text,
            "federation_size": self.federation_size,
            "quorum_required": self.quorum_required,
            "status": self.status,
            "votes_for": list(self.votes_for),
            "votes_against": list(self.votes_against),
            "human0_acknowledged": self.human0_acknowledged,
        }


@dataclass
class VoteRecord:
    """A single ledger-persisted vote event.

    record_id   — sha256(proposal_id + voter_instance_id + vote_value)
    prev_digest — FGCON-CHAIN-0: HMAC of previous record
    chain_link  — HMAC-SHA256 over (record_id + prev_digest + proposal_id)
    """
    record_id: str
    proposal_id: str
    voter_instance_id: str
    vote_value: str          # 'for' | 'against'
    votes_for_count: int
    votes_against_count: int
    quorum_reached: bool
    prev_digest: str
    chain_link: str
    fgcon_version: str = _FGCON_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "proposal_id": self.proposal_id,
            "voter_instance_id": self.voter_instance_id,
            "vote_value": self.vote_value,
            "votes_for_count": self.votes_for_count,
            "votes_against_count": self.votes_against_count,
            "quorum_reached": self.quorum_reached,
            "prev_digest": self.prev_digest,
            "chain_link": self.chain_link,
            "fgcon_version": self.fgcon_version,
        }


# ── core engine ───────────────────────────────────────────────────────────

class FederationGovernanceConsensus:
    """INNOV-34 consensus engine.

    Manages federation membership, proposal lifecycle, voting, quorum
    enforcement, and the append-only HMAC-chain-linked ledger.
    """

    def __init__(
        self,
        instance_id: str,
        ledger_path: Path | None = None,
        hmac_key: str = _FGCON_HMAC_KEY,
    ) -> None:
        self._instance_id = instance_id
        self._ledger_path = ledger_path or Path(_FGCON_LEDGER)
        self._hmac_key = hmac_key.encode()
        self._members: dict[str, FederationMember] = {}
        self._proposals: dict[str, AmendmentProposal] = {}
        self._prev_digest: str = self._genesis_digest()

    # ── internal helpers ──────────────────────────────────────────────────

    def _genesis_digest(self) -> str:
        """Deterministic genesis anchor for the chain."""
        return "sha256:" + hashlib.sha256(b"fgcon-genesis-v1").hexdigest()

    def _record_id(self, proposal_id: str, voter_instance_id: str, vote_value: str) -> str:
        """FGCON-DETERM-0: deterministic record_id."""
        src = f"{proposal_id}:{voter_instance_id}:{vote_value}"
        return "fgcon-vote:" + hashlib.sha256(src.encode()).hexdigest()[:16]

    def _chain_link(self, record_id: str, prev_digest: str, proposal_id: str) -> str:
        """FGCON-CHAIN-0: HMAC-SHA256 chain link."""
        msg = f"{record_id}:{prev_digest}:{proposal_id}".encode()
        return "hmac-sha256:" + hmac.new(self._hmac_key, msg, hashlib.sha256).hexdigest()

    def _persist(self, record: VoteRecord) -> None:
        """FGCON-PERSIST-0: flush to ledger before returning."""
        try:
            self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with self._ledger_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")
                fh.flush()
        except OSError as exc:
            raise FGCONPersistError(
                f"[FGCON-PERSIST-0] ledger write failed: {exc}"
            ) from exc

    def _verify_chain(self) -> bool:
        """FGCON-CHAIN-0: verify ledger chain integrity. Returns True if intact."""
        if not self._ledger_path.exists():
            return True
        prev = self._genesis_digest()
        for line in self._ledger_path.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            expected = self._chain_link(
                rec["record_id"], prev, rec["proposal_id"]
            )
            if rec["chain_link"] != expected:
                return False
            prev = rec["chain_link"]
        return True

    # ── public API ────────────────────────────────────────────────────────

    def register_member(self, member: FederationMember) -> None:
        """Register a federation member. Idempotent on same instance_id."""
        self._members[member.instance_id] = member

    def federation_size(self) -> int:
        """Current count of registered federation members."""
        return len(self._members)

    def quorum_for_size(self, size: int) -> int:
        """FGCON-QUORUM-0: floor(N/2) + 1."""
        return (size // 2) + 1

    def propose_amendment(
        self,
        epoch_id: str,
        amendment_id: str,
        amendment_text: str,
        human0_acknowledged: bool = False,
    ) -> AmendmentProposal:
        """Create a new federation-level amendment proposal.

        FGCON-GATE-0: human0_acknowledged must be True for the proposal to
        be eligible for ratification.
        """
        proposal = AmendmentProposal.create(
            epoch_id=epoch_id,
            proposing_instance=self._instance_id,
            amendment_id=amendment_id,
            amendment_text=amendment_text,
            federation_size=self.federation_size(),
            human0_acknowledged=human0_acknowledged,
        )
        self._proposals[proposal.proposal_id] = proposal
        return proposal

    def vote(
        self,
        proposal_id: str,
        voter_instance_id: str,
        vote_value: str,
    ) -> VoteRecord:
        """Cast a vote on a pending proposal.

        FGCON-UNILATERAL-0: duplicate votes from the same instance are
        rejected (fail-closed).
        FGCON-PERSIST-0:     ledger write occurs before this method returns.
        FGCON-CHAIN-0:       each record is HMAC-chain-linked to its predecessor.
        """
        if proposal_id not in self._proposals:
            raise KeyError(f"Unknown proposal_id: {proposal_id!r}")

        proposal = self._proposals[proposal_id]

        if proposal.status != "pending":
            raise FGCONQuorumError(
                f"[FGCON-0] Proposal {proposal_id!r} is already {proposal.status!r};"
                " no further votes accepted."
            )

        # FGCON-UNILATERAL-0
        if voter_instance_id in proposal.votes_for or voter_instance_id in proposal.votes_against:
            raise FGCONUnilateralError(
                f"[FGCON-UNILATERAL-0] Instance {voter_instance_id!r} has already voted"
                f" on proposal {proposal_id!r}."
            )

        if vote_value not in ("for", "against"):
            raise ValueError(f"vote_value must be 'for' or 'against', got {vote_value!r}")

        # Record vote
        if vote_value == "for":
            proposal.votes_for.append(voter_instance_id)
        else:
            proposal.votes_against.append(voter_instance_id)

        quorum_reached = len(proposal.votes_for) >= proposal.quorum_required

        # Build ledger record
        record_id = self._record_id(proposal_id, voter_instance_id, vote_value)
        chain_link = self._chain_link(record_id, self._prev_digest, proposal_id)

        record = VoteRecord(
            record_id=record_id,
            proposal_id=proposal_id,
            voter_instance_id=voter_instance_id,
            vote_value=vote_value,
            votes_for_count=len(proposal.votes_for),
            votes_against_count=len(proposal.votes_against),
            quorum_reached=quorum_reached,
            prev_digest=self._prev_digest,
            chain_link=chain_link,
        )

        # FGCON-PERSIST-0: flush before returning
        self._persist(record)
        self._prev_digest = chain_link

        return record

    def ratify(self, proposal_id: str) -> AmendmentProposal:
        """Attempt to ratify a proposal.

        FGCON-0: quorum must be met.
        FGCON-GATE-0: human0_acknowledged must be True.
        """
        if proposal_id not in self._proposals:
            raise KeyError(f"Unknown proposal_id: {proposal_id!r}")

        proposal = self._proposals[proposal_id]

        # FGCON-GATE-0
        if not proposal.human0_acknowledged:
            raise FGCONGateError(
                f"[FGCON-GATE-0] Proposal {proposal_id!r} requires human0_acknowledged=True"
                " before ratification."
            )

        # FGCON-0 / FGCON-QUORUM-0
        if len(proposal.votes_for) < proposal.quorum_required:
            raise FGCONQuorumError(
                f"[FGCON-0] Quorum not met for proposal {proposal_id!r}: "
                f"{len(proposal.votes_for)} / {proposal.quorum_required} required."
            )

        proposal.status = "ratified"
        return proposal

    def reject(self, proposal_id: str) -> AmendmentProposal:
        """Mark a proposal as rejected (governance outcome, not a failure)."""
        if proposal_id not in self._proposals:
            raise KeyError(f"Unknown proposal_id: {proposal_id!r}")
        self._proposals[proposal_id].status = "rejected"
        return self._proposals[proposal_id]

    def get_proposal(self, proposal_id: str) -> AmendmentProposal | None:
        """Retrieve a proposal by ID, or None if not found."""
        return self._proposals.get(proposal_id)

    def verify_chain_integrity(self) -> bool:
        """FGCON-CHAIN-0: verify the full ledger chain. Returns True if intact."""
        return self._verify_chain()

    def export_state(self) -> dict[str, Any]:
        """Export the full consensus state for audit / replication."""
        return {
            "fgcon_version": _FGCON_VERSION,
            "instance_id": self._instance_id,
            "federation_size": self.federation_size(),
            "members": [m.to_dict() for m in self._members.values()],
            "proposals": [p.to_dict() for p in self._proposals.values()],
        }
