# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim; import from adaad.agents instead."""

from app._deprecated_shim import warn_legacy_module

warn_legacy_module("app.agents", "adaad.agents")

from adaad.agents import *  # noqa: F401,F403
