# SPDX-License-Identifier: Apache-2.0
"""Epoch telemetry audit helpers for entropy governance observability."""

from __future__ import annotations

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


__all__ = ["get_epoch_entropy_breakdown"]
