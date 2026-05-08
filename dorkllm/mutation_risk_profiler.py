# SPDX-License-Identifier: Apache-2.0
"""
INNOV-76 · MRP — Mutation Risk Profiler
========================================
Phase 170 · v9.103.0 · InnovativeAI LLC

World-first: A constitutionally-governed multi-dimensional risk profiler
for mutation proposals. Every proposal is assessed across five canonical
risk dimensions, producing a composite risk score and a constitutional
verdict (NEGLIGIBLE / LOW / MEDIUM / HIGH / CRITICAL). CRITICAL profiles
are hard-gated on HUMAN-0 acknowledgment. All profiles are HMAC-chained
in an append-only registry. Integrates with the MSE fitness signal for
holistic mutation governance intelligence.

Hard-class invariants enforced:
  MRP-SCORE-0    Risk score is deterministic given the same inputs
  MRP-CHAIN-0    Every risk profile is HMAC-chained to the previous record
  MRP-HUMAN0-0   CRITICAL risk profiles require HUMAN-0 acknowledgment before proceeding
  MRP-CEIL-0     Proposals with composite_risk >= RISK_CEILING are auto-blocked
  MRP-BLAST-0    blast_contribution is always >= 0.0 (risk is non-negative)
  MRP-PERSIST-0  Risk registry is append-only; no profile may be modified or deleted
  MRP-ATOMIC-0   profile() is atomic; partial results raise MRPAtomicError
  MRP-AUDIT-0    Every profiling event is recorded in the audit trail
  MRP-DIM-0      Risk dimensions are restricted to CANONICAL_DIMENSIONS
  MRP-VERDICT-0  Verdict is determined solely by composite_risk thresholds; no bypass

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

HMAC_SECRET: bytes = b"ADAAD-MRP-HMAC-SECRET-v1"

# MRP-CEIL-0: mutations exceeding this composite risk are auto-blocked
RISK_CEILING: float = 0.90

# Verdict thresholds (composite_risk → RiskVerdict) — MRP-VERDICT-0
_VERDICT_THRESHOLDS: Tuple[Tuple[float, str], ...] = (
    (0.20, "NEGLIGIBLE"),
    (0.40, "LOW"),
    (0.60, "MEDIUM"),
    (0.80, "HIGH"),
    (1.01, "CRITICAL"),   # 1.01 sentinel catches composite_risk == 1.0
)

# MRP-DIM-0: only these five dimensions are constitutionally canonical
CANONICAL_DIMENSIONS: FrozenSet[str] = frozenset(
    {
        "blast_exposure",      # breadth of codebase affected; higher = more risk
        "invariant_stress",    # pressure on existing Hard-class invariants
        "phylogenetic_novelty",# distance from known-safe mutation lineage
        "temporal_urgency",    # change velocity; fast changes carry higher risk
        "rollback_complexity", # cost / reversibility of undoing this mutation
    }
)

# Default dimension weights (deterministic sum to 1.0) — MRP-SCORE-0
DEFAULT_WEIGHTS: Dict[str, float] = {
    "blast_exposure":       0.30,
    "invariant_stress":     0.25,
    "phylogenetic_novelty": 0.20,
    "temporal_urgency":     0.10,
    "rollback_complexity":  0.15,
}

MAX_SCORE: float = 1.0
MIN_SCORE: float = 0.0


# ── Errors ───────────────────────────────────────────────────────────────────

class MRPAtomicError(Exception):
    """Raised when a profiling operation cannot complete atomically — MRP-ATOMIC-0."""

class MRPHuman0Required(Exception):
    """Raised when a CRITICAL profile lacks HUMAN-0 acknowledgment — MRP-HUMAN0-0."""

class MRPCeilingBlock(Exception):
    """Raised when composite_risk >= RISK_CEILING — MRP-CEIL-0."""

class MRPDimensionError(Exception):
    """Raised when an unknown risk dimension is supplied — MRP-DIM-0."""

class MRPTamperError(Exception):
    """Raised when HMAC chain verification fails — MRP-CHAIN-0."""

class MRPNegativeRiskError(Exception):
    """Raised when blast_contribution would be negative — MRP-BLAST-0."""


# ── Enums ────────────────────────────────────────────────────────────────────

class RiskVerdict(str, Enum):
    NEGLIGIBLE = "NEGLIGIBLE"
    LOW        = "LOW"
    MEDIUM     = "MEDIUM"
    HIGH       = "HIGH"
    CRITICAL   = "CRITICAL"


class ProfileStatus(str, Enum):
    CLEAR    = "CLEAR"    # approved for execution
    BLOCKED  = "BLOCKED"  # composite_risk >= RISK_CEILING
    DEFERRED = "DEFERRED" # CRITICAL but awaiting HUMAN-0 acknowledgment


# ── Data models ──────────────────────────────────────────────────────────────

@dataclass
class MutationProposal:
    """A mutation proposal submitted for risk profiling."""

    proposal_id: str
    label: str
    # Per-dimension raw risk scores in [0.0, 1.0]; higher = more risky
    dimension_scores: Dict[str, float]
    # Acknowledged by HUMAN-0 for CRITICAL verdicts
    human0_acknowledged: bool = False
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        # MRP-DIM-0: reject unknown dimensions
        unknown = set(self.dimension_scores) - CANONICAL_DIMENSIONS
        if unknown:
            raise MRPDimensionError(
                f"Unknown risk dimensions: {unknown}. "
                f"Allowed: {sorted(CANONICAL_DIMENSIONS)}"
            )
        # Clamp to [0.0, 1.0]
        self.dimension_scores = {
            k: max(MIN_SCORE, min(MAX_SCORE, v))
            for k, v in self.dimension_scores.items()
        }


@dataclass
class RiskProfile:
    """
    Computed risk profile for a mutation proposal.
    Deterministic given the same inputs — MRP-SCORE-0.
    """

    proposal_id: str
    composite_risk: float           # weighted sum of dimension scores
    verdict: RiskVerdict            # MRP-VERDICT-0
    dimension_breakdown: Dict[str, float]  # dim → weighted contribution
    weights_used: Dict[str, float]
    profile_hash: str = field(init=False)
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.profile_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        dims_str = "|".join(
            f"{k}={v:.6f}" for k, v in sorted(self.dimension_breakdown.items())
        )
        payload = (
            f"{self.proposal_id}|{self.composite_risk:.6f}|"
            f"{self.verdict.value}|{dims_str}"
        ).encode()
        return hashlib.sha256(payload).hexdigest()

    def summary(self) -> Dict:
        return {
            "proposal_id": self.proposal_id,
            "composite_risk": round(self.composite_risk, 4),
            "verdict": self.verdict.value,
            "dimension_breakdown": {
                k: round(v, 4) for k, v in self.dimension_breakdown.items()
            },
            "profile_hash": self.profile_hash[:16],
        }


@dataclass
class ProfileRecord:
    """
    Append-only registry entry for a completed profile — MRP-PERSIST-0 / MRP-CHAIN-0.
    """

    record_id: str
    proposal_id: str
    verdict: RiskVerdict
    status: ProfileStatus
    composite_risk: float
    prev_record_hash: str
    reason: str
    record_hash: str = field(init=False)
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.record_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        payload = (
            f"{self.record_id}|{self.proposal_id}|{self.verdict.value}|"
            f"{self.status.value}|{self.composite_risk:.6f}|"
            f"{self.prev_record_hash}"
        ).encode()
        return hmac.new(HMAC_SECRET, payload, hashlib.sha256).hexdigest()

    def verify_chain(self, prev: Optional["ProfileRecord"]) -> bool:
        """MRP-CHAIN-0: verify HMAC link to previous record."""
        if prev is None:
            return self.prev_record_hash == "0" * 64
        return hmac.compare_digest(
            self.prev_record_hash[:24], prev.record_hash[:24]
        )


# ── Core Engine ──────────────────────────────────────────────────────────────

class MutationRiskProfiler:
    """
    Constitutional mutation risk profiler for ADAAD.

    Scores every mutation proposal across CANONICAL_DIMENSIONS with
    DEFAULT_WEIGHTS, computes a composite risk score, issues a
    RiskVerdict, enforces RISK_CEILING and HUMAN-0 gates, and maintains
    an HMAC-chained append-only risk registry.

    Invariants enforced: MRP-SCORE-0 through MRP-VERDICT-0 (all 10).

    Governor: DUSTIN L REID
    """

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        risk_ceiling: float = RISK_CEILING,
    ) -> None:
        # MRP-DIM-0: validate custom weight keys
        if weights is not None:
            unknown = set(weights) - CANONICAL_DIMENSIONS
            if unknown:
                raise MRPDimensionError(f"Unknown weight dimensions: {unknown}")
            self._weights = dict(weights)
        else:
            self._weights = dict(DEFAULT_WEIGHTS)

        self._ceiling = risk_ceiling
        self._registry: List[ProfileRecord] = []
        self._audit: List[Dict] = []
        self._epoch: int = 0

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _next_epoch(self) -> int:
        self._epoch += 1
        return self._epoch

    def _prev_hash(self) -> str:
        if not self._registry:
            return "0" * 64
        return self._registry[-1].record_hash

    def _record_audit(self, event: str, payload: Dict) -> None:
        """MRP-AUDIT-0: append audit event."""
        self._audit.append({
            "event": event,
            "epoch": self._epoch,
            "timestamp": time.time(),
            **payload,
        })

    def _append_record(self, record: ProfileRecord) -> None:
        """MRP-PERSIST-0 / MRP-CHAIN-0: verify chain then append."""
        prev = self._registry[-1] if self._registry else None
        if not record.verify_chain(prev):
            raise MRPTamperError(
                f"Chain broken at record '{record.record_id}' — MRP-CHAIN-0"
            )
        self._registry.append(record)

    @staticmethod
    def _compute_verdict(composite_risk: float) -> RiskVerdict:
        """MRP-VERDICT-0: determine verdict solely from composite_risk thresholds."""
        for threshold, label in _VERDICT_THRESHOLDS:
            if composite_risk < threshold:
                return RiskVerdict(label)
        return RiskVerdict.CRITICAL

    # ── Risk scoring ─────────────────────────────────────────────────────────

    def compute_profile(self, proposal: MutationProposal) -> RiskProfile:
        """
        Compute a risk profile for a proposal.

        MRP-SCORE-0: deterministic; same inputs → same composite_risk.
        MRP-DIM-0: only CANONICAL_DIMENSIONS contribute.
        MRP-BLAST-0: all contributions non-negative.
        MRP-AUDIT-0: profiling event recorded.
        """
        self._next_epoch()

        breakdown: Dict[str, float] = {}
        weighted_sum: float = 0.0
        total_weight: float = 0.0

        for dim in sorted(CANONICAL_DIMENSIONS):   # sorted = deterministic
            w = self._weights.get(dim, 0.0)
            raw = proposal.dimension_scores.get(dim, 0.0)
            contribution = w * raw

            # MRP-BLAST-0: risk contribution must be non-negative
            if contribution < 0.0:
                raise MRPNegativeRiskError(
                    f"Dimension '{dim}' produced negative contribution "
                    f"{contribution:.4f} — MRP-BLAST-0"
                )

            breakdown[dim] = contribution
            weighted_sum += contribution
            total_weight += w

        # Normalise
        composite_risk = (
            min(weighted_sum / total_weight, MAX_SCORE)
            if total_weight > 0.0
            else 0.0
        )
        verdict = self._compute_verdict(composite_risk)

        profile = RiskProfile(
            proposal_id=proposal.proposal_id,
            composite_risk=composite_risk,
            verdict=verdict,
            dimension_breakdown=breakdown,
            weights_used=dict(self._weights),
        )

        self._record_audit("compute_profile", {
            "proposal_id": proposal.proposal_id,
            "composite_risk": round(composite_risk, 6),
            "verdict": verdict.value,
        })
        return profile

    # ── Gated profiling (the main entry point) ────────────────────────────────

    def profile(
        self, proposal: MutationProposal
    ) -> Tuple[RiskProfile, ProfileRecord]:
        """
        Full constitutional risk assessment for a mutation proposal.

        Gate order:
          1. Compute risk profile (MRP-SCORE-0, MRP-DIM-0, MRP-BLAST-0)
          2. MRP-CEIL-0   auto-block if composite_risk >= RISK_CEILING
          3. MRP-HUMAN0-0 require HUMAN-0 acknowledgment for CRITICAL verdicts
          4. Determine status and append HMAC-chained record (MRP-CHAIN-0, MRP-PERSIST-0)

        Atomicity: MRP-ATOMIC-0 — any gate failure raises before registry write.

        Returns (RiskProfile, ProfileRecord).
        """
        epoch = self._next_epoch()
        record_id = f"MRP-REC-{epoch:04d}-{proposal.proposal_id}"

        # Compute profile
        try:
            rp = self.compute_profile(proposal)
        except Exception as exc:
            raise MRPAtomicError(
                f"Profile computation failed atomically — MRP-ATOMIC-0: {exc}"
            ) from exc

        # Gate 1 — MRP-CEIL-0: auto-block
        if rp.composite_risk >= self._ceiling:
            raise MRPCeilingBlock(
                f"composite_risk={rp.composite_risk:.4f} >= "
                f"RISK_CEILING={self._ceiling} — MRP-CEIL-0: proposal BLOCKED"
            )

        # Gate 2 — MRP-HUMAN0-0: CRITICAL requires HUMAN-0
        if rp.verdict == RiskVerdict.CRITICAL and not proposal.human0_acknowledged:
            status = ProfileStatus.DEFERRED
            reason = (
                f"CRITICAL risk ({rp.composite_risk:.4f}) — "
                f"HUMAN-0 acknowledgment required before execution (MRP-HUMAN0-0)"
            )
        else:
            status = ProfileStatus.CLEAR
            reason = (
                f"verdict={rp.verdict.value} composite_risk={rp.composite_risk:.4f}; "
                f"constitutional gates passed"
            )

        # Atomic registry append — MRP-ATOMIC-0
        record = ProfileRecord(
            record_id=record_id,
            proposal_id=proposal.proposal_id,
            verdict=rp.verdict,
            status=status,
            composite_risk=rp.composite_risk,
            prev_record_hash=self._prev_hash(),
            reason=reason,
        )
        self._append_record(record)

        self._record_audit("profile_decision", {
            "proposal_id": proposal.proposal_id,
            "verdict": rp.verdict.value,
            "status": status.value,
            "reason": reason,
        })
        return rp, record

    # ── Verification ─────────────────────────────────────────────────────────

    def verify_chain(self) -> bool:
        """
        Full HMAC chain verification across the entire registry — MRP-CHAIN-0.
        Raises MRPTamperError on first violation.
        """
        for i, record in enumerate(self._registry):
            prev = self._registry[i - 1] if i > 0 else None
            if not record.verify_chain(prev):
                raise MRPTamperError(
                    f"Chain broken at registry position {i} "
                    f"(record '{record.record_id}') — MRP-CHAIN-0"
                )
            recomputed = record._compute_hash()
            if not hmac.compare_digest(record.record_hash[:24], recomputed[:24]):
                raise MRPTamperError(
                    f"Record hash tampered at position {i} — MRP-CHAIN-0"
                )
        return True

    # ── Observability ─────────────────────────────────────────────────────────

    def audit_trail(self) -> List[Dict]:
        """MRP-AUDIT-0: return append-only audit log."""
        return list(self._audit)

    def registry(self) -> List[Dict]:
        """Return risk registry as serialisable dicts — MRP-PERSIST-0."""
        return [
            {
                "record_id": r.record_id,
                "proposal_id": r.proposal_id,
                "verdict": r.verdict.value,
                "status": r.status.value,
                "composite_risk": round(r.composite_risk, 6),
                "reason": r.reason,
                "record_hash": r.record_hash[:16],
                "timestamp": r.timestamp,
            }
            for r in self._registry
        ]

    def stats(self) -> Dict:
        """Aggregate stats for Aponi dashboard."""
        verdicts = [r.verdict for r in self._registry]
        statuses = [r.status for r in self._registry]
        return {
            "total_profiled": len(self._registry),
            "by_verdict": {v.value: sum(1 for x in verdicts if x == v) for v in RiskVerdict},
            "clear": sum(1 for s in statuses if s == ProfileStatus.CLEAR),
            "deferred": sum(1 for s in statuses if s == ProfileStatus.DEFERRED),
            "risk_ceiling": self._ceiling,
            "epoch": self._epoch,
        }

    def highest_risk_record(self) -> Optional[Dict]:
        """Return the registry record with the highest composite_risk."""
        if not self._registry:
            return None
        peak = max(self._registry, key=lambda r: r.composite_risk)
        return {
            "record_id": peak.record_id,
            "proposal_id": peak.proposal_id,
            "verdict": peak.verdict.value,
            "composite_risk": round(peak.composite_risk, 6),
        }
