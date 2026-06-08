"""
Phase 200 Pre-Work — DORK CMCE Adapter (Track A scaffolding)

This module will force high-impact DORK outputs (proposals, mutations, insights)
through the CMCE gate before they can affect system state or the CEL.

See: docs/governance/phase200/PHASE200_DORK_CMCE_INTEGRATION_PREWORK.md
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from runtime.evolution.evolution_kernel import EvolutionKernel
from runtime.governance.cmce.cmce_gate import (
    CMCEGateResult,
    get_cmce_gate,
    evaluate_with_provisional_fallback,
)


class DorkCmceAdapter:
    """
    Phase 200 foundation adapter.

    Usage (future):
        adapter = DorkCmceAdapter(kernel)
        result = adapter.propose_dork_output_with_cmce(dork_proposal)
    """

    def __init__(self, kernel: EvolutionKernel):
        self.kernel = kernel
        self.gate = get_cmce_gate()

    def propose_dork_output_with_cmce(
        self,
        *,
        dork_proposal: Mapping[str, Any],
        dork_agent_id: str = "dork",
        allow_provisional: bool = True,  # Track A: allow provisional during foundation
    ) -> Dict[str, Any]:
        """
        Main entry point for DORK outputs that should be CMCE-gated.

        In Phase 200 this will become mandatory for significant DORK proposals.
        """
        mutation_id = str(dork_proposal.get("id") or dork_proposal.get("proposal_id") or "dork-unknown")
        summary = str(dork_proposal.get("summary") or dork_proposal.get("content") or "")[:500]

        if allow_provisional:
            decision = evaluate_with_provisional_fallback(
                self.gate,
                mutation_id=mutation_id,
                proposer=dork_agent_id,
                scope_paths=dork_proposal.get("affected_paths", []) or [],
                summary=summary,
                requesting_agent=dork_agent_id,
            )
        else:
            # Strict path (post gate closure)
            raw = self.kernel.propose_mutation_with_cmce(
                agent={"agent_id": dork_agent_id},
                mutation={
                    "id": mutation_id,
                    "rationale": summary,
                    "targets": dork_proposal.get("affected_paths", []),
                },
                requesting_agent_id=dork_agent_id,
            )
            decision = raw.get("cmce_decision", {})

        return {
            "dork_proposal_id": mutation_id,
            "cmce_outcome": decision.get("outcome") if isinstance(decision, dict) else decision.outcome.value,
            "cmce_record_id": decision.get("consensus_record_id") if isinstance(decision, dict) else decision.consensus_record_id,
            "proceed": decision.get("outcome") in ("PASSED", "PROVISIONAL", "EXEMPTED") if isinstance(decision, dict) else decision.outcome in (CMCEGateResult.PASSED, CMCEGateResult.PROVISIONAL, CMCEGateResult.EXEMPTED),
            "cmce_decision": decision,
        }


# Convenience function for quick wiring
def get_dork_cmce_adapter(kernel: EvolutionKernel) -> DorkCmceAdapter:
    return DorkCmceAdapter(kernel)