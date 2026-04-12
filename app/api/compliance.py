from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response

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
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
    context: RuntimeContext = Depends(get_runtime_context),
) -> Response:
    if dataset not in COMPLIANCE_EXPORT_DATASETS:
        raise HTTPException(status_code=404, detail="unknown_compliance_dataset")
    rows = compliance_dataset_rows(dataset, context=context)
    if fmt == "csv":
        body = render_csv(rows)
        return Response(
            content=body,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{dataset}.csv"'},
        )
    payload = {
        "schema_version": "1.0",
        "authn": auth_ctx,
        "data": {
            "dataset": dataset,
            "format": "json",
            "record_count": len(rows),
            "records": rows,
        },
    }
    return JSONResponse(content=payload)


@router.post("/api/compliance/exports/{dataset}/jobs")
def create_compliance_export_job(
    dataset: str,
    fmt: str = Query(default="json", pattern="^(json|csv)$"),
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
        export_path.write_text(render_csv(rows), encoding="utf-8")
    else:
        export_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "dataset": dataset,
                    "record_count": len(rows),
                    "records": rows,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    return {
        "schema_version": "1.0",
        "authn": auth_ctx,
        "data": {
            "job_id": job_id,
            "dataset": dataset,
            "format": fmt,
            "record_count": len(rows),
            "path": str(export_path),
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    }
