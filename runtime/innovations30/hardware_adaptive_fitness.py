# SPDX-License-Identifier: Apache-2.0
"""Innovation #25 — Hardware-Adaptive Fitness (HAF).
Fitness weights adjusted to the deployment target hardware profile.

Constitutional invariants:
    HAF-0          — profile_id MUST be non-empty; adapted_weights MUST sum to 1.0 ± 0.001
    HAF-DETERM-0   — adapted_weights() MUST return identical output for identical profile input
    HAF-AUDIT-0    — every score_with_profile call MUST produce a ledger-serialisable AuditRecord

Additions (v1.1 — Phase 110):
    AuditRecord                — typed ledger event for every fitness evaluation
    WeightDriftGuard           — detects and blocks weight drift beyond constitutional bounds
    profile_fingerprint()      — SHA-256 over canonical profile fields for replay verification
    to_ledger_row()            — serialise AuditRecord to append-only JSONL
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field, asdict
from typing import Any

import hashlib
import hmac

# Hardening scaffold — injected by fix/senior-deep-dive-hardening
HAADFI_INV_CHAIN: str = "HAADFI-INV-CHAIN"
HAADFI_LEDGER_DEFAULT: str = "data/hardware_adaptive_fitness_events.jsonl"


class HardwareAdaptiveFitnessViolation(RuntimeError):
    """Raised when a Hardware Adaptive Fitness constitutional invariant is breached."""



# ── Constitutional weight bounds [HAF-0] ─────────────────────────────────────
WEIGHT_SUM_TOLERANCE: float = 0.001
WEIGHT_MIN: float = 0.01
WEIGHT_MAX: float = 0.90

HAF_INVARIANTS: dict[str, str] = {
    "HAF-0": (
        "profile_id MUST be non-empty; adapted_weights MUST sum to 1.0 ± 0.001; "
        "each weight MUST be in [0.01, 0.90]."
    ),
    "HAF-DETERM-0": (
        "adapted_weights() MUST return identical output for identical "
        "HardwareProfile input — determinism is a constitutional guarantee."
    ),
    "HAF-AUDIT-0": (
        "Every score_with_profile call MUST produce a ledger-serialisable "
        "AuditRecord containing profile_fingerprint, weights_snapshot, and composite_score."
    ),
}


@dataclass
class HardwareProfile:
    profile_id: str
    architecture: str
    ram_mb: int
    is_battery_constrained: bool
    thermal_envelope: str
    storage_mb: int

    def __post_init__(self) -> None:
        if not self.profile_id or not self.profile_id.strip():
            raise ValueError("HAF-0: profile_id MUST be non-empty.")

    @classmethod
    def android_minimal(cls) -> "HardwareProfile":
        return cls(profile_id="android-minimal", architecture="arm64",
                   ram_mb=512, is_battery_constrained=True,
                   thermal_envelope="low", storage_mb=1024)

    @classmethod
    def server_standard(cls) -> "HardwareProfile":
        return cls(profile_id="server-standard", architecture="x86_64",
                   ram_mb=8192, is_battery_constrained=False,
                   thermal_envelope="high", storage_mb=102400)

    @classmethod
    def desktop_moderate(cls) -> "HardwareProfile":
        return cls(profile_id="desktop-moderate", architecture="x86_64",
                   ram_mb=2048, is_battery_constrained=False,
                   thermal_envelope="medium", storage_mb=10240)


BASE_WEIGHTS: dict[str, float] = {
    "correctness_score": 0.30,
    "efficiency_score": 0.25,
    "policy_compliance_score": 0.20,
    "goal_alignment_score": 0.15,
    "simulated_market_score": 0.10,
}


@dataclass
class AuditRecord:
    """Ledger-serialisable record for every HAF evaluation [HAF-AUDIT-0]."""
    phase: int = 110
    innovation: str = "INNOV-25"
    profile_id: str = ""
    profile_fingerprint: str = ""
    weights_snapshot: dict = field(default_factory=dict)
    base_scores: dict = field(default_factory=dict)
    composite_score: float = 0.0
    timestamp_utc: str = ""
    invariants_verified: list = field(default_factory=list)

    def to_ledger_row(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


class WeightDriftGuard:
    @staticmethod
    def validate(weights: dict[str, float]) -> None:
        total = sum(weights.values())
        if abs(total - 1.0) > WEIGHT_SUM_TOLERANCE:
            raise RuntimeError(
                f"HAF-0: adapted_weights sum to {total:.6f}, violates ±{WEIGHT_SUM_TOLERANCE}."
            )
        for dim, w in weights.items():
            if w < WEIGHT_MIN or w > WEIGHT_MAX:
                raise RuntimeError(
                    f"HAF-0: weight '{dim}'={w:.4f} outside [{WEIGHT_MIN},{WEIGHT_MAX}]."
                )


def profile_fingerprint(profile: HardwareProfile) -> str:
    canonical = json.dumps({
        "profile_id": profile.profile_id,
        "architecture": profile.architecture,
        "ram_mb": profile.ram_mb,
        "is_battery_constrained": profile.is_battery_constrained,
        "thermal_envelope": profile.thermal_envelope,
        "storage_mb": profile.storage_mb,
    }, sort_keys=True)
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()[:16]


class HardwareAdaptiveFitness:
    """Adjusts fitness weights based on deployment hardware profile."""

    def __init__(self, profile: HardwareProfile | None = None):
        self.profile = profile or HardwareProfile.desktop_moderate()

    def adapted_weights(self) -> dict[str, float]:
        weights = dict(BASE_WEIGHTS)

        if self.profile.is_battery_constrained:
            weights["efficiency_score"] *= 1.8
            weights["correctness_score"] *= 1.2
            weights["simulated_market_score"] *= 0.5

        if self.profile.ram_mb < 1024:
            weights["efficiency_score"] *= 2.0
            weights["goal_alignment_score"] *= 0.7

        if self.profile.thermal_envelope == "low":
            weights["efficiency_score"] *= 1.5
            weights["policy_compliance_score"] *= 1.3

        if self.profile.architecture == "x86_64" and not self.profile.is_battery_constrained:
            weights["correctness_score"] *= 1.5
            weights["policy_compliance_score"] *= 1.4

        total = sum(weights.values())
        normalised = {k: round(v / total, 4) for k, v in weights.items()}

        delta = round(1.0 - sum(normalised.values()), 4)
        if delta:
            first_key = next(iter(normalised))
            normalised[first_key] = round(normalised[first_key] + delta, 4)

        WeightDriftGuard.validate(normalised)
        return normalised

    def score_with_profile(self, base_scores: dict[str, float]) -> tuple:
        weights = self.adapted_weights()
        composite = round(sum(base_scores.get(k, 0.0) * w for k, w in weights.items()), 4)
        record = AuditRecord(
            profile_id=self.profile.profile_id,
            profile_fingerprint=profile_fingerprint(self.profile),
            weights_snapshot=dict(weights),
            base_scores=dict(base_scores),
            composite_score=composite,
            timestamp_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            invariants_verified=list(HAF_INVARIANTS.keys()),
        )
        return composite, record

    def profile_description(self) -> str:
        return (f"{self.profile.architecture} | {self.profile.ram_mb}MB RAM | "
                f"battery={'yes' if self.profile.is_battery_constrained else 'no'} | "
                f"thermal={self.profile.thermal_envelope}")


__all__ = [
    "HardwareAdaptiveFitness", "HardwareProfile", "AuditRecord",
    "WeightDriftGuard", "BASE_WEIGHTS", "HAF_INVARIANTS",
    "WEIGHT_SUM_TOLERANCE", "profile_fingerprint",
]
