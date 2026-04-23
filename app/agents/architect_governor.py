# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim; import from adaad.agents.architect_governor instead."""

from app._deprecated_shim import warn_legacy_module

warn_legacy_module("app.agents.architect_governor", "adaad.agents.architect_governor")

from adaad.agents.architect_governor import *  # noqa: F401,F403
