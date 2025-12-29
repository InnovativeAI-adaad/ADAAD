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

"""
Deterministic orchestrator entrypoint.
"""

import sys
from typing import Dict, Optional

from app import APP_ROOT
from app.architect_agent import ArchitectAgent
from app.agents.mutation_engine import MutationEngine
from app.agents.mutation_request import MutationRequest
from app.beast_mode_loop import BeastModeLoop
from app.dream_mode import DreamMode
from app.mutation_executor import MutationExecutor
from runtime import metrics
from runtime.capability_graph import register_capability
from runtime.element_registry import dump, register
from runtime.invariants import verify_all
from runtime.timeutils import now_iso
from runtime.warm_pool import WarmPool
from security import cryovant
from security.gatekeeper_protocol import run_gatekeeper
from security.ledger import journal
from ui.aponi_dashboard import AponiDashboard


class Orchestrator:
    """
    Coordinates boot order and health checks.
    """

    def __init__(self) -> None:
        self.state: Dict[str, str] = {"status": "initializing"}
        self.agents_root = APP_ROOT / "agents"
        self.lineage_dir = self.agents_root / "lineage"
        self.warm_pool = WarmPool(size=2)
        self.architect = ArchitectAgent(self.agents_root)
        self.dream: Optional[DreamMode] = None
        self.beast: Optional[BeastModeLoop] = None
        self.dashboard = AponiDashboard()
        self.executor = MutationExecutor(self.agents_root)
        self.mutation_engine = MutationEngine(metrics.METRICS_PATH)

    def _fail(self, reason: str) -> None:
        metrics.log(event_type="orchestrator_error", payload={"reason": reason}, level="ERROR")
        self.state["status"] = "error"
        self.state["reason"] = reason
        try:
            journal.ensure_ledger()
            journal.write_entry(agent_id="system", action="orchestrator_failed", payload={"reason": reason})
        except Exception:
            pass
        dump()
        sys.exit(1)

    def boot(self) -> None:
        metrics.log(event_type="orchestrator_start", payload={}, level="INFO")
        gate = run_gatekeeper()
        if not gate.get("ok"):
            self._fail(f"gatekeeper_failed:{','.join(gate.get('missing', []))}")
        self._register_elements()
        self._init_runtime()
        self._init_cryovant()
        self.dream = DreamMode(self.agents_root, self.lineage_dir)
        self.beast = BeastModeLoop(self.agents_root, self.lineage_dir)
        self._health_check_architect()
        self._run_mutation_cycle()
        self._health_check_dream()
        self._register_capabilities()
        self._init_ui()
        self.state["status"] = "ready"
        metrics.log(event_type="orchestrator_ready", payload=self.state, level="INFO")
        journal.write_entry(agent_id="system", action="orchestrator_ready", payload=self.state)
        dump()

    def _register_elements(self) -> None:
        register("Earth", "runtime.metrics")
        register("Earth", "runtime.element_registry")
        register("Earth", "runtime.warm_pool")
        register("Water", "security.cryovant")
        register("Water", "security.ledger.journal")
        register("Wood", "app.architect_agent")
        register("Fire", "app.dream_mode")
        register("Fire", "app.beast_mode_loop")
        register("Metal", "ui.aponi_dashboard")

    def _init_runtime(self) -> None:
        self.warm_pool.start()
        ok, failures = verify_all()
        if not ok:
            self._fail(f"invariants_failed:{','.join(failures)}")

    def _init_cryovant(self) -> None:
        if not cryovant.validate_environment():
            self._fail("cryovant_environment")
        certified, errors = cryovant.certify_agents(self.agents_root)
        if not certified:
            self._fail(f"cryovant_certification:{','.join(errors)}")

    def _health_check_architect(self) -> None:
        scan = self.architect.scan()
        if not scan.get("valid"):
            self._fail("architect_scan_failed")

    def _health_check_dream(self) -> None:
        assert self.dream is not None
        tasks = self.dream.discover_tasks()
        if not tasks:
            metrics.log(event_type="dream_safe_boot", payload={"reason": "no tasks"}, level="WARN")
            self.state["mutation_enabled"] = "false"
            self.state["safe_boot"] = "true"
            return
        metrics.log(event_type="dream_health_ok", payload={"tasks": tasks}, level="INFO")
        self.state["mutation_enabled"] = "true"
        self.state["safe_boot"] = "false"

    def _run_mutation_cycle(self) -> None:
        """
        Execute one architect → mutation engine → executor cycle.
        """
        proposals = self.architect.propose_mutations()
        if not proposals:
            metrics.log(event_type="mutation_cycle_skipped", payload={"reason": "no proposals"}, level="INFO")
            return
        selected, scores = self.mutation_engine.select(proposals)
        metrics.log(event_type="mutation_strategy_scores", payload={"scores": scores}, level="INFO")
        if not selected:
            metrics.log(event_type="mutation_cycle_skipped", payload={"reason": "no selection"}, level="INFO")
            return
        result = self.executor.execute(selected)
        journal.write_entry(
            agent_id=selected.agent_id,
            action="mutation_cycle",
            payload={"result": result, "ts": now_iso()},
        )

    def _register_capabilities(self) -> None:
        register_capability("orchestrator.boot", "0.65.0", 1.0, "Earth")
        register_capability("cryovant.gate", "0.65.0", 1.0, "Water")
        register_capability("architect.scan", "0.65.0", 1.0, "Wood")
        register_capability("dream.cycle", "0.65.0", 1.0, "Fire")
        register_capability("beast.evaluate", "0.65.0", 1.0, "Fire")
        register_capability("ui.dashboard", "0.65.0", 1.0, "Metal")

    def _init_ui(self) -> None:
        self.dashboard.start(self.state)


def main() -> None:
    orchestrator = Orchestrator()
    orchestrator.boot()


if __name__ == "__main__":
    main()
