# SPDX-License-Identifier: Apache-2.0
"""Phase 156 — INNOV-62 · CGAI REST API Router

GET  /api/governance/anomalies/inspect      run full inspection, return findings
GET  /api/governance/anomalies/inspect/{t}  run single named detector
GET  /api/governance/anomalies/detectors    list available detector names

Author: DEVADAAD · InnovativeAI LLC
"""

from __future__ import annotations

try:
    from fastapi import APIRouter
    router = APIRouter(prefix="/api/governance/anomalies", tags=["cgai"])

    @router.get("/inspect")
    def inspect_all():
        from dorkllm.anomaly_inspector import inspect_now
        findings = inspect_now()
        return {
            "finding_count": len(findings),
            "findings": [f.to_dict() for f in findings],
        }

    @router.get("/inspect/{anomaly_type}")
    def inspect_one(anomaly_type: str):
        from dorkllm.anomaly_inspector import get_inspector
        report = get_inspector().inspect_one(anomaly_type)
        if report is None:
            return {"finding": None, "anomaly_type": anomaly_type}
        return {"finding": report.to_dict()}

    @router.get("/detectors")
    def list_detectors():
        from dorkllm.anomaly_inspector import ALL_DETECTORS
        return {"detectors": [d.__name__ for d in ALL_DETECTORS]}

except ImportError:
    router = None  # type: ignore[assignment]
