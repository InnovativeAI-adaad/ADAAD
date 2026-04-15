# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import require_audit_scope
from app.api.schemas.dork_intents import (
    DorkConsoleRouteError,
    DorkConsoleRouteRequest,
    DorkConsoleRouteResponse,
    DorkIntentBundle,
    DorkIntentRouteRequest,
    DorkProposalExecuteRequest,
    DorkProposalExecuteResponse,
)
from runtime.governance.dork_proposal_adapter import (
    DorkProposalPreflightError,
    ProposalValidationError,
    execute_dork_proposal,
)

router = APIRouter(tags=["ui"])


@router.post("/api/dork/intents/route", response_model=DorkIntentBundle)
def route_dork_intent(
    body: DorkIntentRouteRequest,
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
) -> DorkIntentBundle:
    """Route Dork query -> typed intent and execute a deterministic bundle."""
    _ = auth_ctx
    return _execute_dork_bundle(body)


def _execute_dork_bundle(body: DorkIntentRouteRequest) -> DorkIntentBundle:
    from app.orchestration.dork_intent_router import DorkIntentExecutor, DorkIntentRouter

    decision = DorkIntentRouter().route(body)
    return DorkIntentExecutor().execute(request=body, decision=decision)


def _console_outcome(bundle: DorkIntentBundle) -> tuple[str, str]:
    response = bundle.response if isinstance(bundle.response, dict) else {}
    if bundle.intent == "explain_blockers" and int(response.get("blocker_count", 0)) > 0:
        return "blocked", "governance_blockers_detected"
    if bundle.intent == "prepare_mutation_review":
        transition = response.get("transition") if isinstance(response.get("transition"), dict) else {}
        if transition.get("status") != "ok":
            return "blocked", str(transition.get("reason") or "mutation_blocked_fail_closed")
    return "approved", "advisory_clear"


@router.post(
    "/api/dork/console/route",
    response_model=DorkConsoleRouteResponse,
    responses={409: {"model": DorkConsoleRouteError}},
)
def route_dork_console(
    body: DorkConsoleRouteRequest,
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
) -> DorkConsoleRouteResponse:
    """Contract-first route for dork.html deterministic console outcomes."""
    _ = auth_ctx
    request = DorkIntentRouteRequest(**body.model_dump())
    bundle = _execute_dork_bundle(request)
    outcome, reason = _console_outcome(bundle)
    if outcome == "blocked":
        raise HTTPException(
            status_code=409,
            detail=DorkConsoleRouteError(
                error_code="governance_blocked",
                message="Governance gate blocked this request.",
                detail={"reason": reason, "intent": bundle.intent, "bundle_digest": bundle.bundle_digest},
            ).model_dump(),
        )
    return DorkConsoleRouteResponse(
        outcome=outcome,
        outcome_reason=reason,
        console_message=f"Approved: {bundle.summary}",
        bundle=bundle,
    )


@router.post("/api/dork/proposals/execute", response_model=DorkProposalExecuteResponse)
def execute_dork_proposal_route(
    body: DorkProposalExecuteRequest,
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
) -> DorkProposalExecuteResponse:
    """Execute a DORK proposal through GovernanceGate + approved proposal queue."""
    _ = auth_ctx
    try:
        result = execute_dork_proposal(
            proposal_payload=body.proposal,
            trust_mode=body.trust_mode,
            actor=body.actor,
        )
    except DorkProposalPreflightError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
    except ProposalValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=423, detail=str(exc)) from exc
    return DorkProposalExecuteResponse(
        ok=True,
        proposal_id=result.proposal_id,
        gate_decision_id=result.gate_decision_id,
        governance_decision=result.governance_decision,
        queued_event_type=result.queued_event_type,
        queue_hash=result.queue_hash,
    )
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from security.ledger import journal
from security.ledger.append import append_entry

_DORK_EVENT_LEDGER_PATH = Path("security/ledger/dork_events.jsonl")
_STREAM_SUBSCRIBERS: list[asyncio.Queue[dict[str, Any]]] = []
_STREAM_LOCK = asyncio.Lock()


class DorkEventEnvelope(BaseModel):
    """Structured event envelope accepted by the Dork event ingestion endpoint."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=128)
    event_type: str = Field(min_length=1, max_length=128)
    severity: Literal["info", "warn", "error", "success"] = "info"
    payload: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str = Field(min_length=1, max_length=128)
    epoch_id: str = Field(default="", max_length=128)
    ts: str = Field(min_length=1, max_length=64)


def _parse_iso_ts(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("ts_required")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("ts_must_be_iso8601") from exc
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_event_count() -> int:
    if not _DORK_EVENT_LEDGER_PATH.exists():
        return 0
    count = 0
    with _DORK_EVENT_LEDGER_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count


async def _publish_event(frame: dict[str, Any]) -> None:
    dead: list[asyncio.Queue[dict[str, Any]]] = []
    async with _STREAM_LOCK:
        subscribers = list(_STREAM_SUBSCRIBERS)
    for queue in subscribers:
        try:
            queue.put_nowait(frame)
        except asyncio.QueueFull:
            dead.append(queue)
    if dead:
        async with _STREAM_LOCK:
            _STREAM_SUBSCRIBERS[:] = [s for s in _STREAM_SUBSCRIBERS if s not in dead]


@router.post("/api/ledger/log/events")
async def append_dork_event(body: DorkEventEnvelope) -> dict[str, Any]:
    """Append a structured Dork event to the ledger and fan-out to SSE subscribers."""

    try:
        canonical_ts = _parse_iso_ts(body.ts)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    seq = _read_event_count() + 1
    event = {
        "schema_version": "dork_event_envelope.v1",
        "source": body.source,
        "event_type": body.event_type,
        "severity": body.severity,
        "payload": body.payload,
        "correlation_id": body.correlation_id,
        "epoch_id": body.epoch_id,
        "ts": canonical_ts,
        "seq": seq,
    }
    persisted = append_entry(event, path=str(_DORK_EVENT_LEDGER_PATH))
    journal.write_entry(
        agent_id="dork",
        action="dork_event_appended",
        payload={
            "event_type": body.event_type,
            "severity": body.severity,
            "correlation_id": body.correlation_id,
            "epoch_id": body.epoch_id,
            "seq": str(seq),
        },
    )
    await _publish_event({"type": "dork_event", "event": persisted})
    return {"ok": True, "event": persisted}


@router.get("/api/ledger/log/stream")
async def stream_dork_events(request: Request) -> StreamingResponse:
    """SSE stream of structured Dork events in deterministic append order."""

    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
    async with _STREAM_LOCK:
        _STREAM_SUBSCRIBERS.append(queue)

    async def event_generator():
        yield f"event: connected\ndata: {json.dumps({'type': 'connected'})}\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    frame = await asyncio.wait_for(queue.get(), timeout=30.0)
                    data = json.dumps(frame, separators=(",", ":"), sort_keys=True)
                    yield f"event: dork_event\ndata: {data}\n\n"
                except asyncio.TimeoutError:
                    yield "event: heartbeat\ndata: ping\n\n"
        finally:
            async with _STREAM_LOCK:
                _STREAM_SUBSCRIBERS[:] = [s for s in _STREAM_SUBSCRIBERS if s is not queue]

    return StreamingResponse(event_generator(), media_type="text/event-stream")
