# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim; import from adaad.agents.discovery instead."""

from app._deprecated_shim import warn_legacy_module

warn_legacy_module("app.agents.discovery", "adaad.agents.discovery")

from adaad.agents.discovery import *  # noqa: F401,F403
