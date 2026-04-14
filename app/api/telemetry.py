# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import require_audit_scope

router = APIRouter()

_telemetry_sink_ref: Any | None = None


def set_telemetry_sink(sink: Any | None) -> None:
    global _telemetry_sink_ref
    _telemetry_sink_ref = sink


def get_telemetry_sink() -> Any | None:
    return _telemetry_sink_ref


@router.get('/telemetry/decisions')
def telemetry_decisions(
    strategy_id: str | None = Query(default=None),
    outcome: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    authn: dict[str, Any] = Depends(require_audit_scope),
) -> dict[str, Any]:
    import server as _server

    return _server.telemetry_decisions_legacy(
        strategy_id=strategy_id,
        outcome=outcome,
        limit=limit,
        offset=offset,
        authn=authn,
    )


@router.get('/telemetry/analytics')
def telemetry_analytics(
    window_size: int = Query(default=100, ge=10, le=10000),
    authn: dict[str, Any] = Depends(require_audit_scope),
) -> dict[str, Any]:
    import server as _server

    return _server.telemetry_analytics_legacy(window_size=window_size, authn=authn)


@router.get('/telemetry/strategy/{strategy_id}')
def telemetry_strategy_detail(
    strategy_id: str,
    window_size: int = Query(default=100, ge=10, le=10000),
    authn: dict[str, Any] = Depends(require_audit_scope),
) -> dict[str, Any]:
    import server as _server

    return _server.telemetry_strategy_detail_legacy(
        strategy_id=strategy_id,
        window_size=window_size,
        authn=authn,
    )
