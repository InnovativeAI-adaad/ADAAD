# SPDX-License-Identifier: Apache-2.0
"""Deprecated compatibility shim for mutation budget manager."""

from __future__ import annotations

import warnings

warnings.warn(
    "runtime.evolution.mutation_budget_manager is deprecated; use runtime.evolution.mutation_budget",
    DeprecationWarning,
    stacklevel=2,
)

from runtime.evolution.mutation_budget import MutationBudgetDecision, MutationBudgetManager

__all__ = ["MutationBudgetManager", "MutationBudgetDecision"]
