"""
Phase 199 — CMCE Core Integration Foundation
CMCE Gate Adapter

This module provides a clean adapter between the existing
Constitutional Mutation Consensus Engine (INNOV-103) and the
primary mutation pathways (EvolutionKernel, etc.).

This is the foundational integration work for Epoch A.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

# Import the existing, battle-tested CMCE implementation (INNOV-103)
from dorkllm.constitutional_mutation_consensus_engine import (
    VoteType,
    ConsensusOutcome,
    REGISTERED_AGENTS,
    DEFAULT_QUORUM,
    ConstitutionalMutationConsensusEngine,
)


class CMCEGateResult(str, Enum):
    PASSED = "PASSED"
    BLOCKED = "BLOCKED"
    EXEMPTED = "EXEMPTED"
    ERROR = "ERROR"
    PENDING = "PENDING"
    PROVISIONAL = "PROVISIONAL"  # Track A foundation mode: requirement recorded, execution allowed to continue


@dataclass
class CMCEGateDecision:
    outcome: CMCEGateResult
    consensus_record_id: Optional[str] = None
    reason: Optional[str] = None
    exemption_id: Optional[str] = None
    ledger_correlation: Optional[str] = None
    votes: Optional[list[dict]] = None


class ExemptionPolicy:
    """Phase 199 — Extremely narrow exemption policy."""

    ALLOWED_SCOPES = frozenset({"emergency_rollback", "phase199_bootstrap", "governance_drift_closure"})

    @staticmethod
    def is_exempt(scope: str, rationale: str) -> tuple[bool, Optional[str]]:
        if scope not in ExemptionPolicy.ALLOWED_SCOPES:
            return False, f"Scope '{scope}' is not permitted under current policy"

        if len(rationale or "") < 80:
            return False, "Rationale is insufficient for an exemption"

        return True, None


class CMCEGate:
    """
    Phase 199 CMCE Gate.

    This is the new mandatory checkpoint for high-stakes mutations.
    """

    def __init__(self):
        self._engine = ConstitutionalMutationConsensusEngine()  # Real INNOV-103 engine
        self._exemption_policy = ExemptionPolicy()

    def evaluate_mutation(
        self,
        *,
        mutation_id: str,
        proposer: str,
        scope_paths: list[str],
        summary: str,
        requesting_agent: str,
        intent_declaration_id: Optional[str] = None,
        exemption_scope: Optional[str] = None,
        exemption_rationale: Optional[str] = None,
    ) -> CMCEGateDecision:
        """
        Phase 199 CMCE Gate entrypoint.

        Opens a real CMCE consensus round (or grants narrow exemption).
        Returns PENDING so the caller can drive voting via submit_vote + finalize_round.
        """

        # --- Exemption Path (extremely narrow per Phase 199 policy) ---
        if exemption_scope:
            allowed, reason = self._exemption_policy.is_exempt(exemption_scope, exemption_rationale or "")
            if allowed:
                return CMCEGateDecision(
                    outcome=CMCEGateResult.EXEMPTED,
                    reason=f"Exemption granted under scope: {exemption_scope}",
                    exemption_id=f"EXEMPT-{mutation_id[:12]}",
                )
            else:
                return CMCEGateDecision(
                    outcome=CMCEGateResult.BLOCKED,
                    reason=f"Exemption denied: {reason}",
                )

        # --- Normal Path: Real CMCE round via the engine ---
        try:
            # The real engine requires an intent_declaration_id.
            # For Phase 199 foundation we synthesize one if the caller didn't provide it.
            intent_id = intent_declaration_id or f"intent-{mutation_id}"

            round_obj = self._engine.open_round(
                mutation_id=mutation_id,
                intent_declaration_id=intent_id,
                scope_paths=scope_paths,
                proposer=proposer,
            )
            round_id = round_obj.round_id

            return CMCEGateDecision(
                outcome=CMCEGateResult.PENDING,
                consensus_record_id=round_id,
                reason="CMCE round opened via real engine. Awaiting votes from registered agents.",
                ledger_correlation=round_id,
            )

        except Exception as e:
            return CMCEGateDecision(
                outcome=CMCEGateResult.ERROR,
                reason=f"CMCE engine error during round open: {str(e)}",
            )

    def submit_vote(
        self,
        round_id: str,
        agent_id: str,
        vote: VoteType,
        rationale: Optional[str] = None,
    ) -> dict:
        """Submit a vote into an open CMCE round (adapts to real engine cast_vote)."""
        try:
            agent_vote = self._engine.cast_vote(round_id, agent_id, vote, rationale or "")
            return {
                "round_id": round_id,
                "agent": agent_id,
                "vote": vote.value if hasattr(vote, "value") else str(vote),
                "recorded": True,
            }
        except Exception as e:
            return {"round_id": round_id, "agent": agent_id, "error": str(e), "recorded": False}

    def finalize_round(self, round_id: str) -> CMCEGateDecision:
        """Close the round via the real engine and return the final decision."""
        try:
            closed_round = self._engine.close_round(round_id)

            outcome = closed_round.outcome
            reason = getattr(closed_round, "outcome_reason", None) or getattr(closed_round, "reason", "")

            if outcome == ConsensusOutcome.PASSED or outcome == ConsensusOutcome.OVERRIDE:
                return CMCEGateDecision(
                    outcome=CMCEGateResult.PASSED,
                    consensus_record_id=round_id,
                    reason=reason or "Quorum achieved.",
                    votes=list(getattr(closed_round, "votes", {}).values()),
                )
            else:
                return CMCEGateDecision(
                    outcome=CMCEGateResult.BLOCKED,
                    consensus_record_id=round_id,
                    reason=reason or "Round did not reach PASSED consensus.",
                    votes=list(getattr(closed_round, "votes", {}).values()),
                )
        except Exception as e:
            return CMCEGateDecision(
                outcome=CMCEGateResult.ERROR,
                consensus_record_id=round_id,
                reason=f"Error finalizing CMCE round: {str(e)}",
            )


# Singleton-style access for the kernel
def get_cmce_gate() -> CMCEGate:
    return CMCEGate()


def evaluate_with_provisional_fallback(
    gate: CMCEGate,
    *,
    mutation_id: str,
    proposer: str,
    scope_paths: list[str],
    summary: str,
    requesting_agent: str,
    intent_declaration_id: Optional[str] = None,
) -> CMCEGateDecision:
    """
    Phase 199/200 helper: Calls the real gate, but converts PENDING into PROVISIONAL
    so higher layers can proceed during foundation while still recording the requirement.
    """
    decision = gate.evaluate_mutation(
        mutation_id=mutation_id,
        proposer=proposer,
        scope_paths=scope_paths,
        summary=summary,
        requesting_agent=requesting_agent,
        intent_declaration_id=intent_declaration_id,
    )

    if decision.outcome == CMCEGateResult.PENDING:
        return CMCEGateDecision(
            outcome=CMCEGateResult.PROVISIONAL,
            consensus_record_id=decision.consensus_record_id,
            reason="CMCE round opened (PROVISIONAL during Phase 199 foundation). Full consensus required post-gate-closure.",
            ledger_correlation=decision.ledger_correlation,
        )
    return decision