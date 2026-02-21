# SPDX-License-Identifier: Apache-2.0
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import fcntl

from app.agents.base_agent import stage_offspring
from app.beast_mode_loop import BeastModeLoop
from runtime import capability_graph, metrics
from runtime.autonomy.mutation_scaffold import MutationCandidate, rank_mutation_candidates
from runtime.manifest.generator import generate_tool_manifest
from security.ledger import journal


class _FakeClock:
    def __init__(self, wall: float = 0.0, monotonic: float = 0.0) -> None:
        self.wall = wall
        self.monotonic = monotonic

    def wall_time(self) -> float:
        return self.wall

    def monotonic_time(self) -> float:
        return self.monotonic

    def jump(self, *, wall_delta: float = 0.0, monotonic_delta: float = 0.0) -> None:
        self.wall += wall_delta
        self.monotonic += monotonic_delta




class BeastPromotionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._orig_metrics_path = metrics.METRICS_PATH
        metrics.METRICS_PATH = Path(self.tmp.name) / "metrics.jsonl"
        self.addCleanup(setattr, metrics, "METRICS_PATH", self._orig_metrics_path)

        self._orig_capabilities_path = capability_graph.CAPABILITIES_PATH
        capability_graph.CAPABILITIES_PATH = Path(self.tmp.name) / "capabilities.json"
        self.addCleanup(setattr, capability_graph, "CAPABILITIES_PATH", self._orig_capabilities_path)

        self._orig_ledger_root = journal.LEDGER_ROOT
        self._orig_ledger_file = journal.LEDGER_FILE
        journal.LEDGER_ROOT = Path(self.tmp.name) / "ledger"
        journal.LEDGER_FILE = journal.LEDGER_ROOT / "lineage.jsonl"
        self.addCleanup(setattr, journal, "LEDGER_ROOT", self._orig_ledger_root)
        self.addCleanup(setattr, journal, "LEDGER_FILE", self._orig_ledger_file)

        self._orig_threshold = os.environ.get("ADAAD_FITNESS_THRESHOLD")
        os.environ["ADAAD_FITNESS_THRESHOLD"] = "0.1"
        self._orig_autonomy_threshold = os.environ.get("ADAAD_AUTONOMY_THRESHOLD")
        os.environ["ADAAD_AUTONOMY_THRESHOLD"] = "0.25"

        def _restore_threshold() -> None:
            if self._orig_threshold is None:
                os.environ.pop("ADAAD_FITNESS_THRESHOLD", None)
            else:
                os.environ["ADAAD_FITNESS_THRESHOLD"] = self._orig_threshold

        self.addCleanup(_restore_threshold)

        def _restore_autonomy_threshold() -> None:
            if self._orig_autonomy_threshold is None:
                os.environ.pop("ADAAD_AUTONOMY_THRESHOLD", None)
            else:
                os.environ["ADAAD_AUTONOMY_THRESHOLD"] = self._orig_autonomy_threshold

        self.addCleanup(_restore_autonomy_threshold)

    def _seed_agent(self) -> tuple[Path, Path, Path]:
        agents_root = Path(self.tmp.name) / "agents"
        lineage_dir = agents_root / "lineage"
        agent_dir = agents_root / "agentA"
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "meta.json").write_text(json.dumps({"name": "agentA"}), encoding="utf-8")
        (agent_dir / "dna.json").write_text(json.dumps({"seq": "abc"}), encoding="utf-8")
        (agent_dir / "certificate.json").write_text(json.dumps({"signature": "cryovant-dev-seed"}), encoding="utf-8")

        capability_graph.register_capability("orchestrator.boot", "0.1.0", 1.0, "test", identity=generate_tool_manifest(__name__, "orchestrator.boot", "0.1.0"))
        capability_graph.register_capability("cryovant.gate", "0.1.0", 1.0, "test", identity=generate_tool_manifest(__name__, "cryovant.gate", "0.1.0"))

        journal.ensure_ledger()
        journal.write_entry(agent_id="agentA", action="seed", payload={})
        return agents_root, lineage_dir, agent_dir

    @staticmethod
    def _update_staged_payload(staged: Path, **kwargs: object) -> None:
        payload = json.loads((staged / "mutation.json").read_text(encoding="utf-8"))
        payload.update(kwargs)
        (staged / "mutation.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def test_beast_promotes(self) -> None:
        agents_root, lineage_dir, _ = self._seed_agent()
        staged = stage_offspring("agentA", "mutate-me", lineage_dir)
        self._update_staged_payload(
            staged,
            mutation_id="m-autonomy-pass",
            expected_gain=0.8,
            risk_score=0.1,
            complexity=0.1,
            coverage_delta=0.3,
        )

        beast = BeastModeLoop(agents_root, lineage_dir)
        with mock.patch("app.beast_mode_loop.fitness.score_mutation", return_value=0.2):
            result = beast._legacy.run_cycle("agentA")

        self.assertEqual(result["status"], "promoted")
        promoted_path = Path(result["promoted_path"])
        self.assertTrue(promoted_path.exists())
        self.assertFalse(staged.exists())

        registry = capability_graph.get_capabilities()
        self.assertIn("agent.agentA.mutation_quality", registry)

    def test_beast_rejects_when_autonomy_score_below_threshold(self) -> None:
        agents_root, lineage_dir, _ = self._seed_agent()
        staged = stage_offspring("agentA", "mutate-me", lineage_dir)
        self._update_staged_payload(
            staged,
            mutation_id="m-autonomy-reject",
            expected_gain=0.2,
            risk_score=0.9,
            complexity=0.8,
            coverage_delta=0.0,
        )

        beast = BeastModeLoop(agents_root, lineage_dir)
        with mock.patch("app.beast_mode_loop.fitness.score_mutation", return_value=0.99):
            result = beast._legacy.run_cycle("agentA")

        self.assertEqual(result["status"], "discarded")
        self.assertFalse(staged.exists())

    def test_beast_falls_back_to_legacy_gate_when_candidate_features_missing(self) -> None:
        agents_root, lineage_dir, _ = self._seed_agent()
        staged = stage_offspring("agentA", "mutate-me", lineage_dir)
        self._update_staged_payload(staged, mutation_id="m-fallback")

        beast = BeastModeLoop(agents_root, lineage_dir)
        with mock.patch("app.beast_mode_loop.fitness.score_mutation", return_value=0.95):
            result = beast._legacy.run_cycle("agentA")

        self.assertEqual(result["status"], "promoted")
        metrics_rows = [json.loads(line) for line in metrics.METRICS_PATH.read_text(encoding="utf-8").splitlines()]
        fallback_rows = [row for row in metrics_rows if row.get("event") == "beast_autonomy_fallback"]
        self.assertTrue(fallback_rows)
        self.assertIn("expected_gain", fallback_rows[0]["payload"]["missing_candidate_fields"])

    def test_public_run_cycle_routes_through_kernel(self) -> None:
        agents_root, lineage_dir, _ = self._seed_agent()
        beast = BeastModeLoop(agents_root, lineage_dir)

        with mock.patch.object(beast._kernel, "run_cycle", return_value={"status": "kernel-routed"}) as kernel_run:
            result = beast.run_cycle("agentA")

        kernel_run.assert_called_once_with(agent_id="agentA")
        self.assertEqual(result["status"], "kernel-routed")

    def test_tie_breaking_by_mutation_id_is_deterministic(self) -> None:
        candidates = [
            MutationCandidate("mutation-z", expected_gain=0.8, risk_score=0.2, complexity=0.1, coverage_delta=0.1),
            MutationCandidate("mutation-a", expected_gain=0.8, risk_score=0.2, complexity=0.1, coverage_delta=0.1),
        ]

        ranked = rank_mutation_candidates(candidates, acceptance_threshold=0.25)

        self.assertEqual([item.mutation_id for item in ranked], ["mutation-a", "mutation-z"])

    def test_mutation_candidate_uses_canonical_payload_hash_when_mutation_id_missing(self) -> None:
        agents_root, lineage_dir, _ = self._seed_agent()
        staged = stage_offspring("agentA", "mutate-me", lineage_dir)
        self._update_staged_payload(
            staged,
            expected_gain=0.8,
            risk_score=0.1,
            complexity=0.2,
            coverage_delta=0.3,
        )

        beast = BeastModeLoop(agents_root, lineage_dir)
        payload = json.loads((staged / "mutation.json").read_text(encoding="utf-8"))
        candidate, missing_fields = beast._build_mutation_candidate(payload)

        self.assertEqual(missing_fields, [])
        self.assertIsNotNone(candidate)
        self.assertTrue(candidate.mutation_id.startswith("payload-"))

        payload_clone = dict(payload)
        candidate_clone, _ = beast._build_mutation_candidate(payload_clone)
        self.assertEqual(candidate_clone.mutation_id, candidate.mutation_id)


    def test_concurrent_run_cycle_updates_cycle_count_without_corrupting_state(self) -> None:
        agents_root, lineage_dir, _ = self._seed_agent()
        beast = BeastModeLoop(agents_root, lineage_dir)

        runs = 20
        barrier = threading.Barrier(runs)
        results: list[dict[str, object]] = []
        result_lock = threading.Lock()

        def _worker() -> None:
            barrier.wait()
            result = beast._legacy.run_cycle("agentA")
            with result_lock:
                results.append(result)

        threads = [threading.Thread(target=_worker) for _ in range(runs)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(results), runs)
        for result in results:
            self.assertIn(result["status"], {"no_staged", "throttled"})

        state_path = agents_root.parent / "data" / "beast_mode_state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(float(state["cycle_count"]), float(runs))

    def test_lock_contention_emits_metric_event(self) -> None:
        agents_root, lineage_dir, _ = self._seed_agent()
        self.addCleanup(os.environ.pop, "ADAAD_BEAST_STATE_LOCK_CONTENTION_SEC", None)
        os.environ["ADAAD_BEAST_STATE_LOCK_CONTENTION_SEC"] = "0.01"
        beast = BeastModeLoop(agents_root, lineage_dir)

        beast._legacy.state_lock_path.parent.mkdir(parents=True, exist_ok=True)
        with beast._legacy.state_lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)

            thread = threading.Thread(target=beast._legacy._check_limits)
            thread.start()
            time.sleep(0.05)
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            thread.join()

        metrics_rows = [json.loads(line) for line in metrics.METRICS_PATH.read_text(encoding="utf-8").splitlines()]
        contention_rows = [row for row in metrics_rows if row.get("event") == "beast_state_lock_contention"]
        self.assertTrue(contention_rows)

    def test_promotion_failure_rolls_back_certificate_and_keeps_staged(self) -> None:
        agents_root, lineage_dir, agent_dir = self._seed_agent()
        staged = stage_offspring("agentA", "mutate-me", lineage_dir)
        self._update_staged_payload(
            staged,
            mutation_id="m-promotion-failure",
            expected_gain=0.8,
            risk_score=0.1,
            complexity=0.1,
            coverage_delta=0.3,
        )
        cert_before = (agent_dir / "certificate.json").read_text(encoding="utf-8")

        beast = BeastModeLoop(agents_root, lineage_dir)
        with mock.patch("app.beast_mode_loop.fitness.score_mutation", return_value=0.95):
            with mock.patch("app.beast_mode_loop.promote_offspring", side_effect=RuntimeError("forced promotion failure")):
                with self.assertRaisesRegex(RuntimeError, "forced promotion failure"):
                    beast._legacy.run_cycle("agentA")

        self.assertTrue(staged.exists())
        self.assertEqual((agent_dir / "certificate.json").read_text(encoding="utf-8"), cert_before)

        ledger_rows = journal.read_entries(limit=50)
        actions = [row.get("action") for row in ledger_rows]
        self.assertIn("mutation_promotion_rollback", actions)
        self.assertNotIn("mutation_promoted", actions)

    def test_promotion_failure_does_not_leave_promoted_artifact(self) -> None:
        agents_root, lineage_dir, _ = self._seed_agent()
        staged = stage_offspring("agentA", "mutate-me", lineage_dir)
        self._update_staged_payload(
            staged,
            mutation_id="m-no-partial-promote",
            expected_gain=0.8,
            risk_score=0.1,
            complexity=0.1,
            coverage_delta=0.3,
        )

        beast = BeastModeLoop(agents_root, lineage_dir)
        with mock.patch("app.beast_mode_loop.fitness.score_mutation", return_value=0.95):
            with mock.patch("app.beast_mode_loop.promote_offspring", side_effect=RuntimeError("inject promotion fault")):
                with self.assertRaisesRegex(RuntimeError, "inject promotion fault"):
                    beast._legacy.run_cycle("agentA")

        promoted_path = lineage_dir / staged.name
        self.assertFalse(promoted_path.exists())
        self.assertTrue(staged.exists())

        metrics_rows = [json.loads(line) for line in metrics.METRICS_PATH.read_text(encoding="utf-8").splitlines()]
        rollback_rows = [row for row in metrics_rows if row.get("event") == "mutation_promotion_rollback"]
        self.assertTrue(rollback_rows)
        self.assertFalse(any(row.get("event") == "mutation_promoted" for row in metrics_rows))

    def test_throttle_uses_monotonic_cooldown_across_wall_clock_jumps(self) -> None:
        agents_root, lineage_dir, _ = self._seed_agent()
        os.environ["ADAAD_BEAST_CYCLE_BUDGET"] = "1"
        os.environ["ADAAD_BEAST_CYCLE_WINDOW_SEC"] = "200"
        os.environ["ADAAD_BEAST_COOLDOWN_SEC"] = "300"
        self.addCleanup(os.environ.pop, "ADAAD_BEAST_CYCLE_BUDGET", None)
        self.addCleanup(os.environ.pop, "ADAAD_BEAST_CYCLE_WINDOW_SEC", None)
        self.addCleanup(os.environ.pop, "ADAAD_BEAST_COOLDOWN_SEC", None)

        clock = _FakeClock(wall=1_000.0, monotonic=10_000.0)
        beast = BeastModeLoop(agents_root, lineage_dir)
        adapter = beast._legacy
        adapter._wall_time_provider = clock.wall_time
        adapter._monotonic_time_provider = clock.monotonic_time

        self.assertIsNone(adapter._check_limits())
        throttled = adapter._check_limits()
        self.assertEqual(throttled, {"status": "throttled", "reason": "cycle_budget"})

        clock.jump(wall_delta=-500.0, monotonic_delta=100.0)
        still_throttled = adapter._check_limits()
        self.assertEqual(still_throttled, {"status": "throttled", "reason": "cooldown"})

        clock.jump(wall_delta=5_000.0, monotonic_delta=300.0)
        self.assertIsNone(adapter._check_limits())

    def test_legacy_state_migrates_to_monotonic_fields(self) -> None:
        agents_root, lineage_dir, _ = self._seed_agent()
        clock = _FakeClock(wall=1_000.0, monotonic=2_000.0)
        beast = BeastModeLoop(agents_root, lineage_dir)
        adapter = beast._legacy
        adapter._wall_time_provider = clock.wall_time
        adapter._monotonic_time_provider = clock.monotonic_time

        legacy_state = {
            "cycle_window_start": 900.0,
            "cycle_count": 1.0,
            "mutation_window_start": 900.0,
            "mutation_count": 2.0,
            "cooldown_until": 1_050.0,
        }
        adapter.state_path.parent.mkdir(parents=True, exist_ok=True)
        adapter.state_path.write_text(json.dumps(legacy_state), encoding="utf-8")

        throttled = adapter._check_limits()
        self.assertEqual(throttled, {"status": "throttled", "reason": "cooldown"})

        migrated_state = json.loads(adapter.state_path.read_text(encoding="utf-8"))
        self.assertIn("cycle_window_start_mono", migrated_state)
        self.assertIn("mutation_window_start_mono", migrated_state)
        self.assertIn("cooldown_until_mono", migrated_state)
        self.assertGreater(migrated_state["cooldown_until_mono"], clock.monotonic)


if __name__ == "__main__":
    unittest.main()
