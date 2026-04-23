# SPDX-License-Identifier: Apache-2.0
"""Market pipeline for packaging high-quality agent output into value artifacts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass(frozen=True)
class ValueArtifact:
    """Contract for a market-ready value artifact."""

    artifact_id: str
    category: str
    target_user: str
    confidence: float
    deployment_readiness: float
    validation_evidence: list[str]


@dataclass(frozen=True)
class QualityThresholds:
    """Minimum score thresholds required before market packaging."""

    min_confidence: float = 0.8
    min_deployment_readiness: float = 0.75
    min_validation_evidence_items: int = 1


class MarketPipeline:
    """Deterministic, stage-based market pipeline for evaluated agent results."""

    def __init__(self, *, thresholds: QualityThresholds | None = None) -> None:
        self._thresholds = thresholds or QualityThresholds()
        self._published_manifests: list[dict[str, Any]] = []

    @property
    def published_manifests(self) -> list[dict[str, Any]]:
        return list(self._published_manifests)

    def quality_thresholds_met(self, evaluated_result: dict[str, Any]) -> bool:
        evidence = evaluated_result.get("validation_evidence") or []
        return (
            float(evaluated_result.get("confidence", 0.0)) >= self._thresholds.min_confidence
            and float(evaluated_result.get("deployment_readiness", 0.0)) >= self._thresholds.min_deployment_readiness
            and len(evidence) >= self._thresholds.min_validation_evidence_items
        )

    def feed_evaluated_result(self, evaluated_result: dict[str, Any]) -> ValueArtifact | None:
        """Feed an evaluated result into the market pipeline only if quality thresholds pass."""
        if not self.quality_thresholds_met(evaluated_result):
            return None
        packaged = self.package_output(evaluated_result)
        classified = self.classify_use_case(packaged)
        readme = self.generate_readme(classified)
        manifest = self.publish_candidate_manifest(classified, readme)
        self._published_manifests.append(manifest)
        return classified

    def package_output(self, evaluated_result: dict[str, Any]) -> dict[str, Any]:
        """Normalize evaluated output into a deterministic package shape."""
        return {
            "artifact_id": str(evaluated_result["id"]),
            "category": str(evaluated_result["category"]),
            "target_user": str(evaluated_result["target_user"]),
            "confidence": round(float(evaluated_result["confidence"]), 4),
            "deployment_readiness": round(float(evaluated_result["deployment_readiness"]), 4),
            "validation_evidence": [str(item) for item in evaluated_result.get("validation_evidence", [])],
            "summary": str(evaluated_result.get("summary", "")),
        }

    def classify_use_case(self, packaged_output: dict[str, Any]) -> ValueArtifact:
        """Apply market-use-case classification and emit the ValueArtifact contract."""
        return ValueArtifact(
            artifact_id=packaged_output["artifact_id"],
            category=packaged_output["category"],
            target_user=packaged_output["target_user"],
            confidence=float(packaged_output["confidence"]),
            deployment_readiness=float(packaged_output["deployment_readiness"]),
            validation_evidence=list(packaged_output["validation_evidence"]),
        )

    def generate_readme(self, artifact: ValueArtifact) -> str:
        """Generate candidate README content for market handoff."""
        return "\n".join(
            [
                f"# Value Artifact {artifact.artifact_id}",
                "",
                f"- Category: {artifact.category}",
                f"- Target user: {artifact.target_user}",
                f"- Confidence: {artifact.confidence:.2f}",
                f"- Deployment readiness: {artifact.deployment_readiness:.2f}",
                f"- Validation evidence count: {len(artifact.validation_evidence)}",
            ]
        )

    def publish_candidate_manifest(self, artifact: ValueArtifact, readme: str) -> dict[str, Any]:
        """Publish a candidate manifest payload for downstream promotion workflows."""
        return {
            "schema_version": "value_artifact_manifest.v1",
            "artifact": asdict(artifact),
            "readme": readme,
            "status": "candidate",
        }


@dataclass(frozen=True)
class WeeklyMarketSummary:
    artifacts_produced: int
    externally_validated: int
    promoted: int
    window_start: str
    window_end: str


def generate_weekly_market_summary_report(
    events: list[dict[str, Any]],
    *,
    end_at: datetime | None = None,
    lookback_days: int = 7,
) -> WeeklyMarketSummary:
    """Weekly summary report job for market artifact throughput and promotion counts."""
    report_end = end_at or datetime.now(timezone.utc)
    report_start = report_end - timedelta(days=lookback_days)

    def in_window(event: dict[str, Any]) -> bool:
        raw = str(event.get("event_timestamp", "")).strip()
        if not raw:
            return False
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
        return report_start <= ts <= report_end

    window_events = [event for event in events if in_window(event)]
    produced = sum(1 for event in window_events if event.get("event_type") == "market_artifact_produced")
    externally_validated = sum(
        1
        for event in window_events
        if event.get("event_type") == "market_artifact_validated"
        and bool((event.get("payload") or {}).get("external", False))
    )
    promoted = sum(1 for event in window_events if event.get("event_type") == "market_artifact_promoted")

    return WeeklyMarketSummary(
        artifacts_produced=produced,
        externally_validated=externally_validated,
        promoted=promoted,
        window_start=report_start.isoformat().replace("+00:00", "Z"),
        window_end=report_end.isoformat().replace("+00:00", "Z"),
    )
