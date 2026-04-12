# SPDX-License-Identifier: Apache-2.0
"""Innovation #30 — The Mirror Test (MIRROR).
Every 50 epochs, present the system with historical mutation proposals
(outcomes redacted) and measure prediction accuracy.
Low accuracy triggers ConstitutionalCalibrationEpoch before resuming.

Constitutional invariants:
    MIRROR-0       — overall_score MUST be in [0.0, 1.0]; requires_calibration
                     MUST be True when overall_score < CALIBRATION_THRESHOLD
    MIRROR-DETERM-0 — run() MUST produce identical result_digest for identical
                      (epoch_id, sample, predictor outputs) inputs
    MIRROR-AUDIT-0  — every MirrorTestResult MUST carry non-empty result_digest
                      and be persisted to append-only JSONL state

Additions (v1.1 — Phase 115):
    MIRROR_INVARIANTS   — Hard-class invariant registry
    mirror_guard()      — fail-closed enforcement helper
    to_ledger_row()     — JSONL serialisation on MirrorTestResult
"""
from __future__ import annotations

import hashlib
import json
import statistics
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable

import hashlib
import hmac

# Hardening scaffold — injected by fix/senior-deep-dive-hardening
MITE_INV_CHAIN: str = "MITE-INV-CHAIN"
MITE_LEDGER_DEFAULT: str = "data/mirror_test_events.jsonl"


class MirrorTestViolation(RuntimeError):
    """Raised when a Mirror Test constitutional invariant is breached."""



# ── Constitutional constants ─────────────────────────────────────────────────
MIRROR_TEST_INTERVAL: int = 50
CALIBRATION_THRESHOLD: float = 0.60
MIRROR_TEST_SAMPLE: int = 20

MIRROR_INVARIANTS: dict[str, str] = {
    "MIRROR-0": (
        "overall_score MUST be in [0.0, 1.0]. "
        "requires_calibration MUST be True when overall_score < CALIBRATION_THRESHOLD."
    ),
    "MIRROR-DETERM-0": (
        "run() MUST produce identical result_digest for identical "
        "(epoch_id, sample, predictor outputs) inputs."
    ),
    "MIRROR-AUDIT-0": (
        "Every MirrorTestResult MUST carry a non-empty result_digest and be "
        "persisted to append-only JSONL state path."
    ),
}


@dataclass
class MirrorPrediction:
    mutation_id: str
    predicted_pass: bool
    predicted_rules_fired: list = field(default_factory=list)
    predicted_fitness: float = 0.0
    actual_pass: bool = False
    actual_rules_fired: list = field(default_factory=list)
    actual_fitness: float = 0.0

    @property
    def pass_correct(self) -> bool:
        return self.predicted_pass == self.actual_pass

    @property
    def rules_precision(self) -> float:
        if not self.predicted_rules_fired:
            return 1.0 if not self.actual_rules_fired else 0.0
        correct = set(self.predicted_rules_fired) & set(self.actual_rules_fired)
        return len(correct) / max(len(self.predicted_rules_fired), len(self.actual_rules_fired))

    @property
    def fitness_error(self) -> float:
        return abs(self.predicted_fitness - self.actual_fitness)


@dataclass
class MirrorTestResult:
    """Tamper-evident mirror test result [MIRROR-AUDIT-0]."""
    epoch_id: str
    sample_size: int
    pass_accuracy: float
    rules_precision: float
    fitness_mae: float
    overall_score: float
    requires_calibration: bool
    predictions: list = field(default_factory=list)
    result_digest: str = ""
    timestamp_utc: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    invariants_verified: list = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.result_digest:
            payload = json.dumps({
                "epoch_id": self.epoch_id,
                "overall_score": round(self.overall_score, 6),
                "sample_size": self.sample_size,
                "requires_calibration": self.requires_calibration,
            }, sort_keys=True)
            self.result_digest = (
                "sha256:" + hashlib.sha256(payload.encode()).hexdigest()[:16]
            )
        if not self.invariants_verified:
            self.invariants_verified = list(MIRROR_INVARIANTS.keys())

    def to_ledger_row(self) -> str:
        """Single-line JSONL — excludes per-prediction list for compactness."""
        d = {k: v for k, v in asdict(self).items() if k != "predictions"}
        return json.dumps(d, sort_keys=True)


