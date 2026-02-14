# SPDX-License-Identifier: Apache-2.0
"""Input sanity checks for deterministic scoring payloads."""

from __future__ import annotations

from typing import Any, Dict, List

_REQUIRED_TOP_LEVEL = (
    "mutation_id",
    "epoch_id",
    "constitution_hash",
    "test_results",
    "static_analysis",
    "code_diff",
)


def validate_scoring_payload(payload: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    for key in _REQUIRED_TOP_LEVEL:
        if key not in payload:
            errors.append(f"missing:{key}")

    test_results = payload.get("test_results")
    if not isinstance(test_results, dict):
        errors.append("invalid:test_results")
    else:
        for key in ("total", "failed"):
            value = test_results.get(key)
            if not isinstance(value, int) or value < 0:
                errors.append(f"invalid:test_results.{key}")

    code_diff = payload.get("code_diff")
    if not isinstance(code_diff, dict):
        errors.append("invalid:code_diff")
    else:
        for key in ("loc_added", "loc_deleted", "files_touched"):
            value = code_diff.get(key)
            if not isinstance(value, int) or value < 0:
                errors.append(f"invalid:code_diff.{key}")
        tags = code_diff.get("risk_tags", [])
        if not isinstance(tags, list):
            errors.append("invalid:code_diff.risk_tags")

    static_analysis = payload.get("static_analysis")
    if not isinstance(static_analysis, dict):
        errors.append("invalid:static_analysis")
    else:
        issues = static_analysis.get("issues", [])
        if not isinstance(issues, list):
            errors.append("invalid:static_analysis.issues")

    return errors


__all__ = ["validate_scoring_payload"]
