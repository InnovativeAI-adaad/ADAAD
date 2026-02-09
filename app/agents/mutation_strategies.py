# SPDX-License-Identifier: Apache-2.0

"""
Concrete mutation strategies that generate actionable ops.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Tuple

from runtime.timeutils import now_iso


def analyze_dna(agent_dir: Path) -> Dict[str, Any]:
    """Extract current state from agent DNA."""
    dna_path = agent_dir / "dna.json"
    if not dna_path.exists():
        return {}
    return json.loads(dna_path.read_text(encoding="utf-8"))


def add_capability_strategy(agent_dir: Path) -> List[Dict[str, Any]]:
    """Add a new capability trait to agent DNA."""
    dna = analyze_dna(agent_dir)
    current_traits = dna.get("traits", [])

    candidate_traits = [
        "type_aware",
        "test_generator",
        "complexity_reducer",
        "error_handler",
        "performance_optimizer",
    ]

    new_traits = [trait for trait in candidate_traits if trait not in current_traits]
    if not new_traits:
        return []

    return [
        {
            "op": "set",
            "path": "/traits",
            "value": current_traits + [new_traits[0]],
        }
    ]


def increment_version_strategy(agent_dir: Path) -> List[Dict[str, Any]]:
    """Bump the agent's internal version counter."""
    dna = analyze_dna(agent_dir)
    current_version = dna.get("version", 0)

    return [
        {
            "op": "set",
            "path": "/version",
            "value": current_version + 1,
        }
    ]


def add_metadata_strategy(agent_dir: Path) -> List[Dict[str, Any]]:
    """Enrich DNA with operational metadata."""
    dna = analyze_dna(agent_dir)
    mutation_count = int(dna.get("mutation_count", 0))

    return [
        {
            "op": "set",
            "path": "/last_mutation",
            "value": now_iso(),
        },
        {
            "op": "set",
            "path": "/mutation_count",
            "value": mutation_count + 1,
        },
    ]


@dataclass
class MutationStrategy:
    name: str
    generator: Callable[[Path], List[Dict[str, Any]]]
    required_traits: Iterable[str] = field(default_factory=tuple)
    required_capabilities: Iterable[str] = field(default_factory=tuple)
    intent_label: str = ""
    skill_weight: float = 0.5

    def matches(self, dna: Mapping[str, Any]) -> bool:
        traits = set(dna.get("traits", []) or [])
        capabilities = set(dna.get("capabilities", []) or [])
        if not set(self.required_traits).issubset(traits):
            return False
        if not set(self.required_capabilities).issubset(capabilities):
            return False
        return True

    def generate_ops(self, agent_dir: Path) -> List[Dict[str, Any]]:
        return self.generator(agent_dir)


class StrategyRegistry:
    def __init__(self, strategies: Iterable[MutationStrategy]) -> None:
        self._strategies = {strategy.name: strategy for strategy in strategies}

    def list(self) -> List[MutationStrategy]:
        return list(self._strategies.values())

    def get(self, name: str) -> MutationStrategy | None:
        return self._strategies.get(name)

    def get_skill_weight(self, name: str) -> float | None:
        strategy = self.get(name)
        return strategy.skill_weight if strategy else None


    def matching_strategies(self, dna: Mapping[str, Any]) -> List[MutationStrategy]:
        return [strategy for strategy in self._strategies.values() if strategy.matches(dna)]

    def select(
        self,
        agent_dir: Path,
        skill_weights: Mapping[str, float] | None = None,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        dna = analyze_dna(agent_dir)
        candidates: List[Tuple[float, MutationStrategy]] = []
        for strategy in self.matching_strategies(dna):
            weight = strategy.skill_weight
            if skill_weights and strategy.name in skill_weights:
                weight = skill_weights[strategy.name]
            candidates.append((weight, strategy))

        for _, strategy in sorted(candidates, key=lambda item: item[0], reverse=True):
            ops = strategy.generate_ops(agent_dir)
            if ops:
                intent = strategy.intent_label or strategy.name
                return intent, ops
        return "noop", []


DEFAULT_REGISTRY = StrategyRegistry(
    [
        MutationStrategy(
            name="add_capability",
            generator=add_capability_strategy,
            required_traits=(),
            required_capabilities=(),
            intent_label="add_capability",
            skill_weight=0.6,
        ),
        MutationStrategy(
            name="increment_version",
            generator=increment_version_strategy,
            required_traits=(),
            required_capabilities=("versioning",),
            intent_label="increment_version",
            skill_weight=0.65,
        ),
        MutationStrategy(
            name="add_metadata",
            generator=add_metadata_strategy,
            required_traits=("type_aware",),
            required_capabilities=(),
            intent_label="add_metadata",
            skill_weight=0.7,
        ),
    ]
)


def load_skill_weights(state_path: Path) -> Dict[str, float]:
    if not state_path.exists():
        return {}
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    stats = data.get("stats", {}) or {}
    weights: Dict[str, float] = {}
    for name, entry in stats.items():
        if not isinstance(entry, dict):
            continue
        weight = entry.get("skill_weight")
        if isinstance(weight, (int, float)):
            weights[name] = float(weight)
    return weights


def select_strategy(agent_dir: Path, skill_weights: Mapping[str, float] | None = None) -> Tuple[str, List[Dict[str, Any]]]:
    """Pick a mutation strategy and generate ops."""
    return DEFAULT_REGISTRY.select(agent_dir, skill_weights=skill_weights)


__all__ = [
    "MutationStrategy",
    "StrategyRegistry",
    "DEFAULT_REGISTRY",
    "analyze_dna",
    "load_skill_weights",
    "select_strategy",
]
