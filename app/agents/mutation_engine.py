# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim; import from adaad.agents.mutation_engine instead."""

from app._deprecated_shim import warn_legacy_module

warn_legacy_module("app.agents.mutation_engine", "adaad.agents.mutation_engine")

from adaad.agents.mutation_engine import *  # noqa: F401,F403
