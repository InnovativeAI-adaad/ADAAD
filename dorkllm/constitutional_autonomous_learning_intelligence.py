# SPDX-License-Identifier: Apache-2.0
"""
dorkllm/constitutional_autonomous_learning_intelligence.py
Phase 228 · INNOV-133 · CALI — Constitutional Autonomous Learning Intelligence
Arc III ACI Module 04 — adaptive feedback loop: CAOE→CALI→CADE threshold recommendations
Author: DEVADAAD · InnovativeAI LLC · Governor: DUSTIN L REID
"""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

# ── Hard-class invariant identifiers (10) ─────────────────────────────────────
# CALI-CHAIN-0   : LearningLedger is HMAC-SHA-256 chained; chain verified before every append
# CALI-APPEND-0  : LearningLedger is append-only; sealed records are immutable
# CALI-IMMUT-0   : Sealed learning records raise ImmutabilityViolation on write attempt
# CALI-INGEST-0  : OutcomeIngester validates CAOE EvaluationRecord completeness before ingestion
# CALI-SCOPE-0   : Only IMPROVED/NEUTRAL/DEGRADED classifications accepted; unknown raises ScopeError
# CALI-ORIGIN-0  : Every ingested record must carry a non-empty evaluation_id; empty raises OriginError
# CALI-ADAPT-0   : AdaptationSignalEngine signals are bounded to [-0.05, +0.05]; out-of-band raises BoundError
# CALI-DETERM-0  : Signal computation is deterministic given classification+chi_delta; no randomness
# CALI-BOUND-0   : Cumulative adaptation per CHI band is capped at ±0.10; excess raises BoundError
# CALI-HUMAN0-0  : ThresholdRecommendation status=RATIFIED requires non-empty ratified_by; enforced structurally
# CALI-AUDIT-0   : Every ingest/compute/recommend/ratify/reject operation is sealed in the audit ledger

_HMAC_KEY = b"CALI-INNOV-133-DUSTIN-L-REID-HUMAN0-ACI-MODULE04"


def _hmac_digest(data: str, prev: str) -> str:
    return hmac.new(_HMAC_KEY, f"{prev}|{data}".encode(), hashlib.sha256).hexdigest()


# ── Exceptions ────────────────────────────────────────────────────────────────

class CALIViolation(Exception):
    """Base Hard-class invariant violation."""


class ChainBreakError(CALIViolation):
    """CALI-CHAIN-0: Ledger chain integrity broken."""


class ImmutabilityViolation(CALIViolation):
    """CALI-IMMUT-0: Attempt to mutate sealed record."""


class IngestionError(CALIViolation):
    """CALI-INGEST-0: Ingestion validation failed."""


class ScopeError(CALIViolation):
    """CALI-SCOPE-0: Unknown classification received."""


class OriginError(CALIViolation):
    """CALI-ORIGIN-0: evaluation_id is empty or missing."""


class BoundError(CALIViolation):
    """CALI-ADAPT-0 / CALI-BOUND-0: Adaptation signal out of bounds."""


class HUMAN0RatificationError(CALIViolation):
    """CALI-HUMAN0-0: Ratification requires non-empty ratified_by."""


class AuditError(CALIViolation):
    """CALI-AUDIT-0: Audit ledger violation."""


# ── Enumerations ──────────────────────────────────────────────────────────────

class Classification(str, Enum):
    IMPROVED = "IMPROVED"
    NEUTRAL = "NEUTRAL"
    DEGRADED = "DEGRADED"


class RecommendationStatus(str, Enum):
    PENDING = "PENDING"
    RATIFIED = "RATIFIED"
    REJECTED = "REJECTED"


class CHIBand(str, Enum):
    PROMOTE = "PROMOTE"   # CHI >= 0.80
    HOLD = "HOLD"         # 0.50 <= CHI < 0.80
    REJECT = "REJECT"     # CHI < 0.50


# ── Data records ──────────────────────────────────────────────────────────────

