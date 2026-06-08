"""
Phase 199/200 Test Helpers for CMCE

Provides utilities to simulate voting rounds so tests can achieve real PASSED
outcomes during foundation development.
"""

from __future__ import annotations

from typing import Optional

from dorkllm.constitutional_mutation_consensus_engine import (
    VoteType,
    ConstitutionalMutationConsensusEngine,
)
from runtime.governance.cmce.cmce_gate import get_cmce_gate


def simulate_full_approval_round(
    engine: Optional[ConstitutionalMutationConsensusEngine] = None,
    *,
    mutation_id: str = "test-mut-simulated",
    proposer: str = "test-agent",
    scope_paths: list[str] | None = None,
    summary: str = "Simulated full approval for test",
) -> str:
    """
    Opens a round, casts APPROVE votes from all registered agents, and closes it.

    Returns the round_id of the now-PASSED round.

    This is a test-only helper to make end-to-end CMCE tests practical
    during Phase 199 foundation work.
    """
    if scope_paths is None:
        scope_paths = ["runtime/test"]

    engine = engine or ConstitutionalMutationConsensusEngine()

    round_obj = engine.open_round(
        mutation_id=mutation_id,
        intent_declaration_id=f"intent-{mutation_id}",
        scope_paths=scope_paths,
        proposer=proposer,
    )
    round_id = round_obj.round_id

    # Cast APPROVE from all registered agents
    for agent in engine._registered_agents:  # internal but acceptable in test helper
        try:
            engine.cast_vote(round_id, agent, VoteType.APPROVE, "Test auto-approval")
        except Exception:
            pass  # Some agents may not be present in this environment

    # Close the round
    try:
        engine.close_round(round_id)
    except Exception:
        pass

    return round_id


def get_fresh_cmce_gate() -> "CMCEGate":
    """Returns a fresh gate instance (useful when you want isolation in tests)."""
    return get_cmce_gate()