from __future__ import annotations

from datetime import datetime, timedelta, timezone

from runtime.evolution.lineage_v2 import EpochEndEvent, EpochStartEvent, LineageLedgerV2
from tools.monitor_entropy_health import build_health_report, select_recent_epoch_ids


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def test_select_recent_epoch_ids_uses_epoch_timestamps(tmp_path) -> None:
    ledger = LineageLedgerV2(tmp_path / "lineage_v2.jsonl")
    now = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)

    old_ts = now - timedelta(days=10)
    recent_ts = now - timedelta(days=1)

    ledger.append_typed_event(EpochStartEvent(epoch_id="epoch-old", ts=_iso(old_ts)))
    ledger.append_typed_event(EpochEndEvent(epoch_id="epoch-old", ts=_iso(old_ts + timedelta(hours=1))))

    ledger.append_typed_event(EpochStartEvent(epoch_id="epoch-recent", ts=_iso(recent_ts)))
    ledger.append_typed_event(EpochEndEvent(epoch_id="epoch-recent", ts=_iso(recent_ts + timedelta(hours=1))))

    epoch_ids = select_recent_epoch_ids(ledger.read_all(), days=3, now=now)

    assert epoch_ids == ["epoch-recent"]


def test_build_health_report_preserves_output_schema(tmp_path) -> None:
    ledger = LineageLedgerV2(tmp_path / "lineage_v2.jsonl")
    now = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)

    recent_ts = now - timedelta(hours=2)
    ledger.append_typed_event(EpochStartEvent(epoch_id="epoch-1", ts=_iso(recent_ts)))
    ledger.append_event(
        "GovernanceDecisionEvent",
        {
            "epoch_id": "epoch-1",
            "entropy_consumed": 80,
            "entropy_budget": 100,
            "entropy_overflow": True,
        },
    )
    ledger.append_typed_event(EpochEndEvent(epoch_id="epoch-1", ts=_iso(recent_ts + timedelta(hours=1))))

    entries = ledger.read_all()
    epoch_ids = select_recent_epoch_ids(entries, days=1, now=now)
    report = build_health_report(entries, epoch_ids)

    assert report == {
        "overflow_events": 1,
        "max_consumption_observed": 80,
        "budget_utilization_pct": 80.0,
        "status": "alert",
    }
