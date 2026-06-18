# SPDX-License-Identifier: Apache-2.0
"""
dorkllm/constitutional_autonomous_convergence_prover.py
Phase 229 · INNOV-134 · CACP — Constitutional Autonomous Convergence Prover
Arc III ACI Meta-layer: cryptographic convergence proofs across the full ACI pipeline
CASL → CADE → CAPE → CAOE → CALI → CACP (convergence proof)
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

# ── Hard-class invariant identifiers (11) ─────────────────────────────────────
# CACP-CHAIN-0  : ConvergenceLedger is HMAC-SHA-256 chained; verified before every append
# CACP-APPEND-0 : ConvergenceLedger is append-only; sealed proofs cannot be removed
# CACP-IMMUT-0  : Sealed convergence proofs raise ImmutabilityViolation on write attempt
# CACP-SCOPE-0  : Only valid ACI pipeline record types accepted (CASL/CADE/CAPE/CAOE/CALI)
# CACP-ORIGIN-0 : Every proof must reference at least one non-empty ACI cycle record
# CACP-CYCLE-0  : A complete ACI cycle requires records from all 5 pipeline stages
# CACP-DETERM-0 : Convergence score is deterministic given cycle records; no randomness
# CACP-TREND-0  : Trend must be IMPROVING/STABLE/DEGRADING; unknown raises TrendError
# CACP-HUMAN0-0 : DEGRADING trend issues mandatory HUMAN-0 notification flag; flag non-empty required before acknowledgement
# CACP-AUDIT-0  : Every aggregate/compute/prove/acknowledge operation sealed in audit ledger
# CACP-PROOF-0  : Every issued ConvergenceProof carries HMAC-SHA-256 binding of all cycle inputs

_HMAC_KEY = b"CACP-INNOV-134-DUSTIN-L-REID-HUMAN0-ACI-META-LAYER"

# ACI pipeline stages — CACP-SCOPE-0
ACI_PIPELINE_STAGES = frozenset({"CASL", "CADE", "CAPE", "CAOE", "CALI"})

# Convergence thresholds — CACP-DETERM-0
_IMPROVING_THRESHOLD = 0.02   # mean CHI delta per cycle >= +0.02 → IMPROVING
_DEGRADING_THRESHOLD = -0.02  # mean CHI delta per cycle <= -0.02 → DEGRADING


def _hmac_digest(data: str, prev: str) -> str:
    return hmac.new(_HMAC_KEY, f"{prev}|{data}".encode(), hashlib.sha256).hexdigest()


# ── Exceptions ────────────────────────────────────────────────────────────────

class CACPViolation(Exception):
    """Base Hard-class invariant violation."""


class ChainBreakError(CACPViolation):
    """CACP-CHAIN-0: ConvergenceLedger chain integrity broken."""


class ImmutabilityViolation(CACPViolation):
    """CACP-IMMUT-0: Attempt to write to a sealed ConvergenceProof."""


class ScopeError(CACPViolation):
    """CACP-SCOPE-0: Unknown ACI pipeline record type."""


class OriginError(CACPViolation):
    """CACP-ORIGIN-0: Proof references zero ACI cycle records."""


class CycleError(CACPViolation):
    """CACP-CYCLE-0: Incomplete ACI cycle — missing required pipeline stages."""


class TrendError(CACPViolation):
    """CACP-TREND-0: Unknown convergence trend classification."""


class HUMAN0NotificationError(CACPViolation):
    """CACP-HUMAN0-0: DEGRADING proof requires non-empty notified_by before acknowledgement."""


class ProofError(CACPViolation):
    """CACP-PROOF-0: Convergence proof HMAC binding invalid."""


# ── Enumerations ──────────────────────────────────────────────────────────────

class ConvergenceTrend(str, Enum):
    IMPROVING  = "IMPROVING"
    STABLE     = "STABLE"
    DEGRADING  = "DEGRADING"


class ProofStatus(str, Enum):
    PENDING      = "PENDING"
    CERTIFIED    = "CERTIFIED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


# ── Data records ──────────────────────────────────────────────────────────────

@dataclass
class CycleRecord:
    """One complete ACI cycle — CACP-CYCLE-0 requires all 5 stages present."""
    cycle_id: str
    stage_records: Dict[str, Any]   # keyed by stage name: CASL/CADE/CAPE/CAOE/CALI
    chi_before: float
    chi_after: float
    delta_chi: float
    outcome_classification: str     # from CAOE: IMPROVED/NEUTRAL/DEGRADED
    cali_signal: float              # adaptation signal from CALI
    timestamp_utc: float
    hmac_digest: str
    sealed: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycle_id":               self.cycle_id,
            "stages_present":         sorted(self.stage_records.keys()),
            "chi_before":             self.chi_before,
            "chi_after":              self.chi_after,
            "delta_chi":              self.delta_chi,
            "outcome_classification": self.outcome_classification,
            "cali_signal":            self.cali_signal,
            "timestamp_utc":          self.timestamp_utc,
            "hmac_digest":            self.hmac_digest,
            "sealed":                 self.sealed,
        }


@dataclass
class ConvergenceProof:
    """Cryptographic proof of ACI convergence — CACP-PROOF-0."""
    proof_id: str
    cycle_ids: List[str]
    cycle_count: int
    mean_delta_chi: float
    trend: str                      # CACP-TREND-0
    convergence_score: float        # [0.0, 1.0] — deterministic
    proof_binding: str              # HMAC-SHA-256 of all cycle inputs — CACP-PROOF-0
    status: str = ProofStatus.PENDING.value
    degrading_flag: bool = False    # CACP-HUMAN0-0
    notified_by: str = ""           # CACP-HUMAN0-0: required before ACKNOWLEDGED when DEGRADING
    acknowledged_at: Optional[float] = None
    timestamp_utc: float = field(default_factory=time.time)
    hmac_digest: str = ""
    sealed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proof_id":          self.proof_id,
            "cycle_ids":         self.cycle_ids,
            "cycle_count":       self.cycle_count,
            "mean_delta_chi":    self.mean_delta_chi,
            "trend":             self.trend,
            "convergence_score": self.convergence_score,
            "proof_binding":     self.proof_binding,
            "status":            self.status,
            "degrading_flag":    self.degrading_flag,
            "notified_by":       self.notified_by,
            "acknowledged_at":   self.acknowledged_at,
            "timestamp_utc":     self.timestamp_utc,
            "hmac_digest":       self.hmac_digest,
            "sealed":            self.sealed,
        }


@dataclass
class LedgerRecord:
    """Append-only ConvergenceLedger entry — CACP-CHAIN-0."""
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
            "record_id":    self.record_id,
            "operation":    self.operation,
            "subject_id":   self.subject_id,
            "details":      self.details,
            "prev_hash":    self.prev_hash,
            "hmac_digest":  self.hmac_digest,
            "timestamp_utc": self.timestamp_utc,
            "sealed":       self.sealed,
        }


# ── CycleAggregator ───────────────────────────────────────────────────────────

class CycleAggregator:
    """
    CACP-SCOPE-0 / CACP-ORIGIN-0 / CACP-CYCLE-0
    Aggregates and validates ACI pipeline records into complete cycles.
    """

    def __init__(self) -> None:
        self._cycles: List[CycleRecord] = []
        self._prev_hash: str = "GENESIS"

    def aggregate(self, stage_records: Dict[str, Any]) -> CycleRecord:
        """
        Validate and seal a complete ACI cycle.
        CACP-SCOPE-0: all keys must be valid ACI stages.
        CACP-CYCLE-0: all 5 stages must be present.
        CACP-ORIGIN-0: at least one record must be non-empty.
        """
        # CACP-SCOPE-0: reject unknown stage names
        unknown = set(stage_records.keys()) - ACI_PIPELINE_STAGES
        if unknown:
            raise ScopeError(
                f"CACP-SCOPE-0: Unknown ACI pipeline stage(s): {sorted(unknown)}. "
                f"Valid: {sorted(ACI_PIPELINE_STAGES)}"
            )
        # CACP-CYCLE-0: all 5 stages required
        missing = ACI_PIPELINE_STAGES - set(stage_records.keys())
        if missing:
            raise CycleError(
                f"CACP-CYCLE-0: Incomplete ACI cycle — missing stage(s): {sorted(missing)}. "
                f"All 5 pipeline stages required: CASL, CADE, CAPE, CAOE, CALI"
            )
        # CACP-ORIGIN-0: at least one stage record must be non-empty
        non_empty = [v for v in stage_records.values() if v]
        if not non_empty:
            raise OriginError(
                "CACP-ORIGIN-0: All stage records are empty — at least one must carry data"
            )

        # Extract CHI values from stage records
        casl_rec  = stage_records.get("CASL") or {}
        caoe_rec  = stage_records.get("CAOE") or {}
        cali_rec  = stage_records.get("CALI") or {}
        chi_before = float(casl_rec.get("chi_score", caoe_rec.get("chi_before", 0.0)))
        chi_after  = float(caoe_rec.get("chi_after", chi_before))
        delta_chi  = round(chi_after - chi_before, 6)
        outcome    = str(caoe_rec.get("classification", "NEUTRAL"))
        cali_signal = float(cali_rec.get("raw_signal", 0.0))

        cycle_id = str(uuid.uuid4())
        now = time.time()
        payload = f"{cycle_id}|{chi_before}|{chi_after}|{delta_chi}|{outcome}|{cali_signal}"
        digest = _hmac_digest(payload, self._prev_hash)
        self._prev_hash = digest

        cycle = CycleRecord(
            cycle_id=cycle_id,
            stage_records=dict(stage_records),
            chi_before=chi_before,
            chi_after=chi_after,
            delta_chi=delta_chi,
            outcome_classification=outcome,
            cali_signal=cali_signal,
            timestamp_utc=now,
            hmac_digest=digest,
            sealed=True,
        )
        self._cycles.append(cycle)
        return cycle

    def list_cycles(self) -> List[CycleRecord]:
        return list(self._cycles)

    def get_cycle(self, cycle_id: str) -> Optional[CycleRecord]:
        for c in self._cycles:
            if c.cycle_id == cycle_id:
                return c
        return None


# ── ConvergenceEngine ─────────────────────────────────────────────────────────

class ConvergenceEngine:
    """
    CACP-DETERM-0 / CACP-TREND-0 / CACP-PROOF-0
    Computes deterministic convergence scores and trend classifications.
    """

    _VALID_TRENDS = {t.value for t in ConvergenceTrend}

    def compute(self, cycles: List[CycleRecord]) -> Tuple[float, str, float, str]:
        """
        Compute (mean_delta_chi, trend, convergence_score, proof_binding).
        CACP-DETERM-0: purely deterministic — same inputs → same outputs.
        CACP-PROOF-0:  proof_binding is HMAC-SHA-256 of all cycle digests.
        """
        if not cycles:
            raise OriginError(
                "CACP-ORIGIN-0: Cannot compute convergence with zero cycles"
            )

        deltas = [c.delta_chi for c in cycles]
        mean_delta = round(sum(deltas) / len(deltas), 6)

        # CACP-TREND-0: deterministic classification
        if mean_delta >= _IMPROVING_THRESHOLD:
            trend = ConvergenceTrend.IMPROVING.value
        elif mean_delta <= _DEGRADING_THRESHOLD:
            trend = ConvergenceTrend.DEGRADING.value
        else:
            trend = ConvergenceTrend.STABLE.value

        # CACP-TREND-0: validate produced trend
        if trend not in self._VALID_TRENDS:
            raise TrendError(
                f"CACP-TREND-0: Computed unknown trend '{trend}'; "
                f"valid: {sorted(self._VALID_TRENDS)}"
            )

        # CACP-DETERM-0: convergence score — normalised mean_delta mapped to [0, 1]
        # Score = 0.5 baseline + clamp(mean_delta / 0.20, -0.5, +0.5)
        score = round(0.5 + max(-0.5, min(0.5, mean_delta / 0.20)), 4)

        # CACP-PROOF-0: binding HMAC over all cycle HMAC digests
        chain = "|".join(sorted(c.hmac_digest for c in cycles))
        proof_binding = hmac.new(
            _HMAC_KEY, chain.encode(), hashlib.sha256
        ).hexdigest()

        return mean_delta, trend, score, proof_binding


# ── ProofRegistry ─────────────────────────────────────────────────────────────

class ProofRegistry:
    """
    CACP-HUMAN0-0 / CACP-IMMUT-0
    Stores and manages ConvergenceProofs; enforces HUMAN-0 acknowledgement gate
    for DEGRADING proofs.
    """

    def __init__(self) -> None:
        self._proofs: List[ConvergenceProof] = []
        self._prev_hash: str = "GENESIS"

    def register(
        self,
        cycle_ids: List[str],
        mean_delta_chi: float,
        trend: str,
        convergence_score: float,
        proof_binding: str,
    ) -> ConvergenceProof:
        """Register a new ConvergenceProof — starts PENDING."""
        proof_id = str(uuid.uuid4())
        now = time.time()
        degrading = trend == ConvergenceTrend.DEGRADING.value
        payload = f"{proof_id}|{trend}|{mean_delta_chi}|{convergence_score}|{proof_binding}"
        digest = _hmac_digest(payload, self._prev_hash)
        self._prev_hash = digest

        proof = ConvergenceProof(
            proof_id=proof_id,
            cycle_ids=list(cycle_ids),
            cycle_count=len(cycle_ids),
            mean_delta_chi=mean_delta_chi,
            trend=trend,
            convergence_score=convergence_score,
            proof_binding=proof_binding,
            status=ProofStatus.CERTIFIED.value,
            degrading_flag=degrading,
            notified_by="",
            timestamp_utc=now,
            hmac_digest=digest,
            sealed=True,
        )
        self._proofs.append(proof)
        return proof

    def acknowledge(self, proof_id: str, notified_by: str) -> ConvergenceProof:
        """
        HUMAN-0 acknowledges a DEGRADING proof — CACP-HUMAN0-0.
        notified_by must be non-empty for DEGRADING proofs.
        """
        proof = self._get_proof(proof_id)
        # CACP-IMMUT-0: cannot re-acknowledge
        if proof.status == ProofStatus.ACKNOWLEDGED.value:
            raise ImmutabilityViolation(
                f"CACP-IMMUT-0: Proof '{proof_id}' already acknowledged"
            )
        # CACP-HUMAN0-0: DEGRADING requires non-empty notified_by
        if proof.degrading_flag:
            if not notified_by or not str(notified_by).strip():
                raise HUMAN0NotificationError(
                    "CACP-HUMAN0-0: DEGRADING convergence proof requires non-empty "
                    "notified_by before acknowledgement — HUMAN-0 identity required"
                )
        proof.notified_by = str(notified_by).strip()
        proof.status = ProofStatus.ACKNOWLEDGED.value
        proof.acknowledged_at = time.time()
        return proof

    def _get_proof(self, proof_id: str) -> ConvergenceProof:
        for p in self._proofs:
            if p.proof_id == proof_id:
                return p
        raise ProofError(f"CACP-PROOF-0: Proof '{proof_id}' not found")

    def list_proofs(self, trend: Optional[str] = None) -> List[ConvergenceProof]:
        if trend:
            return [p for p in self._proofs if p.trend == trend]
        return list(self._proofs)

    def get_proof(self, proof_id: str) -> Optional[ConvergenceProof]:
        for p in self._proofs:
            if p.proof_id == proof_id:
                return p
        return None

    def degrading_unacknowledged(self) -> List[ConvergenceProof]:
        return [
            p for p in self._proofs
            if p.degrading_flag and p.status != ProofStatus.ACKNOWLEDGED.value
        ]


# ── ConvergenceLedger ─────────────────────────────────────────────────────────

class ConvergenceLedger:
    """
    CACP-CHAIN-0 / CACP-APPEND-0 / CACP-IMMUT-0
    HMAC-SHA-256-chained append-only ledger sealing every CACP operation.
    """

    def __init__(self) -> None:
        self._records: List[LedgerRecord] = []
        self._head: str = "GENESIS"

    def append(self, operation: str, subject_id: str, details: Dict[str, Any]) -> LedgerRecord:
        """Append a sealed record — CACP-CHAIN-0, CACP-APPEND-0."""
        self._verify_chain()
        record_id = str(uuid.uuid4())
        now = time.time()
        payload = f"{record_id}|{operation}|{subject_id}|{now}"
        digest = _hmac_digest(payload, self._head)
        rec = LedgerRecord(
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
        """CACP-CHAIN-0: verify full chain integrity before every append."""
        if not self._records:
            return True
        prev = "GENESIS"
        for rec in self._records:
            expected_payload = f"{rec.record_id}|{rec.operation}|{rec.subject_id}|{rec.timestamp_utc}"
            expected = _hmac_digest(expected_payload, prev)
            if not hmac.compare_digest(expected, rec.hmac_digest):
                raise ChainBreakError(
                    f"CACP-CHAIN-0: Chain integrity broken at record {rec.record_id}"
                )
            prev = rec.hmac_digest
        return True

    def verify_chain(self) -> Dict[str, Any]:
        ok = self._verify_chain()
        return {
            "chain_valid":   ok,
            "record_count":  len(self._records),
            "head":          self._head,
        }

    def list_records(self) -> List[LedgerRecord]:
        return list(self._records)


# ── CACPAuditor ───────────────────────────────────────────────────────────────

class CACPAuditor:
    """CACP-AUDIT-0: Every CACP operation sealed in append-only HMAC-chained audit log."""

    def __init__(self) -> None:
        self._entries: List[Dict[str, Any]] = []
        self._prev: str = "GENESIS"

    def record(self, operation: str, subject_id: str, outcome: str, detail: str = "") -> None:
        entry_id = str(uuid.uuid4())
        now = time.time()
        payload = f"{entry_id}|{operation}|{subject_id}|{outcome}|{now}"
        digest = _hmac_digest(payload, self._prev)
        self._prev = digest
        self._entries.append({
            "audit_id":    entry_id,
            "operation":   operation,
            "subject_id":  subject_id,
            "outcome":     outcome,
            "detail":      detail,
            "timestamp_utc": now,
            "hmac_digest": digest,
        })

    def list_entries(self) -> List[Dict[str, Any]]:
        return list(self._entries)


# ── CACPEngine (facade) ───────────────────────────────────────────────────────

class CACPEngine:
    """
    Facade coordinating CycleAggregator, ConvergenceEngine, ProofRegistry,
    ConvergenceLedger, and CACPAuditor.

    Arc III ACI Meta-layer — proves cryptographically that the full ACI pipeline
    (CASL→CADE→CAPE→CAOE→CALI) is converging toward constitutional health.
    """

    def __init__(self) -> None:
        self._aggregator = CycleAggregator()
        self._engine     = ConvergenceEngine()
        self._registry   = ProofRegistry()
        self._ledger     = ConvergenceLedger()
        self._auditor    = CACPAuditor()

    # ── Cycle aggregation ────────────────────────────────────────────────

    def aggregate_cycle(self, stage_records: Dict[str, Any]) -> CycleRecord:
        """
        Aggregate a complete ACI cycle from all 5 pipeline stage records.
        CACP-SCOPE-0, CACP-CYCLE-0, CACP-ORIGIN-0 enforced.
        """
        cycle = self._aggregator.aggregate(stage_records)
        self._ledger.append("AGGREGATE", cycle.cycle_id, {
            "stages": sorted(stage_records.keys()),
            "chi_before": cycle.chi_before,
            "chi_after":  cycle.chi_after,
            "delta_chi":  cycle.delta_chi,
        })
        self._auditor.record(
            "AGGREGATE", cycle.cycle_id, "OK",
            f"delta_chi={cycle.delta_chi:+.4f}, outcome={cycle.outcome_classification}"
        )
        return cycle

    # ── Convergence proof ────────────────────────────────────────────────

    def prove(self, cycle_ids: Optional[List[str]] = None) -> ConvergenceProof:
        """
        Compute and register a ConvergenceProof.
        Uses specified cycle_ids or all aggregated cycles if None.
        CACP-DETERM-0, CACP-TREND-0, CACP-PROOF-0 enforced.
        CACP-HUMAN0-0: DEGRADING proofs require HUMAN-0 acknowledgement.
        """
        if cycle_ids is not None:
            cycles = [
                c for c in self._aggregator.list_cycles()
                if c.cycle_id in set(cycle_ids)
            ]
            if not cycles:
                raise OriginError(
                    "CACP-ORIGIN-0: No matching cycles found for provided cycle_ids"
                )
        else:
            cycles = self._aggregator.list_cycles()
            if not cycles:
                raise OriginError(
                    "CACP-ORIGIN-0: No aggregated cycles available — aggregate at least one cycle first"
                )

        mean_delta, trend, score, binding = self._engine.compute(cycles)
        proof = self._registry.register(
            cycle_ids=[c.cycle_id for c in cycles],
            mean_delta_chi=mean_delta,
            trend=trend,
            convergence_score=score,
            proof_binding=binding,
        )
        self._ledger.append("PROVE", proof.proof_id, {
            "cycle_count":       proof.cycle_count,
            "mean_delta_chi":    proof.mean_delta_chi,
            "trend":             proof.trend,
            "convergence_score": proof.convergence_score,
            "degrading_flag":    proof.degrading_flag,
        })
        self._auditor.record(
            "PROVE", proof.proof_id,
            "DEGRADING_FLAGGED" if proof.degrading_flag else "OK",
            f"trend={trend}, score={score:.4f}, cycles={len(cycles)}"
        )
        return proof

    # ── HUMAN-0 acknowledgement ──────────────────────────────────────────

    def acknowledge(self, proof_id: str, notified_by: str) -> ConvergenceProof:
        """HUMAN-0 acknowledges a DEGRADING proof — CACP-HUMAN0-0."""
        proof = self._registry.acknowledge(proof_id, notified_by)
        self._ledger.append("ACKNOWLEDGE", proof_id, {
            "notified_by": proof.notified_by,
            "trend":       proof.trend,
        })
        self._auditor.record(
            "ACKNOWLEDGE", proof_id, "ACKNOWLEDGED",
            f"notified_by={proof.notified_by}"
        )
        return proof

    # ── Query / status ───────────────────────────────────────────────────

    def list_cycles(self) -> List[CycleRecord]:
        return self._aggregator.list_cycles()

    def get_cycle(self, cycle_id: str) -> Optional[CycleRecord]:
        return self._aggregator.get_cycle(cycle_id)

    def list_proofs(self, trend: Optional[str] = None) -> List[ConvergenceProof]:
        return self._registry.list_proofs(trend)

    def get_proof(self, proof_id: str) -> Optional[ConvergenceProof]:
        return self._registry.get_proof(proof_id)

    def degrading_unacknowledged(self) -> List[ConvergenceProof]:
        return self._registry.degrading_unacknowledged()

    def verify_chain(self) -> Dict[str, Any]:
        result = self._ledger.verify_chain()
        self._auditor.record("VERIFY_CHAIN", "LEDGER", "OK",
                             f"records={result['record_count']}, head={result['head'][:16]}…")
        return result

    def audit_log(self) -> List[Dict[str, Any]]:
        return self._auditor.list_entries()

    def status(self) -> Dict[str, Any]:
        cycles = self._aggregator.list_cycles()
        proofs = self._registry.list_proofs()
        degrading = self._registry.degrading_unacknowledged()
        return {
            "module":        "CACP",
            "phase":         229,
            "version":       "10.40.0",
            "arc":           "Arc III — Autonomous Constitutional Intelligence (ACI) Meta-layer",
            "innov":         "INNOV-134",
            "governor":      "DUSTIN L REID",
            "aci_loop":      "CASL→CADE→CAPE→CAOE→CALI→CACP (convergence proof)",
            "pipeline_stages": sorted(ACI_PIPELINE_STAGES),
            "cycles_aggregated":          len(cycles),
            "proofs_certified":           len([p for p in proofs if p.status == "CERTIFIED"]),
            "proofs_acknowledged":        len([p for p in proofs if p.status == "ACKNOWLEDGED"]),
            "degrading_unacknowledged":   len(degrading),
            "hard_class_invariants": [
                "CACP-CHAIN-0",  "CACP-APPEND-0", "CACP-IMMUT-0",
                "CACP-SCOPE-0",  "CACP-ORIGIN-0", "CACP-CYCLE-0",
                "CACP-DETERM-0", "CACP-TREND-0",  "CACP-HUMAN0-0",
                "CACP-AUDIT-0",  "CACP-PROOF-0",
            ],
        }
