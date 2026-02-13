# SPDX-License-Identifier: Apache-2.0
"""Predict mutation impact blast radius before execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Set

from app.agents.mutation_request import MutationRequest


@dataclass
class ImpactPrediction:
    affected_files: Set[str]
    affected_agents: Set[str]
    dependency_depth: int
    complexity_delta: int
    risk_score: float
    recommendations: list[str]


class ImpactPredictor:
    def __init__(self, agents_root: Path):
        self.agents_root = agents_root

    def predict(self, request: MutationRequest) -> ImpactPrediction:
        affected_files = self._extract_affected_files(request)
        affected_agents = {p.split("/", 1)[0] for p in affected_files if "/" in p}
        dependency_depth = 1 if affected_files else 0
        complexity_delta = sum(len(t.ops) for t in request.targets) if request.targets else len(request.ops)
        risk_score = min(1.0, (len(affected_agents) / 10.0) * 0.5 + (complexity_delta / 20.0) * 0.5)
        recommendations = self._recommend(risk_score, len(affected_agents))
        return ImpactPrediction(
            affected_files=affected_files,
            affected_agents=affected_agents,
            dependency_depth=dependency_depth,
            complexity_delta=complexity_delta,
            risk_score=risk_score,
            recommendations=recommendations,
        )

    def _extract_affected_files(self, request: MutationRequest) -> Set[str]:
        if request.targets:
            return {f"{request.agent_id}/{target.path}" for target in request.targets}
        return {f"{request.agent_id}/dna.json"}

    @staticmethod
    def _recommend(risk: float, affected_agents: int) -> list[str]:
        recs: list[str] = []
        if risk > 0.8:
            recs.append("high_risk_force_review")
        if affected_agents > 5:
            recs.append("large_blast_radius")
        if risk > 0.5:
            recs.append("enable_extra_monitoring")
        return recs


__all__ = ["ImpactPrediction", "ImpactPredictor"]
