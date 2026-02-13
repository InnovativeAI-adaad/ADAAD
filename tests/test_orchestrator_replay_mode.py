# SPDX-License-Identifier: Apache-2.0

import unittest
from unittest import mock

from app.main import Orchestrator


class OrchestratorReplayModeTest(unittest.TestCase):
    @mock.patch.object(Orchestrator, "_register_elements")
    @mock.patch.object(Orchestrator, "_init_runtime")
    @mock.patch.object(Orchestrator, "_init_cryovant")
    @mock.patch.object(Orchestrator, "_health_check_architect")
    @mock.patch.object(Orchestrator, "_health_check_dream")
    @mock.patch.object(Orchestrator, "_health_check_beast")
    @mock.patch("app.main.run_gatekeeper", return_value={"ok": True})
    @mock.patch("app.main.dump")
    @mock.patch("app.main.journal.write_entry")
    def test_replay_mode_sets_verified_state(
        self,
        _journal,
        _dump,
        _gate,
        _beast,
        _dream,
        _architect,
        _cryovant,
        _runtime,
        _register,
    ) -> None:
        orch = Orchestrator(replay_mode=True)
        orch.evolution_runtime.verify_all_epochs = mock.Mock(return_value=True)
        orch.boot()
        self.assertEqual(orch.state["status"], "replay_verified")

    @mock.patch.object(Orchestrator, "_register_elements")
    @mock.patch.object(Orchestrator, "_init_runtime")
    @mock.patch.object(Orchestrator, "_init_cryovant")
    @mock.patch.object(Orchestrator, "_health_check_architect")
    @mock.patch.object(Orchestrator, "_health_check_dream")
    @mock.patch.object(Orchestrator, "_health_check_beast")
    @mock.patch("app.main.run_gatekeeper", return_value={"ok": True})
    @mock.patch("app.main.dump")
    @mock.patch("app.main.journal.write_entry")
    @mock.patch.object(Orchestrator, "_fail")
    def test_replay_strict_fails_closed_on_divergence(
        self,
        fail,
        _journal,
        _dump,
        _gate,
        _beast,
        _dream,
        _architect,
        _cryovant,
        _runtime,
        _register,
    ) -> None:
        orch = Orchestrator(replay_mode="strict")
        orch.evolution_runtime.verify_all_epochs = mock.Mock(return_value=False)
        orch.boot()
        fail.assert_called_once_with("replay_divergence")

    @mock.patch.object(Orchestrator, "_register_elements")
    @mock.patch.object(Orchestrator, "_init_runtime")
    @mock.patch.object(Orchestrator, "_init_cryovant")
    @mock.patch.object(Orchestrator, "_health_check_architect")
    @mock.patch.object(Orchestrator, "_health_check_dream")
    @mock.patch.object(Orchestrator, "_health_check_beast")
    @mock.patch("app.main.run_gatekeeper", return_value={"ok": True})
    @mock.patch("app.main.dump")
    @mock.patch("app.main.journal.write_entry")
    @mock.patch.object(Orchestrator, "_fail")
    def test_replay_full_sets_warning_without_exit(
        self,
        fail,
        _journal,
        _dump,
        _gate,
        _beast,
        _dream,
        _architect,
        _cryovant,
        _runtime,
        _register,
    ) -> None:
        orch = Orchestrator(replay_mode="full")
        orch.evolution_runtime.verify_all_epochs = mock.Mock(return_value=False)
        orch.boot()
        fail.assert_not_called()
        self.assertEqual(orch.state["status"], "replay_warning")
        self.assertTrue(orch.state.get("replay_divergence"))


if __name__ == "__main__":
    unittest.main()
