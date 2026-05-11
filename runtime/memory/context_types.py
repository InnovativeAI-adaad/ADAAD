# SPDX-License-Identifier: Apache-2.0
"""Shared context type constants for memory context filtering and ledger acceptance."""

from __future__ import annotations

VALID_CONTEXT_TYPES: frozenset[str] = frozenset({
    "mutation_proposal",    # Pre-mutation codebase snapshot
    "fitness_signal",       # FitnessLandscape signal context
    "governance_advisory",  # GovernanceHealthAggregator advisory context
    "craft_pattern",        # CraftPatternExtractor output (Phase 9 PR-9-02)
    "replay_injection",     # ContextReplayInterface injection (Phase 9 PR-9-03)
})
