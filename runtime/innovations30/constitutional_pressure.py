# SPDX-License-Identifier: Apache-2.0
"""INNOV-58 · Constitutional Pressure Index (CPI) — registry wrapper.

Phase 152 / v9.85.0
"""

from __future__ import annotations

INNOV_ID = "INNOV-58"
INNOV_NAME = "Constitutional Pressure Index"
INNOV_PHASE = 152
INNOV_VERSION = "9.85.0"

HARD_CLASS_INVARIANTS = [
    "CPI-DETERM-0",
    "CPI-LEDGER-0",
    "CPI-ALERT-0",
    "CPI-SCOPE-0",
    "CPI-HUMAN0-0",
]

DESCRIPTION = (
    "Proactive governance-health layer. Scores each constitutional domain "
    "(SECURITY, DETERMINISM, REPLAY, HUMAN0, MUTATION, LEDGER) against the "
    "HMAC-chained ledger, emits tamper-evident PRESSURE_SNAPSHOT / PRESSURE_ALERT "
    "events, and injects live pressure signals into the DORK system prompt."
)


def get_metadata() -> dict:
    return {
        "innov_id": INNOV_ID,
        "name": INNOV_NAME,
        "phase": INNOV_PHASE,
        "version": INNOV_VERSION,
        "hard_class_invariants": HARD_CLASS_INVARIANTS,
        "description": DESCRIPTION,
        "module": "dorkllm.constitutional_pressure",
    }
