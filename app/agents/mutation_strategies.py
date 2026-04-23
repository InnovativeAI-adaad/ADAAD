# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim; import from adaad.agents.mutation_strategies instead."""

from app._deprecated_shim import warn_legacy_module

warn_legacy_module("app.agents.mutation_strategies", "adaad.agents.mutation_strategies")

from adaad.agents.mutation_strategies import *  # noqa: F401,F403
