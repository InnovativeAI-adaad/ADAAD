# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim; import from adaad.orchestrator.mutation_orchestration_service instead."""

from app._deprecated_shim import warn_legacy_module

warn_legacy_module("app.orchestration.mutation_orchestration_service", "adaad.orchestrator.mutation_orchestration_service")

from adaad.orchestrator.mutation_orchestration_service import *  # noqa: F401,F403
