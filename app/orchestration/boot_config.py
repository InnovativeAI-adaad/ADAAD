# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim; import from adaad.orchestrator.boot_config instead."""

from app._deprecated_shim import warn_legacy_module

warn_legacy_module("app.orchestration.boot_config", "adaad.orchestrator.boot_config")

from adaad.orchestrator.boot_config import *  # noqa: F401,F403
