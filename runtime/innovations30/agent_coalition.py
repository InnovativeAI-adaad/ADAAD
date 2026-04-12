# SPDX-License-Identifier: Apache-2.0
"""Innovation #39 — Agent Coalition Formation (ACF).

When a mutation is classified as HIGH-COMPLEXITY, agents automatically
form a temporary coalition to evaluate it jointly.  Each coalition member
commits a stake proportional to its declared confidence.  On resolution
the stake pool is distributed proportionally to members whose verdicts
matched the final outcome.  Members whose verdicts diverged from the
outcome are penalised.  The coalition dissolves deterministically after
resolution — no coalition survives across epochs.

Builds on:
  INNOV-14 CJS — constitutional jury deliberation model
  INNOV-15 ARS — reputation staking ledger
  INNOV-16 ERS — emergent role specialisation

Constitutional invariants enforced by this module
──────────────────────────────────────────────────
ACF-0           A HIGH-COMPLEXITY mutation MUST NOT advance to
                GovernanceGate without a resolved CoalitionRecord.
                Unresolved coalitions block epoch advancement.
                Violation raises UnresolvedCoalitionError.

ACF-FORM-0      A coalition MUST have between ACF_MIN_MEMBERS (2)
                and ACF_MAX_MEMBERS (7) members at formation time.
                Under- or over-subscription raises CoalitionSizeError.

ACF-STAKE-0     Every coalition member MUST commit a positive stake
                before the coalition is sealed.  Zero-stake membership
                raises StakeError.

ACF-RESOLVE-0   Coalition resolution MUST be triggered exactly once.
                Re-resolution raises AlreadyResolvedError.

ACF-DISSOLVE-0  A resolved coalition MUST be marked dissolved before
                the next epoch begins.  An undissolved resolved coalition
                raises EpochBoundaryError.

ACF-DETERM-0    coalition_digest MUST be a pure function of
                (coalition_id, member_ids, stakes, outcome).
                No wall-clock reads, no random state.

ACF-CHAIN-0     Each CoalitionRecord carries prev_digest linking it
                to the preceding record — append-only ledger.
                A broken chain raises ChainError.

ACF-SHARE-0     Stake redistribution MUST be calculated with exact
                integer arithmetic (no floating-point rounding).
                Total distributed shares MUST equal total_stake_pool.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any

# ────────────────────────────────────────────────────────────────────────────
# Constants
# ────────────────────────────────────────────────────────────────────────────

ACF_MIN_MEMBERS: int = 2
ACF_MAX_MEMBERS: int = 7
ACF_COMPLEXITY_THRESHOLD: str = "HIGH"   # complexity class triggering coalition

# ────────────────────────────────────────────────────────────────────────────
# Exceptions
# ────────────────────────────────────────────────────────────────────────────

class UnresolvedCoalitionError(RuntimeError):
    """ACF-0 — epoch advance blocked by unresolved coalition."""

class CoalitionSizeError(RuntimeError):
    """ACF-FORM-0 — member count outside [ACF_MIN_MEMBERS, ACF_MAX_MEMBERS]."""

class StakeError(RuntimeError):
    """ACF-STAKE-0 — zero or negative stake committed."""

class AlreadyResolvedError(RuntimeError):
    """ACF-RESOLVE-0 — coalition resolved more than once."""

class EpochBoundaryError(RuntimeError):
    """ACF-DISSOLVE-0 — resolved coalition not dissolved before next epoch."""

class DeterminismError(RuntimeError):
    """ACF-DETERM-0 — coalition_digest is non-deterministic."""

class ChainError(RuntimeError):
    """ACF-CHAIN-0 — ledger hash-chain broken."""

class ShareArithmeticError(RuntimeError):
    """ACF-SHARE-0 — stake redistribution does not balance."""

# ────────────────────────────────────────────────────────────────────────────
# Enumerations
# ────────────────────────────────────────────────────────────────────────────

class CoalitionOutcome(str, Enum):
    APPROVED  = "APPROVED"
    REJECTED  = "REJECTED"
    ESCALATED = "ESCALATED"  # majority inconclusive — routed to HUMAN-0

class MemberVerdict(str, Enum):
    APPROVE  = "APPROVE"
    REJECT   = "REJECT"
    ABSTAIN  = "ABSTAIN"

class CoalitionStatus(str, Enum):
    FORMING    = "FORMING"
    SEALED     = "SEALED"
    RESOLVED   = "RESOLVED"
    DISSOLVED  = "DISSOLVED"

# ────────────────────────────────────────────────────────────────────────────
# Data structures
# ────────────────────────────────────────────────────────────────────────────

@dataclass
class CoalitionMember:
    agent_id: str
    role: str          # from ERS — e.g. "Architect", "Dream", "Beast"
    stake: int         # positive integer units (ACF-STAKE-0)
    verdict: str = ""  # MemberVerdict value; set at resolution time
    share_returned: int = 0   # stake units returned after resolution

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class StakeDistribution:
    """Result of ACF-SHARE-0 exact integer redistribution."""
    total_pool: int
    distributions: dict[str, int]   # agent_id → units returned
    remainder: int                   # any indivisible remainder → treasury

    def validate(self) -> None:
        distributed = sum(self.distributions.values()) + self.remainder
        if distributed != self.total_pool:
            raise ShareArithmeticError(
                f"ACF-SHARE-0: distributed {distributed} ≠ pool {self.total_pool}"
            )


@dataclass
class CoalitionRecord:
    """Append-only ledger entry for one coalition lifecycle (ACF-CHAIN-0)."""
    record_id: str
    coalition_id: str
    mutation_id: str
    complexity_class: str
    member_count: int
    total_stake: int
    outcome: str = ""
    status: str = CoalitionStatus.FORMING.value
    coalition_digest: str = ""
    prev_digest: str = "genesis"
    record_digest: str = ""
    members: list[dict] = field(default_factory=list)
    distributions: dict[str, int] = field(default_factory=dict)

    def compute_coalition_digest(self, member_ids: list[str], stakes: list[int]) -> str:
        """ACF-DETERM-0: pure function of (coalition_id, member_ids, stakes, outcome)."""
        payload = json.dumps(
            {
                "coalition_id": self.coalition_id,
                "member_ids": sorted(member_ids),
                "stakes": sorted(stakes),
                "outcome": self.outcome,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def compute_record_digest(self, secret: bytes) -> str:
        payload = json.dumps(
            {
                "record_id": self.record_id,
                "coalition_id": self.coalition_id,
                "mutation_id": self.mutation_id,
                "outcome": self.outcome,
                "status": self.status,
                "coalition_digest": self.coalition_digest,
                "prev_digest": self.prev_digest,
            },
            sort_keys=True,
        )
        return hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()[:24]


# ────────────────────────────────────────────────────────────────────────────
# Coalition instance — manages one mutation's coalition lifecycle
# ────────────────────────────────────────────────────────────────────────────

class Coalition:
    """Manages the lifecycle of a single agent coalition for one mutation.

    Lifecycle:
      1. __init__     → FORMING
      2. add_member() → validates stake (ACF-STAKE-0)
      3. seal()       → validates member count (ACF-FORM-0) → SEALED
      4. resolve()    → computes outcome + distributions → RESOLVED
      5. dissolve()   → marks dissolved (ACF-DISSOLVE-0) → DISSOLVED
    """

    def __init__(self, coalition_id: str, mutation_id: str, complexity_class: str) -> None:
        self.coalition_id = coalition_id
        self.mutation_id = mutation_id
        self.complexity_class = complexity_class
        self.status = CoalitionStatus.FORMING
        self._members: list[CoalitionMember] = []

    # ── Formation ────────────────────────────────────────────────────────

    def add_member(self, agent_id: str, role: str, stake: int) -> None:
        """Add an agent to the coalition (ACF-STAKE-0)."""
        if self.status != CoalitionStatus.FORMING:
            raise RuntimeError(f"Cannot add member to coalition in status {self.status}")
        if stake <= 0:
            raise StakeError(
                f"ACF-STAKE-0: agent {agent_id!r} committed zero/negative stake {stake}."
            )
        self._members.append(CoalitionMember(agent_id=agent_id, role=role, stake=stake))

    def seal(self) -> None:
        """Seal the coalition — validates member count (ACF-FORM-0)."""
        n = len(self._members)
        if n < ACF_MIN_MEMBERS or n > ACF_MAX_MEMBERS:
            raise CoalitionSizeError(
                f"ACF-FORM-0: coalition has {n} members; "
                f"must be [{ACF_MIN_MEMBERS}, {ACF_MAX_MEMBERS}]."
            )
        self.status = CoalitionStatus.SEALED

    # ── Resolution ───────────────────────────────────────────────────────

    def resolve(self, verdicts: dict[str, str]) -> tuple[CoalitionOutcome, StakeDistribution]:
        """Apply verdicts, compute outcome, redistribute stake (ACF-RESOLVE-0, ACF-SHARE-0).

        Parameters
        ----------
        verdicts : dict[agent_id → MemberVerdict value]
        """
        if self.status == CoalitionStatus.RESOLVED:
            raise AlreadyResolvedError(
                f"ACF-RESOLVE-0: coalition {self.coalition_id} already resolved."
            )
        if self.status != CoalitionStatus.SEALED:
            raise RuntimeError(
                f"Coalition must be SEALED before resolve(); status={self.status}"
            )

        # Record verdicts on members
        for m in self._members:
            m.verdict = verdicts.get(m.agent_id, MemberVerdict.ABSTAIN.value)

        # Majority vote — abstains don't count
        votes = [m.verdict for m in self._members if m.verdict != MemberVerdict.ABSTAIN.value]
        approve_count = votes.count(MemberVerdict.APPROVE.value)
        reject_count  = votes.count(MemberVerdict.REJECT.value)

        if approve_count > reject_count:
            outcome = CoalitionOutcome.APPROVED
            winning_verdict = MemberVerdict.APPROVE.value
        elif reject_count > approve_count:
            outcome = CoalitionOutcome.REJECTED
            winning_verdict = MemberVerdict.REJECT.value
        else:
            outcome = CoalitionOutcome.ESCALATED
            winning_verdict = None  # tie → HUMAN-0

        # ACF-SHARE-0: integer stake redistribution
        dist = self._redistribute_stake(winning_verdict)
        dist.validate()   # raises ShareArithmeticError if unbalanced

        # Apply share_returned to members
        for m in self._members:
            m.share_returned = dist.distributions.get(m.agent_id, 0)

        self.status = CoalitionStatus.RESOLVED
        return outcome, dist

    def dissolve(self) -> None:
        """Mark coalition dissolved (ACF-DISSOLVE-0)."""
        if self.status != CoalitionStatus.RESOLVED:
            raise EpochBoundaryError(
                f"ACF-DISSOLVE-0: cannot dissolve coalition in status {self.status}."
            )
        self.status = CoalitionStatus.DISSOLVED

    # ── Helpers ──────────────────────────────────────────────────────────

    def _redistribute_stake(self, winning_verdict: str | None) -> StakeDistribution:
        """ACF-SHARE-0: exact integer distribution — no floats."""
        total_pool = sum(m.stake for m in self._members)
        distributions: dict[str, int] = {}

        if winning_verdict is None:
            # Escalation: full stake returned to every member
            for m in self._members:
                distributions[m.agent_id] = m.stake
            return StakeDistribution(
                total_pool=total_pool,
                distributions=distributions,
                remainder=0,
            )

        winners = [m for m in self._members if m.verdict == winning_verdict]
        losers  = [m for m in self._members if m.verdict != winning_verdict
                   and m.verdict != MemberVerdict.ABSTAIN.value]

        # Winners recover their own stake
        for m in winners:
            distributions[m.agent_id] = m.stake

        # Losers forfeit their stake into bonus pool
        bonus_pool = sum(m.stake for m in losers)

        # Abstainers recover their stake (no bonus, no penalty)
        for m in self._members:
            if m.verdict == MemberVerdict.ABSTAIN.value:
                distributions[m.agent_id] = m.stake

        # Distribute bonus_pool to winners proportionally by stake (integer)
        winner_total_stake = sum(m.stake for m in winners)
        remainder = bonus_pool
        if winners and winner_total_stake > 0:
            for m in winners:
                bonus = (m.stake * bonus_pool) // winner_total_stake
                distributions[m.agent_id] = distributions.get(m.agent_id, 0) + bonus
                remainder -= bonus
            # Any indivisible remainder goes to treasury (not redistributed)

        return StakeDistribution(
            total_pool=total_pool,
            distributions=distributions,
            remainder=remainder,
        )

    # ── Properties ───────────────────────────────────────────────────────

    @property
    def members(self) -> list[CoalitionMember]:
        return list(self._members)

    @property
    def total_stake(self) -> int:
        return sum(m.stake for m in self._members)

    @property
    def member_count(self) -> int:
        return len(self._members)


# ────────────────────────────────────────────────────────────────────────────
# Coalition Engine — ledger, persistence, epoch gate
# ────────────────────────────────────────────────────────────────────────────

_LEDGER_DEFAULT = Path("artifacts/governance/acf_ledger.jsonl")


class CoalitionEngine:
    """Orchestrates coalition formation, resolution, and ledger management.

    Enforces ACF-0: epoch gate blocks if any SEALED (unresolved) coalition
    exists.  Enforces ACF-DISSOLVE-0: epoch gate blocks if any RESOLVED
    (undissolved) coalition exists.
    """

    def __init__(
        self,
        hmac_secret: bytes,
        ledger_path: Path = _LEDGER_DEFAULT,
    ) -> None:
        self._secret = hmac_secret
        self._ledger_path = ledger_path
        self._prev_digest = "genesis"
        self._record_counter = 0
        self._active: dict[str, Coalition] = {}  # coalition_id → Coalition
        self._records: list[CoalitionRecord] = []
        self._load_ledger()

    # ── Public API ───────────────────────────────────────────────────────

    def form_coalition(
        self,
        coalition_id: str,
        mutation_id: str,
        complexity_class: str,
        members: list[dict],  # [{"agent_id":, "role":, "stake":}, ...]
    ) -> Coalition:
        """Form and seal a coalition for a high-complexity mutation.

        Automatically calls add_member() and seal() — caller just provides
        the member list.  Persists a FORMING→SEALED ledger record.
        """
        coal = Coalition(coalition_id, mutation_id, complexity_class)
        for m in members:
            coal.add_member(m["agent_id"], m["role"], m["stake"])
        coal.seal()  # ACF-FORM-0 enforced here

        self._active[coalition_id] = coal
        rec = self._make_record(coal, CoalitionStatus.SEALED, outcome="")
        self._persist(rec)
        return coal

    def resolve_coalition(
        self,
        coalition_id: str,
        verdicts: dict[str, str],
    ) -> tuple[CoalitionOutcome, StakeDistribution]:
        """Resolve a sealed coalition and persist the outcome record."""
        coal = self._get_active(coalition_id)
        outcome, dist = coal.resolve(verdicts)  # ACF-RESOLVE-0 enforced
        rec = self._make_record(coal, CoalitionStatus.RESOLVED, outcome=outcome.value)
        self._persist(rec)
        return outcome, dist

    def dissolve_coalition(self, coalition_id: str) -> None:
        """Dissolve a resolved coalition (ACF-DISSOLVE-0)."""
        coal = self._get_active(coalition_id)
        coal.dissolve()
        rec = self._make_record(coal, CoalitionStatus.DISSOLVED, outcome="")
        self._persist(rec)
        del self._active[coalition_id]

    def assert_epoch_clear(self) -> None:
        """ACF-0 + ACF-DISSOLVE-0: block epoch advance if coalitions remain active."""
        unresolved = [
            cid for cid, c in self._active.items()
            if c.status in (CoalitionStatus.FORMING, CoalitionStatus.SEALED)
        ]
        if unresolved:
            raise UnresolvedCoalitionError(
                f"ACF-0: epoch advance blocked — unresolved coalitions: {unresolved}"
            )
        undissolved = [
            cid for cid, c in self._active.items()
            if c.status == CoalitionStatus.RESOLVED
        ]
        if undissolved:
            raise EpochBoundaryError(
                f"ACF-DISSOLVE-0: epoch advance blocked — undissolved coalitions: {undissolved}"
            )

    def verify_chain(self) -> bool:
        """Verify the append-only ledger chain (ACF-CHAIN-0)."""
        if not self._ledger_path.exists():
            return True
        prev = "genesis"
        for i, line in enumerate(self._ledger_path.read_text().splitlines()):
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("prev_digest") != prev:
                raise ChainError(
                    f"ACF-CHAIN-0: chain break at line {i}: "
                    f"expected {prev!r}, got {rec.get('prev_digest')!r}"
                )
            prev = rec.get("record_digest", "")
        return True

    def active_count(self) -> int:
        return len(self._active)

    def record_count(self) -> int:
        return self._record_counter

    # ── Helpers ──────────────────────────────────────────────────────────

    def _get_active(self, coalition_id: str) -> Coalition:
        if coalition_id not in self._active:
            raise KeyError(f"Coalition {coalition_id!r} not found in active set.")
        return self._active[coalition_id]

    def _make_record(
        self,
        coal: Coalition,
        status: CoalitionStatus,
        outcome: str,
    ) -> CoalitionRecord:
        self._record_counter += 1
        member_ids = [m.agent_id for m in coal.members]
        stakes     = [m.stake for m in coal.members]

        rec = CoalitionRecord(
            record_id=f"ACF-REC-{self._record_counter:06d}",
            coalition_id=coal.coalition_id,
            mutation_id=coal.mutation_id,
            complexity_class=coal.complexity_class,
            member_count=coal.member_count,
            total_stake=coal.total_stake,
            outcome=outcome,
            status=status.value,
            prev_digest=self._prev_digest,
            members=[m.to_dict() for m in coal.members],
            distributions={m.agent_id: m.share_returned for m in coal.members},
        )
        # ACF-DETERM-0
        rec.coalition_digest = rec.compute_coalition_digest(member_ids, stakes)
        rec.record_digest    = rec.compute_record_digest(self._secret)
        self._prev_digest    = rec.record_digest
        return rec

    def _persist(self, rec: CoalitionRecord) -> None:
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self._ledger_path.open("a") as fh:
            fh.write(json.dumps(asdict(rec), sort_keys=True) + "\n")
        self._records.append(rec)

    def _load_ledger(self) -> None:
        """Replay ledger to restore record_counter and prev_digest."""
        if not self._ledger_path.exists():
            return
        for line in self._ledger_path.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            self._prev_digest = rec.get("record_digest", self._prev_digest)
            self._record_counter += 1


# ────────────────────────────────────────────────────────────────────────────
# Stateless helper — complexity gate
# ────────────────────────────────────────────────────────────────────────────

def requires_coalition(complexity_class: str) -> bool:
    """ACF-0: return True if the complexity class mandates coalition formation."""
    return complexity_class.upper() == ACF_COMPLEXITY_THRESHOLD

    def _append_event(self, event) -> None:
        """CED-INV-AUDIT: append-only JSONL event record; advance HMAC chain head."""
        import json, dataclasses
        ledger = getattr(self, 'ledger_path', None) or getattr(self, 'state_path', None)
        if ledger is None:
            return
        from pathlib import Path
        ledger = Path(ledger)
        ledger.parent.mkdir(parents=True, exist_ok=True)
        row = json.dumps(dataclasses.asdict(event) if hasattr(event, '__dataclass_fields__') else event, sort_keys=True)
        with ledger.open("a") as f:
            f.write(row + "\n")

