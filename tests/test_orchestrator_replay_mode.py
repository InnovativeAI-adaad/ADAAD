import pytest
pytestmark = pytest.mark.regression_standard
# SPDX-License-Identifier: Apache-2.0

import contextlib
import os
import unittest
from unittest import mock

from app.main import (
    Orchestrator,
    _apply_governance_ci_mode_defaults,
    _governance_ci_mode_enabled,
    _read_adaad_version,
    main,
)
from runtime.evolution.checkpoint_verifier import CheckpointVerificationError
from runtime.evolution.replay_mode import ReplayMode, normalize_replay_mode, parse_replay_args


class ADAADVersionReadTest(unittest.TestCase):
    def test_returns_unknown_when_version_read_fails_decode(self) -> None:
        with mock.patch("pathlib.Path.read_text", side_effect=UnicodeDecodeError("utf-8", b"\x80", 0, 1, "invalid start byte")):
            self.assertEqual(_read_adaad_version(), "unknown")

    def test_returns_unknown_when_read_text_result_cannot_be_stripped(self) -> None:
        with mock.patch("pathlib.Path.read_text", return_value=None):
            self.assertEqual(_read_adaad_version(), "unknown")




class ReplayModeNormalizationTest(unittest.TestCase):
    def test_legacy_aliases_are_supported(self) -> None:
        self.assertEqual(normalize_replay_mode(True), ReplayMode.AUDIT)
        self.assertEqual(normalize_replay_mode(False), ReplayMode.OFF)
        self.assertEqual(normalize_replay_mode("full"), ReplayMode.AUDIT)
        self.assertEqual(normalize_replay_mode("audit"), ReplayMode.AUDIT)
        self.assertEqual(normalize_replay_mode("strict"), ReplayMode.STRICT)
        self.assertEqual(normalize_replay_mode("on"), ReplayMode.AUDIT)
        self.assertEqual(normalize_replay_mode("yes"), ReplayMode.AUDIT)




class ReplayModePropertiesTest(unittest.TestCase):
    def test_should_verify_property(self) -> None:
        self.assertTrue(ReplayMode.AUDIT.should_verify)
        self.assertTrue(ReplayMode.STRICT.should_verify)
        self.assertFalse(ReplayMode.OFF.should_verify)


class ReplayModeArgParsingTest(unittest.TestCase):
    def test_parse_replay_args(self) -> None:
        self.assertEqual(parse_replay_args("audit", "epoch-1"), (ReplayMode.AUDIT, "epoch-1"))
        self.assertEqual(parse_replay_args(False), (ReplayMode.OFF, ""))

class OrchestratorReplayModeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._mutation_executor_patch = mock.patch("app.main.MutationExecutor")
        self._mutation_executor_patch.start()
        self._default_provider_patch = mock.patch("app.main.default_provider", return_value=mock.Mock(deterministic=True))
        self._default_provider_patch.start()

    def tearDown(self) -> None:
        self._default_provider_patch.stop()
        self._mutation_executor_patch.stop()

    @contextlib.contextmanager
    def _boot_context(self):
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(Orchestrator, "_register_elements"))
            stack.enter_context(mock.patch("app.main.DreamMode"))
            stack.enter_context(mock.patch("app.main.BeastModeLoop"))
            stack.enter_context(mock.patch("app.main.evaluate_boot_invariants", return_value=mock.Mock(ok=True, payload={"event_type": "boot_invariant_evaluation.v1"})))
            stack.enter_context(mock.patch("app.main.validate_agent_contract_preflight", return_value={"ok": True, "checked_modules": 2, "failing_modules": []}))
            stack.enter_context(mock.patch.object(Orchestrator, "_verify_checkpoint_chain"))
            stack.enter_context(mock.patch.object(Orchestrator, "_health_check_architect"))
            stack.enter_context(mock.patch.object(Orchestrator, "_health_check_dream"))
            stack.enter_context(mock.patch.object(Orchestrator, "_health_check_beast"))
            stack.enter_context(mock.patch.object(Orchestrator, "_governance_gate", return_value=True))
            dump = stack.enter_context(mock.patch("app.main.dump"))
            stack.enter_context(mock.patch("app.main.journal.write_entry"))
            stack.enter_context(mock.patch.object(Orchestrator, "_register_capabilities"))
            stack.enter_context(mock.patch.object(Orchestrator, "_init_ui"))
            stack.enter_context(mock.patch("app.main.metrics.log"))
            stack.enter_context(
                mock.patch.dict(
                    os.environ,
                    {
                        "ADAAD_FORCE_DETERMINISTIC_PROVIDER": "1",
                        "ADAAD_DETERMINISTIC_SEED": "orchestrator-test-seed",
                        "ADAAD_DISABLE_MUTABLE_FS": "1",
                        "ADAAD_DISABLE_NETWORK": "1",
                    },
                    clear=False,
                )
            )
            yield dump



    def test_boot_orders_checkpoint_stage_after_cryovant_before_replay_preflight(self) -> None:
        call_order: list[str] = []

        def _mark(name: str):
            def _inner(*args, **kwargs):
                call_order.append(name)
                return None

            return _inner

        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(Orchestrator, "_register_elements"))
            stack.enter_context(mock.patch("app.main.DreamMode"))
            stack.enter_context(mock.patch("app.main.BeastModeLoop"))
            stack.enter_context(mock.patch("app.main.evaluate_boot_invariants", return_value=mock.Mock(ok=True, payload={"event_type": "boot_invariant_evaluation.v1"})))
            stack.enter_context(mock.patch("app.main.validate_agent_contract_preflight", return_value={"ok": True, "checked_modules": 2, "failing_modules": []}))
            stack.enter_context(mock.patch.object(Orchestrator, "_verify_checkpoint_chain", side_effect=_mark("checkpoint")))
            stack.enter_context(mock.patch.object(Orchestrator, "_health_check_architect"))
            stack.enter_context(mock.patch.object(Orchestrator, "_health_check_dream"))
            stack.enter_context(mock.patch.object(Orchestrator, "_health_check_beast"))
            stack.enter_context(mock.patch.object(Orchestrator, "_run_replay_preflight", side_effect=_mark("replay_preflight")))
            stack.enter_context(mock.patch.object(Orchestrator, "_governance_gate", return_value=True))
            stack.enter_context(mock.patch("app.main.dump"))
            stack.enter_context(mock.patch("app.main.journal.write_entry"))
            stack.enter_context(mock.patch.object(Orchestrator, "_register_capabilities"))
            stack.enter_context(mock.patch.object(Orchestrator, "_init_ui"))
            stack.enter_context(mock.patch("app.main.metrics.log"))
            orch = Orchestrator(replay_mode="off")
            orch.boot()

        self.assertEqual(call_order[:2], ["checkpoint", "replay_preflight"])



    def test_boot_fail_closed_emits_machine_readable_payload(self) -> None:
        failure = mock.Mock(
            ok=False,
            reason="invariants_failed:missing_required_invariant",
            payload={
                "event_type": "boot_invariant_evaluation.v1",
                "status": "error",
                "reason_code": "boot_invariant_governance_invariants_failed",
            },
        )
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, {"ADAAD_FORCE_DETERMINISTIC_PROVIDER": "1"}, clear=False))
            stack.enter_context(mock.patch("app.main.evaluate_boot_invariants", return_value=failure))
            fail = stack.enter_context(mock.patch.object(Orchestrator, "_fail", side_effect=SystemExit(1)))
            stack.enter_context(mock.patch("app.main.metrics.log"))
            orch = Orchestrator(replay_mode="strict")
            with self.assertRaises(SystemExit):
                orch.boot()

        fail.assert_called_once_with(
            "invariants_failed:missing_required_invariant",
            payload={
                "event_type": "boot_invariant_evaluation.v1",
                "status": "error",
                "reason_code": "boot_invariant_governance_invariants_failed",
            },
        )

    def test_boot_fail_closed_on_agent_contract_preflight_failure(self) -> None:
        preflight_failure = {
            "ok": False,
            "checked_modules": 3,
            "failing_modules": [
                {
                    "module": "adaad/agents/sample_agent.py",
                    "ok": False,
                    "violations": [{"code": "signature_mismatch", "message": "def run(input=None) -> dict:"}],
                }
            ],
        }
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, {"ADAAD_FORCE_DETERMINISTIC_PROVIDER": "1"}, clear=False))
            stack.enter_context(mock.patch("app.main.evaluate_boot_invariants", return_value=mock.Mock(ok=True, payload={})))
            stack.enter_context(mock.patch("app.main.validate_agent_contract_preflight", return_value=preflight_failure))
            fail = stack.enter_context(mock.patch.object(Orchestrator, "_fail", side_effect=SystemExit(1)))
            stack.enter_context(mock.patch("app.main.metrics.log"))
            orch = Orchestrator(replay_mode="strict")
            with self.assertRaises(SystemExit):
                orch.boot()

        fail.assert_called_once()
        fail_reason = fail.call_args.args[0]
        fail_payload = fail.call_args.kwargs.get("payload", {})
        self.assertEqual(fail_reason, "agent_contract_preflight_failed")
        self.assertEqual(fail_payload.get("blocked_agent_ids"), ["sample_agent"])

    def test_boot_records_agent_contract_preflight_on_success(self) -> None:
        with self._boot_context():
            orch = Orchestrator(replay_mode="off")
            orch.evolution_runtime.replay_preflight = mock.Mock(return_value={
                "mode": "off",
                "verify_target": "none",
                "has_divergence": False,
                "decision": "skip",
                "results": [],
            })
            orch.boot()

        self.assertEqual(orch.state["agent_contract_preflight"]["ok"], True)
        self.assertEqual(orch.state["agent_contract_preflight"]["blocked_agent_ids"], [])

    def test_replay_off_skips_verification_and_continues_to_ready(self) -> None:
        with self._boot_context():
            orch = Orchestrator(replay_mode="off")
            orch.evolution_runtime.replay_preflight = mock.Mock(return_value={
                "mode": "off",
                "verify_target": "none",
                "has_divergence": False,
                "decision": "skip",
                "results": [],
            })
            orch.boot()
            self.assertEqual(orch.state["status"], "ready")
            orch.evolution_runtime.replay_preflight.assert_called_once()

    @mock.patch.object(Orchestrator, "_fail")
    def test_replay_audit_continues_on_divergence(self, fail: mock.Mock) -> None:
        with self._boot_context():
            orch = Orchestrator(replay_mode="audit")
            orch.evolution_runtime.replay_preflight = mock.Mock(return_value={
                "mode": "audit",
                "verify_target": "all_epochs",
                "has_divergence": True,
                "decision": "continue",
                "results": [{"baseline_epoch": "epoch-1", "expected_digest": "a", "actual_digest": "b", "decision": "diverge", "passed": False}],
            })
            orch.boot()
            fail.assert_not_called()
            self.assertEqual(orch.state["status"], "ready")
            self.assertTrue(orch.state["replay_divergence"])

    @mock.patch.object(Orchestrator, "_fail")
    def test_replay_strict_fails_on_divergence(self, fail: mock.Mock) -> None:
        with self._boot_context():
            orch = Orchestrator(replay_mode="strict")
            orch.evolution_runtime.replay_preflight = mock.Mock(return_value={
                "mode": "strict",
                "verify_target": "all_epochs",
                "has_divergence": True,
                "decision": "fail_closed",
                "fail_closed_payload": {"schema_version": "replay_fail_closed_decision.v1", "reason_code": "hash_mismatch"},
                "results": [{"baseline_epoch": "epoch-1", "expected_digest": "a", "actual_digest": "b", "decision": "diverge", "passed": False}],
            })
            orch.boot()
            fail.assert_called_once()
            self.assertEqual(fail.call_args.args[0], "replay_divergence")
            self.assertIn("artifacts", fail.call_args.kwargs.get("payload", {}))
            self.assertEqual(fail.call_args.kwargs["payload"]["decision_payload"]["reason_code"], "hash_mismatch")

    @mock.patch("app.orchestration.replay_preflight.build_replay_divergence_artifacts")
    @mock.patch.object(Orchestrator, "_fail")
    def test_replay_strict_records_divergence_artifact_paths(self, fail: mock.Mock, build_artifacts: mock.Mock) -> None:
        build_artifacts.return_value = mock.Mock(
            artifact_dir="security/replay_artifacts/replay_divergence_1",
            machine_report_path="security/replay_artifacts/replay_divergence_1/replay_divergence_report.json",
            human_report_path="security/replay_artifacts/replay_divergence_1/replay_divergence_report.md",
        )
        with self._boot_context():
            orch = Orchestrator(replay_mode="strict", replay_epoch="epoch-1")
            orch.evolution_runtime.replay_preflight = mock.Mock(return_value={
                "mode": "strict",
                "verify_target": "single_epoch",
                "has_divergence": True,
                "decision": "fail_closed",
                "results": [{"epoch_id": "epoch-1", "expected_digest": "a", "actual_digest": "b", "decision": "diverge", "passed": False}],
            })
            orch.boot()

            build_artifacts.assert_called_once()
            self.assertEqual(build_artifacts.call_args.kwargs["replay_command"], "python -m app.main --verify-replay --replay strict --replay-epoch epoch-1")
            fail.assert_called_once()
            payload = fail.call_args.kwargs.get("payload", {})
            self.assertEqual(payload["artifacts"]["machine_report"], "security/replay_artifacts/replay_divergence_1/replay_divergence_report.json")

    def test_verify_replay_only_exits_after_preflight(self) -> None:
        with self._boot_context() as dump:
            orch = Orchestrator(replay_mode="audit")
            orch.evolution_runtime.replay_preflight = mock.Mock(return_value={
                "mode": "audit",
                "verify_target": "all_epochs",
                "has_divergence": False,
                "decision": "continue",
                "results": [],
            })
            orch.verify_replay_only()
            dump.assert_called_once()


