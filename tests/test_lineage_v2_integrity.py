# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.evolution.lineage_v2 import LineageIntegrityError, LineageLedgerV2


def test_lineage_integrity_valid_chain(tmp_path: Path) -> None:
    ledger = LineageLedgerV2(tmp_path / "lineage_v2.jsonl")
    ledger.append_event("EpochStartEvent", {"epoch_id": "ep-1"})
    ledger.append_event("MutationBundleEvent", {"epoch_id": "ep-1", "bundle_id": "b1"})

    ledger.verify_integrity()


def test_lineage_integrity_detects_single_line_tamper(tmp_path: Path) -> None:
    path = tmp_path / "lineage_v2.jsonl"
    ledger = LineageLedgerV2(path)
    ledger.append_event("EpochStartEvent", {"epoch_id": "ep-1"})

    entry = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    entry["payload"]["epoch_id"] = "ep-tampered"
    path.write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(LineageIntegrityError, match="lineage_hash_mismatch"):
        ledger.verify_integrity()


def test_lineage_integrity_detects_malformed_json(tmp_path: Path) -> None:
    ledger = LineageLedgerV2(tmp_path / "lineage_v2.jsonl")
    ledger.ledger_path.write_text('{"type":"EpochStartEvent"\n', encoding="utf-8")

    with pytest.raises(LineageIntegrityError, match="lineage_invalid_json"):
        ledger.verify_integrity()


def test_lineage_append_blocked_after_corruption(tmp_path: Path) -> None:
    path = tmp_path / "lineage_v2.jsonl"
    ledger = LineageLedgerV2(path)
    ledger.append_event("EpochStartEvent", {"epoch_id": "ep-1"})

    entry = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    entry["prev_hash"] = "a" * 64
    path.write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(LineageIntegrityError, match="lineage_prev_hash_mismatch"):
        ledger.append_event("EpochEndEvent", {"epoch_id": "ep-1"})
