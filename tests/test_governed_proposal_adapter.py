# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.orchestration.adaad_trigger import AdaadTriggerOrchestrator, GovernanceProposalAdapter

pytestmark = pytest.mark.regression_standard


def test_grok_proposals_cannot_mutate_branches_directly(tmp_path: Path) -> None:
    orchestrator = AdaadTriggerOrchestrator(repo_root=tmp_path)

    envelope = orchestrator.run("DEVADAAD simulate", scenario="merge_ready")

    assert envelope["decision"]["allow_git_mutations"] is False
    assert envelope["stage_result"]["operation"] == "proposal_submit"
    assert envelope["merge_result"]["operation"] == "proposal_promote"
    source = Path("app/orchestration/adaad_trigger.py").read_text(encoding="utf-8")
    assert "subprocess.run([\"git\"" not in source


def test_proposal_submission_requires_governance_gate_approval(tmp_path: Path) -> None:
    adapter = GovernanceProposalAdapter(repo_root=tmp_path)

    class _RejectingGate:
        def __init__(self) -> None:
            self.calls = 0

        def approve_mutation(self, **_: object) -> SimpleNamespace:
            self.calls += 1
            return SimpleNamespace(
                approved=False,
                reason_codes=["law_rejected"],
                failed_rules=["RULE-MOCK-0"],
                decision="reject",
                decision_id="decision-1",
            )

    gate = _RejectingGate()
    adapter._gate = gate  # type: ignore[attr-defined]

    result = adapter.stage(simulation=False, trigger="ADAAD", verified_sha="a" * 40)

    assert gate.calls == 1
    assert result["status"] == "blocked"
    assert result["failure"]["code"] == "governance_gate_rejected"


def test_blocked_proposals_emit_deterministic_structured_failures(tmp_path: Path) -> None:
    adapter = GovernanceProposalAdapter(repo_root=tmp_path)

    first = adapter.merge(
        simulation=False,
        trigger="DEVADAAD",
        verified_sha="a" * 40,
        merge_target_sha="b" * 40,
    )
    second = adapter.merge(
        simulation=False,
        trigger="DEVADAAD",
        verified_sha="a" * 40,
        merge_target_sha="b" * 40,
    )

    assert first == second
    assert first["status"] == "blocked"
    assert first["failure"] == {
        "code": "merge_target_mismatch_verified_sha",
        "message": "Verified SHA does not match merge target SHA.",
        "details": {"verified_sha": "a" * 40, "merge_target_sha": "b" * 40},
    }
