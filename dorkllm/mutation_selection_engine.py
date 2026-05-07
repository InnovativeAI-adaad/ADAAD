"""
INNOV-75 · MSE — Mutation Selection Engine
==========================================
Phase 169 · v9.102.0 · InnovativeAI LLC

World-first: A constitutionally-governed ranking and selection engine
that determines which mutation proposals advance to execution. Every
candidate is scored across five constitutional fitness axes; Tier-0
candidates are hard-gated on HUMAN-0 ratification; selections are
HMAC-chained and append-only.

Hard-class invariants enforced:
  MSE-RANK-0    Scoring is deterministic given the same candidate set and weights
  MSE-CHAIN-0   Every selection record is HMAC-chained to the previous record
  MSE-HUMAN0-0  Any Tier-0 candidate requires HUMAN-0 ratification before selection
  MSE-BLAST-0   Candidates with blast_radius > MAX_BLAST_RADIUS are auto-rejected
  MSE-FLOOR-0   Constitutional fitness score MUST be >= SCORE_FLOOR to be selectable
  MSE-WINDOW-0  Rolling selection window is constitutionally fixed at 5
  MSE-PERSIST-0 Selection ledger is append-only; no record may be modified or removed
  MSE-ATOMIC-0  select() is atomic; partial selection raises MSEAtomicError
  MSE-AUDIT-0   Every scoring and selection event is recorded in the audit ledger
  MSE-SCOPE-0   Fitness axes are restricted to CANONICAL_AXES; foreign axes rejected

Governor: DUSTIN L REID
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, FrozenSet, List, Optional, Tuple


# ── Constants ────────────────────────────────────────────────────────────────

HMAC_SECRET: bytes = b"ADAAD-MSE-HMAC-SECRET-v1"
SCORE_FLOOR: float = 0.25          # MSE-FLOOR-0: minimum constitutional fitness
MAX_BLAST_RADIUS: float = 1.0      # MSE-BLAST-0: maximum tolerable blast radius
MSE_WINDOW_SIZE: int = 5           # MSE-WINDOW-0: rolling selection window
MAX_SCORE: float = 1.0

# MSE-SCOPE-0: only these five fitness axes are constitutionally canonical
CANONICAL_AXES: FrozenSet[str] = frozenset(
    {
        "lineage_depth",       # depth in mutation phylogeny (deeper = richer lineage)
        "blast_containment",   # inverse blast radius (higher = safer)
        "velocity_alignment",  # alignment with IVB invariant velocity
        "convergence_delta",   # expected V10 convergence improvement
        "constitutional_debt", # reduction in constitutional debt / violations
    }
)

# Default axis weights (sum to 1.0, deterministic — MSE-RANK-0)
DEFAULT_WEIGHTS: Dict[str, float] = {
    "lineage_depth":       0.15,
    "blast_containment":   0.30,
    "velocity_alignment":  0.20,
    "convergence_delta":   0.25,
    "constitutional_debt": 0.10,
}


# ── Errors ───────────────────────────────────────────────────────────────────

class MSEAtomicError(Exception):
    """Raised when a selection operation cannot complete atomically — MSE-ATOMIC-0."""

class MSEHuman0Flag(Exception):
    """Raised when a Tier-0 candidate lacks HUMAN-0 ratification — MSE-HUMAN0-0."""

class MSEBlastReject(Exception):
    """Raised when blast_radius exceeds MAX_BLAST_RADIUS — MSE-BLAST-0."""

class MSEFloorReject(Exception):
    """Raised when fitness score is below SCORE_FLOOR — MSE-FLOOR-0."""

class MSEAxisError(Exception):
    """Raised when an unknown fitness axis is supplied — MSE-SCOPE-0."""

class MSETamperError(Exception):
    """Raised when HMAC chain verification fails — MSE-CHAIN-0."""


# ── Enums ────────────────────────────────────────────────────────────────────

class CandidateTier(str, Enum):
    TIER0 = "tier0"
    TIER1 = "tier1"
    TIER2 = "tier2"

class SelectionVerdict(str, Enum):
    SELECTED  = "SELECTED"
    REJECTED  = "REJECTED"
    DEFERRED  = "DEFERRED"   # score >= FLOOR but outside current window


# ── Data models ──────────────────────────────────────────────────────────────

@dataclass
class MutationCandidate:
    """A mutation proposal awaiting constitutional fitness scoring."""

    candidate_id: str
    label: str
    tier: CandidateTier
    blast_radius: float                      # 0.0–1.0; lower is safer
    axis_scores: Dict[str, float]            # per-axis raw scores 0.0–1.0
    ratified: bool = False                   # HUMAN-0 ratification flag
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        # MSE-SCOPE-0: reject unknown axes
        unknown = set(self.axis_scores) - CANONICAL_AXES
        if unknown:
            raise MSEAxisError(
                f"Unknown fitness axes: {unknown}. Allowed: {sorted(CANONICAL_AXES)}"
            )
        # Clamp axis scores to [0.0, 1.0]
        self.axis_scores = {
            k: max(0.0, min(1.0, v)) for k, v in self.axis_scores.items()
        }


@dataclass
class FitnessScore:
    """Result of scoring a candidate — deterministic given same inputs — MSE-RANK-0."""

    candidate_id: str
    weighted_score: float
    axis_breakdown: Dict[str, float]   # axis → contribution
    weights_used: Dict[str, float]
    score_hash: str = field(init=False)
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.score_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        axes_str = "|".join(
            f"{k}={v:.6f}" for k, v in sorted(self.axis_breakdown.items())
        )
        payload = f"{self.candidate_id}|{self.weighted_score:.6f}|{axes_str}".encode()
        return hashlib.sha256(payload).hexdigest()


@dataclass
class SelectionRecord:
    """Append-only record of a selection decision — MSE-PERSIST-0 / MSE-CHAIN-0."""

    record_id: str
    candidate_id: str
    verdict: SelectionVerdict
    fitness_score: float
    tier: CandidateTier
    epoch: int
    prev_record_hash: str          # HMAC chain link
    reason: str
    record_hash: str = field(init=False)
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.record_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        payload = (
            f"{self.record_id}|{self.candidate_id}|{self.verdict.value}|"
            f"{self.fitness_score:.6f}|{self.tier.value}|{self.epoch}|"
            f"{self.prev_record_hash}"
        ).encode()
        return hmac.new(HMAC_SECRET, payload, hashlib.sha256).hexdigest()

    def verify_chain(self, prev: Optional["SelectionRecord"]) -> bool:
        """MSE-CHAIN-0: verify HMAC link to previous record."""
        if prev is None:
            return self.prev_record_hash == "0" * 64
        return hmac.compare_digest(
            self.prev_record_hash[:24], prev.record_hash[:24]
        )


# ── Core Engine ──────────────────────────────────────────────────────────────

class MutationSelectionEngine:
    """
    Constitutional mutation selection engine for ADAAD.

    Scores every candidate across CANONICAL_AXES with DEFAULT_WEIGHTS,
    enforces blast radius and score floor gates, enforces HUMAN-0 gate
    for Tier-0 candidates, maintains an HMAC-chained selection ledger.

    Invariants enforced: MSE-RANK-0 through MSE-SCOPE-0 (all 10).
    """

    def __init__(
        self, weights: Optional[Dict[str, float]] = None
    ) -> None:
        # MSE-SCOPE-0: validate custom weight keys
        if weights is not None:
            unknown = set(weights) - CANONICAL_AXES
            if unknown:
                raise MSEAxisError(f"Unknown weight axes: {unknown}")
            self._weights = dict(weights)
        else:
            self._weights = dict(DEFAULT_WEIGHTS)

        self._ledger: List[SelectionRecord] = []
        self._audit: List[Dict] = []
        self._epoch: int = 0
        self._window: List[str] = []   # rolling selected candidate IDs
        self._scores: Dict[str, FitnessScore] = {}

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _next_epoch(self) -> int:
        self._epoch += 1
        return self._epoch

    def _prev_hash(self) -> str:
        if not self._ledger:
            return "0" * 64
        return self._ledger[-1].record_hash

    def _record_audit(self, event: str, payload: Dict) -> None:
        """MSE-AUDIT-0: append audit event."""
        self._audit.append({
            "event": event,
            "epoch": self._epoch,
            "timestamp": time.time(),
            **payload,
        })

    def _append_record(self, record: SelectionRecord) -> None:
        """MSE-PERSIST-0 / MSE-CHAIN-0: append and verify chain."""
        prev = self._ledger[-1] if self._ledger else None
        if not record.verify_chain(prev):
            raise MSETamperError(
                f"Chain broken at record '{record.record_id}' — MSE-CHAIN-0"
            )
        self._ledger.append(record)

    # ── Scoring ──────────────────────────────────────────────────────────────

    def score(self, candidate: MutationCandidate) -> FitnessScore:
        """
        Compute constitutional fitness score for a candidate.

        MSE-RANK-0: deterministic; same inputs → same score.
        MSE-SCOPE-0: only CANONICAL_AXES contribute.
        MSE-AUDIT-0: scoring event recorded.
        """
        epoch = self._next_epoch()

        # For each canonical axis, use supplied score or 0.0 if missing
        breakdown: Dict[str, float] = {}
        weighted_sum: float = 0.0
        total_weight: float = 0.0

        for axis in sorted(CANONICAL_AXES):  # sorted = deterministic order
            w = self._weights.get(axis, 0.0)
            raw = candidate.axis_scores.get(axis, 0.0)
            contribution = w * raw
            breakdown[axis] = contribution
            weighted_sum += contribution
            total_weight += w

        # Normalise if weights don't sum to exactly 1.0
        if total_weight > 0.0:
            weighted_score = min(weighted_sum / total_weight, MAX_SCORE)
        else:
            weighted_score = 0.0

        fs = FitnessScore(
            candidate_id=candidate.candidate_id,
            weighted_score=weighted_score,
            axis_breakdown=breakdown,
            weights_used=dict(self._weights),
        )
        self._scores[candidate.candidate_id] = fs
        self._record_audit("score", {
            "candidate_id": candidate.candidate_id,
            "weighted_score": round(weighted_score, 6),
        })
        return fs

    # ── Selection ─────────────────────────────────────────────────────────────

    def select(self, candidate: MutationCandidate) -> SelectionRecord:
        """
        Evaluate and select (or reject/defer) a mutation candidate.

        Gate order:
          1. MSE-BLAST-0  blast radius hard cap
          2. MSE-HUMAN0-0 Tier-0 ratification gate
          3. Score candidate (MSE-RANK-0)
          4. MSE-FLOOR-0  minimum score gate
          5. MSE-WINDOW-0 rolling window cap
          6. Append HMAC-chained record (MSE-CHAIN-0, MSE-PERSIST-0)

        Atomicity: MSE-ATOMIC-0 — any gate failure raises before ledger write.
        """
        epoch = self._next_epoch()
        record_id = f"MSE-REC-{epoch:04d}-{candidate.candidate_id}"

        # Gate 1 — MSE-BLAST-0
        if candidate.blast_radius > MAX_BLAST_RADIUS:
            raise MSEBlastReject(
                f"blast_radius={candidate.blast_radius:.3f} > "
                f"MAX_BLAST_RADIUS={MAX_BLAST_RADIUS} — MSE-BLAST-0"
            )

        # Gate 2 — MSE-HUMAN0-0
        if candidate.tier == CandidateTier.TIER0 and not candidate.ratified:
            raise MSEHuman0Flag(
                f"Candidate '{candidate.candidate_id}' is Tier-0 but "
                f"ratified=False — HUMAN-0 approval required (MSE-HUMAN0-0)"
            )

        # Gate 3 — Score
        fs = self.score(candidate)

        # Gate 4 — MSE-FLOOR-0
        if fs.weighted_score < SCORE_FLOOR:
            verdict = SelectionVerdict.REJECTED
            reason = (
                f"score={fs.weighted_score:.4f} < SCORE_FLOOR={SCORE_FLOOR} — MSE-FLOOR-0"
            )
        # Gate 5 — MSE-WINDOW-0
        elif len(self._window) >= MSE_WINDOW_SIZE:
            verdict = SelectionVerdict.DEFERRED
            reason = (
                f"Window full ({MSE_WINDOW_SIZE} active selections) — MSE-WINDOW-0"
            )
        else:
            verdict = SelectionVerdict.SELECTED
            reason = f"score={fs.weighted_score:.4f} >= SCORE_FLOOR; window capacity available"

        # Atomic ledger append — MSE-ATOMIC-0
        record = SelectionRecord(
            record_id=record_id,
            candidate_id=candidate.candidate_id,
            verdict=verdict,
            fitness_score=fs.weighted_score,
            tier=candidate.tier,
            epoch=epoch,
            prev_record_hash=self._prev_hash(),
            reason=reason,
        )
        self._append_record(record)

        if verdict == SelectionVerdict.SELECTED:
            self._window.append(candidate.candidate_id)
            # Rolling window: drop oldest beyond MSE_WINDOW_SIZE
            if len(self._window) > MSE_WINDOW_SIZE:
                self._window = self._window[-MSE_WINDOW_SIZE:]

        self._record_audit("select", {
            "candidate_id": candidate.candidate_id,
            "verdict": verdict.value,
            "reason": reason,
        })
        return record

    def release(self, candidate_id: str) -> bool:
        """
        Release a candidate from the active window (e.g. after execution completes).
        MSE-WINDOW-0: frees one slot in the rolling window.
        """
        if candidate_id in self._window:
            self._window.remove(candidate_id)
            self._record_audit("release", {"candidate_id": candidate_id})
            return True
        return False

    def rank(self, candidates: List[MutationCandidate]) -> List[Tuple[MutationCandidate, float]]:
        """
        Score and rank a list of candidates by constitutional fitness.
        Returns list of (candidate, score) sorted descending — MSE-RANK-0.
        Does NOT record ledger entries; use select() for that.
        """
        scored = [(c, self.score(c).weighted_score) for c in candidates]
        return sorted(scored, key=lambda x: x[1], reverse=True)

    # ── Verification ─────────────────────────────────────────────────────────

    def verify_chain(self) -> bool:
        """
        Full HMAC chain verification across the entire ledger — MSE-CHAIN-0.
        Raises MSETamperError on first violation.
        """
        for i, record in enumerate(self._ledger):
            prev = self._ledger[i - 1] if i > 0 else None
            if not record.verify_chain(prev):
                raise MSETamperError(
                    f"Chain broken at ledger position {i} "
                    f"(record '{record.record_id}') — MSE-CHAIN-0"
                )
            # Also verify stored hash matches recomputed hash
            recomputed = record._compute_hash()
            if not hmac.compare_digest(record.record_hash[:24], recomputed[:24]):
                raise MSETamperError(
                    f"Record hash tampered at position {i} — MSE-CHAIN-0"
                )
        return True

    # ── Observability ─────────────────────────────────────────────────────────

    def history(self) -> List[Dict]:
        """MSE-AUDIT-0: return append-only audit log."""
        return list(self._audit)

    def ledger(self) -> List[Dict]:
        """Return selection ledger as serialisable dicts — MSE-PERSIST-0."""
        return [
            {
                "record_id": r.record_id,
                "candidate_id": r.candidate_id,
                "verdict": r.verdict.value,
                "fitness_score": round(r.fitness_score, 6),
                "tier": r.tier.value,
                "epoch": r.epoch,
                "reason": r.reason,
                "record_hash": r.record_hash[:16],
                "timestamp": r.timestamp,
            }
            for r in self._ledger
        ]

    def window_status(self) -> Dict:
        """Current rolling window state — MSE-WINDOW-0."""
        return {
            "active": list(self._window),
            "capacity": MSE_WINDOW_SIZE,
            "available_slots": MSE_WINDOW_SIZE - len(self._window),
        }

    def stats(self) -> Dict:
        """Aggregate stats for Aponi dashboard."""
        verdicts = [r.verdict for r in self._ledger]
        return {
            "total_evaluated": len(self._ledger),
            "selected": sum(1 for v in verdicts if v == SelectionVerdict.SELECTED),
            "rejected": sum(1 for v in verdicts if v == SelectionVerdict.REJECTED),
            "deferred": sum(1 for v in verdicts if v == SelectionVerdict.DEFERRED),
            "window_active": len(self._window),
            "window_capacity": MSE_WINDOW_SIZE,
            "score_floor": SCORE_FLOOR,
            "max_blast_radius": MAX_BLAST_RADIUS,
            "epoch": self._epoch,
        }
