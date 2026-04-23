# SPDX-License-Identifier: Apache-2.0
from adaad.orchestrator.contracts import StatusEnvelope
from adaad.orchestrator.mutation_orchestration_service import MutationOrchestrationService

__all__ = ["StatusEnvelope", "MutationOrchestrationService", "DorkIntentRouter", "DorkIntentExecutor"]


def __getattr__(name: str):
    if name in {"DorkIntentRouter", "DorkIntentExecutor"}:
        from adaad.orchestrator.dork_intent_router import DorkIntentExecutor, DorkIntentRouter

        return {"DorkIntentRouter": DorkIntentRouter, "DorkIntentExecutor": DorkIntentExecutor}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
