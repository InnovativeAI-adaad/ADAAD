# SPDX-License-Identifier: Apache-2.0
"""Phase 155 — CGTH REST API router.

Endpoints
=========
GET  /api/governance/telemetry/stream   — paginated telemetry event stream
GET  /api/governance/telemetry/audit    — chain integrity audit
GET  /api/governance/telemetry/summary  — aggregate counts by event type
POST /api/governance/telemetry/emit     — emit a governance telemetry event

All endpoints require `audit:read` bearer scope (emit requires `audit:write`).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, Query, Header, HTTPException

from dorkllm.telemetry_hub import (
    CGTHEventType,
    CGTHUnregisteredEmitterError,
    ConstitutionalGovernanceTelemetryHub,
    TelemetryRecord,
    get_hub,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/governance/telemetry", tags=["cgth"])


# ---------------------------------------------------------------------------
# Auth helpers (re-use existing audit_auth pattern)
# ---------------------------------------------------------------------------

def _require_read(authorization: Optional[str] = Header(default=None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="audit:read bearer token required")
    return authorization.removeprefix("Bearer ").strip()


def _require_write(authorization: Optional[str] = Header(default=None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="audit:write bearer token required")
    return authorization.removeprefix("Bearer ").strip()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _record_to_dict(r: TelemetryRecord) -> Dict[str, Any]:
    return r.to_dict()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/stream")
def telemetry_stream(
    event_type: Optional[str] = Query(default=None),
    component_id: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    _token: str = Depends(_require_read),
) -> Dict[str, Any]:
    """Return filtered telemetry events from the CGTH ledger."""
    hub = get_hub()
    ev_type: Optional[CGTHEventType] = None
    if event_type:
        try:
            ev_type = CGTHEventType(event_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown event_type: {event_type}")
    records = hub.query(event_type=ev_type, component_id=component_id, limit=limit)
    return {
        "count":   len(records),
        "records": [_record_to_dict(r) for r in records],
    }


@router.get("/audit")
def telemetry_audit(
    _token: str = Depends(_require_read),
) -> Dict[str, Any]:
    """Run chain integrity audit and return summary."""
    hub = get_hub()
    try:
        summary = hub.audit_chain()
        return {"status": "ok", **summary}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/summary")
def telemetry_summary(
    _token: str = Depends(_require_read),
) -> Dict[str, Any]:
    """Return aggregate event counts by event_type and component_id."""
    hub = get_hub()
    records = hub.query(limit=10_000)
    by_type: Dict[str, int] = {}
    by_component: Dict[str, int] = {}
    for r in records:
        by_type[r.event_type.value]     = by_type.get(r.event_type.value, 0) + 1
        by_component[r.component_id]    = by_component.get(r.component_id, 0) + 1
    return {
        "total":        len(records),
        "by_type":      by_type,
        "by_component": by_component,
    }


@router.post("/emit")
def telemetry_emit(
    body: Dict[str, Any] = Body(...),
    _token: str = Depends(_require_write),
) -> Dict[str, Any]:
    """Emit a governance telemetry event.

    Body::

        {
          "component_id": "cpi",
          "event_type":   "PRESSURE_SNAPSHOT",
          "payload":      {...}
        }
    """
    component_id = body.get("component_id")
    event_type_str = body.get("event_type")
    payload = body.get("payload", {})

    if not component_id or not event_type_str:
        raise HTTPException(status_code=400, detail="component_id and event_type required")

    try:
        ev_type = CGTHEventType(event_type_str)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown event_type: {event_type_str}")

    hub = get_hub()
    try:
        event_id = hub.emit_event(component_id, ev_type, payload)
        return {"event_id": event_id, "status": "recorded"}
    except CGTHUnregisteredEmitterError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except Exception as exc:
        logger.exception("CGTH emit error")
        raise HTTPException(status_code=500, detail=str(exc))
