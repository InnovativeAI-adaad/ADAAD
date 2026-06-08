# SPDX-License-Identifier: Apache-2.0
"""INNOV-115 · CGPR — REST API endpoints.

Phase 210 · v10.21.0 · InnovativeAI LLC · Governor: DUSTIN L REID

Endpoints:
  POST /cgpr/render     — render a new governance proof bundle
  GET  /cgpr/verify/{bundle_id} — verify a bundle from the ledger
  GET  /cgpr/ledger     — list all proof ledger entries
  GET  /cgpr/bundle/{bundle_id} — retrieve a specific bundle from file
  GET  /cgpr/status     — CGPR engine health
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel
except ImportError:
    APIRouter = None  # type: ignore
    HTTPException = Exception  # type: ignore
    BaseModel = object  # type: ignore

from dorkllm.constitutional_governance_proof_renderer import (
    ConstitutionalGovernanceProofRenderer,
    ProofBundle,
    ProofLedger,
    CGPRError,
    CGPRManifestError,
    CGPRAttestError,
    CGPRVerifyError,
    GOVERNOR,
    INNOV_NUMBER,
    PHASE,
    VERSION,
)

router = APIRouter(prefix="/cgpr", tags=["CGPR"])

_renderer: Optional[ConstitutionalGovernanceProofRenderer] = None
BUNDLE_STORE = Path(os.environ.get("CGPR_BUNDLE_STORE", "data/cgpr/bundles"))


def _get_renderer() -> ConstitutionalGovernanceProofRenderer:
    global _renderer
    if _renderer is None:
        _renderer = ConstitutionalGovernanceProofRenderer()
    return _renderer


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

if APIRouter is not None:
    from pydantic import BaseModel as _BaseModel

    class InvariantInput(_BaseModel):
        code: str
        name: str
        phase_introduced: int
        status: str = "ACTIVE"

    class AttestationInput(_BaseModel):
        source: str
        phase: int
        event_type: str
        payload_digest: str

    class RenderRequest(_BaseModel):
        phase: int
        invariants: List[InvariantInput]
        attestations: List[AttestationInput]
        human0_signature_hex: str = ""
        human0_pubkey_fingerprint: str = ""
        export_path: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

if APIRouter is not None:

    @router.post("/render")
    def render_bundle(req: RenderRequest) -> Dict[str, Any]:
        """Render a new governance proof bundle. CGPR-BUNDLE-0 / CGPR-AUDIT-0."""
        renderer = _get_renderer()
        try:
            bundle = renderer.render(
                phase=req.phase,
                invariants=[i.dict() for i in req.invariants],
                attestations=[a.dict() for a in req.attestations],
                human0_signature_hex=req.human0_signature_hex,
                human0_pubkey_fingerprint=req.human0_pubkey_fingerprint,
            )
        except (CGPRManifestError, CGPRAttestError, CGPRError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        if req.export_path:
            renderer.export_json(bundle, Path(req.export_path))

        return {
            "bundle_id": bundle.bundle_id,
            "schema_version": bundle.schema_version,
            "phase": bundle.phase,
            "adaad_version": bundle.adaad_version,
            "generated_at": bundle.generated_at,
            "invariant_count": len(bundle.invariant_manifest),
            "attestation_count": len(bundle.attestations),
            "human0_slot_status": bundle.human0_slot.get("slot_status")
            if isinstance(bundle.human0_slot, dict)
            else bundle.human0_slot["slot_status"],
            "bundle_hmac": bundle.bundle_hmac,
        }

    @router.post("/verify")
    def verify_bundle(bundle_data: Dict[str, Any]) -> Dict[str, Any]:
        """Verify a submitted ProofBundle dict. CGPR-HMAC-0."""
        renderer = _get_renderer()
        try:
            bundle = ProofBundle(**bundle_data)
            report = renderer.verify(bundle)
            return {"verified": True, "report": report}
        except CGPRVerifyError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid bundle format: {exc}")

    @router.get("/ledger")
    def get_ledger() -> Dict[str, Any]:
        """List all proof ledger entries. CGPR-AUDIT-0."""
        renderer = _get_renderer()
        ledger = renderer.ledger
        return {
            "entry_count": ledger.entry_count,
            "head_digest": ledger.head_digest,
            "governor": GOVERNOR,
            "innov": INNOV_NUMBER,
        }

    @router.get("/status")
    def cgpr_status() -> Dict[str, Any]:
        """CGPR engine health check."""
        renderer = _get_renderer()
        return {
            "status": "operational",
            "innov": INNOV_NUMBER,
            "phase": PHASE,
            "adaad_version": VERSION,
            "governor": GOVERNOR,
            "ledger_entries": renderer.ledger.entry_count,
            "head_digest": renderer.ledger.head_digest,
        }
