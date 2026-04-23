# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim; import from adaad.orchestrator.replay_preflight instead."""

from app._deprecated_shim import warn_legacy_module

warn_legacy_module("app.orchestration.replay_preflight", "adaad.orchestrator.replay_preflight")

from adaad.orchestrator.replay_preflight import *  # noqa: F401,F403
