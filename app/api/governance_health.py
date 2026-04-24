# SPDX-License-Identifier: Apache-2.0
"""Phase 157 — INNOV-63 · GHI REST API Router

GET  /api/governance/health          current GHI score + snapshot
GET  /api/governance/health/history  recent GHI history from CGTH

Author: DEVADAAD · InnovativeAI LLC
"""

from __future__ import annotations

try:
    from fastapi import APIRouter
    router = APIRouter(prefix="/api/governance/health", tags=["ghi"])

    @router.get("")
    def get_health():
        from dorkllm.governance_health import score_now
        snapshot = score_now()
        return snapshot.to_dict()

    @router.get("/history")
    def get_health_history(limit: int = 20):
        from dorkllm.governance_health import get_ghi
        return {"history": get_ghi().history(limit=limit)}

except ImportError:
    router = None  # type: ignore[assignment]
