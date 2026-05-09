# SPDX-License-Identifier: Apache-2.0
# COMPLIANCE-CONST-0: limit constants must be defined before Query defaults
# COMPLIANCE-STREAM-0: streaming helpers must be module-local generators
# COMPLIANCE-DATA-0: payload data key must reference resolved rows, not phantom variable
from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Generator

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

# ── Constants (invariant COMPLIANCE-CONST-0) ─────────────────────────────────
_COMPLIANCE_EXPORT_LIMIT_DEFAULT: int = 200
_COMPLIANCE_EXPORT_LIMIT_MAX: int = 1000


# ── Streaming helpers (invariant COMPLIANCE-STREAM-0) ────────────────────────

def _jsonable_scalar(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def stream_csv_rows(rows: list[dict[str, Any]]) -> Generator[str, None, None]:
    """Yield CSV chunks: header row then one row per record."""
    if not rows:
        return
    keys: list[str] = sorted({key for row in rows for key in row.keys()})
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=keys)
    writer.writeheader()
    yield buf.getvalue()
    buf.seek(0)
    buf.truncate(0)
    for row in rows:
        writer.writerow({key: _jsonable_scalar(row.get(key)) for key in keys})
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)


def stream_json_records(
    *, envelope: dict[str, Any], rows: list[dict[str, Any]]
) -> Generator[str, None, None]:
    """Yield a streaming JSON envelope with an inline records array."""
    prefix_obj = dict(envelope)
    data_section = dict(prefix_obj.get("data", {}))
    data_section.pop("records", None)
    prefix_obj["data"] = data_section
    raw = json.dumps(prefix_obj, separators=(",", ":"), sort_keys=True)
    yield raw[:-1] + ',"records":['
    for idx, row in enumerate(rows):
        if idx:
            yield ","
        yield json.dumps(row, separators=(",", ":"), sort_keys=True)
    yield "]}"


# ── Dataset resolver ──────────────────────────────────────────────────────────

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


# ── Endpoints ─────────────────────────────────────────────────────────────────

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
    # invariant COMPLIANCE-DATA-0: use resolved rows, not phantom variable
    payload: dict[str, Any] = {
        "schema_version": "1.1",
        "dataset": dataset,
        "record_count": len(rows),
    }
    envelope = {"schema_version": "1.1", "authn": auth_ctx, "data": payload}
    return StreamingResponse(
        stream_json_records(envelope=envelope, rows=rows),
        media_type="application/json",
    )


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
    record_count = len(rows)
    if fmt == "csv":
        with export_path.open("w", encoding="utf-8", newline="") as handle:
            for chunk in stream_csv_rows(rows):
                handle.write(chunk)
    else:
        payload = {
            "schema_version": "1.1",
            "dataset": dataset,
            "format": "json",
            "record_count": record_count,
            "pagination": {"limit": limit, "offset": offset, "cursor": cursor},
        }
        with export_path.open("w", encoding="utf-8") as handle:
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
            "record_count": record_count,
            "pagination": {"limit": limit, "offset": offset, "cursor": cursor},
            "path": str(export_path),
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    }
