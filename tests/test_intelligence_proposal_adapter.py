# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations
import pytest
pytestmark = pytest.mark.regression_standard

from runtime.intelligence.llm_provider import LLMProviderResult
from runtime.intelligence.proposal import ProposalModule
from runtime.intelligence.proposal_adapter import ProposalAdapter
from runtime.intelligence.strategy import StrategyDecision, StrategyInput


class _FakeProviderClient:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def request_json(self, *, system_prompt: str, user_prompt: str) -> LLMProviderResult:
        assert system_prompt
        assert user_prompt
        return LLMProviderResult(ok=True, payload=self.payload)


def test_proposal_adapter_populates_extended_schema_and_evidence() -> None:
    adapter = ProposalAdapter(
        provider_client=_FakeProviderClient(
            {
                "summary": "llm summary",
                "real_diff": "diff --git a/foo.py b/foo.py",
                "target_files": [
                    {
                        "path": "foo.py",
                        "language": "python",
                        "exists": True,
                        "content": "print('x')",
                        "metadata": {"lines": 1},
                    }
                ],
                "projected_impact": {"risk": "low", "score_delta": 0.12},
                "metadata": {"provider": "stub"},
            }
        ),
        proposal_module=ProposalModule(),
    )

    proposal = adapter.build_from_strategy(
        context=StrategyInput(cycle_id="cycle-1", mutation_score=0.8, governance_debt_score=0.1, signals={"k": "v"}),
        strategy=StrategyDecision(strategy_id="adaptive_self_mutate", rationale="fallback rationale", confidence=0.9),
    )

    assert proposal.summary == "llm summary"
    assert proposal.real_diff.startswith("diff --git")
    assert proposal.target_files[0].path == "foo.py"
    assert proposal.projected_impact["risk"] == "low"
    assert proposal.evidence["llm_raw_payload"]["summary"] == "llm summary"


def test_proposal_adapter_uses_strategy_rationale_when_summary_missing() -> None:
    adapter = ProposalAdapter(
        provider_client=_FakeProviderClient({"projected_impact": {"x": 1}}),
        proposal_module=ProposalModule(),
    )

    proposal = adapter.build_from_strategy(
        context=StrategyInput(cycle_id="c1", mutation_score=0.2, governance_debt_score=0.1),
        strategy=StrategyDecision(strategy_id="adaptive_self_mutate", rationale="fallback rationale", confidence=0.9),
    )

    assert proposal.summary == "fallback rationale"
    assert proposal.evidence["llm_provider_result"]["ok"] is True
    assert proposal.metadata["strategy_id"] == "adaptive_self_mutate"