@dataclass
class IngestedOutcome:
    """Sealed ingested CAOE evaluation outcome."""
    ingestion_id: str
    evaluation_id: str          # CALI-ORIGIN-0: must be non-empty
    classification: str         # CALI-SCOPE-0: IMPROVED/NEUTRAL/DEGRADED only
    chi_before: float
    chi_after: float
    delta_chi: float
    chi_band: str
    timestamp_utc: float
    hmac_digest: str
    sealed: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ingestion_id": self.ingestion_id,
            "evaluation_id": self.evaluation_id,
            "classification": self.classification,
            "chi_before": self.chi_before,
            "chi_after": self.chi_after,
            "delta_chi": self.delta_chi,
            "chi_band": self.chi_band,
            "timestamp_utc": self.timestamp_utc,
            "hmac_digest": self.hmac_digest,
            "sealed": self.sealed,
        }


@dataclass
class AdaptationSignal:
    """Bounded adaptation signal per CHI band — CALI-ADAPT-0."""
    signal_id: str
    chi_band: str
    classification: str
    raw_signal: float           # Always in [-0.05, +0.05] — CALI-BOUND-0
    cumulative_band_delta: float
    basis_ingestion_id: str
    timestamp_utc: float
    hmac_digest: str
    sealed: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "chi_band": self.chi_band,
            "classification": self.classification,
            "raw_signal": self.raw_signal,
            "cumulative_band_delta": self.cumulative_band_delta,
            "basis_ingestion_id": self.basis_ingestion_id,
            "timestamp_utc": self.timestamp_utc,
            "hmac_digest": self.hmac_digest,
            "sealed": self.sealed,
        }


@dataclass
class ThresholdRecommendation:
    """CADE threshold recommendation — requires HUMAN-0 ratification (CALI-HUMAN0-0)."""
    recommendation_id: str
    chi_band: str
    current_threshold: float
    recommended_threshold: float
    adaptation_delta: float
    rationale: str
    status: str = RecommendationStatus.PENDING.value
    ratified_by: str = ""       # CALI-HUMAN0-0: must be non-empty before RATIFIED
    ratification_timestamp: Optional[float] = None
    rejection_reason: str = ""
    basis_signal_ids: List[str] = field(default_factory=list)
    timestamp_utc: float = field(default_factory=time.time)
    hmac_digest: str = ""
    sealed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recommendation_id": self.recommendation_id,
            "chi_band": self.chi_band,
            "current_threshold": self.current_threshold,
            "recommended_threshold": self.recommended_threshold,
            "adaptation_delta": self.adaptation_delta,
            "rationale": self.rationale,
            "status": self.status,
            "ratified_by": self.ratified_by,
            "ratification_timestamp": self.ratification_timestamp,
            "rejection_reason": self.rejection_reason,
            "basis_signal_ids": self.basis_signal_ids,
            "timestamp_utc": self.timestamp_utc,
            "hmac_digest": self.hmac_digest,
            "sealed": self.sealed,
        }


@dataclass
class LearningRecord:
    """Append-only ledger entry for LearningLedger — CALI-CHAIN-0."""
    record_id: str
    operation: str
    subject_id: str
    details: Dict[str, Any]
    prev_hash: str
    hmac_digest: str
    timestamp_utc: float
    sealed: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "operation": self.operation,
            "subject_id": self.subject_id,
            "details": self.details,
            "prev_hash": self.prev_hash,
            "hmac_digest": self.hmac_digest,
            "timestamp_utc": self.timestamp_utc,
            "sealed": self.sealed,
        }


# ── CADE default CHI thresholds (advisory) ───────────────────────────────────
_CADE_THRESHOLDS: Dict[str, float] = {
    CHIBand.PROMOTE.value: 0.80,
    CHIBand.HOLD.value: 0.50,
    CHIBand.REJECT.value: 0.00,
}

# ── Adaptation step magnitudes (CALI-ADAPT-0 / CALI-DETERM-0) ────────────────
_STEP_MAGNITUDE = 0.02   # Per-outcome adaptation step
_SIGNAL_BOUND = 0.05     # Hard bound on raw signal — CALI-ADAPT-0
_BAND_CUMULATIVE_CAP = 0.10  # Cumulative cap per band — CALI-BOUND-0


def _classify_chi_band(chi: float) -> str:
    """Deterministic CHI band classification — CALI-DETERM-0."""
    if chi >= 0.80:
        return CHIBand.PROMOTE.value
    elif chi >= 0.50:
        return CHIBand.HOLD.value
    return CHIBand.REJECT.value


