# SPDX-License-Identifier: Apache-2.0

from runtime.evolution.lineage_v2 import LineageLedgerV2
from runtime.evolution.telemetry_audit import (
    detect_entropy_drift,
    get_epoch_entropy_breakdown,
    get_epoch_entropy_envelope_summary,
)


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


def test_get_epoch_entropy_envelope_summary_aggregates_governance_decisions(tmp_path):
    ledger = LineageLedgerV2(tmp_path / "lineage_v2.jsonl")
    epoch_id = "epoch-envelope"

    ledger.append_event(
        "MutationBundleEvent",
        {
            "epoch_id": epoch_id,
            "accepted": True,
            "entropy_consumed": 12,
            "entropy_budget": 100,
            "entropy_overflow": False,
        },
    )
    ledger.append_event(
        "GovernanceDecisionEvent",
        {
            "epoch_id": epoch_id,
            "accepted": False,
            "reason": "entropy_budget_exceeded",
            "entropy_consumed": 105,
            "entropy_budget": 100,
            "entropy_overflow": True,
        },
    )

    summary = get_epoch_entropy_envelope_summary(epoch_id, ledger=ledger)

    assert summary["decision_events"] == 2
    assert summary["accepted"] == 1
    assert summary["rejected"] == 1
    assert summary["overflow_count"] == 1
    assert summary["consumed_total"] == 117
    assert summary["consumed_max"] == 105


def test_get_epoch_entropy_envelope_summary_zero_for_empty_epoch(tmp_path):
    ledger = LineageLedgerV2(tmp_path / "lineage_v2.jsonl")
    summary = get_epoch_entropy_envelope_summary("epoch-empty", ledger=ledger)

    assert summary["decision_events"] == 0
    assert summary["accepted"] == 0
    assert summary["rejected"] == 0
    assert summary["overflow_count"] == 0
    assert summary["consumed_total"] == 0
    assert summary["consumed_avg"] == 0.0


def test_detect_entropy_drift_detects_growth(tmp_path):
    ledger = LineageLedgerV2(tmp_path / "lineage_v2.jsonl")

    for idx, consumed in enumerate([5, 6, 7, 12, 14, 16], start=1):
        epoch_id = f"epoch-{idx}"
        ledger.append_event(
            "MutationBundleEvent",
            {
                "epoch_id": epoch_id,
                "accepted": True,
                "entropy_consumed": consumed,
                "entropy_budget": 100,
                "entropy_overflow": False,
            },
        )

    result = detect_entropy_drift(lookback_epochs=10, ledger=ledger)
    assert result["drift_detected"] is True
    assert result["drift_ratio"] > 1.3


def test_detect_entropy_drift_handles_insufficient_data(tmp_path):
    ledger = LineageLedgerV2(tmp_path / "lineage_v2.jsonl")
    ledger.append_event(
        "MutationBundleEvent",
        {
            "epoch_id": "epoch-1",
            "accepted": True,
            "entropy_consumed": 4,
            "entropy_budget": 100,
            "entropy_overflow": False,
        },
    )

    result = detect_entropy_drift(lookback_epochs=10, ledger=ledger)
    assert result["drift_detected"] is False
    assert result["reason"] == "insufficient_data"
