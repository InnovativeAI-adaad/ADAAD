# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import pytest

from runtime.governance.grok_proposal_mediator import (
    GrokProposalMediationResult,
    mediate_grok_proposal,
)


class _ApprovedGate:
    class _Decision:
        approved = True
        decision_id = "gate-grok-001"
        decision = "approve"
        reason_codes: list[str] = []

    def approve_mutation(self, **_kwargs):
        return self._Decision()


class _BlockedGate:
    class _Decision:
        approved = False
        decision_id = "gate-grok-002"
        decision = "reject"
        reason_codes = ["policy_violation"]

    def approve_mutation(self, **_kwargs):
        return self._Decision()


def test_mediate_grok_proposal_success(monkeypatch) -> None:
    monkeypatch.setattr(
        "runtime.governance.grok_proposal_mediator.validate_proposal",
        lambda payload: (payload, {"passed": True}),
    )
    monkeypatch.setattr(
        "runtime.governance.grok_proposal_mediator.append_proposal",
        lambda *, proposal_id, request: {
            "event_type": "mcp_proposal_queued",
            "hash": f"sha256:{proposal_id}:{request.get('summary', '')}",
        },
    )

    result = mediate_grok_proposal(
        proposal_payload={"summary": "test", "targets": [], "authority_level": "governor-review"},
        trust_mode="standard",
        actor="grok",
        mediation_context={"source": "unit-test"},
        gate=_ApprovedGate(),
    )

    assert isinstance(result, GrokProposalMediationResult)
    assert result.gate_decision_id == "gate-grok-001"
    assert result.governance_decision == "approve"
    assert result.queued_event_type == "mcp_proposal_queued"
    assert result.queue_hash.startswith("sha256:")


def test_mediate_grok_proposal_permission_block() -> None:
    with pytest.raises(PermissionError, match="policy_violation"):
        mediate_grok_proposal(
            proposal_payload={"summary": "test", "targets": [], "authority_level": "governor-review"},
            trust_mode="standard",
            actor="grok",
            gate=_BlockedGate(),
        )
