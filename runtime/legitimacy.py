# SPDX-License-Identifier: Apache-2.0
"""Legitimacy evaluation and ledger persistence utilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping

from runtime.timeutils import now_iso
from security.ledger.journal import append_tx, write_entry


DIMENSION_WEIGHTS: Dict[str, float] = {
    "lineage_completeness": 0.20,
    "signature_validity": 0.20,
    "founders_law_satisfaction": 0.20,
    "capability_compliance": 0.15,
    "trust_mode_compliance": 0.15,
    "epoch_alignment": 0.10,
}


TIER_THRESHOLDS: Dict[str, float] = {
    "PRODUCTION": 0.95,
    "STABLE": 0.80,
    "SANDBOX": 0.60,
}

@dataclass(frozen=True)
class LegitimacyResult:
    legitimate: bool
    total_score: float
    threshold: float
    component_scores: Dict[str, float]
    failed_dimensions: List[str]
    failure_reasons: Dict[str, List[str]]
    evaluated_at: str
    evidence_hashes: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "legitimate": self.legitimate,
            "total_score": self.total_score,
            "threshold": self.threshold,
            "component_scores": self.component_scores,
            "failed_dimensions": self.failed_dimensions,
            "failure_reasons": self.failure_reasons,
            "evaluated_at": self.evaluated_at,
            "evidence_hashes": self.evidence_hashes,
        }


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "ok", "valid", "pass", "aligned"}
    return False


def _evaluate_dimension(record: Mapping[str, Any], dimension: str) -> tuple[bool, List[str]]:
    if dimension == "lineage_completeness":
        lineage = _as_mapping(record.get("lineage"))
        has_lineage_id = bool(str(lineage.get("lineage_id") or record.get("lineage_id") or "").strip())
        has_parent = bool(str(lineage.get("parent_hash") or record.get("parent_hash") or "").strip())
        has_ancestry = isinstance(lineage.get("ancestry"), list) and len(lineage["ancestry"]) > 0
        ok = has_lineage_id and (has_parent or has_ancestry)
        reasons: List[str] = []
        if not has_lineage_id:
            reasons.append("missing_lineage_id")
        if not (has_parent or has_ancestry):
            reasons.append("missing_lineage_chain")
        return ok, reasons

    if dimension == "signature_validity":
        signature = _as_mapping(record.get("signature"))
        signatures = record.get("signatures")
        if isinstance(signatures, list) and signatures:
            invalid = [idx for idx, sig in enumerate(signatures) if not _bool(_as_mapping(sig).get("valid"))]
            if invalid:
                return False, [f"invalid_signature_at_index:{idx}" for idx in invalid]
            return True, []
        ok = _bool(signature.get("valid") if signature else record.get("signature_valid"))
        return ok, ([] if ok else ["signature_invalid"])

    if dimension == "founders_law_satisfaction":
        founders = _as_mapping(record.get("founders_law"))
        ok = _bool(founders.get("satisfied") if founders else record.get("founders_law_satisfied"))
        return ok, ([] if ok else ["founders_law_violation"])

    if dimension == "capability_compliance":
        capability = _as_mapping(record.get("capability"))
        ok = _bool(capability.get("compliant") if capability else record.get("capability_compliant"))
        return ok, ([] if ok else ["capability_policy_mismatch"])

    if dimension == "trust_mode_compliance":
        trust_mode = _as_mapping(record.get("trust_mode"))
        ok = _bool(trust_mode.get("compliant") if trust_mode else record.get("trust_mode_compliant"))
        return ok, ([] if ok else ["trust_mode_violation"])

    epoch = _as_mapping(record.get("epoch"))
    aligned = epoch.get("aligned")
    if aligned is None:
        expected = str(epoch.get("expected_epoch_id") or record.get("expected_epoch_id") or "")
        current = str(epoch.get("epoch_id") or record.get("epoch_id") or "")
        ok = bool(expected) and expected == current
        return ok, ([] if ok else ["epoch_misaligned"])
    ok = _bool(aligned)
    return ok, ([] if ok else ["epoch_misaligned"])


def evaluate_legitimacy(record: Mapping[str, Any]) -> LegitimacyResult:
    """Evaluate legitimacy dimensions, persist result to ledgers, and return a score breakdown."""
    evaluated_at = now_iso()
    tier = str(record.get("tier") or "STABLE").upper()
    threshold = float(record.get("legitimacy_threshold") or TIER_THRESHOLDS.get(tier, 0.80))
    component_scores: Dict[str, float] = {}
    failure_reasons: Dict[str, List[str]] = {}

    for dimension, weight in DIMENSION_WEIGHTS.items():
        ok, reasons = _evaluate_dimension(record, dimension)
        component_scores[dimension] = round(weight if ok else 0.0, 6)
        if reasons:
            failure_reasons[dimension] = reasons

    total_score = round(sum(component_scores.values()), 6)
    failed_dimensions = sorted(failure_reasons.keys())
    legitimate = total_score >= threshold and not failed_dimensions

    evidence_hashes = record.get("evidence_hashes")
    normalized_hashes = [str(item) for item in evidence_hashes] if isinstance(evidence_hashes, list) else []

    result = LegitimacyResult(
        legitimate=legitimate,
        total_score=total_score,
        threshold=threshold,
        component_scores=component_scores,
        failed_dimensions=failed_dimensions,
        failure_reasons=failure_reasons,
        evaluated_at=evaluated_at,
        evidence_hashes=normalized_hashes,
    )

    summary = {
        "record_id": str(record.get("record_id") or record.get("id") or "unknown"),
        "legitimate": result.legitimate,
        "failed_dimensions": result.failed_dimensions,
        "evaluated_at": result.evaluated_at,
        "evidence_hashes": result.evidence_hashes,
        "total_score": result.total_score,
        "threshold": result.threshold,
        "component_scores": result.component_scores,
        "failure_reasons": result.failure_reasons,
    }
    write_entry(agent_id="governance", action="legitimacy_evaluated", payload=summary)
    append_tx(tx_type="LegitimacyEvaluation", payload=summary)

    return result


__all__ = ["LegitimacyResult", "DIMENSION_WEIGHTS", "TIER_THRESHOLDS", "evaluate_legitimacy"]