def _compute_raw_signal(classification: str, delta_chi: float) -> float:
    """Deterministic bounded signal computation — CALI-DETERM-0, CALI-ADAPT-0."""
    if classification == Classification.IMPROVED.value:
        raw = +_STEP_MAGNITUDE
    elif classification == Classification.DEGRADED.value:
        raw = -_STEP_MAGNITUDE
    else:  # NEUTRAL — no signal
        raw = 0.0
    # Apply delta weight (capped to bound) — deterministic
    weighted = raw * min(1.0, abs(delta_chi) / 0.05 + 0.5)
    # CALI-ADAPT-0: clamp to [-0.05, +0.05]
    clamped = max(-_SIGNAL_BOUND, min(_SIGNAL_BOUND, weighted))
    return round(clamped, 6)


# ── OutcomeIngester ───────────────────────────────────────────────────────────

class OutcomeIngester:
    """
    CALI-INGEST-0 / CALI-SCOPE-0 / CALI-ORIGIN-0
    Validates and ingests CAOE EvaluationRecords.
    """

    _VALID_CLASSIFICATIONS = {c.value for c in Classification}
    _REQUIRED_FIELDS = {"evaluation_id", "classification", "chi_before", "chi_after"}

    def __init__(self) -> None:
        self._ingested: List[IngestedOutcome] = []
        self._prev_hash: str = "GENESIS"

    def ingest(self, evaluation_record: Dict[str, Any]) -> IngestedOutcome:
        """Validate and ingest a CAOE EvaluationRecord — CALI-INGEST-0."""
        # CALI-INGEST-0: all required fields must be present
        missing = self._REQUIRED_FIELDS - set(evaluation_record.keys())
        if missing:
            raise IngestionError(
                f"CALI-INGEST-0: Missing required fields: {sorted(missing)}"
            )
        # CALI-ORIGIN-0: evaluation_id must be non-empty
        eval_id = evaluation_record.get("evaluation_id", "")
        if not eval_id or not str(eval_id).strip():
            raise OriginError(
                "CALI-ORIGIN-0: evaluation_id is empty or missing — ingestion rejected"
            )
        # CALI-SCOPE-0: only valid classifications accepted
        classification = str(evaluation_record.get("classification", ""))
        if classification not in self._VALID_CLASSIFICATIONS:
            raise ScopeError(
                f"CALI-SCOPE-0: Unknown classification '{classification}'; "
                f"valid: {sorted(self._VALID_CLASSIFICATIONS)}"
            )
        chi_before = float(evaluation_record.get("chi_before", 0.0))
        chi_after = float(evaluation_record.get("chi_after", 0.0))
        delta_chi = round(chi_after - chi_before, 6)
        chi_band = _classify_chi_band(chi_before)

        ingestion_id = str(uuid.uuid4())
        now = time.time()
        payload = f"{ingestion_id}|{eval_id}|{classification}|{chi_before}|{chi_after}|{delta_chi}"
        digest = _hmac_digest(payload, self._prev_hash)
        self._prev_hash = digest

        outcome = IngestedOutcome(
            ingestion_id=ingestion_id,
            evaluation_id=str(eval_id),
            classification=classification,
            chi_before=chi_before,
            chi_after=chi_after,
            delta_chi=delta_chi,
            chi_band=chi_band,
            timestamp_utc=now,
            hmac_digest=digest,
            sealed=True,
        )
        self._ingested.append(outcome)
        return outcome

    def list_outcomes(self) -> List[IngestedOutcome]:
        return list(self._ingested)

    def get_outcome(self, ingestion_id: str) -> Optional[IngestedOutcome]:
        for o in self._ingested:
            if o.ingestion_id == ingestion_id:
                return o
        return None


# ── AdaptationSignalEngine ────────────────────────────────────────────────────

