# SPDX-License-Identifier: Apache-2.0
"""Multi-axis deterministic fitness scoring."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FitnessMetrics:
    stability: float
    efficiency: float
    modularity: float
    expandability: float
    revenue_alignment: float


WEIGHTS = {
    "stability": 0.30,
    "efficiency": 0.20,
    "modularity": 0.20,
    "expandability": 0.10,
    "revenue_alignment": 0.20,
}


def weighted_fitness(metrics: FitnessMetrics) -> float:
    score = (
        metrics.stability * WEIGHTS["stability"]
        + metrics.efficiency * WEIGHTS["efficiency"]
        + metrics.modularity * WEIGHTS["modularity"]
        + metrics.expandability * WEIGHTS["expandability"]
        + metrics.revenue_alignment * WEIGHTS["revenue_alignment"]
    )
    return round(score, 8)
