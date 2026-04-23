# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim; import from adaad.agents.sample_agent.__init__ instead."""

from app._deprecated_shim import warn_legacy_module

warn_legacy_module("app.agents.sample_agent", "adaad.agents.sample_agent.__init__")

from adaad.agents.sample_agent import *  # noqa: F401,F403
