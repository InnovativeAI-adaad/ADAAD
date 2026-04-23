# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim; import from adaad.agents.mutation_request instead."""

from app._deprecated_shim import warn_legacy_module

warn_legacy_module("app.agents.mutation_request", "adaad.agents.mutation_request")

from adaad.agents.mutation_request import *  # noqa: F401,F403
