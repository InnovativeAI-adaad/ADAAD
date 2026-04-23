# SPDX-License-Identifier: Apache-2.0
"""INNOV-54 — Live Execution Feed (LEF) registry wrapper.

Phase 148 innovation registry entry.  Exposes the CELFeedEngine under the
standard innovations30 interface so the ADAAD runtime can discover and probe
this innovation without importing dorkllm internals directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from dorkllm.cel_feed import (
    CELFeedEngine,
    CELStepEvent,
    LEFChainViolation,
    LEFFeedIncomplete,
    get_engine,
    make_event,
)

INNOV_ID = "INNOV-54"
INNOV_NAME = "Live Execution Feed"
INNOV_PHASE = 148
INNOV_VERSION = "9.81.0"

# Hard-class invariants introduced by this innovation
INVARIANTS = [
    "LEF-DETERM-0",
    "LEF-CHAIN-0",
    "CEL-FEED-0",
    "LEF-NOWRITE-0",
    "CEL-FEED-COMPLETE-0",
]


def registry_entry() -> Dict[str, Any]:
    """Standard innovations30 registry descriptor."""
    return {
        "id": INNOV_ID,
        "name": INNOV_NAME,
        "phase": INNOV_PHASE,
        "version": INNOV_VERSION,
        "invariants": INVARIANTS,
        "description": (
            "Real-time Server-Sent Events feed that exposes CEL step "
            "execution as a passive, HMAC-chain-linked stream.  Subscribers "
            "are read-only observers; zero CEL state mutation is permitted."
        ),
        "endpoints": [
            "GET /events/cel-feed",
            "GET /events/cel-feed/health",
            "GET /events/cel-feed/chain",
        ],
    }


def probe(phase: int = INNOV_PHASE) -> Dict[str, Any]:
    """INNOV-COMPLETE-0 health probe used by FitnessEngineV2."""
    try:
        # Attempt to retrieve the active engine for the requested phase; if none
        # exists yet (server cold-start) treat as healthy with zero events.
        engine = get_engine(phase)
        result = engine.health_check()
        result["innov_id"] = INNOV_ID
        result["phase"] = phase
        return result
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "innov_id": INNOV_ID, "phase": phase, "error": str(exc)}


def get_feed_engine(phase: int, *, ledger_path: Optional[Path] = None) -> CELFeedEngine:
    """Return the singleton LEF engine for *phase*."""
    return get_engine(phase, ledger_path=ledger_path)


__all__ = [
    "INNOV_ID",
    "INNOV_NAME",
    "INNOV_PHASE",
    "INNOV_VERSION",
    "INVARIANTS",
    "CELFeedEngine",
    "CELStepEvent",
    "LEFChainViolation",
    "LEFFeedIncomplete",
    "get_feed_engine",
    "make_event",
    "probe",
    "registry_entry",
]
