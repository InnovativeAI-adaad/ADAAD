# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from sse_starlette.sse import EventSourceResponse
from starlette.responses import StreamingResponse

from app.api.dependencies import get_runtime_context
from app.services.runtime_context import RuntimeContext

router = APIRouter()


@router.websocket("/ws/events")
async def ws_events(
    websocket: WebSocket,
    context: RuntimeContext = Depends(get_runtime_context),
) -> None:
    from runtime.innovations_bus import get_bus  # adaad: import-boundary-ok:event-bus-runtime-subscription

    relay_policy = websocket.query_params.get("relay_policy", "drop_oldest")
    if relay_policy not in {"drop_oldest", "coalesce_latest"}:
        await websocket.close(code=1008, reason="invalid_relay_policy")
        return

    def _parse_limit(name: str, default: int, cap: int) -> int:
        raw = websocket.query_params.get(name)
        if raw is None:
            return default
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail=f"invalid_{name}") from None
        if value < 0 or value > cap:
            raise HTTPException(status_code=422, detail=f"invalid_{name}")
        return value

    def _parse_float(name: str, default: float, minimum: float, maximum: float) -> float:
        raw = websocket.query_params.get(name)
        if raw is None:
            return default
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail=f"invalid_{name}") from None
        if value < minimum or value > maximum:
            raise HTTPException(status_code=422, detail=f"invalid_{name}")
        return value

    try:
        metrics_limit = _parse_limit("metrics_limit", default=200, cap=500)
        journal_limit = _parse_limit("journal_limit", default=200, cap=500)
        relay_queue_limit = _parse_limit("relay_queue_limit", default=128, cap=512)
        heartbeat_interval_s = _parse_float("heartbeat_interval_s", default=30.0, minimum=1.0, maximum=120.0)
        stale_timeout_s = _parse_float("stale_timeout_s", default=90.0, minimum=2.0, maximum=300.0)
    except HTTPException:
        await websocket.close(code=1008, reason="invalid_query_params")
        return

    await websocket.accept()
    await websocket.send_json(
        {
            "type": "hello",
            "channels": ["metrics", "journal", "innovations"],
            "status": "live",
            "endpoint_meta": {
                "history_caps": {"metrics_limit_max": 500, "journal_limit_max": 500},
                "queue_policy": relay_policy,
                "relay_queue_limit": relay_queue_limit,
                "heartbeat_interval_s": heartbeat_interval_s,
                "stale_timeout_s": stale_timeout_s,
            },
        }
    )
    events = []
    for entry in context.metrics.tail(limit=metrics_limit):
        events.append(
            {
                "channel": "metrics",
                "kind": str(entry.get("event", entry.get("event_type", "metric"))),
                "timestamp": str(entry.get("timestamp", entry.get("ts", ""))),
                "event": entry,
            }
        )
    for entry in context.journal.read_entries(limit=journal_limit):
        events.append(
            {
                "channel": "journal",
                "kind": str(entry.get("action", entry.get("tx_type", "journal"))),
                "timestamp": str(entry.get("timestamp", entry.get("ts", ""))),
                "event": entry,
            }
        )
    await websocket.send_json({"type": "event_batch", "events": events})

    bus = get_bus()
    queue = await bus.subscribe()
    relay_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=relay_queue_limit)
    disconnect_reason = "client_closed"
    dropped_frames = 0
    last_client_signal = asyncio.get_event_loop().time()
    coalesced_latest: dict[str, Any] | None = None
    stop_signal = asyncio.Event()

    async def _client_reader() -> None:
        nonlocal last_client_signal
        while not stop_signal.is_set():
            try:
                message = await asyncio.wait_for(websocket.receive_json(), timeout=heartbeat_interval_s)
            except asyncio.TimeoutError:
                continue
            except Exception:
                break
            if isinstance(message, dict) and message.get("type") == "pong":
                last_client_signal = asyncio.get_event_loop().time()

    async def _relay_ingress() -> None:
        nonlocal dropped_frames, coalesced_latest
        while not stop_signal.is_set():
            frame = await queue.get()
            if relay_policy == "coalesce_latest":
                if relay_queue.full():
                    coalesced_latest = frame
                    dropped_frames += 1
                    context.metrics.log(
                        "ws_events_frames_dropped",
                        payload={"policy": relay_policy, "dropped": dropped_frames},
                    )
                    continue
            if relay_queue.full():
                _ = relay_queue.get_nowait()
                dropped_frames += 1
                context.metrics.log(
                    "ws_events_frames_dropped",
                    payload={"policy": relay_policy, "dropped": dropped_frames},
                )
            await relay_queue.put(frame)
            if coalesced_latest is not None and not relay_queue.full():
                await relay_queue.put(coalesced_latest)
                coalesced_latest = None
            context.metrics.log("ws_events_queue_depth", payload={"depth": relay_queue.qsize(), "limit": relay_queue_limit})

    reader_task = asyncio.create_task(_client_reader())
    ingress_task = asyncio.create_task(_relay_ingress())
    try:
        while True:
            try:
                now = asyncio.get_event_loop().time()
                if (now - last_client_signal) >= stale_timeout_s:
                    disconnect_reason = "stale_client_timeout"
                    await websocket.send_json({"type": "disconnect", "reason": disconnect_reason})
                    break
                frame = await asyncio.wait_for(relay_queue.get(), timeout=heartbeat_interval_s)
                await websocket.send_json({"type": "innovations", "channel": "innovations", **frame})
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping", "ts": datetime.now(timezone.utc).isoformat()})
    except Exception:
        disconnect_reason = "send_or_receive_failure"
    finally:
        stop_signal.set()
        ingress_task.cancel()
        reader_task.cancel()
        for task in (ingress_task, reader_task):
            try:
                await task
            except BaseException:
                pass
        await bus.unsubscribe(queue)
        context.metrics.log(
            "ws_events_disconnect",
            payload={
                "cause": disconnect_reason,
                "dropped_frames": dropped_frames,
                "queue_depth": relay_queue.qsize(),
            },
        )
        try:
            await websocket.close(reason=disconnect_reason)
        except Exception:
            pass


@router.get("/api/webhooks/stream")
async def webhooks_stream(request: Request):
    async def event_generator():
        yield {"event": "connected", "data": json.dumps({"ts": datetime.now(timezone.utc).isoformat()})}
        while True:
            if await request.is_disconnected():
                break
            await asyncio.sleep(30)
            yield {"event": "heartbeat", "data": "ping"}

    return EventSourceResponse(event_generator())


@router.post("/api/dork/stream")
async def dork_stream_proxy(request: Request):
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=503, detail="server_api_key_not_configured")

    body = await request.json()

    async def _gen():
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": body.get("model", "claude-sonnet-4-6"),
                    "max_tokens": body.get("max_tokens", 4096),
                    "stream": True,
                    "system": body.get("system", ""),
                    "messages": body.get("messages", []),
                },
            ) as resp:
                async for chunk in resp.aiter_bytes():
                    yield chunk

    return StreamingResponse(_gen(), media_type="text/event-stream")
