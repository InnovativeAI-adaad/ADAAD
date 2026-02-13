# SPDX-License-Identifier: Apache-2.0
"""Recovery tier management for graceful degradation."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum

from runtime import metrics


class RecoveryTierLevel(str, Enum):
    """Recovery tier levels in order of severity."""

    NONE = "none"
    ADVISORY = "advisory"
    CONSERVATIVE = "conservative"
    GOVERNANCE = "governance"
    CRITICAL = "critical"

    @property
    def severity(self) -> int:
        return {
            RecoveryTierLevel.NONE: 0,
            RecoveryTierLevel.ADVISORY: 1,
            RecoveryTierLevel.CONSERVATIVE: 2,
            RecoveryTierLevel.GOVERNANCE: 3,
            RecoveryTierLevel.CRITICAL: 4,
        }[self]

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, RecoveryTierLevel):
            return NotImplemented
        return self.severity > other.severity

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, RecoveryTierLevel):
            return NotImplemented
        return self.severity < other.severity

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, RecoveryTierLevel):
            return NotImplemented
        return self.severity >= other.severity

    def __le__(self, other: object) -> bool:
        if not isinstance(other, RecoveryTierLevel):
            return NotImplemented
        return self.severity <= other.severity

@dataclass(frozen=True)
class RecoveryPolicy:
    """Defines behavior for each recovery tier."""

    mutation_rate: float
    require_approval: bool
    fail_close: bool
    deterministic: bool
    allow_web_fetch: bool
    allow_llm_calls: bool

    @staticmethod
    def for_tier(tier: RecoveryTierLevel) -> "RecoveryPolicy":
        match tier:
            case RecoveryTierLevel.NONE | RecoveryTierLevel.ADVISORY:
                return RecoveryPolicy(1.0, False, False, False, True, True)
            case RecoveryTierLevel.CONSERVATIVE:
                return RecoveryPolicy(0.5, False, False, False, True, True)
            case RecoveryTierLevel.GOVERNANCE | RecoveryTierLevel.CRITICAL:
                return RecoveryPolicy(0.0, True, True, True, False, False)


@dataclass(frozen=True)
class TierTransition:
    """Record of tier transition."""

    timestamp: float
    from_tier: RecoveryTierLevel
    to_tier: RecoveryTierLevel
    reason: str
    metrics_snapshot: dict[str, int]


class TierManager:
    """Tracks recovery-tier escalation and controlled de-escalation windows."""

    def __init__(
        self,
        *,
        violation_window_seconds: int = 3600,
        recovery_window_seconds: int = 7200,
    ) -> None:
        self.current_tier = RecoveryTierLevel.NONE
        self.tier_history: list[TierTransition] = []
        self.violation_window = violation_window_seconds
        self.recovery_window = recovery_window_seconds

        self._governance_violations: list[float] = []
        self._mutation_failures: list[float] = []
        self._metric_anomalies: list[float] = []
        self._ledger_errors: list[float] = []

    def record_governance_violation(self) -> None:
        self._governance_violations.append(time.time())
        self._prune_old_violations()

    def record_mutation_failure(self) -> None:
        self._mutation_failures.append(time.time())
        self._prune_old_violations()

    def record_metric_anomaly(self) -> None:
        self._metric_anomalies.append(time.time())
        self._prune_old_violations()

    def record_ledger_error(self) -> None:
        self._ledger_errors.append(time.time())
        self._prune_old_violations()

    def _prune_old_violations(self) -> None:
        cutoff = time.time() - self.violation_window
        self._governance_violations = [ts for ts in self._governance_violations if ts > cutoff]
        self._mutation_failures = [ts for ts in self._mutation_failures if ts > cutoff]
        self._metric_anomalies = [ts for ts in self._metric_anomalies if ts > cutoff]
        self._ledger_errors = [ts for ts in self._ledger_errors if ts > cutoff]

    def evaluate_escalation(
        self,
        *,
        governance_violations: int,
        ledger_errors: int,
        mutation_failures: int,
        metric_anomalies: int,
    ) -> RecoveryTierLevel:
        """Backwards-compatible evaluator for externally-provided counters."""
        if ledger_errors > 0:
            return RecoveryTierLevel.CRITICAL
        if governance_violations >= 3:
            return RecoveryTierLevel.GOVERNANCE
        if mutation_failures >= 5:
            return RecoveryTierLevel.CONSERVATIVE
        if metric_anomalies >= 10:
            return RecoveryTierLevel.ADVISORY
        return RecoveryTierLevel.NONE

    def evaluate_tier(self) -> RecoveryTierLevel:
        self._prune_old_violations()
        return self.evaluate_escalation(
            governance_violations=len(self._governance_violations),
            ledger_errors=len(self._ledger_errors),
            mutation_failures=len(self._mutation_failures),
            metric_anomalies=len(self._metric_anomalies),
        )

    def _can_deescalate(self) -> bool:
        if self.current_tier == RecoveryTierLevel.NONE:
            return True
        if not self.tier_history:
            return False
        return (time.time() - self.tier_history[-1].timestamp) >= self.recovery_window

    def apply(self, tier: RecoveryTierLevel, reason: str) -> RecoveryTierLevel:
        """Backward-compatible apply method."""
        self.apply_tier(tier, reason)
        return self.current_tier

    def apply_tier(self, tier: RecoveryTierLevel, reason: str) -> None:
        if tier == self.current_tier:
            return

        transition = TierTransition(
            timestamp=time.time(),
            from_tier=self.current_tier,
            to_tier=tier,
            reason=reason,
            metrics_snapshot={
                "governance_violations": len(self._governance_violations),
                "mutation_failures": len(self._mutation_failures),
                "metric_anomalies": len(self._metric_anomalies),
                "ledger_errors": len(self._ledger_errors),
            },
        )
        self.tier_history.append(transition)

        event_type = "recovery_escalation" if tier.severity > self.current_tier.severity else "recovery_deescalation"
        level = "ERROR" if tier.severity >= RecoveryTierLevel.GOVERNANCE.severity else "WARNING"
        if event_type == "recovery_deescalation":
            level = "INFO"
        metrics.log(
            event_type=event_type,
            payload={
                "from": self.current_tier.value,
                "to": tier.value,
                "reason": reason,
                "metrics": transition.metrics_snapshot,
            },
            level=level,
        )
        self.current_tier = tier

    def auto_evaluate_and_apply(self, reason: str = "auto_evaluation") -> RecoveryTierLevel:
        tier = self.evaluate_tier()
        if tier != self.current_tier:
            self.apply_tier(tier, reason)
        elif tier == RecoveryTierLevel.NONE and self._can_deescalate():
            self.apply_tier(RecoveryTierLevel.NONE, reason)
        return self.current_tier

    def get_policy(self) -> RecoveryPolicy:
        return RecoveryPolicy.for_tier(self.current_tier)

    def get_status(self) -> dict[str, object]:
        return {
            "current_tier": self.current_tier.value,
            "policy": self.get_policy().__dict__,
            "recent_violations": {
                "governance": len(self._governance_violations),
                "mutation_failures": len(self._mutation_failures),
                "metric_anomalies": len(self._metric_anomalies),
                "ledger_errors": len(self._ledger_errors),
            },
            "transition_count": len(self.tier_history),
            "can_deescalate": self._can_deescalate(),
        }


__all__ = ["RecoveryTierLevel", "RecoveryPolicy", "TierTransition", "TierManager"]
