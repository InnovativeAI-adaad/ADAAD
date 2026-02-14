# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from runtime.evolution.scoring_validator import validate_scoring_payload


def test_scoring_validator_accepts_valid_payload() -> None:
    payload = {
        "mutation_id": "m",
        "epoch_id": "e",
        "constitution_hash": "sha256:" + ("a" * 64),
        "test_results": {"total": 1, "failed": 0},
        "static_analysis": {"issues": []},
        "code_diff": {"loc_added": 0, "loc_deleted": 0, "files_touched": 1, "risk_tags": []},
    }
    assert validate_scoring_payload(payload) == []


def test_scoring_validator_rejects_missing_fields() -> None:
    errors = validate_scoring_payload({})
    assert "missing:mutation_id" in errors
    assert "invalid:test_results" in errors
