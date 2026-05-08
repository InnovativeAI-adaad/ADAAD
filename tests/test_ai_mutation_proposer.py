# SPDX-License-Identifier: Apache-2.0
"""
Test suite for runtime/autonomy/ai_mutation_proposer.py.

All 8 tests mock _call_claude — no real API calls are made in unit tests.
"""

from __future__ import annotations

import json
import threading
import time
import pytest
pytestmark = pytest.mark.regression_standard
from unittest.mock import patch, MagicMock

from runtime.autonomy.ai_mutation_proposer import (
    CANONICAL_AGENT_ORDER,
    CONTEXT_HASH_V1_HEX_LEN,
    CONTEXT_HASH_V2_HEX_LEN,
    CodebaseContext,
    _parse_proposals,
    propose_mutations,
    propose_from_all_agents,
)
from runtime.autonomy.mutation_scaffold import MutationCandidate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


VALID_PROPOSALS_JSON = json.dumps([
    {
        "mutation_id": "architect-refactor-001",
        "description": "Introduce adapter pattern for external API clients.",
        "expected_gain": 0.45,
        "risk_score": 0.15,
        "complexity": 0.30,
        "coverage_delta": 0.10,
        "target_files": ["runtime/autonomy/mutation_scaffold.py"],
        "mutation_type": "structural",
    },
    {
        "mutation_id": "architect-iface-002",
        "description": "Extract scoring interface for testability.",
        "expected_gain": 0.40,
        "risk_score": 0.10,
        "complexity": 0.20,
        "coverage_delta": 0.15,
        "target_files": ["runtime/autonomy/mutation_scaffold.py"],
        "mutation_type": "structural",
    },
    {
        "mutation_id": "architect-deps-003",
        "description": "Remove circular dependency between agents and evolution.",
        "expected_gain": 0.50,
        "risk_score": 0.20,
        "complexity": 0.35,
        "coverage_delta": 0.05,
        "target_files": ["runtime/evolution/evolution_loop.py"],
        "mutation_type": "structural",
    },
])


