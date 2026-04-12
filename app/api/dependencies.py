# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import re
from typing import Any

from fastapi import Depends, Header, HTTPException, Request

from app.api.schemas.tenancy import TenantContext
from app.services.runtime_context import RuntimeContext

_TENANT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9._:-]+$")

_gate_open_checker: Any | None = None


def set_gate_open_checker(checker: Any) -> None:
    """Configure the gate-open assertion callable in the composition root."""
    global _gate_open_checker
    _gate_open_checker = checker


def get_runtime_context(request: Request) -> RuntimeContext:
    """Resolve the shared runtime context from FastAPI application state."""
    context = getattr(request.app.state, "runtime_context", None)
    if context is None:
        raise HTTPException(status_code=500, detail="runtime_context_not_configured")
    return context


def auth_context(authorization: str | None = Header(default=None)) -> str | None:
    """Extract the shared Authorization header context for API dependencies."""
    return authorization


def require_audit_scope(authorization: str | None = Depends(auth_context)) -> dict[str, Any]:
    """Enforce read-level access and return normalized auth metadata."""
    from runtime.api.app_layer import require_audit_read_scope

    return require_audit_read_scope(authorization)


def require_gate_open() -> dict[str, Any]:
    """Enforce that the Cryovant gate is open and return gate metadata."""
    if _gate_open_checker is None:
        raise HTTPException(status_code=500, detail="gate_open_checker_not_configured")
    return _gate_open_checker()


def require_tenant_context(
    request: Request,
) -> dict[str, str]:
    """Resolve tenant_id/workspace_id for request-scoped tenancy enforcement."""
    tenant_id_header = request.headers.get("X-Tenant-Id")
    workspace_id_header = request.headers.get("X-Workspace-Id")
    tenant_id = (tenant_id_header or request.query_params.get("tenant_id") or "").strip()
    workspace_id = (workspace_id_header or request.query_params.get("workspace_id") or "").strip()
    if not tenant_id or not workspace_id:
        raise HTTPException(status_code=400, detail="tenant_scope_required")
    if not _TENANT_ID_PATTERN.fullmatch(tenant_id) or not _TENANT_ID_PATTERN.fullmatch(workspace_id):
        raise HTTPException(status_code=400, detail="invalid_tenant_scope")
    return TenantContext(tenant_id=tenant_id, workspace_id=workspace_id).model_dump()
