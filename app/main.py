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

import argparse
import json
import os
import sys
from typing import Any, Dict, Optional

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
from app.agents.discovery import agent_path_from_id
from runtime.constitution import determine_tier, evaluate_mutation, get_forced_tier
from runtime.fitness_v2 import score_mutation_enhanced
from runtime.timeutils import now_iso
from runtime.warm_pool import WarmPool
from runtime.tools.mutation_guard import _apply_ops
from security import cryovant
from security.gatekeeper_protocol import run_gatekeeper
from security.ledger import journal
from ui.aponi_dashboard import AponiDashboard


class Orchestrator:
    """
    Coordinates boot order and health checks.
    """

    def __init__(self, *, dry_run: bool = False) -> None:
        self.state: Dict[str, Any] = {"status": "initializing", "mutation_enabled": False}
        self.agents_root = APP_ROOT / "agents"
        self.lineage_dir = self.agents_root / "lineage"
        self.warm_pool = WarmPool(size=2)
        self.architect = ArchitectAgent(self.agents_root)
        self.dream: Optional[DreamMode] = None
        self.beast: Optional[BeastModeLoop] = None
        self.dashboard = AponiDashboard()
        self.executor = MutationExecutor(self.agents_root)
        self.mutation_engine = MutationEngine(metrics.METRICS_PATH)
        self.dry_run = dry_run

    def _fail(self, reason: str) -> None:
        metrics.log(event_type="orchestrator_error", payload={"reason": reason}, level="ERROR")
        self.state["status"] = "error"
        self.state["reason"] = reason
        try:
            journal.ensure_ledger()
            journal.write_entry(agent_id="system", action="orchestrator_failed", payload={"reason": reason})
        except Exception:
            pass
        try:
            dump()
        except Exception as exc:
            try:
                metrics.log(
                    event_type="orchestrator_dump_failed",
                    payload={"error": str(exc)},
                    level="ERROR",
                )
            except Exception:
                sys.stderr.write(f"orchestrator_dump_failed:{exc}\n")
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
        # Health-First Mode: run architect/dream checks and safe-boot gating
        # before any mutation cycle to enforce boot invariants.
        self._health_check_architect()
        self._health_check_dream()
        if self.state.get("mutation_enabled"):
            self._run_mutation_cycle()
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
            self.state["mutation_enabled"] = False
            self.state["safe_boot"] = True
            return
        metrics.log(event_type="dream_health_ok", payload={"tasks": tasks}, level="INFO")
        self.state["mutation_enabled"] = True
        self.state["safe_boot"] = False

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
        forced_tier = get_forced_tier()
        tier = forced_tier or determine_tier(selected.agent_id)
        if forced_tier is not None:
            metrics.log(
                event_type="mutation_tier_override",
                payload={"agent_id": selected.agent_id, "tier": tier.name},
                level="INFO",
            )
        constitutional_verdict = evaluate_mutation(selected, tier)
        if not constitutional_verdict.get("passed"):
            metrics.log(
                event_type="mutation_rejected_constitutional",
                payload=constitutional_verdict,
                level="ERROR",
            )
            journal.write_entry(
                agent_id=selected.agent_id,
                action="mutation_rejected_constitutional",
                payload=constitutional_verdict,
            )
            if self.dry_run:
                bias = self.mutation_engine.bias_details(selected)
                metrics.log(
                    event_type="mutation_dry_run",
                    payload={
                        "agent_id": selected.agent_id,
                        "strategy_id": selected.intent or "default",
                        "tier": tier.name,
                        "constitution_version": constitutional_verdict.get("constitution_version"),
                        "constitutional_verdict": constitutional_verdict,
                        "bias": bias,
                        "fitness_score": None,
                        "status": "rejected",
                    },
                    level="WARN",
                )
                journal.write_entry(
                    agent_id=selected.agent_id,
                    action="mutation_dry_run",
                    payload={
                        "strategy_id": selected.intent or "default",
                        "tier": tier.name,
                        "constitutional_verdict": constitutional_verdict,
                        "bias": bias,
                        "fitness_score": None,
                        "status": "rejected",
                        "ts": now_iso(),
                    },
                )
            return
        metrics.log(
            event_type="mutation_approved_constitutional",
            payload={
                "agent_id": selected.agent_id,
                "tier": tier.name,
                "constitution_version": constitutional_verdict.get("constitution_version"),
                "warnings": constitutional_verdict.get("warnings", []),
            },
            level="INFO",
        )
        if self.dry_run:
            fitness_score = self._simulate_fitness_score(selected)
            bias = self.mutation_engine.bias_details(selected)
            metrics.log(
                event_type="mutation_dry_run",
                payload={
                    "agent_id": selected.agent_id,
                    "strategy_id": selected.intent or "default",
                    "tier": tier.name,
                    "constitution_version": constitutional_verdict.get("constitution_version"),
                    "constitutional_verdict": constitutional_verdict,
                    "bias": bias,
                    "fitness_score": fitness_score,
                    "status": "approved",
                },
                level="INFO",
            )
            journal.write_entry(
                agent_id=selected.agent_id,
                action="mutation_dry_run",
                payload={
                    "strategy_id": selected.intent or "default",
                    "tier": tier.name,
                    "constitutional_verdict": constitutional_verdict,
                    "bias": bias,
                    "fitness_score": fitness_score,
                    "status": "approved",
                    "ts": now_iso(),
                },
            )
            return

        result = self.executor.execute(selected)
        journal.write_entry(
            agent_id=selected.agent_id,
            action="mutation_cycle",
            payload={
                "result": result,
                "constitutional_verdict": constitutional_verdict,
                "ts": now_iso(),
            },
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

    def _simulate_fitness_score(self, request: MutationRequest) -> float:
        agent_dir = agent_path_from_id(request.agent_id, self.agents_root)
        dna_path = agent_dir / "dna.json"
        dna = {}
        if dna_path.exists():
            dna = json.loads(dna_path.read_text(encoding="utf-8"))
        simulated = json.loads(json.dumps(dna))
        _apply_ops(simulated, request.ops)
        payload = {
            "parent": dna.get("lineage") or "dry_run",
            "intent": request.intent,
            "content": simulated,
        }
        return score_mutation_enhanced(request.agent_id, payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="ADAAD orchestrator")
    parser.add_argument("--dry-run", action="store_true", help="Evaluate mutations without applying them.")
    args = parser.parse_args()

    dry_run_env = os.getenv("ADAAD_DRY_RUN", "").lower() in {"1", "true", "yes", "on"}
    orchestrator = Orchestrator(dry_run=args.dry_run or dry_run_env)
    orchestrator.boot()


if __name__ == "__main__":
    main()
