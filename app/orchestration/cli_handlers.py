# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim; import from adaad.orchestrator.cli_handlers instead."""

from app._deprecated_shim import warn_legacy_module

warn_legacy_module("app.orchestration.cli_handlers", "adaad.orchestrator.cli_handlers")

from adaad.orchestrator.cli_handlers import *  # noqa: F401,F403
