# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

"""
Module: test_null_guards
Purpose: Verify null-safe access and checkpoint registry behavior under malformed payloads.
Author: ADAAD / InnovativeAI-adaad
Integration points:
  - Imports from: runtime.governance.foundation, runtime.evolution.checkpoint_registry
  - Consumed by: pytest stability suite
  - Governance impact: low — validation coverage for fail-safe deserialization paths
"""

from typing import Any

from runtime.evolution.checkpoint_registry import CheckpointRegistry
from runtime.governance.foundation import coerce_log_entry, safe_get


class _RegistryLedgerStub:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = events

    def read_epoch(self, epoch_id: str) -> list[dict[str, Any]]:
        return list(self._events)

    def get_epoch_digest(self, epoch_id: str) -> str:
        return "sha256:" + ("0" * 64)

    def compute_incremental_epoch_digest(self, epoch_id: str) -> str:
        return "sha256:" + ("1" * 64)

    def append_event(self, event_type: str, payload: dict[str, Any]) -> None:
        return None


def test_coerce_log_entry_missing_defaults() -> None:
    entry = coerce_log_entry(None)
    assert entry == {
        "id": "",
        "timestamp": "",
        "mode": "",
        "status": "",
        "mutation_id": "",
        "lineage_ref": "",
        "error": "",
        "metadata": {},
    }


def test_coerce_log_entry_partial_payload() -> None:
    entry = coerce_log_entry({"id": "e-1", "metadata": None, "status": "ok"})
    assert entry["id"] == "e-1"
    assert entry["status"] == "ok"
    assert entry["metadata"] == {}


def test_coerce_log_entry_valid_payload() -> None:
    raw = {
        "id": "e-2",
        "timestamp": "2026-01-01T00:00:00Z",
        "mode": "strict",
        "status": "applied",
        "mutation_id": "m-1",
        "lineage_ref": "lin-1",
        "error": "",
        "metadata": {"source": "test"},
    }
    entry = coerce_log_entry(raw)
    assert entry == raw


def test_safe_get_handles_none_intermediate_nodes() -> None:
    payload = {"a": {"b": None}}
    assert safe_get(payload, "a", "b", "c", default="fallback") == "fallback"
    assert safe_get(payload, "a", "missing", default=3) == 3


def test_registry_validator_valid_entries() -> None:
    ledger = _RegistryLedgerStub(
        [
            {"type": "MutationBundleEvent"},
            {"type": "PromotionEvent"},
            {"type": "ScoringEvent"},
            {"type": "SandboxEvidenceEvent", "payload": {"evidence_hash": "sha256:" + ("2" * 64)}},
            {"type": "EpochCheckpointEvent", "payload": {"checkpoint_hash": "sha256:" + ("3" * 64)}},
        ]
    )
    registry = CheckpointRegistry(ledger)
    payload = registry.create_checkpoint("epoch-1")
    assert payload["mutation_count"] == 1
    assert payload["promotion_event_count"] == 1
    assert payload["scoring_event_count"] == 1
    assert payload["prev_checkpoint_hash"] == "sha256:" + ("3" * 64)


def test_registry_validator_invalid_entries() -> None:
    ledger = _RegistryLedgerStub(
        [
            {"type": "SandboxEvidenceEvent", "payload": None},
            {"type": "EpochCheckpointEvent", "payload": "invalid"},
            {"payload": {"checkpoint_hash": "sha256:" + ("4" * 64)}},
        ]
    )
    registry = CheckpointRegistry(ledger)
    payload = registry.create_checkpoint("epoch-1")
    assert payload["prev_checkpoint_hash"].startswith("sha256:")
    assert payload["evidence_hash"].startswith("sha256:")


def test_registry_validator_empty_entries() -> None:
    registry = CheckpointRegistry(_RegistryLedgerStub([]))
    payload = registry.create_checkpoint("epoch-1")
    assert payload["mutation_count"] == 0
    assert payload["promotion_event_count"] == 0
    assert payload["scoring_event_count"] == 0
