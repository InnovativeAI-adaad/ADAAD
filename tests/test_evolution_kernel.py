# SPDX-License-Identifier: Apache-2.0

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runtime.evolution.evolution_kernel import EvolutionKernel


class EvolutionKernelTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.agents_root = Path(self.tmp.name) / "app" / "agents"
        self.lineage_dir = self.agents_root / "lineage"
        self.agent_dir = self.agents_root / "agent-x"
        self.agent_dir.mkdir(parents=True, exist_ok=True)
        self.lineage_dir.mkdir(parents=True, exist_ok=True)
        (self.agent_dir / "meta.json").write_text(json.dumps({"name": "agent-x"}), encoding="utf-8")
        (self.agent_dir / "dna.json").write_text(json.dumps({"traits": []}), encoding="utf-8")
        (self.agent_dir / "certificate.json").write_text(json.dumps({"signature": "cryovant-dev-seed"}), encoding="utf-8")

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
            mock.patch.object(kernel, "propose_mutation", return_value={"request": {"agent_id": "agent-x", "ops": [{"op": "dna.add_trait"}]}}),
            mock.patch.object(kernel, "validate_mutation", return_value={"valid": True, "policy_valid": True, "mutation_has_ops": True, "errors": []}),
            mock.patch.object(kernel, "execute_in_sandbox", return_value={"status": "applied", "mutation_id": "m-1"}) as execute,
            mock.patch.object(kernel, "evaluate_fitness", return_value={"score": 0.9, "passed": True}) as evaluate,
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

    def test_run_cycle_resolves_agent_paths_before_membership_check(self) -> None:
        alias_root = self.agents_root / ".." / "agents"
        kernel = EvolutionKernel(agents_root=alias_root, lineage_dir=self.lineage_dir, compatibility_adapter=mock.Mock())

        with (
            mock.patch("runtime.evolution.evolution_kernel.iter_agent_dirs", return_value=[self.agent_dir.resolve()]),
            mock.patch.object(kernel, "propose_mutation", return_value={"request": {"agent_id": "agent-x", "ops": [{"op": "dna.add_trait"}]}}),
            mock.patch.object(kernel, "validate_mutation", return_value={"valid": True, "policy_valid": True, "mutation_has_ops": True, "errors": []}),
            mock.patch.object(kernel, "execute_in_sandbox", return_value={"status": "applied", "mutation_id": "m-2"}),
            mock.patch.object(kernel, "evaluate_fitness", return_value={"score": 0.8, "passed": True}),
            mock.patch.object(kernel, "sign_certificate", return_value={"certificate_id": "c-2"}),
        ):
            result = kernel.run_cycle("agent-x")

        self.assertEqual(result["agent_id"], "agent-x")
        self.assertTrue(result["kernel_path"])



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

    def test_run_cycle_rejects_missing_agent(self) -> None:
        kernel = EvolutionKernel(agents_root=self.agents_root, lineage_dir=self.lineage_dir, compatibility_adapter=mock.Mock())
        with self.assertRaisesRegex(RuntimeError, "agent_not_found:missing"):
            kernel.run_cycle("missing")


    def test_run_cycle_skips_pipeline_for_non_functional_change(self) -> None:
        adapter = mock.Mock()
        kernel = EvolutionKernel(agents_root=self.agents_root, lineage_dir=self.lineage_dir, compatibility_adapter=adapter)

        with (
            mock.patch.object(kernel, "propose_mutation", return_value={"request": {"agent_id": "agent-x", "ops": [{"op": "set", "path": "/last_mutation", "value": "x"}]}}),
            mock.patch("runtime.evolution.evolution_kernel.classify_mutation_change") as classify,
            mock.patch("runtime.evolution.evolution_kernel.apply_metadata_updates", return_value={"mutation_count": 2, "version": 3, "last_mutation": "2025-01-01T00:00:00Z"}) as metadata,
            mock.patch.object(kernel, "execute_in_sandbox") as execute,
            mock.patch.object(kernel, "evaluate_fitness") as evaluate,
            mock.patch.object(kernel, "sign_certificate") as sign,
        ):
            classify.return_value = mock.Mock(classification="NON_FUNCTIONAL_CHANGE", run_mutation=False, reason="allowed_metadata_only")
            result = kernel.run_cycle("agent-x")

        metadata.assert_called_once()
        execute.assert_not_called()
        evaluate.assert_not_called()
        sign.assert_not_called()
        self.assertEqual(result["status"], "metadata_only")
        self.assertEqual(result["change_classification"], "NON_FUNCTIONAL_CHANGE")


if __name__ == "__main__":
    unittest.main()
