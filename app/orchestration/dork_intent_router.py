# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim; import from adaad.orchestrator.dork_intent_router instead."""

from app._deprecated_shim import warn_legacy_module

warn_legacy_module("app.orchestration.dork_intent_router", "adaad.orchestrator.dork_intent_router")

from adaad.orchestrator.dork_intent_router import *  # noqa: F401,F403
