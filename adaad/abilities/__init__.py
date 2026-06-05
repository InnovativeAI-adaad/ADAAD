# SPDX-License-Identifier: Apache-2.0
"""ADAAD high-level abilities package (lightweight, importable alone).

This package provides the canonical registry for the element-owned
high-level abilities (e.g. orchestrator.boot, cryovant.gate, architect.scan,
dream.cycle, beast.evaluate, ui.dashboard, cmce.consensus, ...).

It is intentionally small and has no heavy runtime/ or app/ dependencies
so it can be imported early or in isolation (e.g. for DORK intent routing,
UI capability discovery, or governance introspection).

Governance note:
- Registration is the hook point for future GovernanceGate enforcement
  (see comment in registry.py).
- Abilities are distinct from (but complementary to) the deeper
  runtime.capability v2 contracts.
"""

from __future__ import annotations

from .base import Ability
from .registry import (
    register_ability,
    get_ability,
    list_abilities,
    clear_abilities,  # test / dev helper
    abilities_snapshot,
)

__all__ = [
    "Ability",
    "register_ability",
    "get_ability",
    "list_abilities",
    "clear_abilities",
    "abilities_snapshot",
]
