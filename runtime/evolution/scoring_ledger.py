# SPDX-License-Identifier: Apache-2.0
"""Append-only deterministic scoring ledger helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from runtime.governance.policy_artifact import GovernancePolicyError, load_governance_policy
from runtime.state.ledger_store import ScoringLedgerStore


class ScoringLedger:
    def __init__(self, path: Path) -> None:
        backend = "json"
        try:
            backend = load_governance_policy().state_backend
        except GovernancePolicyError:
            backend = "json"
        self.store = ScoringLedgerStore(path=path, backend=backend)

    def append(self, scoring_result: Dict[str, Any]) -> Dict[str, Any]:
        return self.store.append(scoring_result)

    def last_hash(self) -> str:
        return self.store.last_hash()


__all__ = ["ScoringLedger"]
