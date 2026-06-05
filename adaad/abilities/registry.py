# SPDX-License-Identifier: Apache-2.0
"""Lightweight, importable-alone registry for high-level ADAAD abilities.

This module is the single source of truth for the "abilities" surface
that was previously scattered across data/capabilities.json and ad-hoc
registration lists in app/main.py.

Design goals (per "adaad/abilities" charter):
- Importable with zero heavy dependencies (no runtime/, no app/).
- Simple dict-backed O(1) lookup.
- Tier filtering for list_abilities.
- Explicit hook point for future GovernanceGate enforcement on registration
  (see comment in register_ability).
- Compatible with the existing element-owned abilities
  (orchestrator.boot, cryovant.gate, cmce.consensus, ...).

Usage (lightweight):
    from adaad.abilities import Ability, register_ability, get_ability, list_abilities

    register_ability(Ability(name="cmce.consensus", owner="Water", version="0.10.0",
                             requires=["cryovant.gate"], tier=1))
    a = get_ability("cmce.consensus")
    core = list_abilities(tier=1)
"""

from __future__ import annotations

from typing import Any

from .base import Ability

_registry: dict[str, Ability] = {}


def register_ability(ability: Ability) -> None:
    """Register a high-level ability.

    GovernanceGate hook point (future):
        Before the dict insert, a call site such as
            from runtime.governance.gate import GovernanceGate
            GovernanceGate().approve_ability_registration(ability)
        will be inserted once the gate surface for abilities is ratified.
        For now the hook is a comment so that this module remains
        importable in isolation during early Phase 199/200 work.
    """
    if not isinstance(ability, Ability):
        raise TypeError(f"Expected Ability, got {type(ability)}")
    if ability.name in _registry:
        raise ValueError(f"Ability {ability.name} already registered")
    _registry[ability.name] = ability


def get_ability(name: str) -> Ability:
    """Return the Ability by name (raises KeyError if absent)."""
    return _registry[name]


def list_abilities(tier: int | None = None) -> list[Ability]:
    """Return abilities, optionally filtered by tier.

    tier=None  -> all abilities (in registration order)
    tier=0     -> constitutional only
    tier=1     -> core
    tier=2     -> extension
    """
    if tier is None:
        return list(_registry.values())
    return [a for a in _registry.values() if a.tier == tier]


# --- Test / dev helpers (mirrors pattern in adaad/orchestrator/registry.py) ---

def clear_abilities() -> None:
    """Clear the registry (intended for tests only)."""
    _registry.clear()


def abilities_snapshot() -> dict[str, Ability]:
    """Return a shallow copy of the current registry for introspection."""
    return dict(_registry)


__all__ = [
    "Ability",  # re-export for convenience when importing registry directly
    "register_ability",
    "get_ability",
    "list_abilities",
    "clear_abilities",
    "abilities_snapshot",
]
