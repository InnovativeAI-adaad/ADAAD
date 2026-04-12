from __future__ import annotations

import importlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse

from app.api.dependencies import require_audit_scope
from app.services.compliance_exports import COMPLIANCE_EXPORT_DATASETS, stream_csv_rows, stream_json_records
from runtime.api.compliance_export_service import ComplianceExportService

router = APIRouter()


def _server_module() -> Any:
    return importlib.import_module("server")


_COMPLIANCE_EXPORT_LIMIT_DEFAULT = 200
_COMPLIANCE_EXPORT_LIMIT_MAX = 1000
_COMPLIANCE_EXPORT_SERVICE: ComplianceExportService | None = None
_COMPLIANCE_EXPORT_SERVICE_KEY: tuple[str, str, str] | None = None


def _resolve_pagination(*, limit: int, offset: int, cursor: str | None) -> tuple[int, str | None]:
    if cursor is None:
        return offset, None
    try:
        decoded = ComplianceExportService.decode_cursor(cursor)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid_cursor") from exc
    if decoded is None:
        return offset, cursor
    return decoded, cursor


def _service_cache_key(root: Path, replay_proofs_dir: Path, journal_module: Any) -> tuple[str, str, str]:
    return (str(root), str(replay_proofs_dir), repr(journal_module))


def _get_compliance_export_service() -> ComplianceExportService:
    global _COMPLIANCE_EXPORT_SERVICE, _COMPLIANCE_EXPORT_SERVICE_KEY
    srv = _server_module()
    key = _service_cache_key(srv.ROOT, srv.REPLAY_PROOFS_DIR, srv.journal)
    if _COMPLIANCE_EXPORT_SERVICE is None or _COMPLIANCE_EXPORT_SERVICE_KEY != key:
        _COMPLIANCE_EXPORT_SERVICE = ComplianceExportService(
            root=srv.ROOT,
            replay_proofs_dir=srv.REPLAY_PROOFS_DIR,
            journal_read_entries=srv.journal.read_entries,
        )
        _COMPLIANCE_EXPORT_SERVICE_KEY = key
    return _COMPLIANCE_EXPORT_SERVICE


@router.get("/api/compliance/exports/{dataset}")
def get_compliance_export(
    dataset: str,
    fmt: str = Query(default="json", pattern="^(json|csv)$"),
    limit: int = Query(default=_COMPLIANCE_EXPORT_LIMIT_DEFAULT, ge=1, le=_COMPLIANCE_EXPORT_LIMIT_MAX),
    offset: int = Query(default=0, ge=0),
    cursor: str | None = Query(default=None),
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
) -> Response:
    if dataset not in COMPLIANCE_EXPORT_DATASETS:
        raise HTTPException(status_code=404, detail="unknown_compliance_dataset")
    resolved_offset, used_cursor = _resolve_pagination(limit=limit, offset=offset, cursor=cursor)
    export_service = _get_compliance_export_service()
    snapshot = export_service.get_dataset_snapshot(dataset)
    rows, page = export_service.paginate(snapshot, limit=limit, offset=resolved_offset)
    data = {
        "dataset": dataset,
        "format": fmt,
        "record_count": page["returned_records"],
        "records": rows,
        "pagination": {
            "limit": page["limit"],
            "offset": page["offset"],
            "cursor": used_cursor,
            "next_cursor": page["next_cursor"],
            "has_more": page["has_more"],
            "total_records": page["total_records"],
            "returned_records": page["returned_records"],
        },
        "snapshot": {
            "snapshot_id": snapshot.snapshot_id,
            "source_version": snapshot.source_version,
        },
        "indexes": snapshot.indexes,
    }
    if fmt == "csv":
        return StreamingResponse(
            stream_csv_rows(rows),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{dataset}.csv"'},
        )
    payload = {"schema_version": "1.1", "authn": auth_ctx, "data": data}
    return StreamingResponse(stream_json_records(envelope=payload, rows=rows), media_type="application/json")


@router.post("/api/compliance/exports/{dataset}/jobs")
def create_compliance_export_job(
    dataset: str,
    fmt: str = Query(default="json", pattern="^(json|csv)$"),
    limit: int = Query(default=_COMPLIANCE_EXPORT_LIMIT_DEFAULT, ge=1, le=_COMPLIANCE_EXPORT_LIMIT_MAX),
    offset: int = Query(default=0, ge=0),
    cursor: str | None = Query(default=None),
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
) -> dict[str, Any]:
    if dataset not in COMPLIANCE_EXPORT_DATASETS:
        raise HTTPException(status_code=404, detail="unknown_compliance_dataset")
    resolved_offset, used_cursor = _resolve_pagination(limit=limit, offset=offset, cursor=cursor)
    export_service = _get_compliance_export_service()
    snapshot = export_service.get_dataset_snapshot(dataset)
    rows, page = export_service.paginate(snapshot, limit=limit, offset=resolved_offset)
    srv = _server_module()
    srv.COMPLIANCE_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    job_id = f"job-{uuid.uuid4().hex[:12]}"
    extension = "csv" if fmt == "csv" else "json"
    export_path = srv.COMPLIANCE_EXPORT_DIR / f"{dataset}.{timestamp}.{job_id}.{extension}"
    if fmt == "csv":
        with export_path.open("w", encoding="utf-8", newline="") as handle:
            for chunk in stream_csv_rows(rows):
                handle.write(chunk)
    else:
        with export_path.open("w", encoding="utf-8") as handle:
            payload = {
                "schema_version": "1.1",
                "dataset": dataset,
                "format": "json",
                "record_count": page["returned_records"],
                "pagination": {
                    "limit": page["limit"],
                    "offset": page["offset"],
                    "cursor": used_cursor,
                    "next_cursor": page["next_cursor"],
                    "has_more": page["has_more"],
                    "total_records": page["total_records"],
                    "returned_records": page["returned_records"],
                },
                "snapshot": {
                    "snapshot_id": snapshot.snapshot_id,
                    "source_version": snapshot.source_version,
                },
                "indexes": snapshot.indexes,
            }
            for chunk in stream_json_records(envelope={"data": payload}, rows=rows):
                handle.write(chunk)
            handle.write("\n")
    return {
        "schema_version": "1.1",
        "authn": auth_ctx,
        "data": {
            "job_id": job_id,
            "dataset": dataset,
            "format": fmt,
            "record_count": page["returned_records"],
            "pagination": {
                "limit": page["limit"],
                "offset": page["offset"],
                "cursor": used_cursor,
                "next_cursor": page["next_cursor"],
                "has_more": page["has_more"],
                "total_records": page["total_records"],
                "returned_records": page["returned_records"],
            },
            "snapshot": {
                "snapshot_id": snapshot.snapshot_id,
                "source_version": snapshot.source_version,
            },
            "indexes": snapshot.indexes,
            "path": str(export_path),
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    }
