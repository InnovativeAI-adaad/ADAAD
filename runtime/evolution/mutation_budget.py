# SPDX-License-Identifier: Apache-2.0
"""Deterministic mutation budget accounting and ROI gating."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from statistics import median
from typing import Dict, Iterable, Mapping


@dataclass(frozen=True)
class MutationBudgetDecision:
    mutation_cost: float
    fitness_gain: float
    roi: float
    accepted: bool
    reason: str
    threshold: float
    exploration_rate: float
    cycle_used: float
    epoch_used: float


class MutationBudgetManager:
    """Track mutation budget usage and gate approvals with adaptive ROI thresholds."""

    def __init__(
        self,
        *,
        per_cycle_budget: float = 100.0,
        per_epoch_budget: float = 10_000.0,
        roi_threshold: float = 0.1,
        exploration_rate: float = 0.1,
        exploration_step: float = 0.05,
        min_exploration_rate: float = 0.0,
        max_exploration_rate: float = 0.5,
    ) -> None:
        self.per_cycle_budget = max(0.0, float(per_cycle_budget))
        self.per_epoch_budget = max(0.0, float(per_epoch_budget))
        self.roi_threshold = max(0.0, float(roi_threshold))
        self.exploration_rate = max(min_exploration_rate, min(max_exploration_rate, float(exploration_rate)))
        self.exploration_step = max(0.0, float(exploration_step))
        self.min_exploration_rate = max(0.0, float(min_exploration_rate))
        self.max_exploration_rate = max(self.min_exploration_rate, float(max_exploration_rate))

        self._cycle_usage: Dict[str, float] = {}
        self._epoch_usage: Dict[str, float] = {}
        self._decision_by_cycle: Dict[str, MutationBudgetDecision] = {}

    @staticmethod
    def mutation_cost(runtime_cost: float, entropy_delta: float, complexity_delta: float) -> float:
        return max(0.0, float(runtime_cost) + float(entropy_delta) + float(complexity_delta))

    @staticmethod
    def roi(fitness_gain: float, mutation_cost: float) -> float:
        cost = float(mutation_cost)
        gain = float(fitness_gain)
        if cost <= 0.0:
            return float("inf") if gain > 0.0 else 0.0
        return gain / cost

    def evaluate(
        self,
        *,
        cycle_id: str,
        epoch_id: str,
        runtime_cost: float,
        entropy_delta: float,
        complexity_delta: float,
        fitness_gain: float,
    ) -> MutationBudgetDecision:
        mutation_cost = self.mutation_cost(runtime_cost, entropy_delta, complexity_delta)
        roi = self.roi(fitness_gain, mutation_cost)
        effective_threshold = self.roi_threshold * max(0.0, 1.0 - self.exploration_rate)

        cycle_used = self._cycle_usage.get(cycle_id, 0.0) + mutation_cost
        epoch_used = self._epoch_usage.get(epoch_id, 0.0) + mutation_cost

        accepted = True
        reason = "accepted"
        if self.per_cycle_budget and cycle_used > self.per_cycle_budget:
            accepted = False
            reason = "mutation_cycle_budget_exceeded"
        elif self.per_epoch_budget and epoch_used > self.per_epoch_budget:
            accepted = False
            reason = "mutation_epoch_budget_exceeded"
        elif isfinite(roi) and roi < effective_threshold:
            accepted = False
            reason = "mutation_roi_below_threshold"

        if accepted:
            self._cycle_usage[cycle_id] = cycle_used
            self._epoch_usage[epoch_id] = epoch_used
            self.exploration_rate = max(self.min_exploration_rate, self.exploration_rate - self.exploration_step)
        elif reason == "mutation_roi_below_threshold":
            self.exploration_rate = min(self.max_exploration_rate, self.exploration_rate + self.exploration_step)

        decision = MutationBudgetDecision(
            mutation_cost=mutation_cost,
            fitness_gain=float(fitness_gain),
            roi=roi,
            accepted=accepted,
            reason=reason,
            threshold=effective_threshold,
            exploration_rate=self.exploration_rate,
            cycle_used=cycle_used if accepted else self._cycle_usage.get(cycle_id, 0.0),
            epoch_used=epoch_used if accepted else self._epoch_usage.get(epoch_id, 0.0),
        )
        self._decision_by_cycle[cycle_id] = decision
        return decision

    def ingest_rolling_metrics(self, entries: Iterable[Mapping[str, object]]) -> Dict[str, float]:
        """Adapt budget controls from rolling metrics history."""
        rows = [dict(item) for item in entries if isinstance(item, Mapping)]
        if not rows:
            return {
                "acceptance_rate": 0.0,
                "avg_entropy_utilization": 0.0,
                "cost_per_accepted": 0.0,
                "roi_threshold": self.roi_threshold,
                "exploration_rate": self.exploration_rate,
                "per_cycle_budget": self.per_cycle_budget,
            }

        acceptance_rates = [float(item.get("mutation_acceptance_rate", 0.0) or 0.0) for item in rows]
        utilizations = [float((item.get("entropy") or {}).get("utilization", 0.0) or 0.0) for item in rows if isinstance(item.get("entropy"), Mapping)]
        costs = [
            float((item.get("efficiency_cost_signals") or {}).get("cost_units", 0.0) or 0.0)
            for item in rows
            if isinstance(item.get("efficiency_cost_signals"), Mapping)
        ]
        accepted_counts = [
            float((item.get("efficiency_cost_signals") or {}).get("accepted_mutation_count", 0.0) or 0.0)
            for item in rows
            if isinstance(item.get("efficiency_cost_signals"), Mapping)
        ]

        acceptance_rate = sum(acceptance_rates) / len(acceptance_rates)
        avg_entropy_utilization = (sum(utilizations) / len(utilizations)) if utilizations else 0.0
        total_cost = sum(costs)
        total_accepted = sum(accepted_counts)
        cost_per_accepted = total_cost / total_accepted if total_accepted > 0 else total_cost

        if acceptance_rate < 0.30:
            self.roi_threshold = min(1.0, self.roi_threshold * 1.05)
        elif acceptance_rate > 0.70:
            self.roi_threshold = max(0.01, self.roi_threshold * 0.95)

        if avg_entropy_utilization < 0.20:
            self.exploration_rate = min(self.max_exploration_rate, self.exploration_rate + self.exploration_step)
        elif avg_entropy_utilization > 0.85:
            self.exploration_rate = max(self.min_exploration_rate, self.exploration_rate - self.exploration_step)

        median_cost = median(costs) if costs else 0.0
        if median_cost > 0 and cost_per_accepted > (median_cost * 1.5):
            self.per_cycle_budget = max(1.0, self.per_cycle_budget * 0.95)
            self.roi_threshold = min(1.0, self.roi_threshold * 1.05)

        return {
            "acceptance_rate": acceptance_rate,
            "avg_entropy_utilization": avg_entropy_utilization,
            "cost_per_accepted": cost_per_accepted,
            "roi_threshold": self.roi_threshold,
            "exploration_rate": self.exploration_rate,
            "per_cycle_budget": self.per_cycle_budget,
        }

    def decision_for_cycle(self, cycle_id: str) -> MutationBudgetDecision | None:
        return self._decision_by_cycle.get(cycle_id)


__all__ = ["MutationBudgetDecision", "MutationBudgetManager"]
