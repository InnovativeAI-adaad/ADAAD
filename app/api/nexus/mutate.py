from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from security.challenge import within_window
from security.ledger.append import append_entry

router = APIRouter()


class MutationOp(BaseModel):
    op: Literal["add", "replace", "remove"]
    path: str
    value: Any | None = None


class MutationRequest(BaseModel):
    mutation_type: Literal["dna_patch"] = "dna_patch"
    payload: Dict[Literal["dna"], List[MutationOp]]
    signature: str
    nonce: str
    timestamp: str
    challenge_id: str


@router.post("/api/nexus/agents/{agent_id}/mutate")
async def mutate_agent(agent_id: str, request: MutationRequest) -> Dict[str, Any]:
    window_ok = within_window(request.timestamp)
    request_hash = hashlib.sha256(
        json.dumps(
            {
                "agent_id": agent_id,
                "mutation_type": request.mutation_type,
                "payload": request.payload,
                "nonce": request.nonce,
                "timestamp": request.timestamp,
                "challenge_id": request.challenge_id,
                "challenge": "STUB",
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    append_entry(
        {
            "timestamp": request.timestamp,
            "action": "mutate",
            "result": "REJECTED",
            "details": {
                "agent_id": agent_id,
                "mutation_type": request.mutation_type,
                "signature_id": request.signature[:16],
                "window_ok": window_ok,
                "request_hash": request_hash,
            },
        }
    )

    raise HTTPException(
        status_code=403,
        detail={"status": "REJECTED", "reason": "Mutation Engine in STUB state."},
    )


__all__ = ["router"]
