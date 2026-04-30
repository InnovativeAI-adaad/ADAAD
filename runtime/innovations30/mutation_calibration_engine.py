# SPDX-License-Identifier: Apache-2.0
"""Phase 163 · INNOV-69 · Mutation Calibration Engine (MCE)."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum
import hashlib
import hmac
import json
from pathlib import Path
from typing import Dict

VALID_SOURCES = frozenset({"cel_loop", "governance_review", "test_harness", "phase163_migration"})
CHAIN_ROOT = "0" * 64
WEIGHT_KEYS = ("precedent", "invariant", "csi", "forecast")
MAX_DRIFT = 0.05
HUMAN0_SHIFT_GATE = 0.10


class MCEChainError(RuntimeError): ...
class MCEWeightError(RuntimeError): ...
class MCELookupError(RuntimeError): ...
class MCESourceError(RuntimeError): ...
class MCEDriftError(RuntimeError): ...
class MCEHuman0Gate(RuntimeError): ...


class OutcomeClass(str, Enum):
    APPROVED = "APPROVED"
    REVERTED = "REVERTED"
    BLOCKED_POST_GATE = "BLOCKED_POST_GATE"
    NEUTRAL = "NEUTRAL"


@dataclass(frozen=True)
class MutationOutcome:
    impact_id: str
    mutation_id: str
    actual_result: OutcomeClass
    execution_phase: int
    csi_delta: float
    invariant_violations: int
    submitted_by: str


@dataclass(frozen=True)
class CalibrationRecord:
    calibration_id: str
    impact_id: str
    prediction_tier: str
    actual_class: str
    prediction_error: float
    weight_delta: Dict[str, float]
    cumulative_weights: Dict[str, float]
    prev_digest: str
    chain_hash: str
    ledger_seq: int
    timestamp_utc: str


class MutationCalibrationEngine:
    def __init__(self, ledger_path: Path | str = Path("ledger/mutation_calibration.jsonl"), weights_path: Path | str = Path("governance/mce_weights.json"), secret: str = "mce-secret"):
        self.ledger_path = Path(ledger_path)
        self.weights_path = Path(weights_path)
        self.secret = secret.encode()
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self.weights_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.weights_path.exists():
            self._save_weights({"precedent": 0.25, "invariant": 0.35, "csi": 0.20, "forecast": 0.20})

    def _load_weights(self) -> Dict[str, float]:
        return json.loads(self.weights_path.read_text())

    def _save_weights(self, weights: Dict[str, float]) -> None:
        self._validate_weights(weights)
        tmp = self.weights_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(weights, sort_keys=True, indent=2) + "\n")
        tmp.replace(self.weights_path)

    def _validate_weights(self, weights: Dict[str, float]) -> None:
        if set(weights) != set(WEIGHT_KEYS):
            raise MCEWeightError("invalid keys")
        if abs(sum(weights.values()) - 1.0) > 1e-9:
            raise MCEWeightError("weights must sum to 1")

    def _predict_error(self, o: MutationOutcome) -> float:
        base = 0.0 if o.actual_result is OutcomeClass.APPROVED else 0.5
        return min(1.0, base + min(0.5, abs(o.csi_delta) + (o.invariant_violations * 0.1)))

    def _calc_delta(self, err: float) -> Dict[str, float]:
        raw = (err - 0.5) * 0.1
        d = max(-MAX_DRIFT, min(MAX_DRIFT, raw))
        return {"precedent": -d / 3, "invariant": d, "csi": -d / 3, "forecast": -d / 3}

    def _chain(self):
        if not self.ledger_path.exists():
            return []
        return [json.loads(line) for line in self.ledger_path.read_text().splitlines() if line.strip()]

    def calibrate(self, outcome: MutationOutcome, prediction_tier: str = "MEDIUM") -> CalibrationRecord:
        if outcome.submitted_by not in VALID_SOURCES:
            raise MCESourceError("invalid source")
        if not outcome.impact_id:
            raise MCELookupError("impact_id missing")
        weights = self._load_weights()
        err = self._predict_error(outcome)
        delta = self._calc_delta(err)
        new_weights = {k: weights[k] + delta[k] for k in WEIGHT_KEYS}
        self._validate_weights(new_weights)
        if any(abs(new_weights[k] - weights[k]) > HUMAN0_SHIFT_GATE for k in WEIGHT_KEYS):
            raise MCEHuman0Gate("human signoff required")
        chain = self._chain()
        prev_digest = chain[-1]["chain_hash"] if chain else CHAIN_ROOT
        cid_payload = {"impact_id": outcome.impact_id, "actual_class": outcome.actual_result.value, "phase": outcome.execution_phase}
        calibration_id = hashlib.sha256(json.dumps(cid_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        seq = len(chain) + 1
        record0 = CalibrationRecord(calibration_id, outcome.impact_id, prediction_tier, outcome.actual_result.value, err, delta, new_weights, prev_digest, "", seq, now)
        payload = json.dumps(asdict(record0), sort_keys=True, separators=(",", ":"))
        chain_hash = hmac.new(self.secret, f"{prev_digest}:{payload}".encode(), hashlib.sha256).hexdigest()
        record = CalibrationRecord(**{**asdict(record0), "chain_hash": chain_hash})
        with self.ledger_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(record), sort_keys=True) + "\n")
        self._save_weights(new_weights)
        return record

    def verify_chain(self) -> bool:
        prev = CHAIN_ROOT
        for rec in self._chain():
            actual = rec["chain_hash"]
            rec_copy = dict(rec)
            rec_copy["chain_hash"] = ""
            payload = json.dumps(rec_copy, sort_keys=True, separators=(",", ":"))
            expected = hmac.new(self.secret, f"{prev}:{payload}".encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(actual, expected):
                raise MCEChainError("chain mismatch")
            prev = actual
        return True
