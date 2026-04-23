# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim; import from adaad.orchestrator.contracts instead."""

from app._deprecated_shim import warn_legacy_module

warn_legacy_module("app.orchestration.contracts", "adaad.orchestrator.contracts")

from adaad.orchestrator.contracts import *  # noqa: F401,F403
