from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse

from app.api.dependencies import get_runtime_context, require_audit_scope
from app.services.runtime_context import RuntimeContext
from app.services.compliance_exports import (
    COMPLIANCE_EXPORT_DATASETS,
    load_control_evidence_snapshots,
    load_incident_remediation_logs,
    load_policy_change_history,
    load_replay_attestations,
    render_csv,
)

router = APIRouter()


def compliance_dataset_rows(dataset: str, *, context: RuntimeContext) -> list[dict[str, Any]]:
    replay_attestations = load_replay_attestations(replay_proofs_dir=context.replay_proofs_dir)
    if dataset == "control-evidence-snapshots":
        return load_control_evidence_snapshots(root=context.root, replay_attestations=replay_attestations)
    if dataset == "immutable-replay-attestations":
        return replay_attestations
    if dataset == "policy-change-history":
        return load_policy_change_history(root=context.root, journal_module=context.journal)
    if dataset == "incident-remediation-logs":
        return load_incident_remediation_logs(journal_module=context.journal)
    raise HTTPException(status_code=404, detail="unknown_compliance_dataset")


@router.get("/api/compliance/exports/{dataset}")
def get_compliance_export(
    dataset: str,
    fmt: str = Query(default="json", pattern="^(json|csv)$"),
    limit: int = Query(default=_COMPLIANCE_EXPORT_LIMIT_DEFAULT, ge=1, le=_COMPLIANCE_EXPORT_LIMIT_MAX),
    offset: int = Query(default=0, ge=0),
    cursor: str | None = Query(default=None),
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
    context: RuntimeContext = Depends(get_runtime_context),
) -> Response:
    if dataset not in COMPLIANCE_EXPORT_DATASETS:
        raise HTTPException(status_code=404, detail="unknown_compliance_dataset")
    rows = compliance_dataset_rows(dataset, context=context)
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
    context: RuntimeContext = Depends(get_runtime_context),
) -> dict[str, Any]:
    if dataset not in COMPLIANCE_EXPORT_DATASETS:
        raise HTTPException(status_code=404, detail="unknown_compliance_dataset")
    rows = compliance_dataset_rows(dataset, context=context)
    context.compliance_export_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    job_id = f"job-{uuid.uuid4().hex[:12]}"
    extension = "csv" if fmt == "csv" else "json"
    export_path = context.compliance_export_dir / f"{dataset}.{timestamp}.{job_id}.{extension}"
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
