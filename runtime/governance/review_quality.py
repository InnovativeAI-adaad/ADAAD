# SPDX-License-Identifier: Apache-2.0
"""Governance review quality telemetry and aggregate KPI helpers."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List, cast

from runtime import metrics
from runtime.governance.foundation import canonical_json_bytes, sha256_prefixed_digest
from security.ledger.journal import append_tx

REVIEW_QUALITY_EVENT_TYPE = "governance_review_quality"
REVIEW_KPI_SCHEMA_VERSION = "1.0"
DEFAULT_REVIEW_SLA_SECONDS = 24 * 60 * 60


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def _normalize_record(payload: Dict[str, Any]) -> Dict[str, Any]:
    latency_seconds = max(0.0, _as_float(payload.get("latency_seconds"), 0.0))
    comment_count = max(0, int(_as_float(payload.get("comment_count"), 0.0)))
    sla_seconds = int(max(1, _as_float(payload.get("sla_seconds"), float(DEFAULT_REVIEW_SLA_SECONDS))))
    record: Dict[str, Any] = {
        "schema_version": REVIEW_KPI_SCHEMA_VERSION,
        "mutation_id": str(payload.get("mutation_id") or ""),
        "review_id": str(payload.get("review_id") or ""),
        "reviewer": str(payload.get("reviewer") or "unknown").strip() or "unknown",
        "latency_seconds": round(latency_seconds, 6),
        "comment_count": comment_count,
        "decision": str(payload.get("decision") or "unknown").strip().lower() or "unknown",
        "overridden": bool(payload.get("overridden", False)),
        "sla_seconds": sla_seconds,
        "context": str(payload.get("context") or "mutation_review").strip() or "mutation_review",
    }
    record["within_sla"] = float(record["latency_seconds"]) <= int(record["sla_seconds"])
    return record


def _idempotency_key(record: Dict[str, Any]) -> str:
    material = {
        "schema_version": record["schema_version"],
        "mutation_id": record["mutation_id"],
        "review_id": record["review_id"],
        "reviewer": record["reviewer"],
        "latency_seconds": record["latency_seconds"],
        "comment_count": record["comment_count"],
        "decision": record["decision"],
        "overridden": record["overridden"],
        "sla_seconds": record["sla_seconds"],
        "context": record["context"],
    }
    return sha256_prefixed_digest(canonical_json_bytes(material))


def record_review_quality(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Persist a deterministic governance review-quality metric record."""

    record = _normalize_record(payload)
    record["idempotency_key"] = _idempotency_key(record)
    metrics.log(event_type=REVIEW_QUALITY_EVENT_TYPE, payload=record, level="INFO")
    append_tx(
        tx_type=REVIEW_QUALITY_EVENT_TYPE,
        payload=record,
        tx_id=f"TX-{REVIEW_QUALITY_EVENT_TYPE}-{record['idempotency_key'].split(':', 1)[-1][:16]}",
    )
    return record


def _percentiles(samples: List[float]) -> Dict[str, float]:
    if not samples:
        return {"p50": 0.0, "p90": 0.0, "p95": 0.0, "p99": 0.0}
    ordered = sorted(samples)

    def _pick(p: float) -> float:
        index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * p))))
        return round(float(ordered[index]), 6)

    return {"p50": _pick(0.5), "p90": _pick(0.9), "p95": _pick(0.95), "p99": _pick(0.99)}


def summarize_review_quality(entries: Iterable[Dict[str, Any]], *, default_sla_seconds: int = DEFAULT_REVIEW_SLA_SECONDS) -> Dict[str, Any]:
    """Aggregate governance review KPI metrics from review telemetry events."""

    records: List[Dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict) or str(entry.get("event", "")).strip() != REVIEW_QUALITY_EVENT_TYPE:
            continue
        payload_raw = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
        payload = cast(Dict[str, Any], payload_raw)
        normalized = _normalize_record(payload)
        if int(normalized.get("sla_seconds") or 0) <= 0:
            normalized["sla_seconds"] = int(default_sla_seconds)
        records.append(normalized)

    latencies = [float(item["latency_seconds"]) for item in records]
    reviewer_counts: Counter[str] = Counter(str(item.get("reviewer") or "unknown") for item in records)
    total_reviews = len(records)
    overrides = sum(1 for item in records if bool(item.get("overridden")))
    total_comments = sum(int(item.get("comment_count") or 0) for item in records)
    within_sla = sum(1 for item in records if bool(item.get("within_sla")))

    max_share = 0.0
    hhi = 0.0
    if total_reviews > 0:
        shares = [count / total_reviews for count in reviewer_counts.values()]
        if shares:
            max_share = max(shares)
            hhi = sum(share * share for share in shares)

    return {
        "schema_version": REVIEW_KPI_SCHEMA_VERSION,
        "window_count": total_reviews,
        "review_latency_distribution_seconds": {
            "count": total_reviews,
            "average": round(sum(latencies) / total_reviews, 6) if total_reviews else 0.0,
            **_percentiles(latencies),
        },
        "reviewed_within_sla_percent": round((within_sla / total_reviews) * 100.0, 3) if total_reviews else 0.0,
        "reviewer_participation_concentration": {
            "reviewer_count": len(reviewer_counts),
            "largest_reviewer_share": round(max_share, 6),
            "hhi": round(hhi, 6),
            "distribution": dict(sorted(reviewer_counts.items())),
        },
        "review_depth_proxies": {
            "average_comment_count": round(total_comments / total_reviews, 6) if total_reviews else 0.0,
            "override_rate_percent": round((overrides / total_reviews) * 100.0, 3) if total_reviews else 0.0,
            "decision_override_count": overrides,
        },
    }


__all__ = ["REVIEW_QUALITY_EVENT_TYPE", "DEFAULT_REVIEW_SLA_SECONDS", "record_review_quality", "summarize_review_quality"]
