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

    Calls placeholder governance hook before insert (per spec).
    The hook is a no-op placeholder now; real implementation will
    integrate with GovernanceGate.
    """
    if not isinstance(ability, Ability):
        raise TypeError(f"Expected Ability, got {type(ability)}")
    _governance_hook(ability)  # placeholder governance hook
    if ability.name in _registry:
        raise ValueError(f"Ability {ability.name} already registered")
    _registry[ability.name] = ability


def _governance_hook(ability: Ability) -> None:
    """Placeholder governance hook for ability registration.

    Future:
        from runtime.governance.gate import GovernanceGate
        decision = GovernanceGate().approve_ability_registration(ability)
        if not decision.approved:
            raise ValueError(f"GovernanceGate rejected: {decision.reason_codes}")
    Currently a no-op to keep the module importable and side-effect free
    until the gate surface is extended for abilities.
    """
    pass  # placeholder - no-op for now


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


def seed_from_capabilities_json(path: str | None = None) -> int:
    """Seed _registry from data/capabilities.json (the canonical persisted source).

    This makes `data/capabilities.json` seed the registry.

    Called explicitly or on package import (see __init__.py) in a side-effect-
    controlled way: the function is idempotent (skips already-registered names),
    fails gracefully if the json is missing or malformed, and never raises
    during normal import.

    Returns number of newly registered abilities.
    """
    if path is None:
        # adaad/abilities/registry.py -> adaad/ -> root/data/capabilities.json
        from pathlib import Path
        path = str(Path(__file__).resolve().parents[2] / "data" / "capabilities.json")

    try:
        import json
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return 0  # side-effect free: no crash on import if data unavailable

    if not isinstance(data, dict):
        return 0

    count = 0
    for name, entry in data.items():
        if not isinstance(name, str) or name in _registry:
            continue
        try:
            ab = Ability(
                name=name,
                owner=str(entry.get("owner", "Unknown")),
                version=str(entry.get("version", "0.0.0")),
                requires=list(entry.get("requires", [])) if isinstance(entry.get("requires"), (list, tuple)) else [],
                score=float(entry.get("score", 1.0)),
                tier=1,
                identity=entry.get("identity"),
                evidence=dict(entry.get("evidence", {})) if isinstance(entry.get("evidence"), dict) else {},
                updated_at=entry.get("updated_at"),
            )
            register_ability(ab)
            count += 1
        except Exception:
            continue  # per-entry resilience, no global side-effect failure
    return count


__all__ = [
    "Ability",  # re-export for convenience when importing registry directly
    "register_ability",
    "get_ability",
    "list_abilities",
    "clear_abilities",
    "abilities_snapshot",
    "seed_from_capabilities_json",
]
