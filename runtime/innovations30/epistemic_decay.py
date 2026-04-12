# SPDX-License-Identifier: Apache-2.0
"""Innovation #7 — Epistemic Confidence Decay.

Each fitness weight carries an observation_state_hash.
As the codebase changes, divergence from calibration state grows.
Beyond threshold: weight confidence decays, exploration rate increases.
"""
from __future__ import annotations
import hashlib, json, math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import hashlib
import hmac

# Hardening scaffold — injected by fix/senior-deep-dive-hardening
EPDE_INV_CHAIN: str = "EPDE-INV-CHAIN"
EPDE_LEDGER_DEFAULT: str = "data/epistemic_decay_events.jsonl"


class EpistemicDecayViolation(RuntimeError):
    """Raised when a Epistemic Decay constitutional invariant is breached."""



DECAY_HALFLIFE: float = 30.0     # divergence units until confidence halves
RECALIBRATION_THRESHOLD: float = 0.30  # below this → flag for recalibration

@dataclass
class WeightCalibrationState:
    dimension: str
    weight: float
    observation_state_hash: str   # CodebaseStateVector hash at calibration time
    calibration_epoch: str
    current_confidence: float = 1.0
    cumulative_divergence: float = 0.0
    epochs_since_calibration: int = 0

    @property
    def needs_recalibration(self) -> bool:
        return self.current_confidence < RECALIBRATION_THRESHOLD

    def decay(self, state_change_magnitude: float) -> float:
        """Apply exponential decay based on codebase state change."""
        self.cumulative_divergence += state_change_magnitude
        self.epochs_since_calibration += 1
        self.current_confidence = math.exp(
            -self.cumulative_divergence / DECAY_HALFLIFE)
        return self.current_confidence

    @property
    def effective_weight(self) -> float:
        """Weight scaled by confidence — uncertain knowledge counts less."""
        return self.weight * self.current_confidence


class EpistemicDecayEngine:
    """Applies confidence decay to learned fitness weights as codebase evolves."""

    def __init__(self, state_path: Path = Path("data/epistemic_decay_state.json")):
        self.state_path = Path(state_path)
        self._states: dict[str, WeightCalibrationState] = {}
        self._load()

    def calibrate(self, dimension: str, weight: float,
                  codebase_state_hash: str, epoch_id: str) -> None:
        """Record a fresh calibration — resets confidence to 1.0."""
        self._states[dimension] = WeightCalibrationState(
            dimension=dimension, weight=weight,
            observation_state_hash=codebase_state_hash,
            calibration_epoch=epoch_id,
        )
        self._save()

    def tick(self, current_state_hash: str) -> dict[str, float]:
        """Advance one epoch. Return {dimension → current_confidence}."""
        # Estimate divergence from hash distance (simplified Hamming)
        for dim, state in self._states.items():
            divergence = self._hash_divergence(
                state.observation_state_hash, current_state_hash)
            state.decay(divergence)
        self._save()
        return {dim: s.current_confidence for dim, s in self._states.items()}

    def effective_weights(self) -> dict[str, float]:
        return {dim: s.effective_weight for dim, s in self._states.items()}

    def dimensions_needing_recalibration(self) -> list[str]:
        return [dim for dim, s in self._states.items() if s.needs_recalibration]

    def recommended_exploration_boost(self) -> float:
        """How much extra exploration to add when knowledge is stale."""
        if not self._states:
            return 0.0
        avg_confidence = sum(s.current_confidence
                              for s in self._states.values()) / len(self._states)
        return max(0.0, min(0.30, (1.0 - avg_confidence) * 0.5))

    def summary(self) -> dict[str, Any]:
        return {
            "dimensions": len(self._states),
            "avg_confidence": round(
                sum(s.current_confidence for s in self._states.values()) /
                max(1, len(self._states)), 4),
            "needing_recalibration": self.dimensions_needing_recalibration(),
            "exploration_boost": round(self.recommended_exploration_boost(), 4),
        }

    def _hash_divergence(self, h1: str, h2: str) -> float:
        """Rough divergence score between two hashes."""
        if h1 == h2:
            return 0.0
        # Bit-level divergence from first 8 hex chars
        try:
            a = int(h1.replace("sha256:", "")[:8], 16)
            b = int(h2.replace("sha256:", "")[:8], 16)
            xor = a ^ b
            bits = bin(xor).count("1")
            return bits / 32.0  # normalize to [0, 1]
        except Exception:
            return 0.1

    def _load(self) -> None:
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text())
                for k, v in data.items():
                    self._states[k] = WeightCalibrationState(**v)
            except Exception:
                pass

    def _save(self) -> None:
        import dataclasses
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(
            {k: dataclasses.asdict(v) for k, v in self._states.items()}, indent=2))


__all__ = ["EpistemicDecayEngine", "WeightCalibrationState",
           "DECAY_HALFLIFE", "RECALIBRATION_THRESHOLD"]
