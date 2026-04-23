# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime, timezone

import pytest
pytestmark = pytest.mark.regression_standard

from adaad.core.market_pipeline import (
    MarketPipeline,
    QualityThresholds,
    ValueArtifact,
    generate_weekly_market_summary_report,
)


def test_market_pipeline_enforces_quality_thresholds() -> None:
    pipeline = MarketPipeline(thresholds=QualityThresholds(min_confidence=0.9, min_deployment_readiness=0.8, min_validation_evidence_items=2))
    low_quality = {
        "id": "artifact-low",
        "category": "ops",
        "target_user": "sre",
        "confidence": 0.89,
        "deployment_readiness": 0.95,
        "validation_evidence": ["bench-1", "bench-2"],
    }
    assert pipeline.feed_evaluated_result(low_quality) is None
    assert pipeline.published_manifests == []


def test_market_pipeline_runs_all_stages_for_qualified_result() -> None:
    pipeline = MarketPipeline()
    qualified = {
        "id": "artifact-001",
        "category": "workflow",
        "target_user": "ops_manager",
        "confidence": 0.95,
        "deployment_readiness": 0.91,
        "validation_evidence": ["bench-1"],
    }
    artifact = pipeline.feed_evaluated_result(qualified)

    assert isinstance(artifact, ValueArtifact)
    assert artifact.artifact_id == "artifact-001"
    assert len(pipeline.published_manifests) == 1
    assert pipeline.published_manifests[0]["status"] == "candidate"


def test_generate_weekly_market_summary_report_counts_metrics() -> None:
    events = [
        {"event_type": "market_artifact_produced", "event_timestamp": "2026-03-12T00:00:00Z", "payload": {}},
        {"event_type": "market_artifact_produced", "event_timestamp": "2026-03-12T01:00:00Z", "payload": {}},
        {"event_type": "market_artifact_validated", "event_timestamp": "2026-03-13T00:00:00Z", "payload": {"external": True}},
        {"event_type": "market_artifact_validated", "event_timestamp": "2026-03-13T01:00:00Z", "payload": {"external": False}},
        {"event_type": "market_artifact_promoted", "event_timestamp": "2026-03-14T00:00:00Z", "payload": {}},
    ]

    summary = generate_weekly_market_summary_report(
        events,
        end_at=datetime(2026, 3, 14, tzinfo=timezone.utc),
        lookback_days=7,
    )

    assert summary.artifacts_produced == 2
    assert summary.externally_validated == 1
    assert summary.promoted == 1
