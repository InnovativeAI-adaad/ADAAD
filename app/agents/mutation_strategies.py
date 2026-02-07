# SPDX-License-Identifier: Apache-2.0

"""
Concrete mutation strategies that generate actionable ops.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

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


STRATEGIES = {
    "add_capability": add_capability_strategy,
    "increment_version": increment_version_strategy,
    "add_metadata": add_metadata_strategy,
}


def select_strategy(agent_dir: Path) -> Tuple[str, List[Dict[str, Any]]]:
    """Pick a mutation strategy and generate ops."""
    for name, strategy in STRATEGIES.items():
        ops = strategy(agent_dir)
        if ops:
            return name, ops
    return "noop", []


__all__ = ["select_strategy", "STRATEGIES"]
