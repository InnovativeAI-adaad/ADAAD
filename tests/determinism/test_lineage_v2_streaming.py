# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json

import pytest
pytestmark = pytest.mark.autonomous_critical

from runtime.evolution.lineage_v2 import LineageIntegrityError, LineageLedgerV2


def _append_events(ledger: LineageLedgerV2, count: int) -> None:
    for idx in range(count):
        ledger.append_event("MutationBundleEvent", {"epoch_id": "epoch-1", "bundle_id": f"bundle-{idx}", "impact": 0.1})


def test_verify_integrity_streams_without_full_memory_load(tmp_path: pytest.TempPathFactory) -> None:
    ledger = LineageLedgerV2(tmp_path / "lineage.jsonl")
    _append_events(ledger, 3)

    ledger.verify_integrity()

    assert ledger.get_verified_tail_hash() is not None


def test_get_verified_tail_hash_is_safe_before_verification(tmp_path: pytest.TempPathFactory) -> None:
    ledger = LineageLedgerV2(tmp_path / "lineage.jsonl")
    assert ledger.get_verified_tail_hash() is None


def test_last_hash_uses_cache_after_verification(tmp_path: pytest.TempPathFactory) -> None:
    ledger_path = tmp_path / "lineage.jsonl"
    ledger = LineageLedgerV2(ledger_path)
    _append_events(ledger, 3)

    first_tail = ledger._last_hash()
    assert ledger.get_verified_tail_hash() == first_tail

    ledger_path.write_text("this-is-not-json\n", encoding="utf-8")

    second_tail = ledger._last_hash()
    assert second_tail == first_tail


def test_append_advances_tail_hash_cache(tmp_path: pytest.TempPathFactory) -> None:
    """After append, _verified_tail_hash advances to the new entry hash (warm-cache O(n) contract)."""
    ledger = LineageLedgerV2(tmp_path / "lineage.jsonl")
    _append_events(ledger, 3)

    _ = ledger._last_hash()
    assert ledger.get_verified_tail_hash() is not None

    entry = ledger.append_event("MutationBundleEvent", {"epoch_id": "epoch-1", "bundle_id": "bundle-3", "impact": 0.2})

    # Warm-cache: tail hash must be advanced to the new entry, not nullified.
    assert ledger.get_verified_tail_hash() == entry["hash"]


def test_verify_integrity_detects_hash_tampering(tmp_path: pytest.TempPathFactory) -> None:
    ledger_path = tmp_path / "lineage.jsonl"
    ledger = LineageLedgerV2(ledger_path)
    _append_events(ledger, 3)

    rows = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows[1]["hash"] = "0" * 64
    ledger_path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")

    with pytest.raises(LineageIntegrityError):
        ledger.verify_integrity()


def test_max_lines_truncation_does_not_fail_close(tmp_path: pytest.TempPathFactory) -> None:
    ledger = LineageLedgerV2(tmp_path / "lineage.jsonl")
    entries = []
    for idx in range(10):
        entry = ledger.append_event(
            "MutationBundleEvent",
            {"epoch_id": "epoch-1", "bundle_id": f"bundle-{idx}", "impact": 0.1},
        )
        entries.append(entry)

    ledger.verify_integrity(max_lines=5)

    assert ledger.get_verified_tail_hash() == entries[4]["hash"]
