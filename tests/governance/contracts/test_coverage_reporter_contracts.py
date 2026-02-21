# SPDX-License-Identifier: Apache-2.0

import json
from pathlib import Path

from app.agents.mutation_request import MutationRequest
from runtime import constitution
from runtime.governance.coverage_reporter import configure_coverage_artifact_env, write_coverage_artifact


def _request() -> MutationRequest:
    return MutationRequest(
        agent_id="test_subject",
        generation_ts="now",
        intent="coverage",
        ops=[],
        signature="",
        nonce="n",
    )


def test_coverage_artifact_pipeline_drives_constitution_validator(monkeypatch, tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    post_path = tmp_path / "post.json"

    write_coverage_artifact({"totals": {"percent_covered": 88.0}}, baseline_path, source="baseline")
    write_coverage_artifact({"totals": {"percent_covered": 86.0}}, post_path, source="post")

    monkeypatch.setenv("ADAAD_FITNESS_COVERAGE_BASELINE_PATH", str(baseline_path))
    monkeypatch.setenv("ADAAD_FITNESS_COVERAGE_POST_PATH", str(post_path))

    with constitution.deterministic_envelope_scope({"tier": "STABLE"}):
        result = constitution.VALIDATOR_REGISTRY["test_coverage_maintained"](_request())

    assert result["ok"] is False
    assert result["reason"] == "coverage_regressed"


def test_coverage_artifact_writer_is_canonical(tmp_path: Path) -> None:
    output = tmp_path / "artifact.json"
    write_coverage_artifact({"totals": {"percent_covered": 90.0}}, output, source="pytest-cov")
    raw = output.read_text(encoding="utf-8")
    assert raw == json.dumps(json.loads(raw), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def test_configure_coverage_artifact_env_custom_environ(tmp_path: Path) -> None:
    baseline_path = tmp_path / "b.json"
    post_path = tmp_path / "p.json"
    env: dict[str, str] = {}
    configure_coverage_artifact_env(baseline_path=baseline_path, post_path=post_path, environ=env)
    assert env["ADAAD_FITNESS_COVERAGE_BASELINE_PATH"] == str(baseline_path)
    assert env["ADAAD_FITNESS_COVERAGE_POST_PATH"] == str(post_path)
