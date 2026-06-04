# SPDX-License-Identifier: Apache-2.0
"""REST router — INNOV-112 · CMWE — Constitutional Mutation Window Executor.

Endpoints:
  POST /api/cmwe/register    — register a CMSE window for execution
  POST /api/cmwe/execute     — execute a registered window
  GET  /api/cmwe/windows     — list all tracked windows
  GET  /api/cmwe/feedback    — list VelocityFeedback signals
  GET  /api/cmwe/attestations — list all attestation records
  GET  /api/cmwe/verify      — verify AttestationLedger chain
  GET  /api/cmwe/health      — liveness
"""
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dorkllm.constitutional_mutation_window_executor import (
    ConstitutionalMutationWindowExecutor,
    CMWEAuthError,
    CMWEAtomicError,
    CMWEChainError,
    CMWEError,
    CMWEImmutError,
    CMWEPreCheckError,
    CMWEScopeError,
    CMWETimeoutError,
    INNOV_CODE,
    INNOV_NUMBER,
    VERSION,
    PHASE,
)

router = APIRouter(prefix="/api/cmwe", tags=["CMWE"])
_executor = ConstitutionalMutationWindowExecutor()


class RegisterRequest(BaseModel):
    window_id: str
    proposal_id: str
    blast_tier: int = Field(..., ge=0, le=2)
    mutation_scope: list[str] = Field(..., min_length=1)
    constitutional_fitness: float = Field(default=1.0, ge=0.0, le=1.0)
    promoted_by: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class ExecuteRequest(BaseModel):
    window_id: str
    human0_identity: Optional[str] = None
    post_fitness: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    simulate_success: bool = Field(default=True, description="Dry-run: True=SUCCESS, False=FAILED")


@router.post("/register")
def register_window(req: RegisterRequest):
    w = _executor.register(
        window_id=req.window_id,
        proposal_id=req.proposal_id,
        blast_tier=req.blast_tier,
        mutation_scope=req.mutation_scope,
        constitutional_fitness=req.constitutional_fitness,
        promoted_by=req.promoted_by,
        metadata=req.metadata,
    )
    return {"status": "REGISTERED", "window_id": w.window_id,
            "stage": w.stage, "innov_code": INNOV_CODE}


@router.post("/execute")
def execute_window(req: ExecuteRequest):
    try:
        fn = (lambda w: True) if req.simulate_success else (lambda w: False)
        rec = _executor.execute(
            window_id=req.window_id,
            execution_fn=fn,
            human0_identity=req.human0_identity,
            post_fitness=req.post_fitness,
        )
        return {
            "status": "ATTESTED",
            "record_id": rec.record_id,
            "window_id": rec.window_id,
            "outcome": rec.outcome,
            "stage": rec.stage,
            "fitness_delta": rec.fitness_delta,
            "duration_ms": rec.duration_ms,
            "innov_code": INNOV_CODE,
        }
    except CMWEAuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except (CMWEPreCheckError, CMWEScopeError, CMWEImmutError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except CMWETimeoutError as exc:
        raise HTTPException(status_code=408, detail=str(exc))
    except CMWEError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/windows")
def list_windows():
    return {
        "windows": [
            {"window_id": w.window_id, "stage": w.stage, "outcome": w.outcome,
             "blast_tier": w.blast_tier, "constitutional_fitness": w.constitutional_fitness}
            for w in _executor._windows.values()
        ],
        "total": len(_executor._windows),
        "innov_code": INNOV_CODE,
    }


@router.get("/feedback")
def list_feedback():
    fb = _executor.get_feedback_log()
    return {
        "feedback": [
            {"window_id": f.window_id, "outcome": f.outcome,
             "fitness_delta": f.fitness_delta, "duration_ms": f.duration_ms,
             "blast_tier": f.blast_tier, "scope_count": f.scope_count}
            for f in fb
        ],
        "total": len(fb),
        "innov_code": INNOV_CODE,
    }


@router.get("/attestations")
def list_attestations():
    records = _executor.attestation_records()
    return {"attestations": records, "total": len(records), "innov_code": INNOV_CODE}


@router.get("/verify")
def verify_ledger():
    try:
        ok = _executor.verify_ledger()
        return {"chain_valid": ok, "innov_code": INNOV_CODE, "phase": PHASE}
    except CMWEChainError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/health")
def health():
    return {
        "status": "operational",
        "innov_code": INNOV_CODE,
        "innov_number": INNOV_NUMBER,
        "version": VERSION,
        "phase": PHASE,
        "windows_tracked": len(_executor._windows),
        "feedback_signals": len(_executor.get_feedback_log()),
        "governor": "DUSTIN L REID",
    }
