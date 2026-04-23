# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim; import from adaad.orchestrator.adaad_trigger instead."""

from app._deprecated_shim import warn_legacy_module

warn_legacy_module("app.orchestration.adaad_trigger", "adaad.orchestrator.adaad_trigger")

from adaad.orchestrator.adaad_trigger import *  # noqa: F401,F403
