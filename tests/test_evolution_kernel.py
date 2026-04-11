# SPDX-License-Identifier: Apache-2.0

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pytest

from runtime.evolution.evolution_kernel import EvolutionKernel

pytestmark = pytest.mark.regression_standard


class EvolutionKernelTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dashboard_patch = mock.patch("runtime.evolution.evolution_kernel.push_to_dashboard", return_value=True)
        self.dashboard_push = self.dashboard_patch.start()
        self.addCleanup(self.dashboard_patch.stop)
        self.trigger_signal = {
            "previous_failed": False,
            "previous_quarantined": False,
            "latest_fitness_score": 0.6,
            "latest_fitness_threshold": 0.7,
        }
        self.signal_patch = mock.patch.object(EvolutionKernel, "_load_previous_cycle_signal", return_value=self.trigger_signal)
        self.signal_patch.start()
        self.addCleanup(self.signal_patch.stop)
        self.agents_root = Path(self.tmp.name) / "app" / "agents"
        self.lineage_dir = self.agents_root / "lineage"
        self.agent_dir = self.agents_root / "agent-x"
        self.agent_dir.mkdir(parents=True, exist_ok=True)
        self.lineage_dir.mkdir(parents=True, exist_ok=True)
        (self.agent_dir / "meta.json").write_text(json.dumps({"name": "agent-x"}), encoding="utf-8")
        (self.agent_dir / "dna.json").write_text(json.dumps({"traits": []}), encoding="utf-8")
        (self.agent_dir / "certificate.json").write_text(json.dumps({"signature": "cryovant-dev-seed"}), encoding="utf-8")
        (self.agent_dir / "__init__.py").write_text(
            """
AGENT_ID = "agent-x"
VERSION = "1.0.0"
CAPABILITIES = []
GOAL_SCHEMA = {}
OUTPUT_SCHEMA = {}
SPAWN_POLICY = {}

def get_agent_manifest() -> dict:
    return {}

def run_goal(goal) -> dict:
    return {"goal": goal}

def info() -> dict:
    return {"agent": "agent-x"}

def run(input=None) -> dict:
    return {"input": input}

def mutate(src: str) -> str:
    return src

def score(output: dict) -> float:
    return 1.0
""",
            encoding="utf-8",
        )

    def test_load_agent_reads_metadata_triplet(self) -> None:
        kernel = EvolutionKernel(agents_root=self.agents_root, lineage_dir=self.lineage_dir, compatibility_adapter=mock.Mock())
        loaded = kernel.load_agent(self.agent_dir)
        self.assertEqual(loaded["agent_id"], "agent-x")
        self.assertIn("dna", loaded)
        self.assertIn("certificate", loaded)

    def test_validate_mutation_requires_ops(self) -> None:
        kernel = EvolutionKernel(agents_root=self.agents_root, lineage_dir=self.lineage_dir, compatibility_adapter=mock.Mock())
        result = kernel.validate_mutation(None, {"ops": []})
        self.assertFalse(result["valid"])
        self.assertIn("policy_valid", result)

    def test_run_cycle_uses_compatibility_adapter(self) -> None:
        adapter = mock.Mock()
        adapter.run_cycle.return_value = {"status": "ok"}
        kernel = EvolutionKernel(agents_root=self.agents_root, lineage_dir=self.lineage_dir, compatibility_adapter=adapter)
        result = kernel.run_cycle()
        self.assertEqual(result["status"], "ok")
        adapter.run_cycle.assert_called_once_with(None)

    def test_run_cycle_uses_kernel_pipeline_for_specific_agent(self) -> None:
        adapter = mock.Mock()
        kernel = EvolutionKernel(agents_root=self.agents_root, lineage_dir=self.lineage_dir, compatibility_adapter=adapter)

        with (
            mock.patch.object(kernel, "_load_previous_cycle_signal", return_value=self.trigger_signal),
            mock.patch.object(kernel, "propose_mutation", return_value={"request": {"agent_id": "agent-x", "ops": [{"op": "dna.add_trait"}]}}),
            mock.patch.object(kernel, "validate_mutation", return_value={"valid": True, "policy_valid": True, "mutation_has_ops": True, "errors": []}),
            mock.patch.object(kernel.fitness_evaluator, "forecast", return_value={"forecast_score": 0.8, "forecast_gate_threshold": 0.45, "forecast_passed": True, "policy_profile": {}, "policy_artifact": {"version": "mutation_policy_profile.v1", "hash": "sha256:ok"}}),
            mock.patch.object(kernel, "execute_in_sandbox", return_value={"status": "applied", "mutation_id": "m-1"}) as execute,
            mock.patch.object(kernel, "evaluate_fitness", return_value={"score": 0.9, "accepted": True, "passed": True}) as evaluate,
            mock.patch.object(kernel, "sign_certificate", return_value={"certificate_id": "c-1"}) as sign,
        ):
            result = kernel.run_cycle("agent-x")

        adapter.run_cycle.assert_not_called()
        execute.assert_called_once()
        evaluate.assert_called_once()
        sign.assert_called_once()
        self.assertTrue(result["kernel_path"])
        self.assertEqual(result["agent_id"], "agent-x")
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["cycle_outcome_event"]["disposition"], "promoted")

    def test_run_cycle_resolves_agent_paths_before_membership_check(self) -> None:
        alias_root = self.agents_root / ".." / "agents"
        kernel = EvolutionKernel(agents_root=alias_root, lineage_dir=self.lineage_dir, compatibility_adapter=mock.Mock())

        with (
            mock.patch("runtime.evolution.evolution_kernel.iter_agent_dirs", return_value=[self.agent_dir.resolve()]),
            mock.patch.object(kernel, "_load_previous_cycle_signal", return_value=self.trigger_signal),
            mock.patch.object(kernel, "propose_mutation", return_value={"request": {"agent_id": "agent-x", "ops": [{"op": "dna.add_trait"}]}}),
            mock.patch.object(kernel, "validate_mutation", return_value={"valid": True, "policy_valid": True, "mutation_has_ops": True, "errors": []}),
            mock.patch.object(kernel.fitness_evaluator, "forecast", return_value={"forecast_score": 0.8, "forecast_gate_threshold": 0.45, "forecast_passed": True, "policy_profile": {}, "policy_artifact": {"version": "mutation_policy_profile.v1", "hash": "sha256:ok"}}),
            mock.patch.object(kernel, "execute_in_sandbox", return_value={"status": "applied", "mutation_id": "m-2"}),
            mock.patch.object(kernel, "evaluate_fitness", return_value={"score": 0.8, "accepted": True, "passed": True}),
            mock.patch.object(kernel, "sign_certificate", return_value={"certificate_id": "c-2"}),
        ):
            result = kernel.run_cycle("agent-x")

        self.assertEqual(result["agent_id"], "agent-x")
        self.assertTrue(result["kernel_path"])



    def test_run_cycle_rejects_when_forecast_gate_fails(self) -> None:
        adapter = mock.Mock()
        kernel = EvolutionKernel(agents_root=self.agents_root, lineage_dir=self.lineage_dir, compatibility_adapter=adapter)

        with (
            mock.patch.object(kernel, "_load_previous_cycle_signal", return_value=self.trigger_signal),
            mock.patch.object(kernel, "propose_mutation", return_value={"request": {"agent_id": "agent-x", "ops": [{"op": "dna.add_trait"}]}}),
            mock.patch.object(kernel, "validate_mutation", return_value={"valid": True, "policy_valid": True, "mutation_has_ops": True, "errors": []}),
            mock.patch.object(kernel.fitness_evaluator, "forecast", return_value={"forecast_score": 0.1, "forecast_gate_threshold": 0.45, "forecast_passed": False, "policy_profile": {}, "policy_artifact": {"version": "mutation_policy_profile.v1", "hash": "sha256:1"}}),
            mock.patch.object(kernel, "execute_in_sandbox") as execute,
            mock.patch.object(kernel, "evaluate_fitness") as evaluate,
            mock.patch.object(kernel, "sign_certificate") as sign,
        ):
            result = kernel.run_cycle("agent-x")

        execute.assert_not_called()
        evaluate.assert_not_called()
        sign.assert_not_called()
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason"], "forecast_gate_failed")

    def test_execute_in_sandbox_rejects_invalid_schema_before_executor(self) -> None:
        kernel = EvolutionKernel(agents_root=self.agents_root, lineage_dir=self.lineage_dir, compatibility_adapter=mock.Mock())

        invalid = {
            "request": {
                "agent_id": "agent-x",
                "generation_ts": "",
                "intent": "test",
                "ops": [],
                "targets": [],
                "signature": "",
                "nonce": "",
                "extra": "not-allowed",
            }
        }

        with mock.patch.object(kernel.mutation_executor, "execute") as execute:
            result = kernel.execute_in_sandbox({"agent_id": "agent-x"}, invalid)

        execute.assert_not_called()
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason"], "invalid_mutation_proposal_schema")


    def test_evaluate_fitness_uses_mutation_payload_for_scoring_signals(self) -> None:
        kernel = EvolutionKernel(agents_root=self.agents_root, lineage_dir=self.lineage_dir, compatibility_adapter=mock.Mock())
        agent = {"agent_id": "agent-x"}
        mutation_payload = {
            "ops": [{"op": "dna.add_trait", "path": "/traits/-", "value": "fast"}],
            "tests_ok": True,
            "sandbox_ok": True,
            "constitution_ok": True,
            "policy_valid": True,
        }

        enriched = kernel.evaluate_fitness(agent, mutation_payload)
        empty = kernel.evaluate_fitness(agent, {})

        self.assertGreater(enriched["reasons"]["correctness"], empty["reasons"]["correctness"])
        self.assertGreater(enriched["reasons"]["policy_compliance"], empty["reasons"]["policy_compliance"])
        self.assertTrue(enriched["weights"])
        self.assertTrue(enriched["weighted_contributions"])

    def test_run_cycle_skips_sign_when_execution_rejected(self) -> None:
        kernel = EvolutionKernel(agents_root=self.agents_root, lineage_dir=self.lineage_dir, compatibility_adapter=mock.Mock())
        with (
            mock.patch.object(kernel, "_load_previous_cycle_signal", return_value=self.trigger_signal),
            mock.patch.object(kernel, "propose_mutation", return_value={"request": {"agent_id": "agent-x", "ops": [{"op": "dna.add_trait"}]}}),
            mock.patch.object(kernel, "validate_mutation", return_value={"valid": True, "policy_valid": True, "mutation_has_ops": True, "errors": []}),
            mock.patch.object(kernel.fitness_evaluator, "forecast", return_value={"forecast_score": 0.8, "forecast_gate_threshold": 0.45, "forecast_passed": True, "policy_profile": {}, "policy_artifact": {"version": "mutation_policy_profile.v1", "hash": "sha256:ok"}}),
            mock.patch.object(kernel, "execute_in_sandbox", return_value={"status": "rejected", "reason": "sandbox_deny"}),
            mock.patch.object(kernel, "evaluate_fitness", return_value={"accepted": True, "passed": True}),
            mock.patch.object(kernel, "sign_certificate") as sign,
        ):
            result = kernel.run_cycle("agent-x")

        sign.assert_not_called()
        self.assertEqual(result["certificate"]["status"], "skipped")
        self.assertEqual(result["certificate"]["reason"], "execution_not_successful")

    def test_run_cycle_skips_sign_when_fitness_not_accepted(self) -> None:
        kernel = EvolutionKernel(agents_root=self.agents_root, lineage_dir=self.lineage_dir, compatibility_adapter=mock.Mock())
        with (
            mock.patch.object(kernel, "_load_previous_cycle_signal", return_value=self.trigger_signal),
            mock.patch.object(kernel, "propose_mutation", return_value={"request": {"agent_id": "agent-x", "ops": [{"op": "dna.add_trait"}]}}),
            mock.patch.object(kernel, "validate_mutation", return_value={"valid": True, "policy_valid": True, "mutation_has_ops": True, "errors": []}),
            mock.patch.object(kernel.fitness_evaluator, "forecast", return_value={"forecast_score": 0.8, "forecast_gate_threshold": 0.45, "forecast_passed": True, "policy_profile": {}, "policy_artifact": {"version": "mutation_policy_profile.v1", "hash": "sha256:ok"}}),
            mock.patch.object(kernel, "execute_in_sandbox", return_value={"status": "applied", "mutation_id": "m-1"}),
            mock.patch.object(kernel, "evaluate_fitness", return_value={"accepted": False, "passed": False}),
            mock.patch.object(kernel, "sign_certificate") as sign,
        ):
            result = kernel.run_cycle("agent-x")

        sign.assert_not_called()
        self.assertEqual(result["certificate"]["status"], "skipped")
        self.assertEqual(result["certificate"]["reason"], "fitness_not_accepted")

    def test_run_cycle_signs_when_fitness_policy_accepted(self) -> None:
        kernel = EvolutionKernel(agents_root=self.agents_root, lineage_dir=self.lineage_dir, compatibility_adapter=mock.Mock())
        with (
            mock.patch.object(kernel, "_load_previous_cycle_signal", return_value=self.trigger_signal),
            mock.patch.object(kernel, "propose_mutation", return_value={"request": {"agent_id": "agent-x", "ops": [{"op": "dna.add_trait"}]}}),
            mock.patch.object(kernel, "validate_mutation", return_value={"valid": True, "policy_valid": True, "mutation_has_ops": True, "errors": []}),
            mock.patch.object(kernel.fitness_evaluator, "forecast", return_value={"forecast_score": 0.8, "forecast_gate_threshold": 0.45, "forecast_passed": True, "policy_profile": {}, "policy_artifact": {"version": "mutation_policy_profile.v1", "hash": "sha256:ok"}}),
            mock.patch.object(kernel, "execute_in_sandbox", return_value={"status": "applied", "mutation_id": "m-1"}),
            mock.patch.object(kernel, "evaluate_fitness", return_value={"policy": {"accepted": True}, "accepted": False, "passed": False}),
            mock.patch.object(kernel, "sign_certificate", return_value={"certificate_id": "c-1"}) as sign,
        ):
            result = kernel.run_cycle("agent-x")

        sign.assert_called_once()
        self.assertEqual(result["certificate"]["certificate_id"], "c-1")

    def test_run_cycle_rejects_missing_agent(self) -> None:
        kernel = EvolutionKernel(agents_root=self.agents_root, lineage_dir=self.lineage_dir, compatibility_adapter=mock.Mock())
        with self.assertRaisesRegex(RuntimeError, "agent_not_found:missing"):
            kernel.run_cycle("missing")


    def test_run_cycle_skips_pipeline_for_non_functional_change(self) -> None:
        adapter = mock.Mock()
        kernel = EvolutionKernel(agents_root=self.agents_root, lineage_dir=self.lineage_dir, compatibility_adapter=adapter)

        with (
            mock.patch.object(kernel, "_load_previous_cycle_signal", return_value=self.trigger_signal),
            mock.patch.object(kernel, "propose_mutation", return_value={"request": {"agent_id": "agent-x", "ops": [{"op": "set", "path": "/last_mutation", "value": "x"}]}}),
            mock.patch("runtime.evolution.evolution_kernel.classify_mutation_change") as classify,
            mock.patch("runtime.evolution.evolution_kernel.apply_metadata_updates", return_value={"mutation_count": 2, "version": 3, "last_mutation": "2025-01-01T00:00:00Z"}) as metadata,
            mock.patch("runtime.evolution.evolution_kernel.cryovant.touch_non_functional_metadata", return_value={"status": "metadata_touched"}) as touch_metadata,
            mock.patch("runtime.evolution.evolution_kernel.metrics.log") as metrics_log,
            mock.patch.object(kernel, "execute_in_sandbox") as execute,
            mock.patch.object(kernel, "evaluate_fitness") as evaluate,
            mock.patch.object(kernel, "sign_certificate") as sign,
        ):
            classify.return_value = mock.Mock(classification="NON_FUNCTIONAL_CHANGE", run_mutation=False, reason="allowed_metadata_only")
            result = kernel.run_cycle("agent-x")

        metadata.assert_called_once()
        touch_metadata.assert_called_once_with(
            "agent-x",
            self.agent_dir,
            metadata_version=3,
            mutation_count=2,
            metadata_last_mutation="2025-01-01T00:00:00Z",
        )
        metrics_log.assert_any_call(
            event_type="cosmetic_update_only",
            payload={
                "agent_id": "agent-x",
                "change_reason": "allowed_metadata_only",
                "metadata_version": 3,
                "metadata_mutation_count": 2,
                "metadata_last_mutation": "2025-01-01T00:00:00Z",
            },
        )
        metrics_log.assert_any_call(
            event_type="evolution_cycle_outcome",
            payload=mock.ANY,
        )
        execute.assert_not_called()
        evaluate.assert_not_called()
        sign.assert_not_called()
        self.assertEqual(result["status"], "metadata_only")
        self.assertEqual(result["change_classification"], "NON_FUNCTIONAL_CHANGE")
        self.assertTrue(result["cosmetic_only"])
        self.assertEqual(result["cycle_outcome_event"]["disposition"], "cosmetic_only")

    def test_cycle_outcome_event_payload_keys_for_promoted_path(self) -> None:
        kernel = EvolutionKernel(agents_root=self.agents_root, lineage_dir=self.lineage_dir, compatibility_adapter=mock.Mock())
        with (
            mock.patch.object(kernel, "propose_mutation", return_value={"request": {"agent_id": "agent-x", "ops": [{"op": "dna.add_trait"}], "mutation_id": "m-1"}}),
            mock.patch.object(kernel, "validate_mutation", return_value={"valid": True, "policy_valid": True, "mutation_has_ops": True, "errors": []}),
            mock.patch.object(kernel.fitness_evaluator, "forecast", return_value={"forecast_score": 0.8, "forecast_gate_threshold": 0.45, "forecast_passed": True, "policy_profile": {}, "policy_artifact": {"version": "mutation_policy_profile.v1", "hash": "sha256:ok"}}),
            mock.patch.object(kernel, "execute_in_sandbox", return_value={"status": "applied", "mutation_id": "m-1"}),
            mock.patch.object(kernel, "evaluate_fitness", return_value={"score": 0.91, "accepted": True, "passed": True}),
            mock.patch.object(kernel, "sign_certificate", return_value={"status": "signed", "certificate_id": "c-1"}),
        ):
            result = kernel.run_cycle("agent-x")

        event = result["cycle_outcome_event"]
        for key in (
            "agent_id",
            "change_classification",
            "change_reason",
            "execution_status",
            "fitness_score",
            "fitness_accepted",
            "signing_status",
            "disposition",
            "lineage_linkage",
            "lineage_linkage_type",
            "schema_version",
        ):
            self.assertIn(key, event)
        self.assertEqual(event["disposition"], "promoted")
        self.assertEqual(event["lineage_linkage"], "m-1")
        self.assertEqual(event["lineage_linkage_type"], "mutation_id")

    def test_cycle_outcome_event_payload_keys_for_rejected_path(self) -> None:
        kernel = EvolutionKernel(agents_root=self.agents_root, lineage_dir=self.lineage_dir, compatibility_adapter=mock.Mock())
        with (
            mock.patch.object(kernel, "propose_mutation", return_value={"request": {"agent_id": "agent-x", "ops": [{"op": "dna.add_trait"}]}}),
            mock.patch.object(kernel, "validate_mutation", return_value={"valid": False, "policy_valid": False, "mutation_has_ops": True, "errors": ["bad_policy"]}),
        ):
            result = kernel.run_cycle("agent-x")

        event = result["cycle_outcome_event"]
        self.assertEqual(event["disposition"], "rejected")
        self.assertEqual(event["execution_status"], "rejected")
        self.assertIn("lineage_linkage", event)

    def test_cycle_outcome_event_payload_keys_for_quarantine_path(self) -> None:
        kernel = EvolutionKernel(agents_root=self.agents_root, lineage_dir=self.lineage_dir, compatibility_adapter=mock.Mock())
        with (
            mock.patch.object(kernel, "propose_mutation", return_value={"request": {"agent_id": "agent-x", "ops": [{"op": "dna.add_trait"}], "mutation_id": "m-3"}}),
            mock.patch.object(kernel, "validate_mutation", return_value={"valid": True, "policy_valid": True, "mutation_has_ops": True, "errors": []}),
            mock.patch.object(kernel.fitness_evaluator, "forecast", return_value={"forecast_score": 0.8, "forecast_gate_threshold": 0.45, "forecast_passed": True, "policy_profile": {}, "policy_artifact": {"version": "mutation_policy_profile.v1", "hash": "sha256:ok"}}),
            mock.patch.object(kernel, "execute_in_sandbox", return_value={"status": "applied", "mutation_id": "m-3"}),
            mock.patch.object(kernel, "evaluate_fitness", return_value={"score": 0.12, "accepted": False, "passed": False}),
            mock.patch.object(kernel, "sign_certificate") as sign,
        ):
            result = kernel.run_cycle("agent-x")

        sign.assert_not_called()
        event = result["cycle_outcome_event"]
        self.assertEqual(event["disposition"], "quarantined")
        self.assertEqual(event["fitness_accepted"], False)

    def test_run_cycle_mutation_trigger_below_threshold_runs(self) -> None:
        kernel = EvolutionKernel(agents_root=self.agents_root, lineage_dir=self.lineage_dir, compatibility_adapter=mock.Mock())
        trigger_signal = {
            "previous_failed": False,
            "previous_quarantined": False,
            "latest_fitness_score": 0.3,
            "latest_fitness_threshold": 0.7,
        }
        with (
            mock.patch.object(kernel, "_load_previous_cycle_signal", return_value=trigger_signal),
            mock.patch.object(kernel, "propose_mutation", return_value={"request": {"agent_id": "agent-x", "ops": [{"op": "dna.add_trait"}]}}) as propose,
            mock.patch.object(kernel, "validate_mutation", return_value={"valid": True}),
            mock.patch.object(kernel.fitness_evaluator, "forecast", return_value={"forecast_passed": False, "forecast_score": 0.1, "forecast_gate_threshold": 0.45, "policy_profile": {}, "policy_artifact": {"version": "mutation_policy_profile.v1", "hash": "sha256:1"}}),
        ):
            result = kernel.run_cycle("agent-x")
        propose.assert_called_once()
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason"], "forecast_gate_failed")

    def test_run_cycle_mutation_trigger_previous_failure_runs(self) -> None:
        kernel = EvolutionKernel(agents_root=self.agents_root, lineage_dir=self.lineage_dir, compatibility_adapter=mock.Mock())
        trigger_signal = {
            "previous_failed": True,
            "previous_quarantined": False,
            "latest_fitness_score": 0.9,
            "latest_fitness_threshold": 0.7,
        }
        with (
            mock.patch.object(kernel, "_load_previous_cycle_signal", return_value=trigger_signal),
            mock.patch.object(kernel, "propose_mutation", return_value={"request": {"agent_id": "agent-x", "ops": [{"op": "dna.add_trait"}]}}) as propose,
            mock.patch.object(kernel, "validate_mutation", return_value={"valid": True}),
            mock.patch.object(kernel.fitness_evaluator, "forecast", return_value={"forecast_passed": False, "forecast_score": 0.1, "forecast_gate_threshold": 0.45, "policy_profile": {}, "policy_artifact": {"version": "mutation_policy_profile.v1", "hash": "sha256:1"}}),
        ):
            result = kernel.run_cycle("agent-x")
        propose.assert_called_once()
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason"], "forecast_gate_failed")

    def test_run_cycle_mutation_trigger_manual_runs(self) -> None:
        kernel = EvolutionKernel(agents_root=self.agents_root, lineage_dir=self.lineage_dir, compatibility_adapter=mock.Mock())
        trigger_signal = {
            "previous_failed": False,
            "previous_quarantined": False,
            "latest_fitness_score": 0.9,
            "latest_fitness_threshold": 0.7,
        }
        with (
            mock.patch.object(kernel, "_load_previous_cycle_signal", return_value=trigger_signal),
            mock.patch.object(kernel, "propose_mutation", return_value={"request": {"agent_id": "agent-x", "ops": [{"op": "dna.add_trait"}]}}) as propose,
            mock.patch.object(kernel, "validate_mutation", return_value={"valid": True}),
            mock.patch.object(kernel.fitness_evaluator, "forecast", return_value={"forecast_passed": False, "forecast_score": 0.1, "forecast_gate_threshold": 0.45, "policy_profile": {}, "policy_artifact": {"version": "mutation_policy_profile.v1", "hash": "sha256:1"}}),
        ):
            result = kernel.run_cycle("agent-x", manual_trigger=True)
        propose.assert_called_once()
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason"], "forecast_gate_failed")

    def test_run_cycle_mutation_trigger_healthy_skips(self) -> None:
        kernel = EvolutionKernel(agents_root=self.agents_root, lineage_dir=self.lineage_dir, compatibility_adapter=mock.Mock())
        trigger_signal = {
            "previous_failed": False,
            "previous_quarantined": False,
            "latest_fitness_score": 0.91,
            "latest_fitness_threshold": 0.7,
        }
        with (
            mock.patch.object(kernel, "_load_previous_cycle_signal", return_value=trigger_signal),
            mock.patch.object(kernel, "propose_mutation") as propose,
        ):
            result = kernel.run_cycle("agent-x")
        propose.assert_not_called()
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "mutation_not_triggered_policy")
        self.assertEqual(result["trigger_evidence"]["trigger_reason"], "healthy_no_trigger")

    def test_run_cycle_rejects_when_agent_contract_missing_required_function(self) -> None:
        kernel = EvolutionKernel(agents_root=self.agents_root, lineage_dir=self.lineage_dir, compatibility_adapter=mock.Mock())
        (self.agent_dir / "__init__.py").write_text(
            """
AGENT_ID = "agent-x"
VERSION = "1.0.0"
CAPABILITIES = []
GOAL_SCHEMA = {}
OUTPUT_SCHEMA = {}
SPAWN_POLICY = {}

def get_agent_manifest() -> dict:
    return {}

def run_goal(goal) -> dict:
    return {"goal": goal}

def info() -> dict:
    return {"agent": "agent-x"}

def run(input=None) -> dict:
    return {"input": input}

def score(output: dict) -> float:
    return 1.0
""",
            encoding="utf-8",
        )

        with (
            mock.patch("runtime.evolution.evolution_kernel.metrics.log") as metrics_log,
            mock.patch.object(kernel, "propose_mutation") as propose,
        ):
            result = kernel.run_cycle("agent-x")

        propose.assert_not_called()
        metrics_log.assert_called_once()
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason"], "agent_contract_violation")
        self.assertEqual(result["violations"][0]["message"], "Missing mutate")

    def test_run_cycle_rejects_when_agent_contract_signature_mismatch(self) -> None:
        kernel = EvolutionKernel(agents_root=self.agents_root, lineage_dir=self.lineage_dir, compatibility_adapter=mock.Mock())
        (self.agent_dir / "__init__.py").write_text(
            """
AGENT_ID = "agent-x"
VERSION = "1.0.0"
CAPABILITIES = []
GOAL_SCHEMA = {}
OUTPUT_SCHEMA = {}
SPAWN_POLICY = {}

def get_agent_manifest() -> dict:
    return {}

def run_goal(goal) -> dict:
    return {"goal": goal}

def info() -> dict:
    return {"agent": "agent-x"}

def run(payload=None) -> dict:
    return {"input": payload}

def mutate(src: str) -> str:
    return src

def score(output: dict) -> float:
    return 1.0
""",
            encoding="utf-8",
        )

        with (
            mock.patch("runtime.evolution.evolution_kernel.metrics.log") as metrics_log,
            mock.patch.object(kernel, "propose_mutation") as propose,
        ):
            result = kernel.run_cycle("agent-x")

        propose.assert_not_called()
        metrics_log.assert_called_once()
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason"], "agent_contract_violation")
        self.assertTrue(any(v["message"] == "def run(input=None) -> dict:" for v in result["violations"]))


if __name__ == "__main__":
    unittest.main()
