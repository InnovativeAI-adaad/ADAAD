# SPDX-License-Identifier: Apache-2.0
"""Phase 158 — INNOV-64 · CSR REST API Router

GET  /api/governance/repair/status    current GHI status (no CGTH emit)
POST /api/governance/repair/run       generate repair proposals + emit to CGTH
GET  /api/governance/repair/actions   available repair action taxonomy

Author: DEVADAAD · InnovativeAI LLC
"""

from __future__ import annotations

try:
    from fastapi import APIRouter
    router = APIRouter(prefix="/api/governance/repair", tags=["csr"])

    @router.get("/status")
    def get_repair_status():
        """Return current GHI status without emitting any CGTH events."""
        from dorkllm.self_repair import get_csr
        return get_csr().quick_status()

    @router.post("/run")
    def run_repair():
        """Generate repair proposals for the current GHI band and emit to CGTH."""
        from dorkllm.self_repair import repair_now
        run = repair_now()
        return run.to_dict()

    @router.get("/actions")
    def list_repair_actions():
        """Return the full RepairAction taxonomy."""
        from dorkllm.self_repair import RepairAction, RepairPriority
        return {
            "actions":    [a.value for a in RepairAction],
            "priorities": [p.value for p in RepairPriority],
        }

except ImportError:
    router = None  # type: ignore[assignment]
