# SPDX-License-Identifier: Apache-2.0

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.agents.mutation_strategies import DEFAULT_REGISTRY, ai_propose_strategy
from runtime.intelligence.llm_provider import LLMProviderResult


class AiProposeStrategyTest(unittest.TestCase):
    def _write_dna(self, root: Path, payload: dict) -> Path:
        agent_dir = root / "agent"
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "dna.json").write_text(json.dumps(payload), encoding="utf-8")
        return agent_dir

    def test_returns_provider_ops_using_dna_goal_and_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agent_dir = self._write_dna(Path(tmp), {"goal": "reduce complexity", "context": "repair_cycle"})
            provider_result = LLMProviderResult(
                ok=True,
                payload={"ops": [{"op": "replace", "filename": "agent.py", "new_code": "x = 1\n"}]},
            )
            with mock.patch("app.agents.mutation_strategies.LLMProviderClient.request_json", return_value=provider_result) as request_json:
                ops = ai_propose_strategy(agent_dir)

            request_json.assert_called_once()
            self.assertEqual(ops[0]["target"], "agent.py")
            self.assertEqual(ops[0]["source"], "x = 1\n")

    def test_uses_env_defaults_when_dna_goal_context_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agent_dir = self._write_dna(Path(tmp), {"traits": []})
            provider_result = LLMProviderResult(ok=True, payload={"ops": [{"op": "set", "path": "/version", "value": 2}]})

            old_goal = os.environ.get("ADAAD_AI_STRATEGY_GOAL")
            old_context = os.environ.get("ADAAD_AI_STRATEGY_CONTEXT")
            os.environ["ADAAD_AI_STRATEGY_GOAL"] = "stabilize outputs"
            os.environ["ADAAD_AI_STRATEGY_CONTEXT"] = "beast_mode"
            try:
                with mock.patch("app.agents.mutation_strategies.LLMProviderClient.request_json", return_value=provider_result) as request_json:
                    ops = ai_propose_strategy(agent_dir)
            finally:
                if old_goal is None:
                    os.environ.pop("ADAAD_AI_STRATEGY_GOAL", None)
                else:
                    os.environ["ADAAD_AI_STRATEGY_GOAL"] = old_goal
                if old_context is None:
                    os.environ.pop("ADAAD_AI_STRATEGY_CONTEXT", None)
                else:
                    os.environ["ADAAD_AI_STRATEGY_CONTEXT"] = old_context

            self.assertEqual(ops[0]["path"], "/version")
            called_prompt = request_json.call_args.kwargs["user_prompt"]
            self.assertIn("Goal: stabilize outputs", called_prompt)
            self.assertIn("Context: beast_mode", called_prompt)

    def test_returns_noop_when_provider_returns_no_ops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agent_dir = self._write_dna(Path(tmp), {"goal": "maintain quality", "context": "mutation_cycle"})
            with mock.patch(
                "app.agents.mutation_strategies.LLMProviderClient.request_json",
                return_value=LLMProviderResult(ok=False, payload={"proposal_type": "noop"}, error_code="missing_api_key"),
            ):
                ops = ai_propose_strategy(agent_dir)
            self.assertEqual(ops, [])

    def test_registry_has_ai_propose_strategy_for_engine_scoring(self) -> None:
        strategy = DEFAULT_REGISTRY.get("ai_propose")
        self.assertIsNotNone(strategy)
        assert strategy is not None
        self.assertEqual(strategy.intent_label, "ai_propose")
        self.assertGreater(strategy.skill_weight, 0.0)


if __name__ == "__main__":
    unittest.main()
