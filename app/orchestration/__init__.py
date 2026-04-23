# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim; import from adaad.orchestrator instead."""

from app._deprecated_shim import warn_legacy_module
from adaad.orchestrator import MutationOrchestrationService, StatusEnvelope

warn_legacy_module("app.orchestration", "adaad.orchestrator")

__all__ = ["StatusEnvelope", "MutationOrchestrationService", "DorkIntentRouter", "DorkIntentExecutor"]


def __getattr__(name: str):
    if name in {"DorkIntentRouter", "DorkIntentExecutor"}:
        from adaad.orchestrator import DorkIntentExecutor, DorkIntentRouter

        return {"DorkIntentRouter": DorkIntentRouter, "DorkIntentExecutor": DorkIntentExecutor}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
