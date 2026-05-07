# SPDX-License-Identifier: Apache-2.0
"""Phase 163 — INNOV-69 · MCE — Mutation Calibration Engine.

MCE invariants
==============
MCE-CHAIN-0   : calibration ledger is HMAC-chained; chain break -> MCEChainError.
MCE-WEIGHT-0  : weight vector must sum to 1.0 +/- 1e-9 after every update.
MCE-DRIFT-0   : per-cycle delta capped at +/-_MCE_MAX_DELTA per dimension.
MCE-HUMAN0-0  : cumulative shift >_MCE_HUMAN0_THRESHOLD emits HUMAN0_AUTHORISATION.
MCE-DETERM-0  : calibration_id deterministic from (impact_id, actual_class, phase).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dorkllm.telemetry_hub import CGTHEventType, get_hub

# ---------------------------------------------------------------------------
# Invariant constants
# ---------------------------------------------------------------------------
_MCE_COMPONENT_ID: str = "mce"
_MCE_LEDGER_KEY: bytes = os.environ.get(
    "ADAAD_LEDGER_KEY", "adaad-default-ledger-key-mce-v1"
).encode()
_MCE_LEDGER_PATH: Path = Path(os.environ.get("MCE_LEDGER_PATH", "ledger/mutation_calibration.jsonl"))
_MCE_WEIGHTS_PATH: Path = Path(os.environ.get("MCE_WEIGHTS_PATH", "governance/mce_weights.json"))
_MCE_CHAIN_ALGO: str = "sha256"
_MCE_GENESIS_HASH: str = "0" * 64
_MCE_MAX_DELTA: float = 0.05
_MCE_HUMAN0_THRESHOLD: float = 0.10
_MCE_WEIGHT_SUM_TOLERANCE: float = 1e-9
_MCE_LEARNING_RATE: float = 0.01
_MCE_DEFAULT_WEIGHTS: Dict[str, float] = {
    "precedent": 0.25,
    "invariant": 0.35,
    "csi": 0.20,
    "forecast": 0.20,
}
MCE_VALID_SOURCES: frozenset = frozenset({
    "cel_loop",
    "governance_review",
    "test_harness",
    "phase163_migration",
})

# ---------------------------------------------------------------------------
# Typed exceptions (all RuntimeError subclasses — Hard-class requirement)
# ---------------------------------------------------------------------------
class MCEChainError(RuntimeError):
    """MCE-CHAIN-0: HMAC chain integrity violation."""

class MCEWeightError(RuntimeError):
    """MCE-WEIGHT-0: weight vector sum deviates from 1.0."""

class MCEDriftError(RuntimeError):
    """MCE-DRIFT-0: delta exceeded max (informational — clamped in practice)."""

class MCELookupError(RuntimeError):
    """impact_id not found in MIA ledger (non-fatal)."""

class MCESourceError(RuntimeError):
    """Caller not in MCE_VALID_SOURCES allowlist."""

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class OutcomeClass(str, Enum):
    APPROVED          = "APPROVED"
    REVERTED          = "REVERTED"
    BLOCKED_POST_GATE = "BLOCKED_POST_GATE"
    NEUTRAL           = "NEUTRAL"

_OUTCOME_RISK: Dict[str, float] = {
    "APPROVED": 0.0, "NEUTRAL": 0.2, "REVERTED": 0.7, "BLOCKED_POST_GATE": 1.0,
}
_TIER_NUMERIC: Dict[str, float] = {
    "LOW": 0.0, "MEDIUM": 0.33, "HIGH_RISK": 0.67, "CRITICAL": 1.0,
}

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MutationOutcome:
    impact_id:            str
    mutation_id:          str
    actual_result:        OutcomeClass
    execution_phase:      int
    csi_delta:            float
    invariant_violations: int
    submitted_by:         str

    def canonical(self) -> str:
        return json.dumps(
            {"impact_id": self.impact_id, "mutation_id": self.mutation_id,
             "actual_result": self.actual_result.value, "execution_phase": self.execution_phase},
            sort_keys=True, separators=(",", ":"),
        )

@dataclass(frozen=True)
class CalibrationRecord:
    calibration_id:     str
    impact_id:          str
    mutation_id:        str
    prediction_tier:    str
    actual_class:       str
    prediction_error:   float
    weight_delta:       Dict[str, float]
    cumulative_weights: Dict[str, float]
    ledger_seq:         int
    prev_digest:        str   # SHA-256 of previous record canonical JSON
    chain_hash:         str   # HMAC-SHA-256 chain link
    timestamp_utc:      str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "calibration_id":    self.calibration_id,
            "impact_id":         self.impact_id,
            "mutation_id":       self.mutation_id,
            "prediction_tier":   self.prediction_tier,
            "actual_class":      self.actual_class,
            "prediction_error":  round(self.prediction_error, 6),
            "weight_delta":      {k: round(v, 8) for k, v in self.weight_delta.items()},
            "cumulative_weights":{k: round(v, 8) for k, v in self.cumulative_weights.items()},
            "ledger_seq":        self.ledger_seq,
            "prev_digest":       self.prev_digest,
            "chain_hash":        self.chain_hash,
            "timestamp_utc":     self.timestamp_utc,
        }

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _calibration_id(outcome: MutationOutcome) -> str:
    raw = f"mce:{outcome.canonical()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]

def _hmac_link(prev_hash: str, record_canonical: str) -> str:
    msg = f"{prev_hash}:{record_canonical}".encode()
    return hmac.new(_MCE_LEDGER_KEY, msg, _MCE_CHAIN_ALGO).hexdigest()

def _record_digest(record_dict: Dict[str, Any]) -> str:
    canonical = json.dumps(record_dict, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()

def _load_ledger(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    records: List[Dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records

def _verify_chain(records: List[Dict[str, Any]]) -> str:
    prev = _MCE_GENESIS_HASH
    for i, rec in enumerate(records):
        canonical = json.dumps(
            {k: v for k, v in rec.items() if k != "chain_hash"},
            sort_keys=True, separators=(",", ":"),
        )
        expected = _hmac_link(prev, canonical)
        if not hmac.compare_digest(rec["chain_hash"], expected):
            raise MCEChainError(
                f"MCE-CHAIN-0: chain broken at record {i} (seq {rec.get('ledger_seq')})"
            )
        prev = rec["chain_hash"]
    return prev

def _load_weights(path: Path) -> Dict[str, float]:
    if not path.exists():
        return dict(_MCE_DEFAULT_WEIGHTS)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        weights = data.get("weights", _MCE_DEFAULT_WEIGHTS)
        return {k: float(weights.get(k, v)) for k, v in _MCE_DEFAULT_WEIGHTS.items()}
    except Exception:
        return dict(_MCE_DEFAULT_WEIGHTS)

def _write_weights_atomic(path: Path, weights: Dict[str, float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {"weights": {k: round(v, 10) for k, v in weights.items()},
         "component": _MCE_COMPONENT_ID, "innovation": "INNOV-69"},
        indent=2,
    )
    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".mce_weights_tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

def _normalise(weights: Dict[str, float]) -> Dict[str, float]:
    total = sum(weights.values())
    if total == 0.0:
        return dict(_MCE_DEFAULT_WEIGHTS)
    return {k: v / total for k, v in weights.items()}

def _assert_weight_sum(weights: Dict[str, float]) -> None:
    total = sum(weights.values())
    if abs(total - 1.0) > _MCE_WEIGHT_SUM_TOLERANCE:
        raise MCEWeightError(
            f"MCE-WEIGHT-0: weight sum {total:.12f} deviates from 1.0 by "
            f"{abs(total - 1.0):.2e}"
        )

def _clamp_delta(delta: float) -> Tuple[float, bool]:
    if delta > _MCE_MAX_DELTA:
        return _MCE_MAX_DELTA, True
    if delta < -_MCE_MAX_DELTA:
        return -_MCE_MAX_DELTA, True
    return delta, False

# ---------------------------------------------------------------------------
# Calibration engine
# ---------------------------------------------------------------------------
class MutationCalibrationEngine:
    """INNOV-69 · MCE — closes MIA feedback loop via outcome-driven weight calibration."""

    def __init__(
        self,
        ledger_path: Optional[Path] = None,
        weights_path: Optional[Path] = None,
        mia_ledger_path: Optional[Path] = None,
    ) -> None:
        self._ledger_path  = ledger_path  or _MCE_LEDGER_PATH
        self._weights_path = weights_path or _MCE_WEIGHTS_PATH
        self._mia_ledger   = mia_ledger_path or Path(
            os.environ.get("MIA_LEDGER_PATH", "ledger/mutation_impact.jsonl")
        )

    def record_outcome(
        self,
        outcome: MutationOutcome,
        source: str = "cel_loop",
        import_timestamp: Optional[str] = None,
    ) -> CalibrationRecord:
        # MCE-DRIFT-0 source allowlist
        if source not in MCE_VALID_SOURCES:
            raise MCESourceError(
                f"MCE-DRIFT-0: source '{source}' not in MCE_VALID_SOURCES"
            )
        prediction_tier = self._lookup_mia_tier(outcome.impact_id)
        records = _load_ledger(self._ledger_path)
        tip_hash = _verify_chain(records)  # MCE-CHAIN-0

        pred_numeric   = _TIER_NUMERIC.get(prediction_tier, 0.5)
        actual_numeric = _OUTCOME_RISK.get(outcome.actual_result.value, 0.5)
        prediction_error = abs(pred_numeric - actual_numeric)

        current_weights = _load_weights(self._weights_path)
        raw_deltas      = self._compute_deltas(outcome, prediction_error, current_weights)
        clamped_deltas  = {dim: _clamp_delta(d)[0] for dim, d in raw_deltas.items()}

        new_weights_raw = {k: max(0.001, current_weights[k] + clamped_deltas[k]) for k in current_weights}
        new_weights     = _normalise(new_weights_raw)
        _assert_weight_sum(new_weights)  # MCE-WEIGHT-0

        cumulative_shift = {k: abs(new_weights[k] - _MCE_DEFAULT_WEIGHTS[k]) for k in new_weights}
        if any(v > _MCE_HUMAN0_THRESHOLD for v in cumulative_shift.values()):
            self._emit_human0_gate(outcome, new_weights, cumulative_shift)  # MCE-HUMAN0-0

        import datetime
        ts = import_timestamp or datetime.datetime.utcnow().isoformat() + "Z"
        cal_id      = _calibration_id(outcome)
        prev_digest = _record_digest(records[-1]) if records else _MCE_GENESIS_HASH

        rec_body = {
            "calibration_id":    cal_id,
            "impact_id":         outcome.impact_id,
            "mutation_id":       outcome.mutation_id,
            "prediction_tier":   prediction_tier,
            "actual_class":      outcome.actual_result.value,
            "prediction_error":  round(prediction_error, 6),
            "weight_delta":      {k: round(v, 8) for k, v in clamped_deltas.items()},
            "cumulative_weights":{k: round(v, 8) for k, v in new_weights.items()},
            "ledger_seq":        len(records),
            "prev_digest":       prev_digest,
            "timestamp_utc":     ts,
        }
        rec_canonical = json.dumps(rec_body, sort_keys=True, separators=(",", ":"))
        chain_hash = _hmac_link(tip_hash, rec_canonical)
        rec_body["chain_hash"] = chain_hash

        record = CalibrationRecord(
            calibration_id    = cal_id,
            impact_id         = outcome.impact_id,
            mutation_id       = outcome.mutation_id,
            prediction_tier   = prediction_tier,
            actual_class      = outcome.actual_result.value,
            prediction_error  = prediction_error,
            weight_delta      = clamped_deltas,
            cumulative_weights= new_weights,
            ledger_seq        = len(records),
            prev_digest       = prev_digest,
            chain_hash        = chain_hash,
            timestamp_utc     = ts,
        )

        # MCE-AUDIT-0: append-only JSONL write
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self._ledger_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec_body, sort_keys=True) + "\n")

        _write_weights_atomic(self._weights_path, new_weights)
        self._emit_calibration_cycle(record)
        if any(abs(v) > 0.001 for v in clamped_deltas.values()):
            self._emit_weight_updated(record)
        return record

    def current_weights(self) -> Dict[str, float]:
        return _load_weights(self._weights_path)

    def verify_chain(self) -> Dict[str, Any]:
        records = _load_ledger(self._ledger_path)
        try:
            tip = _verify_chain(records)
            return {"status": "ok", "records": len(records), "tip_hash": tip, "component": _MCE_COMPONENT_ID}
        except MCEChainError as exc:
            return {"status": "chain_broken", "error": str(exc), "records": len(records), "component": _MCE_COMPONENT_ID}

    def history(self, limit: int = 50) -> List[Dict[str, Any]]:
        return _load_ledger(self._ledger_path)[-limit:]

    def status(self) -> Dict[str, Any]:
        records = _load_ledger(self._ledger_path)
        weights = _load_weights(self._weights_path)
        tier_errs: Dict[str, List[float]] = {}
        for r in records:
            t = r.get("prediction_tier", "UNKNOWN")
            tier_errs.setdefault(t, []).append(r.get("prediction_error", 0.0))
        mae_by_tier = {t: round(sum(v) / len(v), 4) for t, v in tier_errs.items() if v}
        return {
            "component": _MCE_COMPONENT_ID, "innovation": "INNOV-69", "phase": 163,
            "total_calibrations": len(records),
            "current_weights": {k: round(v, 6) for k, v in weights.items()},
            "mae_by_tier": mae_by_tier,
            "ledger_path": str(self._ledger_path),
            "weights_path": str(self._weights_path),
            "invariants": ["MCE-CHAIN-0","MCE-WEIGHT-0","MCE-DRIFT-0","MCE-HUMAN0-0","MCE-DETERM-0"],
        }

    def _lookup_mia_tier(self, impact_id: str) -> str:
        if not self._mia_ledger.exists():
            return "UNKNOWN"
        try:
            with self._mia_ledger.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    # AUTH-CT-0: constant-time comparison
                    if hmac.compare_digest(rec.get("impact_id", ""), impact_id):
                        return rec.get("tier", "UNKNOWN")
        except Exception:
            pass
        return "UNKNOWN"

    def _compute_deltas(
        self, outcome: MutationOutcome, prediction_error: float, weights: Dict[str, float]
    ) -> Dict[str, float]:
        actual_numeric = _OUTCOME_RISK.get(outcome.actual_result.value, 0.5)
        dim_signals = {
            "precedent": min(1.0, outcome.invariant_violations * 0.3),
            "invariant": float(outcome.invariant_violations > 0),
            "csi":       max(0.0, -outcome.csi_delta),
            "forecast":  actual_numeric,
        }
        deltas: Dict[str, float] = {}
        for dim, signal in dim_signals.items():
            error = prediction_error * _MCE_LEARNING_RATE
            if actual_numeric > 0.5:
                deltas[dim] = error * signal
            else:
                deltas[dim] = -error * weights[dim]
        return deltas

    def _emit_calibration_cycle(self, record: CalibrationRecord) -> None:
        try:
            get_hub().emit_event(
                component_id=_MCE_COMPONENT_ID,
                event_type=CGTHEventType.MUTATION_OUTCOME,
                payload={"event": "mce_calibration_cycle",
                         "calibration_id": record.calibration_id,
                         "impact_id": record.impact_id,
                         "prediction_tier": record.prediction_tier,
                         "actual_class": record.actual_class,
                         "prediction_error": round(record.prediction_error, 6),
                         "ledger_seq": record.ledger_seq,
                         "component": _MCE_COMPONENT_ID},
            )
        except Exception:
            pass

    def _emit_weight_updated(self, record: CalibrationRecord) -> None:
        try:
            get_hub().emit_event(
                component_id=_MCE_COMPONENT_ID,
                event_type=CGTHEventType.PERM_SNAPSHOT,
                payload={"event": "mce_weight_updated",
                         "calibration_id": record.calibration_id,
                         "new_weights": record.cumulative_weights,
                         "weight_delta": record.weight_delta,
                         "component": _MCE_COMPONENT_ID},
            )
        except Exception:
            pass

    def _emit_human0_gate(self, outcome: MutationOutcome, new_weights: Dict[str, float],
                          cumulative_shift: Dict[str, float]) -> None:
        try:
            get_hub().emit_event(
                component_id=_MCE_COMPONENT_ID,
                event_type=CGTHEventType.HUMAN0_AUTHORISATION,
                payload={"event": "mce_human0_weight_gate",
                         "impact_id": outcome.impact_id,
                         "mutation_id": outcome.mutation_id,
                         "proposed_weights": {k: round(v, 6) for k, v in new_weights.items()},
                         "cumulative_shift": {k: round(v, 6) for k, v in cumulative_shift.items()},
                         "threshold": _MCE_HUMAN0_THRESHOLD,
                         "invariant": "MCE-HUMAN0-0",
                         "component": _MCE_COMPONENT_ID},
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_default_engine: Optional[MutationCalibrationEngine] = None

def get_engine() -> MutationCalibrationEngine:
    global _default_engine
    if _default_engine is None:
        _default_engine = MutationCalibrationEngine()
    return _default_engine
