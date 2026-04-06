# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.dependencies import require_audit_scope
from app.api.schemas.dork_intents import DorkIntentBundle, DorkIntentRouteRequest
from app.orchestration.dork_intent_router import DorkIntentExecutor, DorkIntentRouter

router = APIRouter(tags=["ui"])


@router.post("/api/dork/intents/route", response_model=DorkIntentBundle)
def route_dork_intent(
    body: DorkIntentRouteRequest,
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
) -> DorkIntentBundle:
    """Route Dork query -> typed intent and execute a deterministic bundle."""
    _ = auth_ctx
    decision = DorkIntentRouter().route(body)
    return DorkIntentExecutor().execute(request=body, decision=decision)
