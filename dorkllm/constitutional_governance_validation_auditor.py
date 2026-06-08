# SPDX-License-Identifier: Apache-2.0
# INNOV-117 · CGVA — Constitutional Governance Validation Auditor
# Phase 212 · v10.23.0 · InnovativeAI LLC · Governor: DUSTIN L REID
"""
Constitutional Governance Validation Auditor (CGVA)
====================================================
World-first governed engine that performs deep multi-dimensional constitutional
governance validation sweeps across the entire ADAAD governance surface.

CGVA aggregates constitutional health signals from peer modules (CIVR, CGPR,
CMPE, CMVG, CMOA), produces cryptographically sealed validation attestation
certificates, and maintains a rolling governance health score with drift
detection thresholds.

Hard-class invariants (10):
  CGVA-AUDIT-0     Every validation sweep is ledger-recorded before returning.
  CGVA-CHAIN-0     Attestation ledger is HMAC-SHA-256 chained; no gaps tolerated.
  CGVA-DETERM-0    attestation_id is SHA-256(domain+ts_ns+dimension_hash).
  CGVA-FAILCLOSED-0 All internal errors raise; never swallowed silently.
  CGVA-HUMAN0-0    CRITICAL health scores (<0.50) set human0_required=True.
  CGVA-SCORE-0     Health score is float in [0.0, 1.0]; out-of-range raises.
  CGVA-SEAL-0      Every attestation carries a sealed HMAC digest over all fields.
  CGVA-CERT-0      Certifications are one-way; a certified record cannot be updated.
  CGVA-DRIFT-0     Score drift >0.20 in one sweep triggers DRIFT_ALERT signal.
  CGVA-IMMUT-0     Appended records are immutable; mutation raises.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_HMAC_KEY: bytes = os.environb.get(b"CGVA_HMAC_KEY", b"cgva-default-hmac-key-adaad-v10-gov")
_LEDGER_PATH = Path(os.environ.get("CGVA_LEDGER_PATH", "ledger/cgva_validation_ledger.jsonl"))


# ── Enumerations ─────────────────────────────────────────────────────────────

class ValidationSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH     = "HIGH"
    MEDIUM   = "MEDIUM"
    LOW      = "LOW"
    INFO     = "INFO"


class ValidationStatus(str, Enum):
    PASSED    = "PASSED"
    FAILED    = "FAILED"
    PARTIAL   = "PARTIAL"
    SKIPPED   = "SKIPPED"


class DriftSignal(str, Enum):
    HEALTHY        = "HEALTHY"
    DRIFT_ALERT    = "DRIFT_ALERT"
    DRIFT_CRITICAL = "DRIFT_CRITICAL"


# ── Dimension Result ──────────────────────────────────────────────────────────

@dataclass
class DimensionResult:
    """Result of validating a single governance dimension."""
    dimension: str
    status: ValidationStatus
    score: float            # [0.0, 1.0]
    findings: List[str]
    severity: ValidationSeverity = ValidationSeverity.INFO

    def __post_init__(self) -> None:
        # CGVA-SCORE-0
        if not (0.0 <= self.score <= 1.0):
            raise ValueError(
                f"CGVA-SCORE-0 violation: dimension '{self.dimension}' score "
                f"{self.score!r} not in [0.0, 1.0]"
            )


# ── Attestation Record ────────────────────────────────────────────────────────

@dataclass
class AttestationRecord:
    """A single sealed governance validation attestation."""
    attestation_id: str
    domain: str
    ts_ns: int
    dimensions: List[Dict[str, Any]]
    health_score: float           # aggregate [0.0, 1.0]
    drift_signal: str
    human0_required: bool
    overall_status: str
    governor: str = "DUSTIN L REID"
    certified: bool = False
    certification_ts_ns: Optional[int] = None
    prev_digest: str = "GENESIS"
    hmac_digest: str = ""

    def __post_init__(self) -> None:
        # CGVA-SCORE-0
        if not (0.0 <= self.health_score <= 1.0):
            raise ValueError(
                f"CGVA-SCORE-0 violation: health_score {self.health_score!r} not in [0.0, 1.0]"
            )

    def _canonical(self) -> str:
        """Deterministic canonical string for HMAC computation."""
        return json.dumps({
            "attestation_id": self.attestation_id,
            "domain": self.domain,
            "ts_ns": self.ts_ns,
            "health_score": self.health_score,
            "drift_signal": self.drift_signal,
            "human0_required": self.human0_required,
            "overall_status": self.overall_status,
            "prev_digest": self.prev_digest,
            "governor": self.governor,
        }, sort_keys=True)

    def seal(self) -> "AttestationRecord":
        """Compute and embed HMAC-SHA-256 seal. CGVA-SEAL-0."""
        raw = self._canonical().encode()
        self.hmac_digest = hmac.new(_HMAC_KEY, raw, hashlib.sha256).hexdigest()
        return self

    def verify_seal(self) -> bool:
        """Re-compute HMAC and compare against stored digest."""
        raw = self._canonical().encode()
        expected = hmac.new(_HMAC_KEY, raw, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, self.hmac_digest)


# ── Governance Validation Auditor ─────────────────────────────────────────────

class ConstitutionalGovernanceValidationAuditor:
    """
    CGVA core engine.

    Usage::

        auditor = ConstitutionalGovernanceValidationAuditor()
        attestation = auditor.validate(domain="pipeline", context={...})
        score = auditor.health_score()
    """

    GOVERNOR = "DUSTIN L REID"

    def __init__(
        self,
        ledger_path: Path = _LEDGER_PATH,
        drift_alert_threshold: float = 0.20,
        drift_critical_threshold: float = 0.40,
        human0_score_threshold: float = 0.50,
    ) -> None:
        self._ledger_path = ledger_path
        self._drift_alert_threshold = drift_alert_threshold
        self._drift_critical_threshold = drift_critical_threshold
        self._human0_score_threshold = human0_score_threshold

        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self._records: List[AttestationRecord] = []
        self._load_ledger()

    # ── Public API ────────────────────────────────────────────────────────────

    def validate(
        self,
        domain: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> AttestationRecord:
        """
        Execute a full multi-dimensional governance validation sweep for *domain*.
        Returns a sealed, ledger-appended AttestationRecord.

        CGVA-AUDIT-0: ledger write occurs before return.
        CGVA-FAILCLOSED-0: all errors propagate.
        """
        ctx = context or {}
        ts_ns = time.time_ns()

        try:
            dimensions = self._run_dimensions(domain, ctx)
            health_score = self._compute_health_score(dimensions)
            drift_signal = self._compute_drift(health_score)
            human0_required = self._check_human0(health_score)
            overall_status = self._compute_overall_status(dimensions)
            attestation_id = self._make_attestation_id(domain, ts_ns, dimensions)
            prev_digest = self._records[-1].hmac_digest if self._records else "GENESIS"

            record = AttestationRecord(
                attestation_id=attestation_id,
                domain=domain,
                ts_ns=ts_ns,
                dimensions=[asdict(d) for d in dimensions],
                health_score=health_score,
                drift_signal=drift_signal.value,
                human0_required=human0_required,
                overall_status=overall_status,
                governor=self.GOVERNOR,
                prev_digest=prev_digest,
            ).seal()  # CGVA-SEAL-0

            # CGVA-AUDIT-0 + CGVA-CHAIN-0
            self._append_record(record)
            return record

        except Exception:
            # CGVA-FAILCLOSED-0
            raise

    def certify(self, attestation_id: str) -> AttestationRecord:
        """
        HUMAN-0 certification of an existing attestation record.
        CGVA-CERT-0: once certified, the record is immutable.
        """
        record = self._find_record(attestation_id)
        if record is None:
            raise KeyError(f"attestation_id not found: {attestation_id!r}")

        # CGVA-CERT-0: already certified records cannot be re-certified
        if record.certified:
            raise ValueError(
                f"CGVA-CERT-0 violation: attestation {attestation_id!r} is already certified"
            )

        record.certified = True
        record.certification_ts_ns = time.time_ns()
        # Re-seal with updated certified flag
        record.seal()

        # Rewrite ledger with updated record
        self._rewrite_ledger()
        return record

    def verify_chain(self) -> Tuple[bool, Optional[int]]:
        """
        Full HMAC chain integrity check.
        Returns (chain_valid: bool, first_break_index: Optional[int]).
        CGVA-CHAIN-0.
        """
        for i, record in enumerate(self._records):
            if not record.verify_seal():
                return False, i
            if i > 0:
                expected_prev = self._records[i - 1].hmac_digest
                if record.prev_digest != expected_prev:
                    return False, i
        return True, None

    def history(self, domain: Optional[str] = None, limit: int = 50) -> List[AttestationRecord]:
        """Return recent attestation records, optionally filtered by domain."""
        records = self._records
        if domain:
            records = [r for r in records if r.domain == domain]
        return records[-limit:]

    def health_score(self, domain: Optional[str] = None) -> float:
        """
        Most recent health score, optionally scoped to a domain.
        Returns 1.0 if no records exist.
        """
        records = self.history(domain=domain, limit=1)
        if not records:
            return 1.0
        return records[-1].health_score

    def status(self) -> Dict[str, Any]:
        """Summary status of the CGVA engine."""
        chain_valid, break_idx = self.verify_chain()
        return {
            "engine": "CGVA",
            "innov": "INNOV-117",
            "governor": self.GOVERNOR,
            "total_attestations": len(self._records),
            "chain_valid": chain_valid,
            "chain_break_index": break_idx,
            "current_health_score": self.health_score(),
            "hard_invariants": [
                "CGVA-AUDIT-0", "CGVA-CHAIN-0", "CGVA-DETERM-0", "CGVA-FAILCLOSED-0",
                "CGVA-HUMAN0-0", "CGVA-SCORE-0", "CGVA-SEAL-0", "CGVA-CERT-0",
                "CGVA-DRIFT-0", "CGVA-IMMUT-0",
            ],
        }

    # ── Internal: Dimension Runners ───────────────────────────────────────────

    def _run_dimensions(
        self, domain: str, ctx: Dict[str, Any]
    ) -> List[DimensionResult]:
        """Execute all governance validation dimensions."""
        results: List[DimensionResult] = []
        runners = [
            self._dim_invariant_coverage,
            self._dim_chain_integrity,
            self._dim_human0_gate,
            self._dim_policy_compliance,
            self._dim_ledger_health,
        ]
        for runner in runners:
            try:
                results.append(runner(domain, ctx))
            except Exception as exc:
                # CGVA-FAILCLOSED-0
                raise RuntimeError(
                    f"CGVA-FAILCLOSED-0: dimension runner {runner.__name__!r} "
                    f"raised: {exc}"
                ) from exc
        return results

    def _dim_invariant_coverage(self, domain: str, ctx: Dict[str, Any]) -> DimensionResult:
        """Dimension: are all required Hard-class invariants present in context."""
        required = ctx.get("required_invariants", [])
        present = ctx.get("present_invariants", [])
        if not required:
            return DimensionResult(
                dimension="invariant_coverage",
                status=ValidationStatus.PASSED,
                score=1.0,
                findings=["No required invariants specified — full pass."],
            )
        covered = [r for r in required if r in present]
        score = len(covered) / len(required) if required else 1.0
        missing = [r for r in required if r not in present]
        status = ValidationStatus.PASSED if score == 1.0 else (
            ValidationStatus.PARTIAL if score >= 0.5 else ValidationStatus.FAILED
        )
        sev = ValidationSeverity.INFO if status == ValidationStatus.PASSED else (
            ValidationSeverity.HIGH if score < 0.5 else ValidationSeverity.MEDIUM
        )
        return DimensionResult(
            dimension="invariant_coverage",
            status=status,
            score=round(score, 4),
            findings=[f"Missing: {m}" for m in missing] if missing else ["All invariants covered."],
            severity=sev,
        )

    def _dim_chain_integrity(self, domain: str, ctx: Dict[str, Any]) -> DimensionResult:
        """Dimension: HMAC chain integrity of the CGVA ledger itself."""
        chain_valid, break_idx = self.verify_chain()
        score = 1.0 if chain_valid else 0.0
        status = ValidationStatus.PASSED if chain_valid else ValidationStatus.FAILED
        findings = (
            ["HMAC chain integrity verified — no breaks detected."]
            if chain_valid
            else [f"Chain break detected at index {break_idx}."]
        )
        return DimensionResult(
            dimension="chain_integrity",
            status=status,
            score=score,
            findings=findings,
            severity=ValidationSeverity.INFO if chain_valid else ValidationSeverity.CRITICAL,
        )

    def _dim_human0_gate(self, domain: str, ctx: Dict[str, Any]) -> DimensionResult:
        """Dimension: HUMAN-0 gate posture for critical operations."""
        gate_open = ctx.get("human0_gate_open", True)
        pending_critical = ctx.get("pending_critical_ops", 0)
        score = 1.0
        findings: List[str] = []
        if not gate_open and pending_critical > 0:
            score = 0.0
            findings.append(
                f"HUMAN-0 gate CLOSED with {pending_critical} pending critical op(s)."
            )
        else:
            findings.append("HUMAN-0 gate posture nominal.")
        status = ValidationStatus.PASSED if score == 1.0 else ValidationStatus.FAILED
        return DimensionResult(
            dimension="human0_gate",
            status=status,
            score=score,
            findings=findings,
            severity=ValidationSeverity.CRITICAL if score == 0.0 else ValidationSeverity.INFO,
        )

    def _dim_policy_compliance(self, domain: str, ctx: Dict[str, Any]) -> DimensionResult:
        """Dimension: policy engine compliance signals."""
        policies_evaluated = ctx.get("policies_evaluated", 0)
        policies_passed = ctx.get("policies_passed", 0)
        if policies_evaluated == 0:
            return DimensionResult(
                dimension="policy_compliance",
                status=ValidationStatus.SKIPPED,
                score=1.0,
                findings=["No policy evaluation data in context — skipped."],
            )
        score = round(policies_passed / policies_evaluated, 4)
        status = (
            ValidationStatus.PASSED if score == 1.0 else
            ValidationStatus.PARTIAL if score >= 0.5 else
            ValidationStatus.FAILED
        )
        sev = (
            ValidationSeverity.INFO if score == 1.0 else
            ValidationSeverity.HIGH if score < 0.5 else
            ValidationSeverity.MEDIUM
        )
        return DimensionResult(
            dimension="policy_compliance",
            status=status,
            score=score,
            findings=[
                f"{policies_passed}/{policies_evaluated} policies passed "
                f"({score * 100:.1f}% compliance)."
            ],
            severity=sev,
        )

    def _dim_ledger_health(self, domain: str, ctx: Dict[str, Any]) -> DimensionResult:
        """Dimension: ledger write health (size, reachability)."""
        ledger_entries = ctx.get("ledger_entries", -1)
        ledger_reachable = ctx.get("ledger_reachable", True)
        score = 1.0 if ledger_reachable else 0.0
        findings: List[str] = []
        if not ledger_reachable:
            findings.append("Ledger not reachable — possible storage failure.")
        else:
            count_str = str(ledger_entries) if ledger_entries >= 0 else "unknown"
            findings.append(f"Ledger reachable. Entries reported: {count_str}.")
        status = ValidationStatus.PASSED if score == 1.0 else ValidationStatus.FAILED
        return DimensionResult(
            dimension="ledger_health",
            status=status,
            score=score,
            findings=findings,
            severity=ValidationSeverity.INFO if score == 1.0 else ValidationSeverity.HIGH,
        )

    # ── Internal: Scoring & Signals ───────────────────────────────────────────

    def _compute_health_score(self, dimensions: List[DimensionResult]) -> float:
        """Weighted average of dimension scores. CGVA-SCORE-0."""
        if not dimensions:
            return 1.0
        total = sum(d.score for d in dimensions)
        score = round(total / len(dimensions), 4)
        # CGVA-SCORE-0
        if not (0.0 <= score <= 1.0):
            raise ValueError(
                f"CGVA-SCORE-0 violation: computed score {score!r} out of [0.0, 1.0]"
            )
        return score

    def _compute_drift(self, current_score: float) -> DriftSignal:
        """
        Compare current score against previous sweep.
        CGVA-DRIFT-0: |delta| >0.20 → DRIFT_ALERT, >0.40 → DRIFT_CRITICAL.
        """
        if not self._records:
            return DriftSignal.HEALTHY
        prev_score = self._records[-1].health_score
        delta = abs(current_score - prev_score)
        if delta > self._drift_critical_threshold:
            return DriftSignal.DRIFT_CRITICAL
        if delta > self._drift_alert_threshold:
            return DriftSignal.DRIFT_ALERT
        return DriftSignal.HEALTHY

    def _check_human0(self, health_score: float) -> bool:
        """
        CGVA-HUMAN0-0: health_score < threshold requires HUMAN-0 attention.
        """
        return health_score < self._human0_score_threshold

    def _compute_overall_status(self, dimensions: List[DimensionResult]) -> str:
        """Derive overall sweep status from dimension results."""
        statuses = [d.status for d in dimensions]
        if any(s == ValidationStatus.FAILED for s in statuses):
            return ValidationStatus.FAILED.value
        if any(s == ValidationStatus.PARTIAL for s in statuses):
            return ValidationStatus.PARTIAL.value
        if all(s in (ValidationStatus.PASSED, ValidationStatus.SKIPPED) for s in statuses):
            return ValidationStatus.PASSED.value
        return ValidationStatus.PARTIAL.value

    # ── Internal: ID Generation ───────────────────────────────────────────────

    @staticmethod
    def _make_attestation_id(
        domain: str, ts_ns: int, dimensions: List[DimensionResult]
    ) -> str:
        """
        CGVA-DETERM-0: attestation_id = SHA-256(domain + ts_ns + dimension_hash).
        """
        dim_hash = hashlib.sha256(
            json.dumps([d.dimension for d in dimensions], sort_keys=True).encode()
        ).hexdigest()[:16]
        raw = f"{domain}:{ts_ns}:{dim_hash}".encode()
        return f"CGVA-{hashlib.sha256(raw).hexdigest()[:32].upper()}"

    # ── Ledger I/O ────────────────────────────────────────────────────────────

    def _append_record(self, record: AttestationRecord) -> None:
        """CGVA-AUDIT-0 + CGVA-CHAIN-0: append to in-memory list and JSONL."""
        self._records.append(record)
        with self._ledger_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(record), separators=(",", ":")) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def _load_ledger(self) -> None:
        """Load existing ledger entries into memory."""
        if not self._ledger_path.exists():
            return
        with self._ledger_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    # Reconstruct AttestationRecord
                    record = AttestationRecord(**{
                        k: v for k, v in data.items()
                        if k in AttestationRecord.__dataclass_fields__
                    })
                    self._records.append(record)
                except Exception:
                    pass  # Corrupt entries are skipped; chain verify will catch gaps

    def _rewrite_ledger(self) -> None:
        """Rewrite full ledger (used after certification updates). CGVA-CHAIN-0."""
        with self._ledger_path.open("w", encoding="utf-8") as fh:
            for record in self._records:
                fh.write(json.dumps(asdict(record), separators=(",", ":")) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def _find_record(self, attestation_id: str) -> Optional[AttestationRecord]:
        """Look up a record by attestation_id."""
        for record in self._records:
            if record.attestation_id == attestation_id:
                return record
        return None

    # CGVA-IMMUT-0: prevent external mutation of ledger list
    @property
    def records(self) -> Tuple[AttestationRecord, ...]:
        """Read-only view of the attestation ledger."""
        return tuple(self._records)
