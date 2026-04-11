# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.dependencies import require_tenant_context
from runtime.evolution.lineage_v2 import LineageLedgerV2


def _request_with_query(query_string: str) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/audit/epochs/e1/lineage",
        "headers": [],
        "query_string": query_string.encode("utf-8"),
    }
    return Request(scope)


def test_require_tenant_context_from_query_params() -> None:
    request = _request_with_query("tenant_id=t-1&workspace_id=w-1")
    ctx = require_tenant_context(request=request)
    assert ctx == {"tenant_id": "t-1", "workspace_id": "w-1"}


def test_require_tenant_context_missing_scope_fails_closed() -> None:
    request = _request_with_query("tenant_id=t-1")
    with pytest.raises(HTTPException) as exc_info:
        require_tenant_context(request=request)
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "tenant_scope_required"


def test_lineage_ledger_tenant_partition_filters_rows(tmp_path) -> None:
    tenant_path = tmp_path / "security" / "ledger" / "lineage_v2.jsonl"
    tenant_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "type": "MutationBundleEvent",
            "payload": {"epoch_id": "e1", "tenant_id": "tenant-a", "workspace_id": "ws-1"},
            "prev_hash": "x",
            "hash": "y",
        },
        {
            "type": "MutationBundleEvent",
            "payload": {"epoch_id": "e2", "tenant_id": "tenant-b", "workspace_id": "ws-2"},
            "prev_hash": "x2",
            "hash": "y2",
        },
    ]
    tenant_partitioned_path = tenant_path.parent / "tenants" / "tenant-a" / "ws-1" / tenant_path.name
    tenant_partitioned_path.parent.mkdir(parents=True, exist_ok=True)
    tenant_partitioned_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    ledger = LineageLedgerV2(
        ledger_path=tenant_path,
        tenant_context={"tenant_id": "tenant-a", "workspace_id": "ws-1"},
    )
    result = ledger._read_entries_unverified()
    assert len(result) == 1
    assert result[0]["payload"]["tenant_id"] == "tenant-a"
