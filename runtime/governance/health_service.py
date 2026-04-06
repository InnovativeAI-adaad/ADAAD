# SPDX-License-Identifier: Apache-2.0
"""Canonical governance health domain service.

This module is the single source of truth for ``governance_health_service``.
Do not duplicate logic in API facades; wrappers must delegate here to keep one
response schema across callsites.
"""

from __future__ import annotations

from typing import Any, Dict

from runtime.governance.health_aggregator import (
    HEALTH_DEGRADED_THRESHOLD,
    GovernanceHealthAggregator,
)
from runtime.governance.strategy_capability import StrategyCapability


def governance_health_service(*, epoch_id: str) -> Dict[str, Any]:
    """Compute governance health snapshot for ``epoch_id``.

    Read-only. No mutation authority. All dependencies are wired best-effort;
    any missing dependency degrades the corresponding signal to its safe default.
    """
    reviewer_reputation_ledger = None
    amendment_engine = None
    evidence_matrix = None
    epoch_telemetry = None
    degradation_reasons: list[dict[str, str]] = []

    try:
        from runtime.governance.reviewer_reputation_ledger import ReviewerReputationLedger
        reviewer_reputation_ledger = ReviewerReputationLedger()
        reviewer_reputation_ledger.load()
    except ImportError:
        _append_degradation_reason(
            degradation_reasons,
            component="reviewer_reputation_ledger",
            reason_code="dependency_import_failed",
            scope="critical",
        )
    except Exception:
        _append_degradation_reason(
            degradation_reasons,
            component="reviewer_reputation_ledger",
            reason_code="dependency_init_or_load_failed",
            scope="critical",
        )

    try:
        from runtime.autonomy.roadmap_amendment_engine import RoadmapAmendmentEngine
        amendment_engine = RoadmapAmendmentEngine()
    except ImportError:
        _append_degradation_reason(
            degradation_reasons,
            component="roadmap_amendment_engine",
            reason_code="dependency_import_failed",
            scope="critical",
        )
    except Exception:
        _append_degradation_reason(
            degradation_reasons,
            component="roadmap_amendment_engine",
            reason_code="dependency_init_or_load_failed",
            scope="critical",
        )

    try:
        from runtime.governance.federation.federated_evidence_matrix import FederatedEvidenceMatrix
        evidence_matrix = FederatedEvidenceMatrix()
    except ImportError:
        _append_degradation_reason(
            degradation_reasons,
            component="federated_evidence_matrix",
            reason_code="dependency_import_failed",
            scope="critical",
        )
    except Exception:
        _append_degradation_reason(
            degradation_reasons,
            component="federated_evidence_matrix",
            reason_code="dependency_init_or_load_failed",
            scope="critical",
        )

    try:
        from runtime.autonomy.epoch_telemetry import EpochTelemetry
        epoch_telemetry = EpochTelemetry.load_from_disk()
    except ImportError:
        _append_degradation_reason(
            degradation_reasons,
            component="epoch_telemetry",
            reason_code="dependency_import_failed",
            scope="critical",
        )
    except Exception:
        _append_degradation_reason(
            degradation_reasons,
            component="epoch_telemetry",
            reason_code="dependency_init_or_load_failed",
            scope="critical",
        )

    # Wire routing analytics engine from active telemetry sink (best-effort advisory).
    routing_analytics_engine, routing_reason_code = _build_routing_analytics_engine()
    if routing_reason_code is not None:
        _append_degradation_reason(
            degradation_reasons,
            component="routing_analytics_engine",
            reason_code=routing_reason_code,
            scope="advisory",
        )

    agg = GovernanceHealthAggregator(
        reviewer_reputation_ledger=reviewer_reputation_ledger,
        roadmap_amendment_engine=amendment_engine,
        federated_evidence_matrix=evidence_matrix,
        epoch_telemetry=epoch_telemetry,
        routing_analytics_engine=routing_analytics_engine,
    )

    snapshot = agg.compute(epoch_id)

    h = snapshot.health_score
    if h >= 0.80:
        status = "green"
    elif h >= HEALTH_DEGRADED_THRESHOLD:
        status = "amber"
    else:
        status = "red"

    critical_dependency_degraded = any(
        reason["scope"] == "critical" for reason in degradation_reasons
    )

    routing_health_summary: Dict[str, Any] = {
        "available": False,
        "status": "green",
        "health_score": 1.0,
        "dominant_strategy": None,
        "report_digest": None,
        "analytics_version": "22.0",
    }
    if snapshot.routing_health_report is not None:
        routing_health_summary = {
            "available": snapshot.routing_health_report.get("available", True),
            "status": snapshot.routing_health_report.get("status", "green"),
            "health_score": snapshot.routing_health_report.get("health_score", 1.0),
            "dominant_strategy": snapshot.routing_health_report.get("dominant_strategy"),
            "report_digest": snapshot.routing_health_report.get("report_digest"),
            "analytics_version": "22.0",
        }

    from runtime.governance.health_pressure_adaptor import HealthPressureAdaptor

    pressure_adj = HealthPressureAdaptor().compute(snapshot.health_score)
    review_pressure_summary = {
        "pressure_tier": pressure_adj.pressure_tier,
        "health_band": pressure_adj.health_band,
        "adjusted_tiers": list(pressure_adj.adjusted_tiers),
        "advisory_only": pressure_adj.advisory_only,
        "adjustment_digest": pressure_adj.adjustment_digest,
    }

    strategy_capability = StrategyCapability().build(
        epoch_id=snapshot.epoch_id,
        routing_health=routing_health_summary,
        governance_health_score=snapshot.health_score,
    )

    return {
        "epoch_id": snapshot.epoch_id,
        "health_score": snapshot.health_score,
        "status": status,
        "signal_breakdown": snapshot.signal_breakdown,
        "weight_snapshot_digest": snapshot.weight_snapshot_digest,
        "constitution_version": snapshot.constitution_version,
        "scoring_algorithm_version": snapshot.scoring_algorithm_version,
        "degraded": snapshot.degraded,
        "dependency_degraded": critical_dependency_degraded,
        "degradation_reasons": list(degradation_reasons),
        "routing_health": routing_health_summary,
        "review_pressure": review_pressure_summary,
        "strategy_capability": strategy_capability,
    }


def _append_degradation_reason(
    reasons: list[dict[str, str]],
    *,
    component: str,
    reason_code: str,
    scope: str,
) -> None:
    """Append deterministic degradation reason item."""
    reasons.append(
        {
            "component": component,
            "reason_code": reason_code,
            "scope": scope,
        }
    )


def _build_routing_analytics_engine() -> tuple[Any | None, str | None]:
    """Best-effort routing analytics engine from configured telemetry sink."""
    try:
        from app.api.telemetry import get_telemetry_sink
        from runtime.intelligence.file_telemetry_sink import (
            FileTelemetrySink,
            TelemetryLedgerReader,
        )
        from runtime.intelligence.strategy_analytics import StrategyAnalyticsEngine
    except ImportError:
        return None, "dependency_import_failed"
    except Exception:
        return None, "dependency_init_or_load_failed"

    try:
        sink = get_telemetry_sink()
        if sink is None:
            return None, "telemetry_sink_unavailable"
        if not isinstance(sink, FileTelemetrySink):
            return None, "telemetry_sink_not_file_backed"
        reader = TelemetryLedgerReader(sink._path)
        return StrategyAnalyticsEngine(reader), None
    except Exception:
        return None, "dependency_init_or_load_failed"