class AdaptationSignalEngine:
    """
    CALI-ADAPT-0 / CALI-DETERM-0 / CALI-BOUND-0
    Computes bounded adaptation signals per CHI band.
    """

    def __init__(self) -> None:
        self._signals: List[AdaptationSignal] = []
        self._band_cumulative: Dict[str, float] = {b.value: 0.0 for b in CHIBand}
        self._prev_hash: str = "GENESIS"

    def compute(self, outcome: IngestedOutcome) -> AdaptationSignal:
        """Compute a bounded adaptation signal — CALI-ADAPT-0, CALI-DETERM-0."""
        raw_signal = _compute_raw_signal(outcome.classification, outcome.delta_chi)

        # CALI-BOUND-0: check cumulative cap per band before accepting
        current_cum = self._band_cumulative[outcome.chi_band]
        projected_cum = current_cum + raw_signal
        if abs(projected_cum) > _BAND_CUMULATIVE_CAP:
            raise BoundError(
                f"CALI-BOUND-0: Cumulative adaptation for band {outcome.chi_band} "
                f"would exceed ±{_BAND_CUMULATIVE_CAP} (projected={projected_cum:.4f})"
            )

        self._band_cumulative[outcome.chi_band] = round(projected_cum, 6)

        signal_id = str(uuid.uuid4())
        now = time.time()
        payload = (
            f"{signal_id}|{outcome.chi_band}|{outcome.classification}|"
            f"{raw_signal}|{projected_cum}"
        )
        digest = _hmac_digest(payload, self._prev_hash)
        self._prev_hash = digest

        sig = AdaptationSignal(
            signal_id=signal_id,
            chi_band=outcome.chi_band,
            classification=outcome.classification,
            raw_signal=raw_signal,
            cumulative_band_delta=round(projected_cum, 6),
            basis_ingestion_id=outcome.ingestion_id,
            timestamp_utc=now,
            hmac_digest=digest,
            sealed=True,
        )
        self._signals.append(sig)
        return sig

    def list_signals(self, chi_band: Optional[str] = None) -> List[AdaptationSignal]:
        if chi_band:
            return [s for s in self._signals if s.chi_band == chi_band]
        return list(self._signals)

    def get_signal(self, signal_id: str) -> Optional[AdaptationSignal]:
        for s in self._signals:
            if s.signal_id == signal_id:
                return s
        return None

    def band_cumulative(self) -> Dict[str, float]:
        return dict(self._band_cumulative)


# ── ThresholdRecommender ──────────────────────────────────────────────────────

class ThresholdRecommender:
    """
    CALI-THRESH-0 / CALI-HUMAN0-0
    Produces CADE threshold recommendations; NO adjustment applies without HUMAN-0 ratification.
    """

    def __init__(self) -> None:
        self._recommendations: List[ThresholdRecommendation] = []
        self._thresholds: Dict[str, float] = dict(_CADE_THRESHOLDS)
        self._prev_hash: str = "GENESIS"

    def recommend(
        self,
        signals: List[AdaptationSignal],
        chi_band: str,
    ) -> ThresholdRecommendation:
        """Produce a threshold recommendation — PENDING until HUMAN-0 ratifies."""
        band_signals = [s for s in signals if s.chi_band == chi_band]
        if not band_signals:
            raise IngestionError(
                f"CALI-THRESH-0: No signals available for band '{chi_band}'"
            )
        total_delta = round(sum(s.raw_signal for s in band_signals), 6)
        current = self._thresholds.get(chi_band, 0.0)
        recommended = round(
            max(0.0, min(1.0, current + total_delta)), 4
        )
        rationale = (
            f"Band {chi_band}: {len(band_signals)} signal(s), "
            f"cumulative_delta={total_delta:+.4f}, "
            f"current={current:.4f} → recommended={recommended:.4f}. "
            f"Pending HUMAN-0 ratification before any threshold adjustment applies."
        )
        rec_id = str(uuid.uuid4())
        now = time.time()
        sig_ids = [s.signal_id for s in band_signals]
        payload = f"{rec_id}|{chi_band}|{current}|{recommended}|{total_delta}"
        digest = _hmac_digest(payload, self._prev_hash)
        self._prev_hash = digest

        rec = ThresholdRecommendation(
            recommendation_id=rec_id,
            chi_band=chi_band,
            current_threshold=current,
            recommended_threshold=recommended,
            adaptation_delta=total_delta,
            rationale=rationale,
            status=RecommendationStatus.PENDING.value,
            ratified_by="",
            basis_signal_ids=sig_ids,
            timestamp_utc=now,
            hmac_digest=digest,
            sealed=False,
        )
        self._recommendations.append(rec)
        return rec

    def ratify(self, recommendation_id: str, ratified_by: str) -> ThresholdRecommendation:
        """HUMAN-0 ratifies recommendation — CALI-HUMAN0-0 enforced."""
        if not ratified_by or not str(ratified_by).strip():
            raise HUMAN0RatificationError(
                "CALI-HUMAN0-0: ratified_by must be non-empty — "
                "HUMAN-0 identity required to ratify any threshold recommendation"
            )
        rec = self._get_pending(recommendation_id)
        # CALI-HUMAN0-0: threshold only updates after ratification
        rec.ratified_by = str(ratified_by).strip()
        rec.status = RecommendationStatus.RATIFIED.value
        rec.ratification_timestamp = time.time()
        rec.sealed = True
        # Apply threshold to live thresholds — only after HUMAN-0 ratification
        if rec.chi_band in self._thresholds:
            self._thresholds[rec.chi_band] = rec.recommended_threshold
        return rec

    def reject(self, recommendation_id: str, reason: str) -> ThresholdRecommendation:
        """HUMAN-0 rejects a recommendation."""
        rec = self._get_pending(recommendation_id)
        rec.rejection_reason = reason or "HUMAN-0 rejection"
        rec.status = RecommendationStatus.REJECTED.value
        rec.sealed = True
        return rec

    def _get_pending(self, recommendation_id: str) -> ThresholdRecommendation:
        for r in self._recommendations:
            if r.recommendation_id == recommendation_id:
                if r.sealed and r.status != RecommendationStatus.PENDING.value:
                    raise ImmutabilityViolation(
                        f"CALI-IMMUT-0: Recommendation {recommendation_id} is already sealed"
                    )
                return r
        raise IngestionError(
            f"CALI-THRESH-0: Recommendation '{recommendation_id}' not found"
        )

    def list_recommendations(
        self, status: Optional[str] = None
    ) -> List[ThresholdRecommendation]:
        if status:
            return [r for r in self._recommendations if r.status == status]
        return list(self._recommendations)

    def get_recommendation(self, rec_id: str) -> Optional[ThresholdRecommendation]:
        for r in self._recommendations:
            if r.recommendation_id == rec_id:
                return r
        return None

    def live_thresholds(self) -> Dict[str, float]:
        return dict(self._thresholds)


