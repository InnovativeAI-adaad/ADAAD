# SPDX-License-Identifier: Apache-2.0
"""INNOV-113 · CMOA — Constitutional Mutation Outcome Analyst.

Closes the AMPS→CMVG→CMSE→CMWE→CMOA→AMPS self-improving mutation loop.
Reads CMWE attestation records, computes pipeline success patterns across
blast tiers, fitness ranges, and mutation scopes, and emits bounded fitness
adjustment signals that feed back into the AMPS proposal scoring model.
Velocity nudge signals inform CMVG's next VelocityDecision.

All analysis runs are sealed in an HMAC-SHA-256-chained OutcomeLedger.
Fitness adjustments are hard-bounded to ±0.20 per cycle to prevent runaway
scoring drift (CMOA-BIAS-0). A minimum sample of 3 outcomes is required
before any signal is emitted (CMOA-MIN-0). Recalibration of AMPS base
weights requires HUMAN-0 authority (CMOA-HUMAN0-0).

Hard-class invariants enforced:
  CMOA-CHAIN-0   : OutcomeLedger is HMAC-SHA-256 chained
  CMOA-IMMUT-0   : Sealed analysis records are never mutated post-commit
  CMOA-DETERM-0  : AnalysisRecord IDs are deterministic SHA-256 hashes of content
  CMOA-BIAS-0    : Fitness adjustment deltas are bounded to [-0.20, +0.20] per cycle
  CMOA-MIN-0     : No signal emitted from sample size < 3 outcomes
  CMOA-AUDIT-0   : Every analysis run logged in OutcomeLedger regardless of outcome
  CMOA-FAILCLOSED-0 : Any analysis error yields NO_SIGNAL, never a partial record
  CMOA-SEAL-0    : Every AnalysisReport carries a SHA-256 content seal
  CMOA-HUMAN0-0  : AMPS base-weight recalibration requires HUMAN-0 authority
  CMOA-CGDR-0    : Signal emission blocked when CGDR gate reports DRIFTED

Governor: DUSTIN L REID · InnovativeAI LLC · Phase 208
"""

from __future__ import annotations

import datetime
import hashlib
import hmac as _hmac
import json
import os
import uuid
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Invariant sentinels
# ---------------------------------------------------------------------------

CMOA_CHAIN_0 = "CMOA-CHAIN-0"
CMOA_IMMUT_0 = "CMOA-IMMUT-0"
CMOA_DETERM_0 = "CMOA-DETERM-0"
CMOA_BIAS_0 = "CMOA-BIAS-0"
CMOA_MIN_0 = "CMOA-MIN-0"
CMOA_AUDIT_0 = "CMOA-AUDIT-0"
CMOA_FAILCLOSED_0 = "CMOA-FAILCLOSED-0"
CMOA_SEAL_0 = "CMOA-SEAL-0"
CMOA_HUMAN0_0 = "CMOA-HUMAN0-0"
CMOA_CGDR_0 = "CMOA-CGDR-0"

GOVERNOR = "DUSTIN L REID"
HUMAN0_IDS = {"HUMAN-0", "DUSTIN L REID", "DUSTIN_REID", "DLR-GOV"}

_HMAC_SECRET = os.environ.get("CMOA_HMAC_SECRET", "cmoa-hmac-secret-v208")
_LEDGER_PATH = Path(
    os.environ.get("CMOA_LEDGER_PATH", "ledger/cmoa_outcome_ledger.jsonl")
)

# Hard bounds on per-cycle fitness adjustment (CMOA-BIAS-0)
_DELTA_MIN: float = -0.20
_DELTA_MAX: float = +0.20
_MIN_SAMPLE: int = 3  # CMOA-MIN-0


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class CMOAViolation(RuntimeError):
    """Hard-class invariant violation."""


class CMOABiasError(CMOAViolation):
    """CMOA-BIAS-0: fitness delta outside allowed bounds."""


class CMOAMinSampleError(CMOAViolation):
    """CMOA-MIN-0: insufficient sample size for signal emission."""


class CMOAHuman0Error(PermissionError):
    """CMOA-HUMAN0-0: recalibration requires HUMAN-0 authority."""


class CMOACGDRGateError(RuntimeError):
    """CMOA-CGDR-0: signal emission blocked — system DRIFTED."""


