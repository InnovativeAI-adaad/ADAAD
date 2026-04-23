# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim; import from adaad.agents.base_agent instead."""

from app._deprecated_shim import warn_legacy_module

warn_legacy_module("app.agents.base_agent", "adaad.agents.base_agent")

from adaad.agents.base_agent import *  # noqa: F401,F403
