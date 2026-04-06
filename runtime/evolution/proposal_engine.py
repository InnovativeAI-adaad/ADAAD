# SPDX-License-Identifier: Apache-2.0
"""Proposal generation entrypoint for AGM evolution steps.

ProposalEngine is the stable API consumed by AGM execution loops.  The
``generate`` method wires together:

1. ``StrategyModule.select`` — deterministic objective prioritisation
2. ``ProposalAdapter.build_from_strategy`` — LLM-backed JSON proposal
3. Constitutional fail-closed fallback — if the LLM path fails the engine
   returns a well-formed noop Proposal rather than raising, preserving
   governance continuity.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Mapping

from runtime.intelligence.llm_provider import (
    LLMProviderClient,
    LLMProviderConfig,
    RetryPolicy,
    load_provider_config,
)
from runtime.intelligence.proposal import Proposal, ProposalModule
from runtime.intelligence.proposal_adapter import ProposalAdapter
from runtime.intelligence.strategy import StrategyInput, StrategyModule


@dataclass(frozen=True)
class ProposalRequest:
    cycle_id: str
    strategy_id: str
    context: Mapping[str, Any] = field(default_factory=dict)


def _noop_proposal(request: ProposalRequest, reason: str) -> Proposal:
    """Return a constitutional noop Proposal when LLM path cannot proceed."""
    return Proposal(
        proposal_id=f"{request.cycle_id}:{request.strategy_id}:noop",
        title=f"Noop — {reason}",
        summary=(
            f"ProposalEngine fell back to noop for strategy "
            f"'{request.strategy_id}': {reason}"
        ),
        estimated_impact=0.0,
        evidence={
            "evidence_schema_version": "dork-evidence-v1",
            "source_path": "proposal_orchestrator",
            "provider": "noop",
        },
        metadata={
            "cycle_id": request.cycle_id,
            "strategy_id": request.strategy_id,
            "noop_reason": reason,
            "governance_continuity": "preserved",
        },
    )


class ProposalEngine:
    """Stable generator API used by AGM execution loops.

    Instantiate with an explicit ``ProposalAdapter`` for full control
    (e.g. in tests), or call the no-argument constructor to auto-configure
    from environment variables::

        ADAAD_ANTHROPIC_API_KEY   — Anthropic API key
        ADAAD_LLM_MODEL           — model id (default claude-3-5-sonnet-20241022)
        ADAAD_LLM_TIMEOUT_SECONDS — per-request timeout (default 15)
        ADAAD_LLM_MAX_TOKENS      — response token cap (default 800)
        ADAAD_LLM_FALLBACK_TO_NOOP — "true" (default) keeps governance alive
    """

    def __init__(
        self,
        *,
        adapter: ProposalAdapter | None = None,
        strategy_module: StrategyModule | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._strategy_module = strategy_module or StrategyModule()

        if adapter is not None:
            self._adapter: ProposalAdapter | None = adapter
        else:
            config = load_provider_config(env)
            if config.api_key:
                client = LLMProviderClient(
                    config=config,
                    retry_policy=RetryPolicy(),
                )
                self._adapter = ProposalAdapter(
                    provider_client=client,
                    proposal_module=ProposalModule(),
                )
            else:
                # No API key configured — noop adapter path
                self._adapter = None

    def generate(self, request: ProposalRequest) -> Proposal:
        """Generate an LLM-backed mutation proposal governed by AGM strategy.

        The method is fail-closed: any error in the LLM path causes a
        well-formed noop Proposal to be returned, never an exception.
        """
        if self._adapter is None:
            return _noop_proposal(request, "no_api_key_configured")

        try:
            strategy_input = self._build_strategy_input(request)
            strategy_decision = self._strategy_module.select(strategy_input)
            proposal = self._adapter.build_from_strategy(
                context=strategy_input,
                strategy=strategy_decision,
            )
            return proposal

        except Exception as exc:  # noqa: BLE001 — fail-closed governance continuity
            reason = exc.__class__.__name__
            return _noop_proposal(request, reason)

    # ──────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_strategy_input(request: ProposalRequest) -> StrategyInput:
        """Map ProposalRequest context into a typed StrategyInput."""
        ctx = dict(request.context)
        return StrategyInput(
            cycle_id=request.cycle_id,
            mutation_score=float(ctx.get("mutation_score", 0.5)),
            governance_debt_score=float(ctx.get("governance_debt_score", 0.0)),
            horizon_cycles=int(ctx.get("horizon_cycles", 1)),
            resource_budget=float(ctx.get("resource_budget", 1.0)),
            goal_backlog=dict(ctx.get("goal_backlog") or {}),
            lineage_health=float(ctx.get("lineage_health", 1.0)),
            signals={k: v for k, v in ctx.items()
                     if k not in {
                         "mutation_score", "governance_debt_score",
                         "horizon_cycles", "resource_budget",
                         "goal_backlog", "lineage_health",
                     }},
        )
