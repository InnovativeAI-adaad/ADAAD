# SPDX-License-Identifier: Apache-2.0
from app.orchestration.contracts import StatusEnvelope
from app.orchestration.mutation_orchestration_service import MutationOrchestrationService

__all__ = ["StatusEnvelope", "MutationOrchestrationService", "DorkIntentRouter", "DorkIntentExecutor"]


def __getattr__(name: str):
    if name in {"DorkIntentRouter", "DorkIntentExecutor"}:
        from app.orchestration.dork_intent_router import DorkIntentExecutor, DorkIntentRouter

        return {"DorkIntentRouter": DorkIntentRouter, "DorkIntentExecutor": DorkIntentExecutor}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
