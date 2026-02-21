# SPDX-License-Identifier: Apache-2.0
"""Dispatcher that executes registered handlers and appends latency metadata."""

from __future__ import annotations

import logging
from time import monotonic_ns, perf_counter
from typing import Any

from adaad.orchestrator.registry import HandlerRegistry, get_tool

try:
    from runtime import metrics as runtime_metrics
except Exception:  # pragma: no cover - runtime package optional for isolated usage
    runtime_metrics = None

MAX_LATENCY_MS = 50.0
_LOGGER = logging.getLogger("adaad.dispatcher")


def _latency_budget_meta(*, route: str, latency_ms: float) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "route": route,
        "latency_ms": round(latency_ms, 3),
        "latency_target_ms": MAX_LATENCY_MS,
        "within_target": latency_ms <= MAX_LATENCY_MS,
    }
    if not meta["within_target"]:
        meta["warning"] = "latency_budget_exceeded"
        _LOGGER.warning("dispatcher latency target exceeded", extra={"route": route, "latency_ms": latency_ms})
        if runtime_metrics is not None:
            try:
                runtime_metrics.log(
                    event_type="dispatch_latency_budget_exceeded",
                    payload={"route": route, "latency_ms": round(latency_ms, 3), "target_ms": MAX_LATENCY_MS},
                    level="WARNING",
                )
            except Exception:
                pass
    return meta


def _error_envelope(*, code: str, message: str, route: str, latency_ms: float) -> dict[str, Any]:
    return {
        "status": "error",
        "error": {
            "code": code,
            "message": message,
        },
        "metadata": _latency_budget_meta(route=route, latency_ms=latency_ms),
    }


class Dispatcher:
    """Route requests through a preloaded registry."""

    def __init__(self, registry: HandlerRegistry) -> None:
        self._registry = registry

    def dispatch(self, key: str, payload: Any = None) -> dict[str, Any]:
        started = perf_counter()
        try:
            handler = self._registry.get(key)
        except KeyError:
            latency_ms = (perf_counter() - started) * 1000.0
            return _error_envelope(code="route_not_found", message=f"unknown route: {key}", route=key, latency_ms=latency_ms)

        try:
            result = handler(payload)
        except Exception as exc:  # pragma: no cover
            latency_ms = (perf_counter() - started) * 1000.0
            return _error_envelope(code="handler_execution_failed", message=str(exc), route=key, latency_ms=latency_ms)

        latency_ms = (perf_counter() - started) * 1000.0
        meta = _latency_budget_meta(route=key, latency_ms=latency_ms)
        if isinstance(result, dict):
            response = dict(result)
            metadata = dict(response.get("metadata") or {})
            metadata.update(meta)
            response["metadata"] = metadata
            return response
        return {"result": result, "metadata": meta}


# Compatibility function-based API supporting prior *args/**kwargs use.
def dispatch(tool_name: str, /, *args: Any, **kwargs: Any) -> dict[str, Any]:
    started_ns = monotonic_ns()
    try:
        run_tool = get_tool(tool_name)
    except KeyError:
        now_ns = monotonic_ns()
        return _error_envelope(
            code="route_not_found",
            message=f"unknown route: {tool_name}",
            route=tool_name,
            latency_ms=(now_ns - started_ns) / 1_000_000,
        )

    try:
        result = run_tool(*args, **kwargs)
    except Exception as exc:  # pragma: no cover
        now_ns = monotonic_ns()
        envelope = _error_envelope(
            code="handler_execution_failed",
            message=str(exc),
            route=tool_name,
            latency_ms=(now_ns - started_ns) / 1_000_000,
        )
        envelope["_dispatch_meta"] = {
            "tool": tool_name,
            "started_mono_ns": started_ns,
            "finished_mono_ns": now_ns,
            "latency_ns": max(0, now_ns - started_ns),
        }
        return envelope

    finished_ns = monotonic_ns()
    latency_ms = (finished_ns - started_ns) / 1_000_000
    envelope: dict[str, Any] = {
        "result": result,
        "metadata": _latency_budget_meta(route=tool_name, latency_ms=latency_ms),
        "_dispatch_meta": {
            "tool": tool_name,
            "started_mono_ns": started_ns,
            "finished_mono_ns": finished_ns,
            "latency_ns": max(0, finished_ns - started_ns),
            "latency_target_ms": MAX_LATENCY_MS,
            "within_target": latency_ms <= MAX_LATENCY_MS,
        },
    }
    if latency_ms > MAX_LATENCY_MS:
        envelope["_dispatch_meta"]["warning"] = "latency_budget_exceeded"
    return envelope


__all__ = ["Dispatcher", "dispatch", "MAX_LATENCY_MS"]