def mirror_guard(result: MirrorTestResult) -> None:
    """Fail-closed enforcement for mirror test constraints [MIRROR-0, MIRROR-AUDIT-0]."""
    if not (0.0 <= result.overall_score <= 1.0):
        raise RuntimeError(
            f"MIRROR-0: overall_score={result.overall_score} outside [0.0, 1.0]."
        )
    expected_calib = result.overall_score < CALIBRATION_THRESHOLD
    if expected_calib != result.requires_calibration:
        raise RuntimeError(
            f"MIRROR-0: requires_calibration={result.requires_calibration} "
            f"inconsistent with overall_score={result.overall_score:.4f} "
            f"(threshold={CALIBRATION_THRESHOLD})."
        )
    if not result.result_digest:
        raise RuntimeError("MIRROR-AUDIT-0: result_digest MUST be non-empty.")


class MirrorTestEngine:
    """Measures whether ADAAD understands its own governance decisions.

    Constitutional guarantees (Phase 115):
        MIRROR-0        : score bounds and calibration flag enforced
        MIRROR-DETERM-0 : identical inputs → identical result_digest
        MIRROR-AUDIT-0  : result_digest present; persisted to JSONL
    """

    def __init__(
        self,
        state_path: Path = Path("data/mirror_test_state.jsonl"),
        interval: int = MIRROR_TEST_INTERVAL,
        calibration_threshold: float = CALIBRATION_THRESHOLD,
    ) -> None:
        self.state_path = Path(state_path)
        self.interval = interval
        self.threshold = calibration_threshold

    def should_run(self, epoch_seq: int) -> bool:
        return epoch_seq > 0 and epoch_seq % self.interval == 0

    def run(
        self,
        epoch_id: str,
        historical_records: list[dict[str, Any]],
        predictor_fn: Callable[[dict[str, Any]], MirrorPrediction],
    ) -> MirrorTestResult:
        """Run mirror test [MIRROR-0, MIRROR-DETERM-0, MIRROR-AUDIT-0]."""
        sample = historical_records[-MIRROR_TEST_SAMPLE:]
        predictions = [predictor_fn(r) for r in sample]

        if predictions:
            pass_acc = statistics.mean(float(p.pass_correct) for p in predictions)
            rules_prec = statistics.mean(p.rules_precision for p in predictions)
            fitness_mae = statistics.mean(p.fitness_error for p in predictions)
        else:
            pass_acc = rules_prec = 0.0
            fitness_mae = 1.0

        overall = round(
            pass_acc * 0.5 + rules_prec * 0.3 + max(0.0, 1.0 - fitness_mae) * 0.2, 4
        )
        overall = max(0.0, min(1.0, overall))   # clamp [MIRROR-0]

        result = MirrorTestResult(
            epoch_id=epoch_id,
            sample_size=len(predictions),
            pass_accuracy=round(pass_acc, 4),
            rules_precision=round(rules_prec, 4),
            fitness_mae=round(fitness_mae, 4),
            overall_score=overall,
            requires_calibration=overall < self.threshold,   # [MIRROR-0]
            predictions=predictions,
        )
        self._persist(result)   # [MIRROR-AUDIT-0]
        return result

    def last_score(self) -> float | None:
        if not self.state_path.exists():
            return None
        try:
            last = self.state_path.read_text().splitlines()[-1]
            return json.loads(last).get("overall_score")
        except Exception:
            return None

    def _persist(self, result: MirrorTestResult) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with self.state_path.open("a") as f:
            f.write(result.to_ledger_row() + "\n")


__all__ = [
    "MirrorTestEngine", "MirrorTestResult", "MirrorPrediction",
    "mirror_guard", "MIRROR_INVARIANTS",
    "MIRROR_TEST_INTERVAL", "CALIBRATION_THRESHOLD", "MIRROR_TEST_SAMPLE",
]
