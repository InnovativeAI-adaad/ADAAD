from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import get_runtime_context, require_audit_scope, require_tenant_context
from app.services.runtime_context import RuntimeContext

router = APIRouter()


def _load_bundle(bundle_id: str, *, context: RuntimeContext) -> tuple[dict[str, Any], str]:
    bundle_file = context.forensic_export_dir / f"{bundle_id}.json"
    if not bundle_file.exists():
        raise HTTPException(status_code=404, detail="bundle_not_found")
    try:
        return json.loads(bundle_file.read_text(encoding="utf-8")), str(bundle_file)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="bundle_read_error") from exc


def _redact_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    result = dict(bundle)
    if "export_metadata" in result:
        em = dict(result["export_metadata"])
        if "signer" in em:
            em["signer"] = {k: v for k, v in em["signer"].items() if k != "signature"}
        result["export_metadata"] = em
    return result


@router.get("/api/audit/epochs/{epoch_id}/replay-proof")
def audit_replay_proof(
    epoch_id: str,
    redaction: str | None = Query(default=None),
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
    tenant_ctx: dict[str, str] = Depends(require_tenant_context),
    context: RuntimeContext = Depends(get_runtime_context),
) -> dict[str, Any]:
    proof_file = context.replay_proofs_dir / f"{epoch_id}.replay_attestation.v1.json"
    if not proof_file.exists():
        raise HTTPException(status_code=404, detail="replay_proof_not_found")
    try:
        bundle: dict[str, Any] = json.loads(proof_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="proof_read_error") from exc
    proof_tenant = bundle.get("tenant") if isinstance(bundle.get("tenant"), dict) else {}
    proof_tenant_id = str(bundle.get("tenant_id") or proof_tenant.get("tenant_id") or "").strip()
    proof_workspace_id = str(bundle.get("workspace_id") or proof_tenant.get("workspace_id") or "").strip()
    if proof_tenant_id and proof_workspace_id:
        if proof_tenant_id != tenant_ctx["tenant_id"] or proof_workspace_id != tenant_ctx["workspace_id"]:
            raise HTTPException(status_code=403, detail="tenant_scope_mismatch")

    if redaction == "sensitive" and "signatures" in bundle:
        bundle = {**bundle}
        del bundle["signatures"]

    return {
        "schema_version": "1.0",
        "authn": auth_ctx,
        "data": {
            "epoch_id": epoch_id,
            "bundle_path": str(proof_file),
            "bundle": bundle,
            "verification": {
                "proof_digest_present": "proof_digest" in bundle,
                "signatures_present": "signatures" in bundle,
            },
        },
    }


@router.get("/api/audit/epochs/{epoch_id}/lineage")
def audit_epoch_lineage(
    epoch_id: str,
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
    tenant_ctx: dict[str, str] = Depends(require_tenant_context),
    context: RuntimeContext = Depends(get_runtime_context),
) -> dict[str, Any]:
    ledger = context.lineage_ledger_cls(tenant_context=tenant_ctx)
    lineage = ledger.read_epoch(epoch_id)
    lineage_digest = ledger.compute_incremental_epoch_digest(epoch_id)
    expected = ledger.get_expected_epoch_digest(epoch_id) or ""
    journal_entries = context.journal.read_entries(limit=200, tenant_context=tenant_ctx)
    return {
        "schema_version": "1.0",
        "authn": auth_ctx,
        "data": {
            "epoch_id": epoch_id,
            "lineage": lineage,
            "lineage_digest": lineage_digest,
            "expected_epoch_digest": expected,
            "journal_entries": journal_entries,
        },
    }


@router.get("/api/audit/bundles/{bundle_id}")
def audit_bundle(
    bundle_id: str,
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
    tenant_ctx: dict[str, str] = Depends(require_tenant_context),
    context: RuntimeContext = Depends(get_runtime_context),
) -> dict[str, Any]:
    raw_bundle, bundle_path = _load_bundle(bundle_id, context=context)
    bundle_tenant = raw_bundle.get("tenant") if isinstance(raw_bundle.get("tenant"), dict) else {}
    bundle_tenant_id = str(raw_bundle.get("tenant_id") or bundle_tenant.get("tenant_id") or "").strip()
    bundle_workspace_id = str(raw_bundle.get("workspace_id") or bundle_tenant.get("workspace_id") or "").strip()
    if bundle_tenant_id and bundle_workspace_id:
        if bundle_tenant_id != tenant_ctx["tenant_id"] or bundle_workspace_id != tenant_ctx["workspace_id"]:
            raise HTTPException(status_code=403, detail="tenant_scope_mismatch")
    builder = context.evidence_bundle_builder_factory(export_dir=context.forensic_export_dir)
    validation = builder.validate_bundle(raw_bundle)
    return {
        "schema_version": "1.0",
        "authn": auth_ctx,
        "data": {
            "bundle_id": bundle_id,
            "bundle_path": bundle_path,
            "bundle": _redact_bundle(raw_bundle),
            "validation": validation,
        },
    }