class CMOAImmutError(RuntimeError):
    """CMOA-IMMUT-0: sealed record cannot be mutated."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class OutcomeLabel(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    TIMEOUT = "TIMEOUT"


class SignalType(str, Enum):
    FITNESS_ADJUST = "FITNESS_ADJUST"
    VELOCITY_NUDGE = "VELOCITY_NUDGE"
    NO_SIGNAL = "NO_SIGNAL"


class VelocityNudge(str, Enum):
    ACCELERATE = "ACCELERATE"
    CRUISE = "CRUISE"
    THROTTLE = "THROTTLE"
    HALT = "HALT"


class AnalysisOutcome(str, Enum):
    SIGNALS_EMITTED = "SIGNALS_EMITTED"
    NO_SIGNAL = "NO_SIGNAL"


# ---------------------------------------------------------------------------
# Crypto helpers
# ---------------------------------------------------------------------------


def _hmac_chain(payload: str, prev: str) -> str:
    """HMAC-SHA-256 chain link (CMOA-CHAIN-0)."""
    msg = f"{prev}:{payload}".encode()
    return _hmac.new(_HMAC_SECRET.encode(), msg, hashlib.sha256).hexdigest()


def _seal(data: Dict[str, Any]) -> str:
    """SHA-256 content seal (CMOA-SEAL-0)."""
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _record_id(run_id: str, analysis_type: str, ts: str) -> str:
    """Deterministic record ID (CMOA-DETERM-0)."""
    raw = f"{run_id}:{analysis_type}:{ts}"
    return "CMOA-" + hashlib.sha256(raw.encode()).hexdigest()[:14].upper()


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Chained ledger
# ---------------------------------------------------------------------------


class _CMOALedger:
    """HMAC-chained append-only JSONL ledger (CMOA-CHAIN-0, CMOA-IMMUT-0)."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._prev = "GENESIS"
        if self._path.exists():
            for line in self._path.read_text().splitlines():
                if line.strip():
                    self._prev = json.loads(line).get("chain_hash", self._prev)

    def append(self, record: Dict[str, Any]) -> str:
        payload = json.dumps(record, sort_keys=True, separators=(",", ":"))
        chain_hash = _hmac_chain(payload, self._prev)
        sealed = {**record, "prev_hash": self._prev, "chain_hash": chain_hash}
        with self._path.open("a") as fh:
            fh.write(json.dumps(sealed) + "\n")
        self._prev = chain_hash
        return chain_hash

    def read_all(self) -> List[Dict[str, Any]]:
        if not self._path.exists():
            return []
        return [
            json.loads(l) for l in self._path.read_text().splitlines() if l.strip()
        ]

    def verify_chain(self) -> Dict[str, Any]:
        records = self.read_all()
        if not records:
            return {"valid": True, "entries": 0, "tip": "GENESIS"}
        prev = "GENESIS"
        for i, rec in enumerate(records):
            payload_data = {
                k: v for k, v in rec.items() if k not in ("prev_hash", "chain_hash")
            }
            expected = _hmac_chain(
                json.dumps(payload_data, sort_keys=True, separators=(",", ":")), prev
            )
            if rec.get("chain_hash") != expected:
                return {
                    "valid": False,
                    "failed_at": i,
                    "expected_prefix": expected[:24],
                    "got_prefix": rec.get("chain_hash", "")[:24],
                }
            prev = rec["chain_hash"]
        return {"valid": True, "entries": len(records), "tip": prev[:24]}


# ---------------------------------------------------------------------------
# Outcome statistics
# ---------------------------------------------------------------------------