def _make_context() -> CodebaseContext:
    return CodebaseContext(
        file_summaries={"runtime/autonomy/mutation_scaffold.py": "Scoring helpers."},
        recent_failures=["test_some_feature"],
        current_epoch_id="epoch-test-001",
        explore_ratio=0.5,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_propose_mutations_architect_returns_candidates() -> None:
    ctx = _make_context()
    with patch(
        "runtime.autonomy.ai_mutation_proposer._call_claude",
        return_value=VALID_PROPOSALS_JSON,
    ):
        result = propose_mutations("architect", ctx, api_key="test-key")
    assert len(result) >= 3
    assert all(isinstance(c, MutationCandidate) for c in result)


def test_agent_origin_set_correctly() -> None:
    ctx = _make_context()
    with patch(
        "runtime.autonomy.ai_mutation_proposer._call_claude",
        return_value=VALID_PROPOSALS_JSON,
    ):
        result = propose_mutations("architect", ctx, api_key="test-key")
    assert all(c.agent_origin == "architect" for c in result)


def test_markdown_fence_stripped() -> None:
    ctx = _make_context()
    fenced = f"```json\n{VALID_PROPOSALS_JSON}\n```"
    with patch(
        "runtime.autonomy.ai_mutation_proposer._call_claude",
        return_value=fenced,
    ):
        result = propose_mutations("dream", ctx, api_key="test-key")
    assert len(result) >= 1  # Parsed without JSONDecodeError


def test_invalid_agent_raises_value_error() -> None:
    ctx = _make_context()
    with pytest.raises(ValueError, match="Unknown agent"):
        propose_mutations("unknown_agent", ctx, api_key="test-key")


def test_parent_id_propagates() -> None:
    ctx = _make_context()
    with patch(
        "runtime.autonomy.ai_mutation_proposer._call_claude",
        return_value=VALID_PROPOSALS_JSON,
    ):
        result = propose_mutations("beast", ctx, api_key="test-key", parent_id="parent-xyz")
    assert all(c.parent_id == "parent-xyz" for c in result)


def test_context_hash_set_in_candidate() -> None:
    ctx = _make_context()
    with patch(
        "runtime.autonomy.ai_mutation_proposer._call_claude",
        return_value=VALID_PROPOSALS_JSON,
    ):
        result = propose_mutations("architect", ctx, api_key="test-key")
    assert all(len(c.source_context_hash) > 0 for c in result)


def test_parse_proposals_rebuilds_missing_ids_deterministically() -> None:
    ctx = _make_context()
    raw = json.dumps([
        {
            "description": "Add deterministic mutation-id fallback coverage.",
            "expected_gain": 0.35,
            "risk_score": 0.2,
            "complexity": 0.25,
            "coverage_delta": 0.1,
            "target_files": ["runtime/autonomy/ai_mutation_proposer.py"],
            "mutation_type": "coverage",
        }
    ])

    first = _parse_proposals(
        raw, "architect", ctx, parent_id="parent-001", epoch_id="epoch-test-001"
    )
    second = _parse_proposals(
        raw, "architect", ctx, parent_id="parent-001", epoch_id="epoch-test-001"
    )

    assert [candidate.mutation_id for candidate in first] == [
        candidate.mutation_id for candidate in second
    ]
    assert first[0].mutation_id.startswith("architect-auto-")


def test_parse_proposals_rebuilds_wrong_prefix_ids_deterministically() -> None:
    ctx = _make_context()
    raw = json.dumps([
        {
            "mutation_id": "dream-cross-agent-123",
            "description": "Repair an ID with the wrong agent prefix.",
            "expected_gain": 0.35,
            "risk_score": 0.2,
            "complexity": 0.25,
            "coverage_delta": 0.1,
            "target_files": ["runtime/autonomy/ai_mutation_proposer.py"],
            "mutation_type": "coverage",
        }
    ])

    first = _parse_proposals(
        raw, "architect", ctx, parent_id="parent-001", epoch_id="epoch-test-001"
    )
    second = _parse_proposals(
        raw, "architect", ctx, parent_id="parent-001", epoch_id="epoch-test-001"
    )

    assert [candidate.mutation_id for candidate in first] == [
        candidate.mutation_id for candidate in second
    ]
    assert first[0].mutation_id.startswith("architect-dream-cross-agent-123-")


def test_parse_proposals_rebuilt_ids_remain_unique_within_batch() -> None:
    ctx = _make_context()
    base = {
        "description": "Repair duplicate missing IDs within the same batch.",
        "expected_gain": 0.35,
        "risk_score": 0.2,
        "complexity": 0.25,
        "coverage_delta": 0.1,
        "target_files": ["runtime/autonomy/ai_mutation_proposer.py"],
        "mutation_type": "coverage",
    }
    raw = json.dumps([base, dict(base)])

    proposals = _parse_proposals(
        raw, "architect", ctx, parent_id="parent-001", epoch_id="epoch-test-001"
    )
    generated_ids = [candidate.mutation_id for candidate in proposals]

    assert len(generated_ids) == 2
    assert len(set(generated_ids)) == len(generated_ids)


def test_context_hash_is_deterministic_for_same_context() -> None:
    ctx = _make_context()
    first = ctx.context_hash()
    second = ctx.context_hash()
    assert first == second


def test_context_hash_uses_sha256_short_hex_width() -> None:
    ctx = _make_context()
    digest = ctx.context_hash()
    assert len(digest) == CONTEXT_HASH_V2_HEX_LEN
    assert all(ch in "0123456789abcdef" for ch in digest)


def test_context_hash_v2_width_differs_from_legacy_md5_width() -> None:
    ctx = _make_context()
    legacy = ctx.context_hash_legacy()
    v2 = ctx.context_hash()
    assert len(legacy) == CONTEXT_HASH_V1_HEX_LEN
    assert len(v2) == CONTEXT_HASH_V2_HEX_LEN
    assert legacy != v2


def test_propose_all_agents_returns_all_keys() -> None:
    ctx = _make_context()
    with patch(
        "runtime.autonomy.ai_mutation_proposer._call_claude",
        return_value=VALID_PROPOSALS_JSON,
    ), patch(
        "runtime.autonomy.ai_mutation_proposer._load_operator_outcome_history",
        return_value={},
    ):
        result = propose_from_all_agents(ctx, api_key="test-key")
    assert tuple(result.proposals_by_agent.keys()) == CANONICAL_AGENT_ORDER
    assert result.failures_by_agent == {}


def test_propose_all_agents_deterministic_order_when_completion_is_out_of_order() -> None:
    ctx = _make_context()
    delays = {
        "architect": 0.08,
        "dream": 0.01,
        "beast": 0.04,
    }

    def _slow_propose(agent: str, *_args, **_kwargs):
        time.sleep(delays[agent])
        return [MagicMock(spec=MutationCandidate)]

    with patch(
        "runtime.autonomy.ai_mutation_proposer.propose_mutations",
        side_effect=_slow_propose,
    ), patch(
        "runtime.autonomy.ai_mutation_proposer._load_operator_outcome_history",
        return_value={},
    ):
        result = propose_from_all_agents(ctx, api_key="test-key", timeout=1)

    assert tuple(result.proposals_by_agent.keys()) == CANONICAL_AGENT_ORDER
    assert all(len(result.proposals_by_agent[agent]) == 1 for agent in CANONICAL_AGENT_ORDER)


def test_propose_all_agents_failure_isolated_per_agent() -> None:
    ctx = _make_context()

    def _partial_failure(agent: str, *_args, **_kwargs):
        if agent == "dream":
            raise TimeoutError("dream timed out")
        return [MagicMock(spec=MutationCandidate)]

    with patch(
        "runtime.autonomy.ai_mutation_proposer.propose_mutations",
        side_effect=_partial_failure,
    ), patch(
        "runtime.autonomy.ai_mutation_proposer._load_operator_outcome_history",
        return_value={},
    ):
        result = propose_from_all_agents(ctx, api_key="test-key", timeout=2, retries=0)

    assert len(result.proposals_by_agent["architect"]) == 1
    assert len(result.proposals_by_agent["beast"]) == 1
    assert result.proposals_by_agent["dream"] == []
    assert result.failures_by_agent["dream"]["code"] == "agent_timeout"


def test_propose_all_agents_global_timeout_cancels_pending_work() -> None:
    ctx = _make_context()
    gate = threading.Event()

    def _hung_propose(agent: str, *_args, **_kwargs):
        if agent == "architect":
            return [MagicMock(spec=MutationCandidate)]
        gate.wait(timeout=0.5)
        return [MagicMock(spec=MutationCandidate)]

    with patch(
        "runtime.autonomy.ai_mutation_proposer.propose_mutations",
        side_effect=_hung_propose,
    ), patch(
        "runtime.autonomy.ai_mutation_proposer._load_operator_outcome_history",
        return_value={},
    ):
        result = propose_from_all_agents(
            ctx,
            api_key="test-key",
            timeout=1,
            global_timeout_budget=0.02,
        )

    assert len(result.proposals_by_agent["architect"]) == 1
    assert result.failures_by_agent["dream"]["code"] == "global_timeout"
    assert result.failures_by_agent["beast"]["code"] == "global_timeout"


def test_malformed_json_raises() -> None:
    ctx = _make_context()
    with patch(
        "runtime.autonomy.ai_mutation_proposer._call_claude",
        return_value="this is not json at all",
    ):
        with pytest.raises(json.JSONDecodeError):
            propose_mutations("architect", ctx, api_key="test-key")


def test_propose_all_agents_applies_operator_registry_metadata() -> None:
    ctx = _make_context()

    def _single(agent: str, *_args, **_kwargs):
        return [
            MutationCandidate(
                mutation_id=f"{agent}-m-1",
                expected_gain=0.5,
                risk_score=0.2,
                complexity=0.2,
                coverage_delta=0.1,
                agent_origin=agent,
            )
        ]

    with patch(
        "runtime.autonomy.ai_mutation_proposer.propose_mutations",
        side_effect=_single,
    ), patch(
        "runtime.autonomy.ai_mutation_proposer._load_operator_outcome_history",
        return_value={},
    ):
        result = propose_from_all_agents(ctx, api_key="test-key", retries=0)

    all_candidates = [
        candidate
        for proposals in result.proposals_by_agent.values()
        for candidate in proposals
    ]
    assert all(candidate.operator_key != "static" for candidate in all_candidates)


# ---------------------------------------------------------------------------
# WORK-66-C: LLM failover governance contract — FINDING-66-001
# ---------------------------------------------------------------------------

class TestLLMFailoverContract:
    """Gate tests asserting the LLM failover governance contract is upheld.

    Contract: docs/governance/LLM_FAILOVER_CONTRACT.md
    """

    def test_single_agent_failure_produces_structured_payload(self):
        """A failed agent must produce a structured failure payload with required keys."""
        ctx = _make_context()

        def _raise_for_arch(agent, *args, **kwargs):
            if agent == "architect":
                raise TimeoutError("simulated timeout")
            return []

        with patch(
            "runtime.autonomy.ai_mutation_proposer.propose_mutations",
            side_effect=_raise_for_arch,
        ), patch(
            "runtime.autonomy.ai_mutation_proposer._load_operator_outcome_history",
            return_value={},
        ):
            result = propose_from_all_agents(ctx, api_key="test-key", retries=0)

        assert "architect" in result.failures_by_agent
        payload = result.failures_by_agent["architect"]
        # Required keys per contract §4.2 (failure_payload fields)
        for key in ("agent", "code", "attempts", "timeout_seconds", "detail"):
            assert key in payload, f"Failure payload missing required key: {key!r}"

    def test_single_agent_failure_code_is_agent_timeout_for_timeout_error(self):
        """TimeoutError must produce code='agent_timeout' per contract §3.1."""
        ctx = _make_context()

        def _raise(agent, *args, **kwargs):
            raise TimeoutError("timeout")

        with patch(
            "runtime.autonomy.ai_mutation_proposer.propose_mutations",
            side_effect=_raise,
        ), patch(
            "runtime.autonomy.ai_mutation_proposer._load_operator_outcome_history",
            return_value={},
        ):
            result = propose_from_all_agents(ctx, api_key="test-key", retries=0)

        for agent in ("architect", "dream", "beast"):
            assert result.failures_by_agent[agent]["code"] == "agent_timeout", (
                f"Expected code='agent_timeout' for {agent}, "
                f"got {result.failures_by_agent[agent]['code']!r}"
            )

    def test_all_agents_failed_produces_zero_total_proposals(self):
        """Zero-proposal epoch: all agents fail → total proposal count is 0."""
        ctx = _make_context()

        with patch(
            "runtime.autonomy.ai_mutation_proposer.propose_mutations",
            side_effect=Exception("api_error"),
        ), patch(
            "runtime.autonomy.ai_mutation_proposer._load_operator_outcome_history",
            return_value={},
        ):
            result = propose_from_all_agents(ctx, api_key="test-key", retries=0)

        total = sum(len(p) for p in result.proposals_by_agent.values())
        assert total == 0, (
            f"Zero-proposal epoch must have 0 total proposals, got {total}. "
            "Contract §5: no mutation may proceed in a zero-proposal epoch."
        )

    def test_all_agents_failed_is_detectable_without_logs(self):
        """Zero-proposal epoch must be detectable from AgentProposalBatch alone."""
        ctx = _make_context()

        with patch(
            "runtime.autonomy.ai_mutation_proposer.propose_mutations",
            side_effect=Exception("api_error"),
        ), patch(
            "runtime.autonomy.ai_mutation_proposer._load_operator_outcome_history",
            return_value={},
        ):
            result = propose_from_all_agents(ctx, api_key="test-key", retries=0)

        all_proposals_empty = all(
            len(p) == 0 for p in result.proposals_by_agent.values()
        )
        all_agents_failed = len(result.failures_by_agent) == len(("architect", "dream", "beast"))
        assert all_proposals_empty and all_agents_failed, (
            "Zero-proposal epoch must be deterministically detectable from "
            "AgentProposalBatch.proposals_by_agent and .failures_by_agent. "
            "Contract §4.4: no log inspection required."
        )

    def test_successful_agent_is_absent_from_failures(self):
        """Successful agents must not appear in failures_by_agent. Contract §3."""
        ctx = _make_context()

        def _succeed_arch_fail_others(agent, *args, **kwargs):
            if agent == "architect":
                return [
                    MutationCandidate(
                        mutation_id="arch-m-1",
                        expected_gain=0.5, risk_score=0.2,
                        complexity=0.2, coverage_delta=0.1,
                        agent_origin="architect",
                    )
                ]
            raise Exception("fail")

        with patch(
            "runtime.autonomy.ai_mutation_proposer.propose_mutations",
            side_effect=_succeed_arch_fail_others,
        ), patch(
            "runtime.autonomy.ai_mutation_proposer._load_operator_outcome_history",
            return_value={},
        ):
            result = propose_from_all_agents(ctx, api_key="test-key", retries=0)

        assert "architect" not in result.failures_by_agent, (
            "Successful agents must not appear in failures_by_agent."
        )
        assert len(result.proposals_by_agent["architect"]) >= 1