class OrchestratorCheckpointStageTest(unittest.TestCase):
    def setUp(self) -> None:
        self._mutation_executor_patch = mock.patch("app.main.MutationExecutor")
        self._mutation_executor_patch.start()
        self._default_provider_patch = mock.patch("app.main.default_provider", return_value=mock.Mock(deterministic=True))
        self._default_provider_patch.start()

    def tearDown(self) -> None:
        self._default_provider_patch.stop()
        self._mutation_executor_patch.stop()

    def test_checkpoint_stage_emits_verified_event_on_success(self) -> None:
        orch = Orchestrator(replay_mode="off")
        with mock.patch("app.main.CheckpointVerifier.verify_all_checkpoints", return_value={"epoch_count": 1, "checkpoint_count": 2}) as verify:
            with mock.patch("app.main.journal.write_entry") as write_entry:
                orch._verify_checkpoint_chain()

        verify.assert_called_once_with(orch.evolution_runtime.ledger.ledger_path)
        write_entry.assert_called_once()
        self.assertEqual(write_entry.call_args.kwargs["action"], "checkpoint_chain_verified")

    def test_checkpoint_stage_emits_violated_event_and_fails_closed(self) -> None:
        orch = Orchestrator(replay_mode="off")
        with mock.patch(
            "app.main.CheckpointVerifier.verify_all_checkpoints",
            side_effect=CheckpointVerificationError(code="checkpoint_prev_missing", detail="epoch=e1;index=1"),
        ):
            with mock.patch("app.main.journal.write_entry") as write_entry:
                with mock.patch.object(orch, "_fail") as fail:
                    orch._verify_checkpoint_chain()

        self.assertEqual(write_entry.call_args.kwargs["action"], "checkpoint_chain_violated")
        fail.assert_called_once_with("checkpoint_chain_violated:checkpoint_prev_missing:epoch=e1;index=1")


