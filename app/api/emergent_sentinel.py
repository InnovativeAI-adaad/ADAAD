# SPDX-License-Identifier: Apache-2.0
"""Phase 160 — INNOV-66 · EBS API router."""

from __future__ import annotations

try:
    from fastapi import APIRouter
    from pydantic import BaseModel, Field

    router = APIRouter(prefix="/api/governance/ebs", tags=["ebs"])

    class DetectRequest(BaseModel):
        signal: str = Field(..., min_length=1)
        severity: str = Field(default="INFO")
        context: dict = Field(default_factory=dict)

    @router.get("/status")
    def get_ebs_status():
        from dorkllm.emergent_sentinel import get_sentinel
        return get_sentinel().status()

    @router.get("/baseline/chain")
    def get_baseline_chain(limit: int = 20):
        from dorkllm.emergent_sentinel import get_sentinel
        return get_sentinel().baseline_chain(limit=limit)

    @router.get("/alerts/chain")
    def get_alerts_chain(limit: int = 20):
        from dorkllm.emergent_sentinel import get_sentinel
        return get_sentinel().alerts_chain(limit=limit)

    @router.post("/detect")
    def detect(payload: DetectRequest):
        from dorkllm.emergent_sentinel import get_sentinel

        result = get_sentinel().detect(payload.model_dump())
        return {"ok": True, "result": result.to_dict()}

except ImportError:
    router = None  # type: ignore[assignment]
