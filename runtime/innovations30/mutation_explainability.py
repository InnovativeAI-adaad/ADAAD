# SPDX-License-Identifier: Apache-2.0
"""INNOV-55 — Mutation Explainability Engine (MXE) registry wrapper.

Phase 149 innovation registry entry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from runtime.mcp.mutation_explainability import (
    MXEExplainer,
    MutationExplanation,
    MXEChainViolation,
    MXEAuditViolation,
    MXEMutabilityViolation,
    MXEScopeViolation,
    explain_mutation,
    get_explainer,
)

INNOV_ID = "INNOV-55"
INNOV_NAME = "Mutation Explainability Engine"
INNOV_PHASE = 149
INNOV_VERSION = "9.82.0"

INVARIANTS = [
    "MXE-DETERM-0",
    "MXE-CHAIN-0",
    "MXE-IMMUT-0",
    "MXE-SCOPE-0",
    "MXE-AUDIT-0",
]


def registry_entry() -> Dict[str, Any]:
    return {
        "id": INNOV_ID,
        "name": INNOV_NAME,
        "phase": INNOV_PHASE,
        "version": INNOV_VERSION,
        "invariants": INVARIANTS,
        "description": (
            "Generates, persists, and retrieves deterministic, HMAC-chain-linked "
            "constitutional explanations for every mutation verdict "
            "(ACCEPT / REJECT / BLOCK).  Every verdict produces an immutable "
            "explanation record before the call returns (MXE-AUDIT-0).  "
            "Explanations are scoped exclusively to the mutation proposal pipeline "
            "and never read CEL internal state (MXE-SCOPE-0)."
        ),
        "endpoints": [
            "POST /mutation/explain",
            "GET  /mutation/explanations/{mutation_id}",
            "GET  /mutation/explanations",
            "GET  /mutation/explanations/chain",
            "GET  /mutation/explanations/health",
        ],
    }


def probe() -> Dict[str, Any]:
    """INNOV-COMPLETE-0 health probe used by FitnessEngineV2."""
    try:
        result = get_explainer().health_check()
        result["innov_id"] = INNOV_ID
        return result
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "innov_id": INNOV_ID, "error": str(exc)}


__all__ = [
    "INNOV_ID",
    "INNOV_NAME",
    "INNOV_PHASE",
    "INNOV_VERSION",
    "INVARIANTS",
    "MXEExplainer",
    "MutationExplanation",
    "MXEChainViolation",
    "MXEAuditViolation",
    "MXEMutabilityViolation",
    "MXEScopeViolation",
    "explain_mutation",
    "get_explainer",
    "probe",
    "registry_entry",
]
