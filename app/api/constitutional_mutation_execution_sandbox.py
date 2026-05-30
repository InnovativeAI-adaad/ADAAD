"""
REST API endpoints for Constitutional Mutation Execution Sandbox (CMES) — Phase 199
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from dorkllm.constitutional_mutation_execution_sandbox import (
    ConstitutionalMutationExecutionSandbox,
    CMESSandboxLedger,
    MutationSpec,
    BlastRadius,
    CMESConstitutionalViolation,
    CMESPromotionBlocked,
)

router = APIRouter(prefix="/cmes", tags=["CMES"])
_sandbox = ConstitutionalMutationExecutionSandbox(ledger=CMESSandboxLedger())


class OpenSandboxRequest(BaseModel):
    mutation_id: str
    module_path: str
    blast_radius: str
    description: str
    invariants_targeted: List[str] = []
    expected_test_markers: List[str] = []
    seed: Optional[str] = None
    proposed_by: str = "MutationAgent"


class ExecuteRequest(BaseModel):
    run_id: str


class Human0ActionRequest(BaseModel):
    run_id: str
    human0_identity: str


@router.post("/sandbox/open")
def open_sandbox(req: OpenSandboxRequest) -> Dict[str, Any]:
    """Open a new sandbox execution for a proposed mutation. CMES-SCOPE-0."""
    try:
        spec_kwargs = req.dict()
        spec_kwargs["blast_radius"] = BlastRadius(req.blast_radius)
        if spec_kwargs.get("seed") is None:
            del spec_kwargs["seed"]
        spec = MutationSpec(**spec_kwargs)
        run = _sandbox.open_sandbox(spec)
        return {"run_id": run.run_id, "status": run.status.value, "mutation_id": spec.mutation_id}
    except CMESConstitutionalViolation as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/sandbox/execute")
def execute_sandbox(req: ExecuteRequest) -> Dict[str, Any]:
    """Execute the sandbox run and capture BehavioralDelta. CMES-ISOLATE-0, CMES-DELTA-0."""
    try:
        run = _sandbox.execute(req.run_id)
        return {
            "run_id": run.run_id,
            "status": run.status.value,
            "delta": run.delta.to_dict() if run.delta else None,
            "failure_reason": run.failure_reason,
        }
    except CMESConstitutionalViolation as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/sandbox/promote")
def promote(req: Human0ActionRequest) -> Dict[str, Any]:
    """Promote a PASSED sandbox run to live. CMES-HUMAN0-0, CMES-PROMOTE-0."""
    try:
        promoted = _sandbox.promote(req.run_id, req.human0_identity)
        return {"promoted_run_id": promoted.run_id, "status": promoted.status.value,
                "promoted_by": promoted.promoted_by}
    except CMESPromotionBlocked as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except CMESConstitutionalViolation as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@router.post("/sandbox/discard")
def discard(req: Human0ActionRequest) -> Dict[str, Any]:
    """Discard a sandbox run. CMES-HUMAN0-0."""
    try:
        discarded = _sandbox.discard(req.run_id, req.human0_identity)
        return {"discarded_run_id": discarded.run_id, "status": discarded.status.value,
                "discarded_by": discarded.discarded_by}
    except CMESConstitutionalViolation as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@router.post("/sandbox/replay/{run_id}")
def replay(run_id: str) -> Dict[str, Any]:
    """Replay a sandbox run for determinism verification. CMES-REPLAY-0."""
    try:
        return _sandbox.replay(run_id)
    except CMESConstitutionalViolation as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/chain/verify")
def verify_chain() -> Dict[str, Any]:
    """Verify HMAC chain integrity of sandbox ledger. CMES-CHAIN-0."""
    try:
        ok = _sandbox.verify_chain()
        return {"chain_valid": ok, "governor": "DUSTIN L REID"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/summary")
def summary() -> Dict[str, Any]:
    """Return sandbox execution summary and invariant manifest."""
    return _sandbox.summary()


@router.get("/export")
def export() -> Dict[str, Any]:
    """Export full sandbox ledger."""
    return _sandbox.export()
