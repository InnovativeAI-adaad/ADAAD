# SPDX-License-Identifier: Apache-2.0

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runtime.autonomy.loop import AgentAction, run_self_check_loop
from runtime.autonomy.mutation_scaffold import MutationCandidate, rank_mutation_candidates
from runtime.autonomy.roles import SandboxPermission, default_role_specs
from runtime.autonomy.scoreboard import build_scoreboard_views


class AutonomyEnhancementTest(unittest.TestCase):
    def test_default_roles_define_required_agents(self) -> None:
        roles = default_role_specs()
        self.assertEqual(set(roles.keys()), {"ArchitectAgent", "ExecutorAgent", "ValidatorAgent", "MutatorAgent", "GovernanceAgent"})
        self.assertEqual(roles["GovernanceAgent"].sandbox_permission, SandboxPermission.GOVERNANCE)
        self.assertIn("adjudicate(proposal)", roles["GovernanceAgent"].interface)

    def test_autonomy_loop_escalates_on_failed_post_condition(self) -> None:
        actions = [
            AgentAction(agent="ExecutorAgent", action="apply_patch", duration_ms=25, ok=True),
            AgentAction(agent="ValidatorAgent", action="run_tests", duration_ms=30, ok=True),
        ]
        result = run_self_check_loop(
            cycle_id="cycle-1",
            actions=actions,
            post_condition_checks={"tests_pass": lambda: False},
            mutation_score=0.95,
            mutate_threshold=0.8,
        )
        self.assertEqual(result.decision, "escalate")
        self.assertFalse(result.post_conditions_passed)

    def test_rank_mutation_candidates_is_deterministic(self) -> None:
        candidates = [
            MutationCandidate("m2", expected_gain=0.70, risk_score=0.20, complexity=0.15, coverage_delta=0.10),
            MutationCandidate("m1", expected_gain=0.70, risk_score=0.20, complexity=0.15, coverage_delta=0.10),
            MutationCandidate("m3", expected_gain=0.40, risk_score=0.30, complexity=0.35, coverage_delta=0.00),
        ]
        ranked = rank_mutation_candidates(candidates, acceptance_threshold=0.2)
        self.assertEqual([item.mutation_id for item in ranked], ["m1", "m2", "m3"])
        self.assertTrue(ranked[0].accepted)

    def test_scoreboard_builds_required_views(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            metrics_path = Path(tmp) / "metrics.jsonl"
            with mock.patch("runtime.metrics.METRICS_PATH", metrics_path):
                from runtime import metrics

                metrics.log("autonomy_action", {"agent": "ExecutorAgent", "duration_ms": 40, "ok": True})
                metrics.log("mutation_executed", {"ok": True})
                metrics.log("sandbox_validation_failed", {"reason": "missing_signature"})

                scoreboard = build_scoreboard_views(limit=50)

        self.assertIn("performance_by_agent", scoreboard)
        self.assertIn("mutation_outcomes", scoreboard)
        self.assertIn("sandbox_failure_reasons", scoreboard)
        self.assertIn("ExecutorAgent", scoreboard["performance_by_agent"])
        self.assertEqual(scoreboard["mutation_outcomes"].get("mutation_executed"), 1)
        self.assertEqual(scoreboard["sandbox_failure_reasons"].get("missing_signature"), 1)


    def test_scoreboard_handles_missing_metrics_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            metrics_path = Path(tmp) / "missing_metrics.jsonl"
            with mock.patch("runtime.metrics.METRICS_PATH", metrics_path):
                scoreboard = build_scoreboard_views(limit=25)

        self.assertEqual(scoreboard["performance_by_agent"], {})
        self.assertEqual(scoreboard["mutation_outcomes"], {})
        self.assertEqual(scoreboard["sandbox_failure_reasons"], {})

    def test_scoreboard_ignores_malformed_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            metrics_path = Path(tmp) / "metrics.jsonl"
            metrics_path.write_text(
                '{"event":"autonomy_action","payload":{"agent":"ExecutorAgent","duration_ms":"not-an-int"}}\n'
                '{"event":"sandbox_validation_failed","payload":"not-a-dict"}\n',
                encoding="utf-8",
            )
            with mock.patch("runtime.metrics.METRICS_PATH", metrics_path):
                scoreboard = build_scoreboard_views(limit=50)

        self.assertEqual(scoreboard["performance_by_agent"]["ExecutorAgent"]["avg_duration_ms"], 0.0)
        self.assertEqual(scoreboard["sandbox_failure_reasons"]["unknown"], 1)


if __name__ == "__main__":
    unittest.main()