class GovernanceCIModeTest(unittest.TestCase):
    def test_governance_ci_mode_env_toggle(self) -> None:
        with mock.patch.dict(os.environ, {"ADAAD_GOVERNANCE_CI_MODE": "1"}, clear=False):
            self.assertTrue(_governance_ci_mode_enabled())

    def test_apply_governance_ci_mode_defaults_sets_provider_env(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            _apply_governance_ci_mode_defaults()
            self.assertEqual(os.getenv("ADAAD_FORCE_DETERMINISTIC_PROVIDER"), "1")
            self.assertEqual(os.getenv("ADAAD_DETERMINISTIC_SEED"), "adaad-governance-ci")



class OrchestratorDreamHealthMetricsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._mutation_executor_patch = mock.patch("app.main.MutationExecutor")
        self._mutation_executor_patch.start()
        self._default_provider_patch = mock.patch("app.main.default_provider", return_value=mock.Mock(deterministic=True))
        self._default_provider_patch.start()

    def tearDown(self) -> None:
        self._default_provider_patch.stop()
        self._mutation_executor_patch.stop()

    def test_health_check_dream_logs_summary_for_ready_transition(self) -> None:
        orch = Orchestrator(replay_mode="off")
        orch.dream = mock.Mock()
        orch.dream.discover_tasks.return_value = ["task-a", "task-b"]
        orch.mutation_orchestrator = mock.Mock()
        orch.mutation_orchestrator.evaluate_dream_tasks.return_value = mock.Mock(
            status="ok",
            reason="tasks_ready",
            payload={"safe_boot": False, "task_count": 2},
        )

        with mock.patch("app.main.metrics.log") as log_metric:
            orch._health_check_dream()

        self.assertTrue(orch.state["mutation_enabled"])
        self.assertFalse(orch.state["safe_boot"])
        log_metric.assert_called_once_with(
            event_type="dream_health_ok",
            payload={"tasks": ["task-a", "task-b"]},
            level="INFO",
        )

    def test_health_check_dream_logs_summary_for_safe_boot_transition(self) -> None:
        orch = Orchestrator(replay_mode="off")
        orch.dream = mock.Mock()
        orch.dream.discover_tasks.return_value = []
        orch.mutation_orchestrator = mock.Mock()
        orch.mutation_orchestrator.evaluate_dream_tasks.return_value = mock.Mock(
            status="warn",
            reason="no_tasks",
            payload={"safe_boot": True},
        )

        with mock.patch("app.main.metrics.log") as log_metric:
            orch._health_check_dream()

        self.assertFalse(orch.state["mutation_enabled"])
        self.assertTrue(orch.state["safe_boot"])
        log_metric.assert_called_once_with(
            event_type="dream_safe_boot",
            payload={"reason": "no tasks"},
            level="WARN",
        )


class OrchestratorFailEnvelopeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._mutation_executor_patch = mock.patch("app.main.MutationExecutor")
        self._mutation_executor_patch.start()
        self._default_provider_patch = mock.patch("app.main.default_provider", return_value=mock.Mock(deterministic=True))
        self._default_provider_patch.start()

    def tearDown(self) -> None:
        self._default_provider_patch.stop()
        self._mutation_executor_patch.stop()

    def test_fail_emits_structured_envelope_when_journal_and_dump_fail(self) -> None:
        orch = Orchestrator(replay_mode="off")
        with contextlib.ExitStack() as stack:
            log_metric = stack.enter_context(mock.patch("app.main.metrics.log"))
            stack.enter_context(mock.patch("app.main.journal.ensure_ledger", side_effect=RuntimeError("ledger down")))
            stack.enter_context(mock.patch("app.main.dump", side_effect=RuntimeError("dump down")))
            stack.enter_context(mock.patch("sys.stderr.write"))
            with self.assertRaises(SystemExit):
                orch._fail("checkpoint_chain_violated:missing_previous")

        self.assertEqual(orch.state["reason_code"], "checkpoint_chain_violated")
        envelope = orch.state["failure_envelope"]
        self.assertEqual(envelope["event_type"], "orchestrator_failure_envelope.v1")
        self.assertEqual(envelope["journal_write_status"], "failed")
        self.assertEqual(envelope["dump_status"], "failed")
        self.assertEqual(envelope["fallback_stderr_status"], "not_needed")
        self.assertEqual(
            envelope["failure_chain"],
            [
                {
                    "step": "journal_write",
                    "reason_code": "orchestrator_failure_journal_write_failed",
                    "error": "RuntimeError:ledger down",
                },
                {
                    "step": "dump",
                    "reason_code": "orchestrator_failure_dump_failed",
                    "error": "RuntimeError:dump down",
                },
            ],
        )
        self.assertTrue(
            any(
                call.kwargs.get("event_type") == "orchestrator_failure_envelope"
                and call.kwargs.get("payload", {}).get("primary_reason_code") == "checkpoint_chain_violated"
                for call in log_metric.mock_calls
            )
        )


class ReplayProofExportCliTest(unittest.TestCase):
    def test_export_replay_proof_uses_epoch_flag_and_deterministic_path(self) -> None:
        fake_builder = mock.Mock()
        fake_builder.write_bundle.return_value = mock.Mock(as_posix=mock.Mock(return_value="security/ledger/replay_proofs/epoch-42.replay_attestation.v1.json"))
        with mock.patch("app.orchestration.cli_handlers.ReplayProofBuilder", return_value=fake_builder):
            with mock.patch("sys.argv", ["app.main", "--export-replay-proof", "--epoch", "epoch-42"]):
                with mock.patch("builtins.print") as printer:
                    main()
        fake_builder.write_bundle.assert_called_once_with("epoch-42")
        printer.assert_called_once_with("security/ledger/replay_proofs/epoch-42.replay_attestation.v1.json")

    def test_export_replay_proof_requires_epoch(self) -> None:
        with mock.patch("sys.argv", ["app.main", "--export-replay-proof"]):
            with self.assertRaises(SystemExit):
                main()


class AdaadStatusCliTest(unittest.TestCase):
    def test_adaad_status_prints_table_and_json_and_skips_boot(self) -> None:
        report = mock.Mock()
        with mock.patch("app.orchestration.cli_handlers.build_status_report", return_value=report) as build:
            with mock.patch("app.orchestration.cli_handlers.render_human_table", return_value="TABLE") as table:
                with mock.patch("app.orchestration.cli_handlers.report_as_json", return_value='{"status":"ok"}') as as_json:
                    with mock.patch("app.main.Orchestrator") as orchestrator_cls:
                        with mock.patch("sys.argv", ["app.main", "--adaad-status", "--status-format", "both", "--trigger-mode", "DEVADAAD"]):
                            with mock.patch("builtins.print") as printer:
                                main()
        build.assert_called_once()
        table.assert_called_once_with(report)
        as_json.assert_called_once_with(report)
        orchestrator_cls.assert_not_called()
        printer.assert_has_calls([mock.call("TABLE"), mock.call(), mock.call('{"status":"ok"}')])


class AdaadRunbookCliTest(unittest.TestCase):
    def test_adaad_runbook_exports_and_skips_boot(self) -> None:
        fake_artifacts = mock.Mock()
        with mock.patch("app.orchestration.cli_handlers.export_runbook_artifacts", return_value=fake_artifacts) as export_runbook:
            with mock.patch("app.orchestration.cli_handlers.render_runbook_summary", return_value="RUNBOOK-SUMMARY") as render_summary:
                with mock.patch("app.main.Orchestrator") as orchestrator_cls:
                    with mock.patch(
                        "sys.argv",
                        [
                            "app.main",
                            "--adaad-runbook",
                            "--runbook-verbosity",
                            "full_governance",
                            "--runbook-output-dir",
                            "security/custom",
                            "--trigger-mode",
                            "DEVADAAD",
                        ],
                    ):
                        with mock.patch("builtins.print") as printer:
                            main()
        export_runbook.assert_called_once()
        render_summary.assert_called_once_with(fake_artifacts)
        orchestrator_cls.assert_not_called()
        printer.assert_called_once_with("RUNBOOK-SUMMARY")


class ReplayNamespaceCliTest(unittest.TestCase):
    def test_replay_verify_emits_deterministic_json(self) -> None:
        fake_runtime = mock.Mock()
        fake_runtime.replay_preflight.return_value = {
            "mode": "strict",
            "verify_target": "single_epoch",
            "has_divergence": False,
            "decision": "continue",
            "results": [],
        }
        with mock.patch("app.orchestration.cli_handlers.EvolutionRuntime", return_value=fake_runtime):
            with mock.patch("sys.argv", ["app.main", "replay", "verify", "--epoch", "epoch-1", "--mode", "strict"]):
                with mock.patch("builtins.print") as printer:
                    main()
        emitted = printer.call_args.args[0]
        payload = __import__("json").loads(emitted)
        self.assertEqual(payload["schema_version"], "replay_cli.verify.v1")
        self.assertEqual(payload["command"], "verify")
        self.assertEqual(payload["epoch"], "epoch-1")

    def test_replay_bundle_accepts_pr_id_epoch_resolution(self) -> None:
        fake_ledger = mock.Mock()
        fake_ledger.list_epoch_ids.return_value = ["epoch-1"]
        fake_ledger.read_epoch.return_value = [{"payload": {"pr_id": "PR-123"}}]

        fake_runtime = mock.Mock()
        fake_runtime.ledger = fake_ledger

        fake_builder = mock.Mock()
        fake_builder.write_bundle.return_value = mock.Mock(as_posix=mock.Mock(return_value="security/ledger/replay_proofs/epoch-1.replay_attestation.v1.json"))

        with mock.patch("app.orchestration.cli_handlers.EvolutionRuntime", return_value=fake_runtime):
            with mock.patch("app.orchestration.cli_handlers.ReplayProofBuilder", return_value=fake_builder):
                with mock.patch("sys.argv", ["app.main", "replay", "bundle", "--pr-id", "PR-123"]):
                    with mock.patch("builtins.print") as printer:
                        main()

        fake_builder.write_bundle.assert_called_once_with("epoch-1")
        payload = __import__("json").loads(printer.call_args.args[0])
        self.assertEqual(payload["epoch"], "epoch-1")
        self.assertEqual(payload["pr_id"], "PR-123")


if __name__ == "__main__":
    unittest.main()
