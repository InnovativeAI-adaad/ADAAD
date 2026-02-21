from __future__ import annotations

from runtime.governance.review_quality import (
    REVIEW_QUALITY_EVENT_TYPE,
    record_review_quality,
    summarize_review_quality,
)


def test_record_review_quality_emits_metrics_and_journal(monkeypatch) -> None:
    from runtime.governance import review_quality

    metric_calls = []
    tx_calls = []
    monkeypatch.setattr(review_quality.metrics, "log", lambda **kwargs: metric_calls.append(kwargs))
    monkeypatch.setattr(review_quality, "append_tx", lambda **kwargs: tx_calls.append(kwargs))

    record = record_review_quality(
        {
            "mutation_id": "m-1",
            "review_id": "r-1",
            "reviewer": "alice",
            "latency_seconds": 42,
            "comment_count": 2,
            "decision": "approve",
            "overridden": False,
        }
    )

    assert record["within_sla"] is True
    assert metric_calls[0]["event_type"] == REVIEW_QUALITY_EVENT_TYPE
    assert tx_calls[0]["tx_type"] == REVIEW_QUALITY_EVENT_TYPE


def test_summarize_review_quality_aggregates() -> None:
    entries = [
        {
            "event": REVIEW_QUALITY_EVENT_TYPE,
            "payload": {
                "mutation_id": "m-1",
                "review_id": "r-1",
                "reviewer": "alice",
                "latency_seconds": 100,
                "comment_count": 1,
                "decision": "approve",
                "overridden": False,
                "sla_seconds": 86400,
            },
        },
        {
            "event": REVIEW_QUALITY_EVENT_TYPE,
            "payload": {
                "mutation_id": "m-2",
                "review_id": "r-2",
                "reviewer": "bob",
                "latency_seconds": 100000,
                "comment_count": 0,
                "decision": "reject",
                "overridden": True,
                "sla_seconds": 86400,
            },
        },
    ]
    summary = summarize_review_quality(entries)

    assert summary["window_count"] == 2
    assert summary["reviewed_within_sla_percent"] == 50.0
    assert summary["review_depth_proxies"]["decision_override_count"] == 1
    assert summary["reviewer_participation_concentration"]["reviewer_count"] == 2