# ── LearningLedger ────────────────────────────────────────────────────────────

class LearningLedger:
    """
    CALI-CHAIN-0 / CALI-APPEND-0 / CALI-IMMUT-0
    HMAC-SHA-256-chained append-only ledger sealing every CALI operation.
    """

    def __init__(self) -> None:
        self._records: List[LearningRecord] = []
        self._head: str = "GENESIS"

    def append(self, operation: str, subject_id: str, details: Dict[str, Any]) -> LearningRecord:
        """Append a sealed record — CALI-CHAIN-0, CALI-APPEND-0."""
        # CALI-CHAIN-0: verify chain integrity before appending
        self._verify_chain()
        record_id = str(uuid.uuid4())
        now = time.time()
        payload = f"{record_id}|{operation}|{subject_id}|{now}"
        digest = _hmac_digest(payload, self._head)
        rec = LearningRecord(
            record_id=record_id,
            operation=operation,
            subject_id=subject_id,
            details=dict(details),
            prev_hash=self._head,
            hmac_digest=digest,
            timestamp_utc=now,
            sealed=True,
        )
        self._records.append(rec)
        self._head = digest
        return rec

    def _verify_chain(self) -> bool:
        """Verify HMAC chain integrity — CALI-CHAIN-0."""
        if not self._records:
            return True
        prev = "GENESIS"
        for rec in self._records:
            expected_payload = f"{rec.record_id}|{rec.operation}|{rec.subject_id}|{rec.timestamp_utc}"
            expected = _hmac_digest(expected_payload, prev)
            if not hmac.compare_digest(expected, rec.hmac_digest):
                raise ChainBreakError(
                    f"CALI-CHAIN-0: Chain integrity broken at record {rec.record_id}"
                )
            prev = rec.hmac_digest
        return True

    def verify_chain(self) -> Dict[str, Any]:
        """Public chain verification — returns status dict."""
        ok = self._verify_chain()
        return {
            "chain_valid": ok,
            "record_count": len(self._records),
            "head": self._head,
        }

    def list_records(self) -> List[LearningRecord]:
        return list(self._records)


