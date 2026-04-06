# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import pytest

from scripts.validate_dork_evidence_schema import validate_dork_evidence_artifact


def _valid_artifact() -> dict[str, object]:
    return {
        "evidence_schema_version": "dork-evidence-v1",
        "artifact_id": "123e4567-e89b-42d3-a456-426614174000",
        "generated_at": "2026-04-06T12:00:00Z",
        "source_path": "provider_adapter",
        "provider": "llm_provider_client",
        "provider_ok": True,
        "prompt_hash": "a" * 64,
        "response_hash": "b" * 64,
    }


def test_valid_v1_artifact_passes() -> None:
    assert validate_dork_evidence_artifact(_valid_artifact()) == []


def test_missing_version_fails() -> None:
    artifact = _valid_artifact()
    artifact.pop("evidence_schema_version")
    assert validate_dork_evidence_artifact(artifact) == ["missing_required:evidence_schema_version"]


def test_unknown_version_fails() -> None:
    artifact = _valid_artifact()
    artifact["evidence_schema_version"] = "dork-evidence-v999"
    assert validate_dork_evidence_artifact(artifact) == ["unknown_evidence_schema_version:dork-evidence-v999"]


@pytest.mark.parametrize(
    "field,value,expected_error",
    [
        ("prompt_hash", "not-a-sha", "invalid_format:prompt_hash_sha256"),
        ("generated_at", "2026-04-06 12:00:00", "invalid_format:generated_at_iso8601_utc"),
    ],
)
def test_malformed_sha_or_timestamp_fails(field: str, value: object, expected_error: str) -> None:
    artifact = _valid_artifact()
    artifact[field] = value
    errors = validate_dork_evidence_artifact(artifact)
    assert expected_error in errors
