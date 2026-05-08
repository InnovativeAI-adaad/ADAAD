# SPDX-License-Identifier: Apache-2.0
"""Autonomous deterministic evolution scheduler."""

from __future__ import annotations

from dataclasses import dataclass

from core.random_control import DeterministicSeedManager


@dataclass(frozen=True)
class VariantRecord:
    variant_id: str
    fitness_score: float
    revenue_score: float


class EvolutionScheduler:
    def __init__(self, seed_manager: DeterministicSeedManager) -> None:
        self.seed_manager = seed_manager
        self.history: list[dict[str, object]] = []

    def select_top_variants(self, pool: list[VariantRecord], k: int = 1) -> list[VariantRecord]:
        ordered = sorted(pool, key=lambda item: (item.fitness_score, item.revenue_score), reverse=True)
        return ordered[:k]

    def run_epoch(self, epoch: int, pool: list[VariantRecord], k: int = 1) -> list[VariantRecord]:
        namespace = f"epoch:{epoch}"
        seed = self.seed_manager.derive(namespace).seed
        selected = self.select_top_variants(pool=pool, k=k)
        self.history.append({"epoch": epoch, "seed": seed, "selected": [v.variant_id for v in selected]})
        return selected
