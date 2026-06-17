# SPDX-License-Identifier: Apache-2.0
"""ADAAD high-level abilities package (lightweight, importable alone).

This package provides the canonical registry for the element-owned
high-level abilities (e.g. orchestrator.boot, cryovant.gate, architect.scan,
dream.cycle, beast.evaluate, ui.dashboard, cmce.consensus, ...).

Phase 199+ self-capable extension:
- Discovery beyond static seed (discovery.py).
- Abilities-specific drift detection + hygiene reports (drift.py).
- Pluggable governance hook (registry.set_governance_hook) for wiring to
  constitutional self-mutation (CMES sandbox trial deltas, CGDR healthy gate, etc.).
- Provenance tracking on Ability (seed vs discovered/synthesized/promoted/hygiene).
- Promoted registration path + convenience discover_and_register / detect_and_reconcile_drift.
- Meta self-abilities (adaad.abilities.*) for introspection, drift hygiene, and self-registration.

It is intentionally small and has no heavy runtime/ or app/ dependencies
so it can be imported early or in isolation (e.g. for DORK intent routing,
UI capability discovery, or governance introspection).

Governance note:
- Registration is the hook point for GovernanceGate / CMES / CGDR enforcement
  (see registry.py and the orchestrator bridge).
- Abilities are distinct from (but complementary to) the deeper
  runtime.capability v2 contracts and adaad/agents/* contracts.
"""

from __future__ import annotations

from .base import Ability, AbilityProtocol
from .registry import (
    register_ability,
    register_promoted_ability,
    get_ability,
    list_abilities,
    clear_abilities,  # test / dev helper
    abilities_snapshot,
    seed_from_capabilities_json,
    set_governance_hook,
    get_governance_hook,
    discover_and_register,
    detect_and_reconcile_drift,
)
from .discovery import discover_abilities
from .drift import detect_abilities_drift, AbilitiesDriftReport, DriftItem

# Make data/capabilities.json seed the registry on (package) import.
# This is done in a side-effect-free / controlled way:
# - seed_from_capabilities_json() is idempotent (no dups)
# - it swallows errors (missing file, bad json, bad entries) so import never breaks
# - it only adds entries not already present
# Callers that want explicit control can call the function directly or clear first.
seed_from_capabilities_json()

__all__ = [
    "Ability",
    "AbilityProtocol",
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
    "discover_abilities",
    "detect_abilities_drift",
    "AbilitiesDriftReport",
    "DriftItem",
]
