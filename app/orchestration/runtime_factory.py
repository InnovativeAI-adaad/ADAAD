# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim; import from adaad.orchestrator.runtime_factory instead."""

from app._deprecated_shim import warn_legacy_module

warn_legacy_module("app.orchestration.runtime_factory", "adaad.orchestrator.runtime_factory")

from adaad.orchestrator.runtime_factory import *  # noqa: F401,F403