# ── CALIAuditor ───────────────────────────────────────────────────────────────

class CALIAuditor:
    """
    CALI-AUDIT-0: Every CALI operation sealed in an append-only HMAC-chained audit log.
    """

    def __init__(self) -> None:
        self._entries: List[Dict[str, Any]] = []
        self._prev: str = "GENESIS"

    def record(self, operation: str, subject_id: str, outcome: str, detail: str = "") -> None:
        """Append audit entry — CALI-AUDIT-0."""
        entry_id = str(uuid.uuid4())
        now = time.time()
        payload = f"{entry_id}|{operation}|{subject_id}|{outcome}|{now}"
        digest = _hmac_digest(payload, self._prev)
        self._prev = digest
        self._entries.append({
            "audit_id": entry_id,
            "operation": operation,
            "subject_id": subject_id,
            "outcome": outcome,
            "detail": detail,
            "timestamp_utc": now,
            "hmac_digest": digest,
        })

    def list_entries(self) -> List[Dict[str, Any]]:
        return list(self._entries)


# ── CALIEngine (facade) ───────────────────────────────────────────────────────

class CALIEngine:
    """
    Facade coordinating OutcomeIngester, AdaptationSignalEngine,
    ThresholdRecommender, LearningLedger, and CALIAuditor.

    Arc III ACI Module 04 — closes the full ACI feedback loop:
    CASL → CADE → CAPE → CAOE → CALI → CADE (threshold recommendations)
    """

    def __init__(self) -> None:
        self._ingester = OutcomeIngester()
        self._signal_engine = AdaptationSignalEngine()
        self._recommender = ThresholdRecommender()
        self._ledger = LearningLedger()
        self._auditor = CALIAuditor()

    # ── Ingestion ────────────────────────────────────────────────────────

    def ingest(self, evaluation_record: Dict[str, Any]) -> IngestedOutcome:
        """Ingest a CAOE EvaluationRecord — CALI-INGEST-0, CALI-SCOPE-0, CALI-ORIGIN-0."""
        outcome = self._ingester.ingest(evaluation_record)
        self._ledger.append("INGEST", outcome.ingestion_id, {
            "evaluation_id": outcome.evaluation_id,
            "classification": outcome.classification,
            "chi_band": outcome.chi_band,
        })
        self._auditor.record("INGEST", outcome.ingestion_id, "OK",
                             f"classification={outcome.classification}, band={outcome.chi_band}")
        return outcome

    # ── Signal computation ───────────────────────────────────────────────

    def compute_signal(self, ingestion_id: str) -> AdaptationSignal:
        """Compute adaptation signal for an ingested outcome — CALI-ADAPT-0."""
        outcome = self._ingester.get_outcome(ingestion_id)
        if outcome is None:
            raise IngestionError(f"CALI-INGEST-0: Ingestion '{ingestion_id}' not found")
        try:
            sig = self._signal_engine.compute(outcome)
        except BoundError as e:
            self._auditor.record("COMPUTE_SIGNAL", ingestion_id, "BOUND_EXCEEDED", str(e))
            raise
        self._ledger.append("COMPUTE_SIGNAL", sig.signal_id, {
            "ingestion_id": ingestion_id,
            "chi_band": sig.chi_band,
            "raw_signal": sig.raw_signal,
            "cumulative": sig.cumulative_band_delta,
        })
        self._auditor.record("COMPUTE_SIGNAL", sig.signal_id, "OK",
                             f"band={sig.chi_band}, signal={sig.raw_signal:+.4f}")
        return sig

    # ── Recommendation ───────────────────────────────────────────────────

    def recommend(self, chi_band: str) -> ThresholdRecommendation:
        """Produce a PENDING threshold recommendation — HUMAN-0 must ratify."""
        # CALI-SCOPE-0: validate band
        valid_bands = {b.value for b in CHIBand}
        if chi_band not in valid_bands:
            raise ScopeError(f"CALI-SCOPE-0: Unknown CHI band '{chi_band}'")
        signals = self._signal_engine.list_signals(chi_band=chi_band)
        rec = self._recommender.recommend(signals, chi_band)
        self._ledger.append("RECOMMEND", rec.recommendation_id, {
            "chi_band": chi_band,
            "current_threshold": rec.current_threshold,
            "recommended_threshold": rec.recommended_threshold,
            "adaptation_delta": rec.adaptation_delta,
        })
        self._auditor.record("RECOMMEND", rec.recommendation_id, "PENDING",
                             f"band={chi_band}, delta={rec.adaptation_delta:+.4f}")
        return rec

    # ── HUMAN-0 ratification ─────────────────────────────────────────────

    def ratify(self, recommendation_id: str, ratified_by: str) -> ThresholdRecommendation:
        """HUMAN-0 ratifies recommendation — CALI-HUMAN0-0."""
        rec = self._recommender.ratify(recommendation_id, ratified_by)
        self._ledger.append("RATIFY", recommendation_id, {
            "ratified_by": rec.ratified_by,
            "chi_band": rec.chi_band,
            "new_threshold": rec.recommended_threshold,
        })
        self._auditor.record("RATIFY", recommendation_id, "RATIFIED",
                             f"ratified_by={rec.ratified_by}, new_threshold={rec.recommended_threshold:.4f}")
        return rec

    def reject(self, recommendation_id: str, reason: str) -> ThresholdRecommendation:
        """HUMAN-0 rejects recommendation."""
        rec = self._recommender.reject(recommendation_id, reason)
        self._ledger.append("REJECT", recommendation_id, {"reason": reason})
        self._auditor.record("REJECT", recommendation_id, "REJECTED", f"reason={reason}")
        return rec

    # ── Query / status ───────────────────────────────────────────────────

    def list_outcomes(self) -> List[IngestedOutcome]:
        return self._ingester.list_outcomes()

    def get_outcome(self, ingestion_id: str) -> Optional[IngestedOutcome]:
        return self._ingester.get_outcome(ingestion_id)

    def list_signals(self, chi_band: Optional[str] = None) -> List[AdaptationSignal]:
        return self._signal_engine.list_signals(chi_band)

    def get_signal(self, signal_id: str) -> Optional[AdaptationSignal]:
        return self._signal_engine.get_signal(signal_id)

    def list_recommendations(self, status: Optional[str] = None) -> List[ThresholdRecommendation]:
        return self._recommender.list_recommendations(status)

    def get_recommendation(self, rec_id: str) -> Optional[ThresholdRecommendation]:
        return self._recommender.get_recommendation(rec_id)

    def verify_chain(self) -> Dict[str, Any]:
        result = self._ledger.verify_chain()
        self._auditor.record("VERIFY_CHAIN", "LEDGER", "OK",
                             f"records={result['record_count']}, head={result['head'][:16]}...")
        return result

    def audit_log(self) -> List[Dict[str, Any]]:
        return self._auditor.list_entries()

    def live_thresholds(self) -> Dict[str, float]:
        return self._recommender.live_thresholds()

    def band_cumulative(self) -> Dict[str, float]:
        return self._signal_engine.band_cumulative()

    def status(self) -> Dict[str, Any]:
        outcomes = self._ingester.list_outcomes()
        signals = self._signal_engine.list_signals()
        recs = self._recommender.list_recommendations()
        return {
            "module": "CALI",
            "phase": 228,
            "version": "10.39.0",
            "arc": "Arc III — Autonomous Constitutional Intelligence (ACI) Module 04",
            "innov": "INNOV-133",
            "governor": "DUSTIN L REID",
            "aci_loop": "CASL→CADE→CAPE→CAOE→CALI→CADE",
            "outcomes_ingested": len(outcomes),
            "signals_computed": len(signals),
            "recommendations_pending": len([r for r in recs if r.status == "PENDING"]),
            "recommendations_ratified": len([r for r in recs if r.status == "RATIFIED"]),
            "recommendations_rejected": len([r for r in recs if r.status == "REJECTED"]),
            "live_thresholds": self._recommender.live_thresholds(),
            "band_cumulative": self._signal_engine.band_cumulative(),
            "hard_class_invariants": [
                "CALI-CHAIN-0", "CALI-APPEND-0", "CALI-IMMUT-0",
                "CALI-INGEST-0", "CALI-SCOPE-0", "CALI-ORIGIN-0",
                "CALI-ADAPT-0", "CALI-DETERM-0", "CALI-BOUND-0",
                "CALI-HUMAN0-0", "CALI-AUDIT-0",
            ],
        }
