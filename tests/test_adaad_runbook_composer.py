# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

import pytest

from adaad.orchestrator.runbook_composer import compose_runbook, export_runbook_artifacts
from adaad.orchestrator.status import build_status_report


@pytest.fixture()
def repo_fixture(tmp_path: Path) -> Path:
    (tmp_path / "docs/governance").mkdir(parents=True)
    (tmp_path / "docs/comms").mkdir(parents=True)

    (tmp_path / "docs/governance/ADAAD_PR_PROCESSION_2026-03-v2.md").write_text(
        """
adaad_pr_procession_contract:
  state_alignment:
    expected_next_pr: "PR-PHASE65-01 (Phase 65 — First Autonomous Capability Evolution)"

| Phase | Version | Depends on | Status |
|---|---|---|---|
| 64 | v8.7.0 | Phase 63 | shipped |
| 65 | v9.0.0 | Phase 64 | next |
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "docs/comms/claims_evidence_matrix.md").write_text(
        """
| Claim ID | Claim | Evidence | Scope | Status |
|---|---|---|---|---|
| `claim-complete` | done | ref | f | Complete |
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / ".adaad_agent_state.json").write_text(
        json.dumps(
            {
                "blocked_reason": None,
                "last_gate_results": {
                    "tier_0": "pass",
                    "tier_1": "pass",
                    "tier_2": "pass",
                    "tier_3": "pass",
                    "tier_m": "pass",
                },
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_compose_runbook_detects_pre_release_for_devadaad(repo_fixture: Path) -> None:
    report = build_status_report(repo_root=repo_fixture, trigger_mode="DEVADAAD")

    runbook = compose_runbook(report=report, verbosity_mode="compact")

    assert runbook.scenario_class == "pre_release"
    assert len(runbook.steps) == 3


def test_compose_runbook_detects_replay_incident(repo_fixture: Path) -> None:
    (repo_fixture / ".adaad_agent_state.json").write_text(
        json.dumps(
            {
                "blocked_reason": "replay_divergence_detected",
                "last_gate_results": {
                    "tier_0": "pass",
                    "tier_1": "pass",
                    "tier_2": "fail",
                    "tier_3": "pass",
                },
            }
        ),
        encoding="utf-8",
    )
    report = build_status_report(repo_root=repo_fixture, trigger_mode="ADAAD")

    runbook = compose_runbook(report=report, verbosity_mode="full_governance")

    assert runbook.scenario_class == "replay_incident"
    assert any(step.title == "Governance completeness attest" for step in runbook.steps)


def test_export_runbook_artifacts_writes_markdown_and_json(repo_fixture: Path) -> None:
    artifacts = export_runbook_artifacts(
        repo_root=repo_fixture,
        trigger_mode="ADAAD",
        verbosity_mode="compact",
        output_dir=repo_fixture / "security/adaad_runbooks",
    )

    markdown = Path(artifacts.markdown_path)
    payload = json.loads(Path(artifacts.json_path).read_text(encoding="utf-8"))

    assert markdown.exists()
    assert "# ADAAD Live Runbook" in markdown.read_text(encoding="utf-8")
    assert payload["schema_version"] == "adaad_runbook.v1"
    assert payload["scenario_class"] == artifacts.runbook.scenario_class
