# SPDX-License-Identifier: Apache-2.0
"""Impact scoring for governed mutation bundles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from app.agents.mutation_request import MutationRequest


@dataclass(frozen=True)
class ImpactScore:
    semantic_depth: float
    structural_risk: float
    governance_proximity: float
    lineage_divergence: float

    @property
    def total(self) -> float:
        total = (
            (self.semantic_depth * 0.35)
            + (self.structural_risk * 0.30)
            + (self.governance_proximity * 0.20)
            + (self.lineage_divergence * 0.15)
        )
        return round(min(1.0, max(0.0, total)), 3)


class ImpactScorer:
    """Compute normalized impact score for a mutation request."""

    _HIGH_RISK_KEYWORDS = {"security", "governance", "constitution", "runtime", "core"}
    _TARGET_TYPE_WEIGHTS = {
        "runtime": 1.0,
        "security": 1.0,
        "governance": 1.0,
        "code": 0.8,
        "dna": 0.3,
        "docs": 0.1,
    }

    def score(self, request: MutationRequest) -> ImpactScore:
        targets = request.targets or []
        target_paths = [t.path.lower() for t in targets]
        target_types = [t.target_type.lower() for t in targets if t.target_type]

        ops_count = sum(len(t.ops) for t in targets) if targets else len(request.ops)
        semantic_depth = min(1.0, ops_count / 12.0)

        structural_hits = self._keyword_hits(target_paths, self._HIGH_RISK_KEYWORDS)
        path_risk = min(1.0, structural_hits / max(1, len(target_paths))) if target_paths else 0.2
        type_risk = max((self._TARGET_TYPE_WEIGHTS.get(t, 0.5) for t in target_types), default=0.2)
        structural_risk = min(1.0, max(path_risk, type_risk))

        governance_proximity = 1.0 if any("certificate" in p or "ledger" in p for p in target_paths) else 0.25
        lineage_divergence = min(1.0, len({t.target_type for t in targets}) / 4.0) if targets else 0.1
        return ImpactScore(
            semantic_depth=round(semantic_depth, 3),
            structural_risk=round(structural_risk, 3),
            governance_proximity=round(governance_proximity, 3),
            lineage_divergence=round(lineage_divergence, 3),
        )

    @staticmethod
    def _keyword_hits(values: List[str], keywords: set[str]) -> int:
        hits = 0
        for value in values:
            if any(keyword in value for keyword in keywords):
                hits += 1
        return hits


__all__ = ["ImpactScorer", "ImpactScore"]
