# SPDX-License-Identifier: Apache-2.0
"""DORK proposal execution adapter through governance-approved interfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime.governance.foundation.determinism import default_provider
from runtime.governance.gate import GovernanceGate
from runtime.mcp.proposal_queue import append_proposal
from runtime.mcp.proposal_validator import ProposalValidationError, validate_proposal


@dataclass(frozen=True)
class DorkProposalResult:
    proposal_id: str
    gate_decision_id: str
    governance_decision: str
    queued_event_type: str
    queue_hash: str


def execute_dork_proposal(
    *,
    proposal_payload: dict[str, Any],
    trust_mode: str,
    actor: str,
    gate: GovernanceGate | None = None,
) -> DorkProposalResult:
    """Execute proposal preflight + queue using concrete governance surfaces."""
    governance_gate = gate or GovernanceGate()
    proposal_id = default_provider().next_id(label="dork-proposal", length=12)

    gate_decision = governance_gate.approve_mutation(
        mutation_id=proposal_id,
        trust_mode=str(trust_mode or "standard"),
        mutation_payload={"proposal": dict(proposal_payload)},
        mutation_context={"surface": "dork_api", "actor": str(actor or "dork")},
        human_override=False,
    )
    if not gate_decision.approved:
        raise PermissionError(
            "governance_gate_blocked:"
            + ",".join(gate_decision.reason_codes or ["unknown_reason"])
        )

    request, _validation = validate_proposal(dict(proposal_payload))
    queued = append_proposal(proposal_id=proposal_id, request=request)
    return DorkProposalResult(
        proposal_id=proposal_id,
        gate_decision_id=gate_decision.decision_id,
        governance_decision=gate_decision.decision,
        queued_event_type=str(queued.get("event_type", "")),
        queue_hash=str(queued.get("hash", "")),
    )


__all__ = [
    "DorkProposalResult",
    "ProposalValidationError",
    "execute_dork_proposal",
]
