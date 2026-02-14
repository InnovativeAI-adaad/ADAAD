# SPDX-License-Identifier: Apache-2.0

from runtime.evolution.lineage_v2 import LineageLedgerV2
from runtime.evolution.telemetry_audit import get_epoch_entropy_breakdown


def test_get_epoch_entropy_breakdown_aggregates_declared_and_observed_bits(tmp_path):
    ledger = LineageLedgerV2(tmp_path / "lineage_v2.jsonl")
    epoch_id = "epoch-telemetry"

    ledger.append_event(
        "PromotionEvent",
        {
            "epoch_id": epoch_id,
            "payload": {
                "entropy_declared_bits": 10,
                "entropy_observed_bits": 6,
                "entropy_observed_sources": ["runtime_rng"],
            },
        },
    )
    ledger.append_event(
        "PromotionEvent",
        {
            "epoch_id": epoch_id,
            "payload": {
                "entropy_declared_bits": 4,
                "entropy_observed_bits": 2,
                "entropy_observed_sources": ["runtime_clock", "external_io"],
            },
        },
    )

    breakdown = get_epoch_entropy_breakdown(epoch_id, ledger=ledger)

    assert breakdown["declared_bits"] == 14
    assert breakdown["observed_bits"] == 8
    assert breakdown["total_bits"] == 22
    assert breakdown["observed_sources"]["runtime_rng"] == 6
    assert breakdown["observed_sources"]["runtime_clock"] == 2
    assert breakdown["observed_sources"]["external_io"] == 2


def test_get_epoch_entropy_breakdown_returns_zeroes_for_empty_epoch(tmp_path):
    ledger = LineageLedgerV2(tmp_path / "lineage_v2.jsonl")
    breakdown = get_epoch_entropy_breakdown("epoch-empty", ledger=ledger)

    assert breakdown["declared_bits"] == 0
    assert breakdown["observed_bits"] == 0
    assert breakdown["total_bits"] == 0
    assert breakdown["event_count"] == 0
