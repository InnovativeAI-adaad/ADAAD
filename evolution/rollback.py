# SPDX-License-Identifier: Apache-2.0
"""Automatic rollback and pruning logic."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VariantHealth:
    variant_id: str
    invariant_ok: bool
    fitness_score: float
    revenue_score: float


def rollback_if_needed(history: list[str], current: VariantHealth) -> str:
    if current.invariant_ok:
        return current.variant_id
    if len(history) < 2:
        return history[0]
    return history[-2]


def prune_variants(pool: list[VariantHealth], *, min_fitness: float, min_revenue: float) -> list[VariantHealth]:
    return [v for v in pool if v.fitness_score >= min_fitness and v.revenue_score >= min_revenue]
