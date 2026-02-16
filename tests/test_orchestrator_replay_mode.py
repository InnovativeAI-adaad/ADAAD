# SPDX-License-Identifier: Apache-2.0

import contextlib
import os
import unittest
from unittest import mock

from app.main import Orchestrator
from runtime.evolution.replay_mode import ReplayMode, normalize_replay_mode, parse_replay_args


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
    @contextlib.contextmanager
    def _boot_context(self):
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(Orchestrator, "_register_elements"))
            stack.enter_context(mock.patch.object(Orchestrator, "_init_runtime"))
            stack.enter_context(mock.patch.object(Orchestrator, "_init_cryovant"))
            stack.enter_context(mock.patch.object(Orchestrator, "_health_check_architect"))
            stack.enter_context(mock.patch.object(Orchestrator, "_health_check_dream"))
            stack.enter_context(mock.patch.object(Orchestrator, "_health_check_beast"))
            stack.enter_context(mock.patch("app.main.run_gatekeeper", return_value={"ok": True}))
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
                    },
                    clear=False,
                )
            )
            yield dump

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
                "results": [{"baseline_epoch": "epoch-1", "expected_digest": "a", "actual_digest": "b", "decision": "diverge", "passed": False}],
            })
            orch.boot()
            fail.assert_called_once_with("replay_divergence")

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


if __name__ == "__main__":
    unittest.main()
