# SPDX-License-Identifier: Apache-2.0
"""Governed mediation adapter for Grok-originated mutation proposals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from runtime.governance.foundation.determinism import default_provider
from runtime.governance.gate import GovernanceGate
from runtime.mcp.proposal_queue import append_proposal
from runtime.mcp.proposal_validator import ProposalValidationError, validate_proposal


@dataclass(frozen=True)
class GrokProposalMediationResult:
    """Canonical mediation result for Grok proposal submissions."""

    proposal_id: str
    gate_decision_id: str
    governance_decision: str
    queued_event_type: str
    queue_hash: str


def _normalized_context(context: Mapping[str, Any] | None) -> dict[str, str]:
    if not context:
        return {}
    normalized: dict[str, str] = {}
    for key, value in context.items():
        normalized[str(key)] = str(value)
    return normalized


def mediate_grok_proposal(
    *,
    proposal_payload: dict[str, Any],
    trust_mode: str,
    actor: str,
    mediation_context: Mapping[str, Any] | None = None,
    gate: GovernanceGate | None = None,
) -> GrokProposalMediationResult:
    """Run governance decision + queue append for a Grok proposal payload.

    This function is a live entrypoint designed for orchestration-level invocation.
    """

    governance_gate = gate or GovernanceGate()
    proposal_id = default_provider().next_id(label="grok-proposal", length=12)

    gate_decision = governance_gate.approve_mutation(
        mutation_id=proposal_id,
        trust_mode=str(trust_mode or "standard"),
        mutation_payload={"proposal": dict(proposal_payload)},
        mutation_context={
            "surface": "grok_api",
            "actor": str(actor or "grok"),
            **_normalized_context(mediation_context),
        },
        human_override=False,
    )
    if not gate_decision.approved:
        raise PermissionError(
            "governance_gate_blocked:" + ",".join(gate_decision.reason_codes or ["unknown_reason"])
        )

    request, _validation = validate_proposal(dict(proposal_payload))
    queued = append_proposal(proposal_id=proposal_id, request=request)
    return GrokProposalMediationResult(
        proposal_id=proposal_id,
        gate_decision_id=gate_decision.decision_id,
        governance_decision=gate_decision.decision,
        queued_event_type=str(queued.get("event_type", "")),
        queue_hash=str(queued.get("hash", "")),
    )


__all__ = [
    "GrokProposalMediationResult",
    "ProposalValidationError",
    "mediate_grok_proposal",
]
