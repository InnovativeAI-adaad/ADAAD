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
Dream mode handles mutation cycles for agents.
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Optional

from app.agents.base_agent import stage_offspring
from app.agents.discovery import agent_path_from_id, iter_agent_dirs, resolve_agent_id
from runtime import metrics
from runtime.evolution.entropy_discipline import EntropyBudget, deterministic_context, deterministic_token_with_budget
from runtime.evolution.fitness import FitnessEvaluator
from security import cryovant

ELEMENT_ID = "Fire"


class DreamMode:
    """
    Drives creative mutation cycles.
    """

    def __init__(self, agents_root: Path, lineage_dir: Path, *, replay_mode: str = "off", recovery_tier: str | None = None):
        self.agents_root = agents_root
        self.lineage_dir = lineage_dir
        self.replay_mode = replay_mode
        self.recovery_tier = recovery_tier
        self.entropy_budget = EntropyBudget()
        self.fitness_evaluator = FitnessEvaluator()

    @staticmethod
    def _read_json(path: Path) -> Dict[str, object]:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _extract_dream_scope(meta: Dict[str, object]) -> Optional[Dict[str, object]]:
        scope = meta.get("dream_scope")
        if not isinstance(scope, dict):
            return None
        allow = scope.get("allow", [])
        if isinstance(allow, str):
            allow = [allow]
        if not isinstance(allow, list):
            return None
        if not scope.get("enabled", True):
            return None
        if "mutation" not in allow:
            return None
        return scope

    def write_dream_manifest(
        self,
        *,
        agent_id: str,
        epoch_id: str,
        bundle_id: str,
        staged_path: Path,
        fitness: object,
    ) -> Path:
        """Persist deterministic dream-cycle metadata for audit and replay analysis."""
        manifest_path = staged_path / "dream_manifest.json"
        manifest = {
            "agent_id": agent_id,
            "epoch_id": epoch_id,
            "bundle_id": bundle_id,
            "staged_path": str(staged_path),
            "lineage_dir": str(self.lineage_dir),
            "replay_mode": self.replay_mode,
            "recovery_tier": self.recovery_tier,
            "fitness": fitness.to_dict(),
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return manifest_path

    def discover_tasks(self) -> List[str]:
        """
        Discover mutation-ready agents.
        """
        tasks: List[str] = []
        for agent_dir in iter_agent_dirs(self.agents_root):
            agent_id = resolve_agent_id(agent_dir, self.agents_root)
            meta = self._read_json(agent_dir / "meta.json")
            if not self._extract_dream_scope(meta):
                metrics.log(
                    event_type="dream_scope_blocked",
                    payload={"agent": agent_id},
                    level="WARNING",
                    element_id=ELEMENT_ID,
                )
                continue
            tasks.append(agent_id)
        metrics.log(event_type="dream_discovery", payload={"tasks": tasks}, level="INFO")
        return tasks

    def run_cycle(self, agent_id: Optional[str] = None, *, epoch_id: str = "", bundle_id: str = "dream") -> Dict[str, str]:
        """
        Run a single dream mutation cycle. Dream only stages candidates; it does not promote.
        """
        metrics.log(event_type="evolution_cycle_start", payload={"agent": agent_id}, level="INFO", element_id=ELEMENT_ID)
        tasks = self.discover_tasks()
        if not tasks:
            metrics.log(event_type="evolution_cycle_end", payload={"agent": agent_id, "status": "skipped"}, level="WARNING", element_id=ELEMENT_ID)
            return {"status": "skipped", "reason": "no tasks"}

        selected = agent_id or tasks[0]
        if not cryovant.validate_ancestry(selected):
            metrics.log(event_type="evolution_cycle_end", payload={"agent": selected, "status": "blocked"}, level="ERROR", element_id=ELEMENT_ID)
            return {"status": "blocked", "agent": selected}

        agent_dir = agent_path_from_id(selected, self.agents_root)
        meta = self._read_json(agent_dir / "meta.json")
        dream_scope = self._extract_dream_scope(meta)
        if not dream_scope:
            metrics.log(
                event_type="dream_scope_blocked",
                payload={"agent": selected},
                level="ERROR",
                element_id=ELEMENT_ID,
            )
            return {"status": "blocked", "agent": selected, "reason": "dream_scope_missing"}

        metrics.log(event_type="evolution_cycle_decision", payload={"selected_agent": selected}, level="INFO", element_id=ELEMENT_ID)
        if deterministic_context(replay_mode=self.replay_mode, recovery_tier=self.recovery_tier):
            seed = f"{epoch_id}::{selected}"
            numeric_token, self.entropy_budget = deterministic_token_with_budget(
                seed,
                f"mutation_{bundle_id}",
                budget=self.entropy_budget,
            )
            token = str(numeric_token)
        else:
            token = str(time.time())
        mutation_content = f"{selected}-mutation-{token}"
        handoff_contract = {
            "schema_version": "1.0",
            "issued_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "issuer": "DreamMode",
            "agent": selected,
            "dream_scope": dream_scope,
            "constraints": {"sandboxed": True},
        }
        staged_path = stage_offspring(
            parent_id=selected,
            content=mutation_content,
            lineage_dir=self.lineage_dir,
            dream_mode=True,
            sandboxed=True,
            handoff_contract=handoff_contract,
            mutation_intent="dream_mutation",
        )
        metrics.log(
            event_type="dream_candidate_generated",
            payload={"agent": selected, "staged_path": str(staged_path)},
            level="INFO",
            element_id=ELEMENT_ID,
        )
        fitness = self.fitness_evaluator.evaluate_content(mutation_content, constitution_ok=True)
        metrics.log(
            event_type="dream_mutation_fitness",
            payload={"agent": selected, "fitness": fitness.to_dict(), "viable": fitness.is_viable()},
            level="INFO" if fitness.is_viable() else "WARNING",
            element_id=ELEMENT_ID,
        )
        self.write_dream_manifest(
            agent_id=selected,
            epoch_id=epoch_id,
            bundle_id=bundle_id,
            staged_path=staged_path,
            fitness=fitness,
        )
        metrics.log(
            event_type="evolution_cycle_validation",
            payload={"agent": selected, "result": "validated"},
            level="INFO",
            element_id=ELEMENT_ID,
        )
        metrics.log(
            event_type="evolution_cycle_end",
            payload={"agent": selected, "status": "completed"},
            level="INFO",
            element_id=ELEMENT_ID,
        )
        return {
            "status": "completed",
            "agent": selected,
            "staged_path": str(staged_path),
            "fitness": str(fitness.score),
            "viable": "true" if fitness.is_viable() else "false",
        }
