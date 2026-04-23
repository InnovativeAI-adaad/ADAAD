# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim; import from adaad.agents.invariants instead."""

from app._deprecated_shim import warn_legacy_module

warn_legacy_module("app.agents.invariants", "adaad.agents.invariants")

from adaad.agents.invariants import *  # noqa: F401,F403
