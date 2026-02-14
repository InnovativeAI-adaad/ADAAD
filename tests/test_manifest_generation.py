from __future__ import annotations

from runtime.manifest.generator import generate_manifest
from runtime.manifest.validator import validate_manifest
from runtime.mutation_lifecycle import MutationLifecycleContext


def test_generate_manifest_validates_against_schema() -> None:
    context = MutationLifecycleContext(
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
    manifest = generate_manifest(context, "completed", risk_score=0.1)
    ok, errors = validate_manifest(manifest)
    assert ok is True
    assert errors == []