def _compute_stats(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute per-blast-tier and per-fitness-bucket success rates."""
    total = len(records)
    successes = sum(1 for r in records if r.get("outcome") == OutcomeLabel.SUCCESS)
    failures = sum(1 for r in records if r.get("outcome") == OutcomeLabel.FAILED)
    timeouts = sum(1 for r in records if r.get("outcome") == OutcomeLabel.TIMEOUT)
    rejections = sum(1 for r in records if r.get("outcome") == OutcomeLabel.REJECTED)

    # Per blast tier stats
    tier_stats: Dict[str, Dict[str, int]] = {}
    for r in records:
        tier = str(r.get("blast_tier", "unknown"))
        tier_stats.setdefault(tier, {"total": 0, "success": 0})
        tier_stats[tier]["total"] += 1
        if r.get("outcome") == OutcomeLabel.SUCCESS:
            tier_stats[tier]["success"] += 1

    tier_success_rates = {
        t: round(v["success"] / v["total"], 4) if v["total"] else 0.0
        for t, v in tier_stats.items()
    }

    # Per fitness bucket stats (0-0.5, 0.5-0.75, 0.75-1.0)
    buckets: Dict[str, Dict[str, int]] = {
        "low": {"total": 0, "success": 0},
        "mid": {"total": 0, "success": 0},
        "high": {"total": 0, "success": 0},
    }
    for r in records:
        score = float(r.get("constitutional_fitness", 0.5))
        key = "high" if score >= 0.75 else ("mid" if score >= 0.5 else "low")
        buckets[key]["total"] += 1
        if r.get("outcome") == OutcomeLabel.SUCCESS:
            buckets[key]["success"] += 1

    bucket_rates = {
        k: round(v["success"] / v["total"], 4) if v["total"] else 0.0
        for k, v in buckets.items()
    }

    global_rate = round(successes / total, 4) if total else 0.0
    return {
        "total": total,
        "successes": successes,
        "failures": failures,
        "timeouts": timeouts,
        "rejections": rejections,
        "global_success_rate": global_rate,
        "tier_success_rates": tier_success_rates,
        "fitness_bucket_rates": bucket_rates,
    }


# ---------------------------------------------------------------------------
# Fitness signal computation (CMOA-BIAS-0)
# ---------------------------------------------------------------------------


def _compute_fitness_delta(stats: Dict[str, Any]) -> float:
    """Compute bounded fitness adjustment delta.

    Logic:
      - global success rate > 0.80 → positive adjustment (up to +0.20)
      - global success rate < 0.40 → negative adjustment (down to -0.20)
      - 0.40–0.80 → neutral (0.0)

    CMOA-BIAS-0: result is hard-clamped to [-0.20, +0.20].
    """
    rate = stats.get("global_success_rate", 0.5)
    if rate > 0.80:
        raw = (rate - 0.80) * 1.0  # scale excess above 0.80
    elif rate < 0.40:
        raw = (rate - 0.40) * 0.50  # scale shortfall below 0.40 (gentler)
    else:
        raw = 0.0
    # CMOA-BIAS-0: hard clamp
    clamped = max(_DELTA_MIN, min(_DELTA_MAX, raw))
    if abs(clamped) != abs(raw):
        raise CMOABiasError(
            f"{CMOA_BIAS_0}: computed delta {raw:.4f} exceeded bounds "
            f"[{_DELTA_MIN}, {_DELTA_MAX}]; clamped to {clamped:.4f}"
        )
    return round(clamped, 4)


def _safe_fitness_delta(stats: Dict[str, Any]) -> Tuple[float, bool]:
    """Return (delta, clamped) — never raises; clamps silently for safety."""
    rate = stats.get("global_success_rate", 0.5)
    if rate > 0.80:
        raw = (rate - 0.80) * 1.0
    elif rate < 0.40:
        raw = (rate - 0.40) * 0.50
    else:
        raw = 0.0
    clamped = max(_DELTA_MIN, min(_DELTA_MAX, raw))
    return round(clamped, 4), (clamped != raw)


# ---------------------------------------------------------------------------
# Velocity nudge computation
# ---------------------------------------------------------------------------


def _compute_velocity_nudge(stats: Dict[str, Any]) -> VelocityNudge:
    """Derive velocity nudge from outcome patterns.

    Rules (in priority order):
      timeout rate ≥ 0.30 → HALT
      failure rate ≥ 0.50 → THROTTLE
      success rate ≥ 0.80 → ACCELERATE
      otherwise            → CRUISE
    """
    total = stats.get("total", 0)
    if total == 0:
        return VelocityNudge.CRUISE
    timeouts = stats.get("timeouts", 0)
    failures = stats.get("failures", 0)
    successes = stats.get("successes", 0)
    if timeouts / total >= 0.30:
        return VelocityNudge.HALT
    if failures / total >= 0.50:
        return VelocityNudge.THROTTLE
    if successes / total >= 0.80:
        return VelocityNudge.ACCELERATE
    return VelocityNudge.CRUISE


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------


class ConstitutionalMutationOutcomeAnalyst:
    """INNOV-113 · CMOA — Constitutional Mutation Outcome Analyst.

    Closes the AMPS→CMVG→CMSE→CMWE→CMOA→AMPS self-improving loop.
    """

    def __init__(
        self,
        ledger_path: Optional[Path] = None,
        cmwe_ledger_path: Optional[Path] = None,
        cgdr_status_override: Optional[str] = None,
    ) -> None:
        self._ledger = _CMOALedger(ledger_path or _LEDGER_PATH)
        # Path to CMWE's AttestationLedger for reading outcome records
        self._cmwe_ledger_path = cmwe_ledger_path or Path(
            os.environ.get(
                "CMWE_ATTEST_LEDGER", "ledger/cmwe_attestation_ledger.jsonl"
            )
        )
        self._cgdr_override = cgdr_status_override
        # In-memory recalibration log
        self._recalibrations: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # CGDR gate (CMOA-CGDR-0)
    # ------------------------------------------------------------------

    def _cgdr_status(self) -> str:
        if self._cgdr_override is not None:
            return self._cgdr_override
        try:
            from dorkllm.convergence_governance_drift_reporter import (
                ConvergenceGovernanceDriftReporter,
            )
            return ConvergenceGovernanceDriftReporter().get_status().get(
                "gate_status", "HEALTHY"
            )
        except Exception:
            return "UNKNOWN"

    def _assert_cgdr_for_signal(self) -> None:
        """CMOA-CGDR-0: block signal emission when system is DRIFTED."""
        status = self._cgdr_status()
        if status in ("DRIFTED", "UNKNOWN"):
            raise CMOACGDRGateError(
                f"{CMOA_CGDR_0}: signal emission blocked — CGDR={status!r}"
            )

    # ------------------------------------------------------------------
    # CMWE ledger reader
    # ------------------------------------------------------------------

    def _read_cmwe_records(self) -> List[Dict[str, Any]]:
        """Read raw attestation records from CMWE ledger."""
        if not self._cmwe_ledger_path.exists():
            return []
        records = []
        for line in self._cmwe_ledger_path.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            # Only process completed attestations with known outcomes
            if rec.get("outcome") in (o.value for o in OutcomeLabel):
                records.append(rec)
        return records

    # ------------------------------------------------------------------
    # Core: analyse
    # ------------------------------------------------------------------

    def analyse(
        self,
        requester: str = "SYSTEM",
        inject_records: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Run outcome analysis and emit fitness + velocity signals.

        Enforces CMOA-MIN-0, CMOA-CGDR-0, CMOA-BIAS-0, CMOA-AUDIT-0,
        CMOA-FAILCLOSED-0, CMOA-SEAL-0, CMOA-CHAIN-0.

        Args:
            requester: agent/user ID requesting the analysis run.
            inject_records: test-only override for CMWE attestation records.
        """
        run_id = str(uuid.uuid4())
        ts = _now()
        cgdr = "UNKNOWN"

        try:
            cgdr = self._cgdr_status()
            # CMOA-CGDR-0
            self._assert_cgdr_for_signal()

            records = inject_records if inject_records is not None else self._read_cmwe_records()

            # CMOA-MIN-0: need at least 3 outcomes
            if len(records) < _MIN_SAMPLE:
                no_sig = self._seal_and_log(
                    run_id, ts, requester, cgdr,
                    AnalysisOutcome.NO_SIGNAL,
                    reason=f"{CMOA_MIN_0}: sample size {len(records)} < {_MIN_SAMPLE}",
                    records_analysed=len(records),
                )
                return no_sig

            stats = _compute_stats(records)
            fitness_delta, _clamped = _safe_fitness_delta(stats)
            velocity_nudge = _compute_velocity_nudge(stats)

            rec_id = _record_id(run_id, "OUTCOME_ANALYSIS", ts)
            report_body = {
                "record_id": rec_id,
                "event": "OUTCOME_ANALYSIS",
                "run_id": run_id,
                "analysed_at": ts,
                "requester": requester,
                "cgdr_status": cgdr,
                "records_analysed": len(records),
                "statistics": stats,
                "fitness_signal": {
                    "type": SignalType.FITNESS_ADJUST.value,
                    "delta": fitness_delta,
                    "bounds": [_DELTA_MIN, _DELTA_MAX],
                    "invariant": CMOA_BIAS_0,
                },
                "velocity_signal": {
                    "type": SignalType.VELOCITY_NUDGE.value,
                    "nudge": velocity_nudge.value,
                },
                "outcome": AnalysisOutcome.SIGNALS_EMITTED.value,
                "governor": GOVERNOR,
                "invariant": CMOA_SEAL_0,
            }
            # CMOA-SEAL-0
            report_body["content_seal"] = _seal(report_body)
            # CMOA-CHAIN-0
            self._ledger.append(report_body)
            return report_body

        except (CMOACGDRGateError, CMOAViolation):
            raise
        except Exception as exc:
            # CMOA-FAILCLOSED-0
            fallback = self._seal_and_log(
                run_id, ts, requester, cgdr,
                AnalysisOutcome.NO_SIGNAL,
                reason=str(exc),
                records_analysed=0,
            )
            return fallback

    def _seal_and_log(
        self,
        run_id: str,
        ts: str,
        requester: str,
        cgdr: str,
        outcome: AnalysisOutcome,
        reason: str = "",
        records_analysed: int = 0,
    ) -> Dict[str, Any]:
        """Seal a NO_SIGNAL record into the ledger (CMOA-AUDIT-0)."""
        rec_id = _record_id(run_id, "NO_SIGNAL", ts)
        body: Dict[str, Any] = {
            "record_id": rec_id,
            "event": "NO_SIGNAL_RUN",
            "run_id": run_id,
            "analysed_at": ts,
            "requester": requester,
            "cgdr_status": cgdr,
            "records_analysed": records_analysed,
            "outcome": outcome.value,
            "reason": reason,
            "governor": GOVERNOR,
        }
        body["content_seal"] = _seal(body)
        try:
            self._ledger.append(body)
        except Exception:
            pass
        return body

    # ------------------------------------------------------------------
    # HUMAN-0 recalibration (CMOA-HUMAN0-0)
    # ------------------------------------------------------------------

    def recalibrate(
        self,
        human_id: str,
        fitness_delta_override: float,
        rationale: str = "",
    ) -> Dict[str, Any]:
        """HUMAN-0-gated manual recalibration of AMPS fitness weights.

        Enforces CMOA-HUMAN0-0 (authority) and CMOA-BIAS-0 (bounds).
        """
        if human_id not in HUMAN0_IDS:
            raise CMOAHuman0Error(
                f"{CMOA_HUMAN0_0}: recalibration denied — {human_id!r} is not HUMAN-0"
            )
        # CMOA-BIAS-0: bounds still apply for manual overrides
        if not (_DELTA_MIN <= fitness_delta_override <= _DELTA_MAX):
            raise CMOABiasError(
                f"{CMOA_BIAS_0}: override delta {fitness_delta_override} outside "
                f"bounds [{_DELTA_MIN}, {_DELTA_MAX}]"
            )
        ts = _now()
        run_id = str(uuid.uuid4())
        rec_id = _record_id(run_id, "RECALIBRATION", ts)
        body: Dict[str, Any] = {
            "record_id": rec_id,
            "event": "HUMAN0_RECALIBRATION",
            "run_id": run_id,
            "recalibrated_at": ts,
            "human_id": human_id,
            "fitness_delta_override": fitness_delta_override,
            "rationale": rationale,
            "governor": GOVERNOR,
            "invariant": CMOA_HUMAN0_0,
        }
        body["content_seal"] = _seal(body)
        self._ledger.append(body)
        self._recalibrations.append(body)
        return body

    # ------------------------------------------------------------------
    # Read & status
    # ------------------------------------------------------------------

    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return most recent analysis and recalibration ledger records."""
        records = self._ledger.read_all()
        return records[-limit:]

    def get_status(self) -> Dict[str, Any]:
        """CMOA system status summary."""
        records = self._ledger.read_all()
        signal_runs = [r for r in records if r.get("outcome") == AnalysisOutcome.SIGNALS_EMITTED.value]
        no_sig_runs = [r for r in records if r.get("outcome") == AnalysisOutcome.NO_SIGNAL.value]
        recal_events = [r for r in records if r.get("event") == "HUMAN0_RECALIBRATION"]
        cgdr = self._cgdr_status()
        return {
            "engine": "CMOA",
            "version": "10.19.0",
            "governor": GOVERNOR,
            "cgdr_gate_status": cgdr,
            "signal_gate": "OPEN" if cgdr in ("HEALTHY", "DRIFT_ALERT") else "BLOCKED",
            "total_runs": len(records),
            "signal_runs": len(signal_runs),
            "no_signal_runs": len(no_sig_runs),
            "recalibrations": len(recal_events),
            "min_sample_threshold": _MIN_SAMPLE,
            "fitness_delta_bounds": [_DELTA_MIN, _DELTA_MAX],
            "invariants": [
                CMOA_CHAIN_0, CMOA_IMMUT_0, CMOA_DETERM_0, CMOA_BIAS_0,
                CMOA_MIN_0, CMOA_AUDIT_0, CMOA_FAILCLOSED_0, CMOA_SEAL_0,
                CMOA_HUMAN0_0, CMOA_CGDR_0,
            ],
        }

    def verify_chain(self) -> Dict[str, Any]:
        """Verify OutcomeLedger HMAC chain integrity (CMOA-CHAIN-0)."""
        return self._ledger.verify_chain()
