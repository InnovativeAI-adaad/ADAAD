# SPDX-License-Identifier: Apache-2.0
"""Deterministic mutation scoring algorithm for governance decisions."""

from __future__ import annotations

import copy
from types import MappingProxyType
from typing import Any, Dict

from runtime.governance.foundation import (
    RuntimeDeterminismProvider,
    canonical_json,
    default_provider,
    require_replay_safe_provider,
    sha256_prefixed_digest,
)

ALGORITHM_VERSION = "v1.0.0"

SEVERITY_WEIGHTS = MappingProxyType(
    {
        "LOW": 1,
        "MEDIUM": 3,
        "HIGH": 5,
        "CRITICAL": 10,
    }
)

RISK_WEIGHTS = MappingProxyType(
    {
        "API": 30,
        "PERF": 20,
        "SECURITY": 50,
        "DEFAULT": 10,
    }
)

MAX_LOC = 100_000
MAX_FILES = 1_000
MAX_ISSUES = 10_000


class ScoringValidationError(ValueError):
    """Raised when scoring input violates deterministic hard limits."""


def validate_input(scoring_input: Dict[str, Any]) -> None:
    """Validate hard limits to prevent unbounded scoring work."""
    code_diff = scoring_input.get("code_diff", {})
    loc_added = int(code_diff.get("loc_added", 0) or 0)
    loc_deleted = int(code_diff.get("loc_deleted", 0) or 0)
    files_touched = int(code_diff.get("files_touched", 0) or 0)

    if loc_added + loc_deleted > MAX_LOC:
        raise ScoringValidationError(f"LOC exceeds maximum: {loc_added + loc_deleted} > {MAX_LOC}")
    if files_touched > MAX_FILES:
        raise ScoringValidationError(f"Files touched exceeds maximum: {files_touched} > {MAX_FILES}")

    issues = (scoring_input.get("static_analysis", {}) or {}).get("issues", [])
    if len(issues) > MAX_ISSUES:
        raise ScoringValidationError(f"Static analysis issues exceed maximum: {len(issues)} > {MAX_ISSUES}")


def canonicalize_input(scoring_input: Dict[str, Any]) -> str:
    """Canonicalize input without mutating caller-owned data."""
    normalized = copy.deepcopy(scoring_input)

    code_diff = normalized.get("code_diff", {})
    if isinstance(code_diff.get("risk_tags"), list):
        code_diff["risk_tags"] = sorted(str(tag) for tag in code_diff["risk_tags"])

    static_analysis = normalized.get("static_analysis", {})
    issues = static_analysis.get("issues")
    if isinstance(issues, list):
        static_analysis["issues"] = sorted(
            issues,
            key=lambda item: str((item or {}).get("rule_id", "")),
        )

    return canonical_json(normalized)


def compute_input_hash(canonical_input: str) -> str:
    return sha256_prefixed_digest(canonical_input)


def score_tests(test_results: Dict[str, Any]) -> int:
    total = int(test_results.get("total", 0) or 0)
    failed = int(test_results.get("failed", 0) or 0)

    if failed > 0:
        return 0
    if total > 0:
        return 1000
    return 500


def compute_static_penalty(static_analysis: Dict[str, Any]) -> int:
    penalty = 0
    for issue in static_analysis.get("issues", []):
        severity = str((issue or {}).get("severity", "")).upper()
        penalty += 10 * int(SEVERITY_WEIGHTS.get(severity, 0))
    return penalty


def compute_diff_penalty(code_diff: Dict[str, Any]) -> int:
    loc_added = int(code_diff.get("loc_added", 0) or 0)
    loc_deleted = int(code_diff.get("loc_deleted", 0) or 0)
    files_touched = int(code_diff.get("files_touched", 0) or 0)
    return (loc_added + loc_deleted) + (5 * files_touched)


def compute_risk_penalty(code_diff: Dict[str, Any]) -> int:
    penalty = 0
    for tag in code_diff.get("risk_tags", []) or []:
        penalty += int(RISK_WEIGHTS.get(str(tag), RISK_WEIGHTS["DEFAULT"]))
    return penalty


def compute_score(
    scoring_input: Dict[str, Any],
    *,
    provider: RuntimeDeterminismProvider | None = None,
    replay_mode: str = "off",
    recovery_tier: str | None = None,
) -> Dict[str, Any]:
    """Compute deterministic score with canonical hashing and bounded arithmetic."""
    runtime_provider = provider or default_provider()
    require_replay_safe_provider(runtime_provider, replay_mode=replay_mode, recovery_tier=recovery_tier)

    validate_input(scoring_input)
    canonical_input = canonicalize_input(scoring_input)
    input_hash = compute_input_hash(canonical_input)

    test_score = score_tests(scoring_input.get("test_results", {}))
    static_penalty = compute_static_penalty(scoring_input.get("static_analysis", {}))
    diff_penalty = compute_diff_penalty(scoring_input.get("code_diff", {}))
    risk_penalty = compute_risk_penalty(scoring_input.get("code_diff", {}))

    final_score = max(0, test_score - static_penalty - diff_penalty - risk_penalty)

    return {
        "mutation_id": scoring_input.get("mutation_id", ""),
        "epoch_id": scoring_input.get("epoch_id", ""),
        "score": int(final_score),
        "input_hash": input_hash,
        "algorithm_version": ALGORITHM_VERSION,
        "constitution_hash": scoring_input.get("constitution_hash", ""),
        "timestamp": runtime_provider.iso_now(),
        "components": {
            "test_score": int(test_score),
            "static_penalty": int(static_penalty),
            "diff_penalty": int(diff_penalty),
            "risk_penalty": int(risk_penalty),
        },
    }


__all__ = [
    "ALGORITHM_VERSION",
    "MAX_FILES",
    "MAX_ISSUES",
    "MAX_LOC",
    "RISK_WEIGHTS",
    "SEVERITY_WEIGHTS",
    "ScoringValidationError",
    "canonicalize_input",
    "compute_diff_penalty",
    "compute_input_hash",
    "compute_risk_penalty",
    "compute_score",
    "compute_static_penalty",
    "score_tests",
    "validate_input",
]
