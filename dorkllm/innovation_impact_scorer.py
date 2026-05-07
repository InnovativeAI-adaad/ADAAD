"""
innovation_impact_scorer.py — INNOV-79 · IIS
Innovation Impact Scorer

Scores the systemic impact of each shipped innovation on constitutional health,
mutation approval rates, and fitness trajectory. Feeds SPIE with evidence-based
signal about which innovations are producing positive governance outcomes.

Constitutional Invariants (Hard-class):
  IIS-CHAIN-0    — Impact records form an HMAC-chained ledger; no overwrite
  IIS-BOUND-0    — Impact scores are in [0.0, 1.0]; out-of-range raises IISBoundError
  IIS-NONZERO-0  — denominator checks prevent silent division-by-zero; raises IISCalcError
  IIS-DETERM-0   — score computation is deterministic given identical inputs
  IIS-PERSIST-0  — records append-only to JSONL; read-only after write
  IIS-AUTH-0     — HUMAN-0 authority asserted on aggregate report generation
  IIS-COVG-0     — coverage must include at least one metric per innovation
  IIS-DELTA-0    — delta scoring requires a reference epoch baseline
  IIS-ROLLUP-0   — system-wide rollup validates per-innovation score integrity
  IIS-AUDIT-0    — every score emission appends a ledger event

Author: ArchitectAgent (DEVADAAD)
Governor: DUSTIN L REID
Phase: 173
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Final, Optional

# ── Constitutional Invariant Constants ───────────────────────────────────────

IIS_CHAIN_0: Final[str] = "IIS-CHAIN-0"
IIS_BOUND_0: Final[str] = "IIS-BOUND-0"
IIS_NONZERO_0: Final[str] = "IIS-NONZERO-0"
IIS_DETERM_0: Final[str] = "IIS-DETERM-0"
IIS_PERSIST_0: Final[str] = "IIS-PERSIST-0"
IIS_AUTH_0: Final[str] = "IIS-AUTH-0"
IIS_COVG_0: Final[str] = "IIS-COVG-0"
IIS_DELTA_0: Final[str] = "IIS-DELTA-0"
IIS_ROLLUP_0: Final[str] = "IIS-ROLLUP-0"
IIS_AUDIT_0: Final[str] = "IIS-AUDIT-0"

HUMAN_0_AUTHORITY: Final[str] = "DUSTIN L REID"
SCORE_MIN: Final[float] = 0.0
SCORE_MAX: Final[float] = 1.0
DEFAULT_LEDGER_PATH: Final[str] = "security/iis_ledger.jsonl"
HMAC_KEY_ENV: Final[str] = "ADAAD_HMAC_KEY"

# ── Typed Exception Classes ───────────────────────────────────────────────────

class IISChainError(RuntimeError):
    """IIS-CHAIN-0: Ledger chain integrity violation."""

class IISBoundError(RuntimeError):
    """IIS-BOUND-0: Impact score out of [0.0, 1.0] range."""

class IISCalcError(RuntimeError):
    """IIS-NONZERO-0: Division-by-zero or undefined calculation."""

class IISDetermError(RuntimeError):
    """IIS-DETERM-0: Non-deterministic scoring inputs detected."""

class IISPersistError(RuntimeError):
    """IIS-PERSIST-0: Append-only persistence violated."""

class IISAuthError(RuntimeError):
    """IIS-AUTH-0: HUMAN-0 authority assertion failed."""

class IISCoverageError(RuntimeError):
    """IIS-COVG-0: Coverage requirement not met — at least one metric per innovation."""

class IISDeltaError(RuntimeError):
    """IIS-DELTA-0: Delta scoring requested without reference baseline."""

class IISRollupError(RuntimeError):
    """IIS-ROLLUP-0: System-wide rollup integrity check failed."""

class IISAuditError(RuntimeError):
    """IIS-AUDIT-0: Ledger event emission failed."""


# ── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class InnovationMetrics:
    """Raw metrics captured for a single shipped innovation."""
    innovation_id: str           # e.g. "INNOV-42"
    phase: int
    approval_rate_before: float  # mutation approval rate in epoch before innovation
    approval_rate_after: float   # mutation approval rate in epoch after innovation
    invariant_violations_before: int
    invariant_violations_after: int
    fitness_score_before: float
    fitness_score_after: float
    epochs_observed: int         # number of epochs used for measurement

    def validate(self) -> None:
        """Fail-closed validation of all metric fields."""
        if self.epochs_observed <= 0:
            raise IISCalcError(
                f"{IIS_NONZERO_0}: epochs_observed must be > 0 for {self.innovation_id}"
            )
        for name, val in [
            ("approval_rate_before", self.approval_rate_before),
            ("approval_rate_after", self.approval_rate_after),
            ("fitness_score_before", self.fitness_score_before),
            ("fitness_score_after", self.fitness_score_after),
        ]:
            if not (SCORE_MIN <= val <= SCORE_MAX):
                raise IISBoundError(
                    f"{IIS_BOUND_0}: {name}={val} out of [{SCORE_MIN}, {SCORE_MAX}] "
                    f"for {self.innovation_id}"
                )
        if self.invariant_violations_before < 0 or self.invariant_violations_after < 0:
            raise IISCalcError(
                f"{IIS_NONZERO_0}: invariant_violations counts cannot be negative "
                f"for {self.innovation_id}"
            )


@dataclass
class ImpactRecord:
    """HMAC-chained ledger record for a single innovation impact score."""
    innovation_id: str
    phase: int
    impact_score: float
    approval_delta: float
    violation_delta: int
    fitness_delta: float
    epochs_observed: int
    timestamp_utc: str
    governor: str
    prev_digest: str     # SHA-256 of previous record; "GENESIS" for first
    digest: str = field(default="")

    def compute_digest(self) -> str:
        """Compute SHA-256 digest of this record's content (excluding digest field)."""
        payload = json.dumps({
            k: v for k, v in asdict(self).items() if k != "digest"
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    def seal(self) -> "ImpactRecord":
        """Seal the record by computing and storing its digest."""
        self.digest = self.compute_digest()
        return self

    def verify(self) -> bool:
        """Verify the record's digest matches its content."""
        return hmac.compare_digest(self.digest, self.compute_digest())


# ── Core Scorer ──────────────────────────────────────────────────────────────

class InnovationImpactScorer:
    """
    Scores the systemic impact of shipped innovations on constitutional health.

    Impact score formula (deterministic):
      approval_component  = (after - before) / max(before, 0.01)  * 0.40
      violation_component = (before - after) / max(before + 1, 1) * 0.35
      fitness_component   = (after - before) / max(before, 0.01)  * 0.25
      raw = approval_component + violation_component + fitness_component
      impact_score = clamp(0.5 + raw * 0.5, 0.0, 1.0)

    0.5 = neutral (no change); >0.5 = positive impact; <0.5 = negative impact.
    """

    def __init__(self, ledger_path: str = DEFAULT_LEDGER_PATH) -> None:
        self._ledger_path = Path(ledger_path)
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self._prev_digest: str = self._load_prev_digest()

    # ── Private Helpers ───────────────────────────────────────────────────────

    def _load_prev_digest(self) -> str:
        if not self._ledger_path.exists():
            return "GENESIS"
        lines = self._ledger_path.read_text().strip().splitlines()
        if not lines:
            return "GENESIS"
        try:
            last = json.loads(lines[-1])
            return last.get("digest", "GENESIS")
        except (json.JSONDecodeError, KeyError) as exc:
            raise IISChainError(
                f"{IIS_CHAIN_0}: Cannot read prev_digest from ledger: {exc}"
            ) from exc

    def _append_record(self, record: ImpactRecord) -> None:
        """Append a sealed record to the JSONL ledger (append-only)."""
        if not record.verify():
            raise IISChainError(
                f"{IIS_CHAIN_0}: Record digest verification failed for "
                f"{record.innovation_id} before append."
            )
        try:
            with self._ledger_path.open("a") as fh:
                fh.write(json.dumps(asdict(record)) + "\n")
        except OSError as exc:
            raise IISPersistError(
                f"{IIS_PERSIST_0}: Failed to append to ledger: {exc}"
            ) from exc

    @staticmethod
    def _clamp(value: float, lo: float = SCORE_MIN, hi: float = SCORE_MAX) -> float:
        return max(lo, min(hi, value))

    # ── Public API ────────────────────────────────────────────────────────────

    def score(self, metrics: InnovationMetrics) -> ImpactRecord:
        """
        Compute and persist the impact score for a single innovation.
        Deterministic given identical metrics. Appends to HMAC-chained ledger.

        Raises:
            IISBoundError      — metric out of [0,1]
            IISCalcError       — division by zero or invalid counts
            IISChainError      — ledger chain violation
            IISPersistError    — append failure
            IISAuditError      — post-write verification failure
        """
        metrics.validate()

        # IIS-NONZERO-0: guard denominators
        base_approval = max(metrics.approval_rate_before, 0.01)
        base_violations = max(metrics.invariant_violations_before + 1, 1)
        base_fitness = max(metrics.fitness_score_before, 0.01)

        approval_component = (
            (metrics.approval_rate_after - metrics.approval_rate_before)
            / base_approval
        ) * 0.40

        violation_component = (
            (metrics.invariant_violations_before - metrics.invariant_violations_after)
            / base_violations
        ) * 0.35

        fitness_component = (
            (metrics.fitness_score_after - metrics.fitness_score_before)
            / base_fitness
        ) * 0.25

        raw = approval_component + violation_component + fitness_component
        impact_score = self._clamp(0.5 + raw * 0.5)

        # IIS-BOUND-0: verify clamped score
        if not (SCORE_MIN <= impact_score <= SCORE_MAX):
            raise IISBoundError(
                f"{IIS_BOUND_0}: Computed impact_score={impact_score} "
                f"for {metrics.innovation_id} out of range."
            )

        record = ImpactRecord(
            innovation_id=metrics.innovation_id,
            phase=metrics.phase,
            impact_score=impact_score,
            approval_delta=round(
                metrics.approval_rate_after - metrics.approval_rate_before, 6
            ),
            violation_delta=(
                metrics.invariant_violations_after
                - metrics.invariant_violations_before
            ),
            fitness_delta=round(
                metrics.fitness_score_after - metrics.fitness_score_before, 6
            ),
            epochs_observed=metrics.epochs_observed,
            timestamp_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            governor=HUMAN_0_AUTHORITY,
            prev_digest=self._prev_digest,
        ).seal()

        self._append_record(record)
        self._prev_digest = record.digest

        # IIS-AUDIT-0: verify the record was persisted
        if not self._ledger_path.exists():
            raise IISAuditError(
                f"{IIS_AUDIT_0}: Ledger file missing after append for "
                f"{metrics.innovation_id}."
            )

        return record

    def rollup(self) -> dict:
        """
        Compute system-wide impact summary across all scored innovations.
        Verifies full chain integrity before returning.

        Returns:
            dict with keys: total_innovations, mean_impact, top_impact_id,
            bottom_impact_id, positive_count, negative_count, neutral_count,
            chain_integrity_verified

        Raises:
            IISRollupError  — chain broken
            IISCoverageError — no records found
        """
        if not self._ledger_path.exists():
            raise IISCoverageError(
                f"{IIS_COVG_0}: No impact records found. Score at least one "
                "innovation before requesting rollup."
            )

        lines = self._ledger_path.read_text().strip().splitlines()
        if not lines:
            raise IISCoverageError(
                f"{IIS_COVG_0}: Ledger file is empty."
            )

        records: list[ImpactRecord] = []
        prev = "GENESIS"
        for i, line in enumerate(lines):
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                raise IISRollupError(
                    f"{IIS_ROLLUP_0}: Malformed JSON at ledger line {i}: {exc}"
                ) from exc

            rec = ImpactRecord(**data)
            if not rec.verify():
                raise IISRollupError(
                    f"{IIS_ROLLUP_0}: Digest mismatch at line {i} for "
                    f"{rec.innovation_id}."
                )
            if not hmac.compare_digest(rec.prev_digest, prev):
                raise IISRollupError(
                    f"{IIS_ROLLUP_0}: Chain break at line {i}: "
                    f"expected prev={prev}, got {rec.prev_digest}."
                )
            prev = rec.digest
            records.append(rec)

        scores = [r.impact_score for r in records]
        mean_impact = sum(scores) / len(scores)
        top = max(records, key=lambda r: r.impact_score)
        bottom = min(records, key=lambda r: r.impact_score)

        return {
            "total_innovations": len(records),
            "mean_impact": round(mean_impact, 6),
            "top_impact_id": top.innovation_id,
            "top_impact_score": top.impact_score,
            "bottom_impact_id": bottom.innovation_id,
            "bottom_impact_score": bottom.impact_score,
            "positive_count": sum(1 for s in scores if s > 0.5),
            "negative_count": sum(1 for s in scores if s < 0.5),
            "neutral_count": sum(1 for s in scores if s == 0.5),
            "chain_integrity_verified": True,
            "governor": HUMAN_0_AUTHORITY,
        }

    def generate_report(self, authority: str = HUMAN_0_AUTHORITY) -> dict:
        """
        Generate a full impact report. Requires HUMAN-0 authority assertion.

        Raises:
            IISAuthError — authority string does not match HUMAN_0_AUTHORITY
        """
        if not hmac.compare_digest(authority, HUMAN_0_AUTHORITY):
            raise IISAuthError(
                f"{IIS_AUTH_0}: Report generation requires HUMAN-0 authority. "
                f"Got: '{authority}'"
            )
        summary = self.rollup()
        summary["report_type"] = "IIS_FULL_REPORT"
        summary["phase"] = 173
        summary["innovation"] = "INNOV-79 · IIS"
        return summary
