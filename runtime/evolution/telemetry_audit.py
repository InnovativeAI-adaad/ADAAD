# SPDX-License-Identifier: Apache-2.0
"""Epoch telemetry audit helpers for entropy governance observability."""

from __future__ import annotations

from statistics import mean
from typing import Any, Dict

from runtime.evolution.lineage_v2 import LineageLedgerV2


def get_epoch_entropy_breakdown(epoch_id: str, ledger: LineageLedgerV2 | None = None) -> Dict[str, Any]:
    """Return declared/observed entropy aggregates for an epoch.

    Sources are extracted from `PromotionEvent.payload` fields emitted by
    mutation governance (`entropy_declared_bits`, `entropy_observed_bits`,
    `entropy_observed_sources`).
    """

    runtime_ledger = ledger or LineageLedgerV2()
    declared_bits = 0
    observed_bits = 0
    source_totals: dict[str, int] = {"runtime_rng": 0, "runtime_clock": 0, "external_io": 0}
    event_count = 0

    for entry in runtime_ledger.read_epoch(epoch_id):
        if entry.get("type") != "PromotionEvent":
            continue
        payload = dict((entry.get("payload") or {}).get("payload") or {})
        event_count += 1

        declared_bits += max(0, int(payload.get("entropy_declared_bits", 0) or 0))
        observed_value = max(0, int(payload.get("entropy_observed_bits", 0) or 0))
        observed_bits += observed_value

        raw_sources = payload.get("entropy_observed_sources") or []
        normalized_sources = tuple(sorted({str(item).strip().lower() for item in raw_sources if str(item).strip()}))
        for source in normalized_sources:
            source_totals[source] = source_totals.get(source, 0) + observed_value

    return {
        "epoch_id": epoch_id,
        "event_count": event_count,
        "declared_bits": declared_bits,
        "observed_bits": observed_bits,
        "total_bits": declared_bits + observed_bits,
        "observed_sources": source_totals,
    }


def get_epoch_entropy_envelope_summary(epoch_id: str, ledger: LineageLedgerV2 | None = None) -> Dict[str, Any]:
    """Return envelope-unit entropy usage summary for governance decisions in an epoch."""

    runtime_ledger = ledger or LineageLedgerV2()
    decision_events = 0
    accepted = 0
    rejected = 0
    overflow_count = 0
    consumed_total = 0
    consumed_max = 0
    budgets: list[int] = []

    for entry in runtime_ledger.read_epoch(epoch_id):
        event_type = str(entry.get("type") or "")
        if event_type not in {"GovernanceDecisionEvent", "MutationBundleEvent"}:
            continue
        payload = dict(entry.get("payload") or {})
        if "entropy_consumed" not in payload:
            continue

        decision_events += 1
        accepted_flag = bool(payload.get("accepted", event_type == "MutationBundleEvent"))
        if accepted_flag:
            accepted += 1
        else:
            rejected += 1

        consumed = max(0, int(payload.get("entropy_consumed", 0) or 0))
        budget = max(0, int(payload.get("entropy_budget", 0) or 0))
        overflow = bool(payload.get("entropy_overflow", False))

        consumed_total += consumed
        consumed_max = max(consumed_max, consumed)
        budgets.append(budget)
        if overflow:
            overflow_count += 1

    avg_consumed = float(consumed_total / decision_events) if decision_events else 0.0
    avg_budget = float(sum(budgets) / len(budgets)) if budgets else 0.0
    return {
        "epoch_id": epoch_id,
        "decision_events": decision_events,
        "accepted": accepted,
        "rejected": rejected,
        "overflow_count": overflow_count,
        "consumed_total": consumed_total,
        "consumed_max": consumed_max,
        "consumed_avg": avg_consumed,
        "budget_avg": avg_budget,
    }


def detect_entropy_drift(
    lookback_epochs: int = 10,
    ledger: LineageLedgerV2 | None = None,
    *,
    min_decisions_per_epoch: int = 1,
    drift_threshold: float = 1.3,
) -> Dict[str, Any]:
    """Detect trend drift in envelope entropy consumption across recent epochs."""

    runtime_ledger = ledger or LineageLedgerV2()
    epoch_ids = runtime_ledger.list_epoch_ids()
    if lookback_epochs > 0:
        epoch_ids = epoch_ids[-lookback_epochs:]

    samples = [get_epoch_entropy_envelope_summary(epoch_id, ledger=runtime_ledger) for epoch_id in epoch_ids]
    filtered = [item for item in samples if int(item.get("decision_events", 0)) >= int(min_decisions_per_epoch)]

    consumed_avgs = [float(item["consumed_avg"]) for item in filtered]
    if len(consumed_avgs) < 3:
        return {
            "drift_detected": False,
            "reason": "insufficient_data",
            "sample_count": len(consumed_avgs),
            "epochs_considered": epoch_ids,
        }

    baseline_window = consumed_avgs[: min(3, len(consumed_avgs))]
    recent_window = consumed_avgs[-min(3, len(consumed_avgs)) :]

    baseline_mean = float(mean(baseline_window))
    recent_mean = float(mean(recent_window))
    denominator = baseline_mean if baseline_mean > 0 else 1.0
    drift_ratio = float(recent_mean / denominator)
    drift_detected = drift_ratio > float(drift_threshold)

    return {
        "drift_detected": drift_detected,
        "drift_ratio": drift_ratio,
        "baseline_mean": baseline_mean,
        "recent_mean": recent_mean,
        "threshold": float(drift_threshold),
        "sample_count": len(consumed_avgs),
        "epochs_considered": epoch_ids,
        "recommendation": "investigate_entropy_regression" if drift_detected else "stable",
    }


__all__ = [
    "get_epoch_entropy_breakdown",
    "get_epoch_entropy_envelope_summary",
    "detect_entropy_drift",
]
