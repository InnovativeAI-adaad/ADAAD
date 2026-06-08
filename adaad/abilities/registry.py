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

from .base import ALLOWED_PROVENANCE, Ability

_registry: dict[str, Ability] = {}

# Pluggable governance hook (Phase 199+ self-capable extension).
# Default is no-op (preserves lightweight importable-alone contract).
# Real implementation (lazy, from orchestrator bridge) can wire to CMES sandbox
# trial + CGDR healthy check + CMAC admission before allowing insert.
_governance_hook = None


def _default_governance_hook(ability: Ability) -> None:
    """Default (no-op) hook. Overridable via set_governance_hook for constitutional wiring."""
    pass


def set_governance_hook(hook: Any) -> None:
    """Install a governance hook called before every register_ability.
    Pass None to reset to default no-op. Hook signature: (Ability) -> None
    and must raise on rejection (fail-closed).
    """
    global _governance_hook
    if hook is None:
        _governance_hook = _default_governance_hook
    else:
        _governance_hook = hook


def get_governance_hook() -> Any:
    """Return the currently installed hook (or default)."""
    return _governance_hook or _default_governance_hook


def register_ability(ability: Ability) -> None:
    """Register a high-level ability.

    Calls the current governance hook (pluggable; default no-op) before insert.
    Hook may raise to reject (fail-closed, ABILITY-REG-HOOK-0).
    Provenance on the Ability is preserved (enables beyond-seed tracking).
    """
    if not isinstance(ability, Ability):
        raise TypeError(f"Expected Ability, got {type(ability)}")
    if ability.provenance not in ALLOWED_PROVENANCE:
        raise ValueError(f"Ability.provenance {ability.provenance!r} not allowed")
    hook = get_governance_hook()
    hook(ability)
    if ability.name in _registry:
        raise ValueError(f"Ability {ability.name} already registered")
    _registry[ability.name] = ability


# Back-compat alias for old internal name (some call sites may reference it).
_governance_hook = _default_governance_hook  # type: ignore[assignment]


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
    """Return a shallow copy of the current registry for introspection.
    Includes provenance for self-capable drift and promotion tracking.
    """
    return dict(_registry)


def register_promoted_ability(ability: Ability, *, force_provenance: str | None = None) -> None:
    """Register an ability that has passed constitutional promotion (e.g. CMES PASSED + HUMAN-0).
    Sets provenance to a promoted value if not already set. Still executes the
    current governance hook (which may be the full CMES/CGDR-aware one).
    """
    if force_provenance:
        # Rebuild with desired provenance (Ability is frozen)
        ability = Ability(
            name=ability.name,
            owner=ability.owner,
            version=ability.version,
            requires=list(ability.requires),
            score=ability.score,
            tier=ability.tier,
            identity=ability.identity,
            evidence=dict(ability.evidence),
            updated_at=ability.updated_at,
            provenance=force_provenance,
        )
    elif ability.provenance not in ("promoted_via_cmes", "hygiene_reconciled"):
        # Default promoted provenance when called via this path
        ability = Ability(
            name=ability.name,
            owner=ability.owner,
            version=ability.version,
            requires=list(ability.requires),
            score=ability.score,
            tier=ability.tier,
            identity=ability.identity,
            evidence=dict(ability.evidence),
            updated_at=ability.updated_at,
            provenance="promoted_via_cmes",
        )
    register_ability(ability)


def discover_and_register(*, sources: list[str] | None = None) -> int:
    """Convenience: run discovery and register all non-duplicate results.
    Each registration still goes through the current (pluggable) governance hook.
    Returns count of newly registered.
    """
    from .discovery import discover_abilities
    count = 0
    for ab in discover_abilities(sources=sources):
        if ab.name in _registry:
            continue
        try:
            register_ability(ab)
            count += 1
        except Exception:
            # Hook or dup rejected — continue (fail-closed per item)
            continue
    return count


def detect_and_reconcile_drift(*, auto_register_discovered: bool = False) -> dict[str, Any]:
    """Run drift detection and optionally auto-register clean discovered items.
    Returns a small dict with the report + actions taken. Does not auto-write
    capabilities.json (that is a separate governed hygiene/CGVE step).
    """
    from .drift import detect_abilities_drift
    report = detect_abilities_drift(include_discovered=True)
    actions: list[str] = []
    if auto_register_discovered and report.parity_ok:
        # Only when clean; otherwise let caller decide
        added = discover_and_register()
        if added:
            actions.append(f"auto-registered {added} discovered abilities (parity was clean)")
    return {
        "report": report.to_dict(),
        "actions": actions,
        "parity_ok": report.parity_ok,
    }


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
    "register_promoted_ability",
    "get_ability",
    "list_abilities",
    "clear_abilities",
    "abilities_snapshot",
    "seed_from_capabilities_json",
    "set_governance_hook",
    "get_governance_hook",
    "discover_and_register",
    "detect_and_reconcile_drift",
]
