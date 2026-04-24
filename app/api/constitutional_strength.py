# SPDX-License-Identifier: Apache-2.0
"""Phase 159 - INNOV-65 . CSI REST API Router

GET  /api/governance/csi           current CSI score + snapshot
GET  /api/governance/csi/history   recent CSI history from CGTH
GET  /api/governance/csi/band      score band + color for UI display

Author: DEVADAAD . InnovativeAI LLC
"""

from __future__ import annotations

try:
    from fastapi import APIRouter
    router = APIRouter(prefix="/api/governance/csi", tags=["csi"])

    @router.get("")
    def get_csi():
        from dorkllm.constitutional_strength import compute_csi
        snapshot = compute_csi()
        return snapshot.to_dict()

    @router.get("/history")
    def get_csi_history(limit: int = 20):
        from dorkllm.telemetry_hub import CGTHEventType, get_hub
        hub = get_hub()
        records = [
            r for r in hub.query()
            if r.event_type == CGTHEventType.PERM_SNAPSHOT
            and isinstance(r.payload, dict)
            and r.payload.get("component_id") == "csi"
        ]
        return {
            "history": [
                r.payload for r in records[-limit:]
            ]
        }

    @router.get("/band")
    def get_csi_band():
        """Return score + band + UI color for the dork.html header display."""
        from dorkllm.constitutional_strength import compute_csi
        snapshot = compute_csi()
        _color = {
            "EXCELLENT": "#22c55e",
            "HEALTHY":   "#84cc16",
            "CAUTION":   "#f97316",
            "CRITICAL":  "#ef4444",
        }
        return {
            "score":   snapshot.score,
            "band":    snapshot.band.value,
            "color":   _color.get(snapshot.band.value, "#8c919b"),
            "advisory": snapshot.advisory,
        }

except ImportError:
    router = None  # type: ignore[assignment]
