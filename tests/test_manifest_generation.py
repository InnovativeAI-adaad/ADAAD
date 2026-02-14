from __future__ import annotations

from copy import deepcopy

from runtime.manifest.generator import generate_manifest
from runtime.manifest.validator import validate_manifest
from runtime.mutation_lifecycle import MutationLifecycleContext


def _context() -> MutationLifecycleContext:
    return MutationLifecycleContext(
        mutation_id="m-1",
        agent_id="sample",
        epoch_id="epoch-1",
        cert_refs={"bundle_id": "b-1"},
        fitness_score=0.9,
        metadata={"lineage": {"node": "x"}},
        stage_timestamps={
            "proposed": "2026-01-01T00:00:00Z",
            "staged": "2026-01-01T00:01:00Z",
            "certified": "2026-01-01T00:02:00Z",
            "executing": "2026-01-01T00:03:00Z",
            "completed": "2026-01-01T00:04:00Z",
        },
        founders_law_result=(True, []),
    )


def test_generate_manifest_validates_against_schema() -> None:
    manifest = generate_manifest(_context(), "completed", risk_score=0.1)
    ok, errors = validate_manifest(manifest)
    assert ok is True
    assert errors == []


def test_validate_manifest_rejects_malformed_nested_and_field_types() -> None:
    manifest = generate_manifest(_context(), "completed", risk_score=0.1)
    manifest["law_version"] = 123
    manifest["cert_references"] = {"bundle_id": "b-1", "issuer": 7}
    manifest["stage_timestamps"]["staged"] = "2026-01-01 00:01:00"
    manifest["fitness_summary"]["passed"] = "yes"

    ok, errors = validate_manifest(manifest)

    assert ok is False
    assert "invalid_law_version" in errors
    assert "invalid_cert_reference_value:issuer" in errors
    assert "invalid_stage_timestamp_format:staged" in errors
    assert "invalid_fitness_passed" in errors


def test_validate_manifest_rejects_inconsistent_timestamp_and_unknown_terminal_status() -> None:
    manifest = generate_manifest(_context(), "completed", risk_score=0.1)
    manifest["proposed_at"] = "2026-01-01T00:00:59Z"
    manifest["stage_timestamps"]["certified"] = "2025-12-31T23:59:59Z"
    manifest["terminal_status"] = "done"

    ok, errors = validate_manifest(manifest)

    assert ok is False
    assert "inconsistent_proposed_timestamp" in errors
    assert "non_monotonic_stage_timestamps" in errors
    assert "invalid_terminal_status" in errors


def test_validate_manifest_forward_compatible_for_future_versions() -> None:
    manifest = generate_manifest(_context(), "completed", risk_score=0.1)
    migrated = deepcopy(manifest)
    migrated["manifest_version"] = "3.0"

    ok, errors = validate_manifest(migrated)

    assert ok is True
    assert errors == []
