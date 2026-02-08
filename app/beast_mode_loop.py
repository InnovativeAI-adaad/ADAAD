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
Beast mode evaluates mutations and promotes approved staged candidates.
"""

import json
import os
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.agents.base_agent import promote_offspring
from app.agents.discovery import agent_path_from_id, iter_agent_dirs, resolve_agent_id
from runtime import fitness, metrics
from runtime.capability_graph import get_capabilities, register_capability
from security import cryovant
from security.ledger import journal

ELEMENT_ID = "Fire"


class BeastModeLoop:
    """
    Executes evaluation cycles against mutated offspring.
    """

    def __init__(self, agents_root: Path, lineage_dir: Path):
        self.agents_root = agents_root
        self.lineage_dir = lineage_dir
        self.threshold = float(os.getenv("ADAAD_FITNESS_THRESHOLD", "0.70"))
        self.cycle_budget = int(os.getenv("ADAAD_BEAST_CYCLE_BUDGET", "50"))
        self.cycle_window_sec = int(os.getenv("ADAAD_BEAST_CYCLE_WINDOW_SEC", "3600"))
        self.mutation_quota = int(os.getenv("ADAAD_BEAST_MUTATION_QUOTA", "25"))
        self.mutation_window_sec = int(os.getenv("ADAAD_BEAST_MUTATION_WINDOW_SEC", "3600"))
        self.cooldown_sec = int(os.getenv("ADAAD_BEAST_COOLDOWN_SEC", "300"))
        self.state_path = self.agents_root.parent / "data" / "beast_mode_state.json"

    def _load_state(self) -> Dict[str, float]:
        if not self.state_path.exists():
            return {
                "cycle_window_start": 0.0,
                "cycle_count": 0.0,
                "mutation_window_start": 0.0,
                "mutation_count": 0.0,
                "cooldown_until": 0.0,
            }
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {
                "cycle_window_start": 0.0,
                "cycle_count": 0.0,
                "mutation_window_start": 0.0,
                "mutation_count": 0.0,
                "cooldown_until": 0.0,
            }

    def _save_state(self, state: Dict[str, float]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")

    def _refresh_window(self, start_key: str, count_key: str, window_sec: int, now: float, state: Dict[str, float]) -> None:
        window_start = float(state.get(start_key, 0.0))
        if window_start <= 0.0 or now - window_start >= window_sec:
            state[start_key] = now
            state[count_key] = 0.0

    def _throttle(self, reason: str, payload: Dict[str, float], state: Dict[str, float]) -> Dict[str, str]:
        state["cooldown_until"] = payload["cooldown_until"]
        self._save_state(state)
        metrics.log(event_type="beast_cycle_throttled", payload=payload, level="WARNING", element_id=ELEMENT_ID)
        return {"status": "throttled", "reason": reason}

    def _check_limits(self) -> Optional[Dict[str, str]]:
        now = time.time()
        state = self._load_state()
        cooldown_until = float(state.get("cooldown_until", 0.0))
        if cooldown_until and now < cooldown_until:
            payload = {"cooldown_until": cooldown_until, "now": now}
            return self._throttle("cooldown", payload, state)

        self._refresh_window("cycle_window_start", "cycle_count", self.cycle_window_sec, now, state)
        self._refresh_window("mutation_window_start", "mutation_count", self.mutation_window_sec, now, state)

        if self.cycle_budget > 0 and float(state.get("cycle_count", 0.0)) >= self.cycle_budget:
            cooldown_until = now + self.cooldown_sec
            metrics.log(
                event_type="beast_cycle_budget_exceeded",
                payload={"budget": self.cycle_budget, "window_sec": self.cycle_window_sec, "count": state.get("cycle_count", 0.0)},
                level="WARNING",
                element_id=ELEMENT_ID,
            )
            return self._throttle(
                "cycle_budget",
                {"cooldown_until": cooldown_until, "now": now, "limit": self.cycle_budget, "count": state.get("cycle_count", 0.0)},
                state,
            )

        state["cycle_count"] = float(state.get("cycle_count", 0.0)) + 1.0
        self._save_state(state)
        return None

    def _check_mutation_quota(self) -> Optional[Dict[str, str]]:
        now = time.time()
        state = self._load_state()
        self._refresh_window("mutation_window_start", "mutation_count", self.mutation_window_sec, now, state)

        if self.mutation_quota > 0 and float(state.get("mutation_count", 0.0)) >= self.mutation_quota:
            cooldown_until = now + self.cooldown_sec
            metrics.log(
                event_type="beast_mutation_quota_exceeded",
                payload={"quota": self.mutation_quota, "window_sec": self.mutation_window_sec, "count": state.get("mutation_count", 0.0)},
                level="WARNING",
                element_id=ELEMENT_ID,
            )
            return self._throttle(
                "mutation_quota",
                {"cooldown_until": cooldown_until, "now": now, "limit": self.mutation_quota, "count": state.get("mutation_count", 0.0)},
                state,
            )

        state["mutation_count"] = float(state.get("mutation_count", 0.0)) + 1.0
        self._save_state(state)
        return None

    def _available_agents(self) -> List[str]:
        agents: List[str] = []
        for agent_dir in iter_agent_dirs(self.agents_root):
            agents.append(resolve_agent_id(agent_dir, self.agents_root))
        return agents

    def _latest_staged(self, agent_id: str) -> Tuple[Optional[Path], Optional[Dict[str, str]]]:
        staging_root = self.lineage_dir / "_staging"
        if not staging_root.exists():
            return None, None
        candidates = [item for item in staging_root.iterdir() if item.is_dir()]
        candidates.sort(key=lambda entry: entry.stat().st_mtime, reverse=True)
        for candidate in candidates:
            mutation_file = candidate / "mutation.json"
            if not mutation_file.exists():
                continue
            try:
                payload = json.loads(mutation_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if payload.get("parent") == agent_id:
                return candidate, payload
        return None, None

    def _discard(self, staged_dir: Path, payload: Dict[str, str], score: float) -> None:
        shutil.rmtree(staged_dir, ignore_errors=True)
        metrics.log(
            event_type="mutation_discarded",
            payload={"staged": str(staged_dir), "score": score, "parent": payload.get("parent")},
            level="WARNING",
            element_id=ELEMENT_ID,
        )

    def run_cycle(self, agent_id: Optional[str] = None) -> Dict[str, str]:
        metrics.log(event_type="beast_cycle_start", payload={"agent": agent_id}, level="INFO", element_id=ELEMENT_ID)
        throttled = self._check_limits()
        if throttled:
            metrics.log(event_type="beast_cycle_end", payload=throttled, level="WARNING", element_id=ELEMENT_ID)
            return throttled
        agents = self._available_agents()
        if not agents:
            metrics.log(event_type="beast_cycle_end", payload={"status": "skipped"}, level="WARNING", element_id=ELEMENT_ID)
            return {"status": "skipped", "reason": "no agents"}

        selected = agent_id or agents[0]
        metrics.log(event_type="beast_cycle_decision", payload={"agent": selected}, level="INFO", element_id=ELEMENT_ID)
        if not cryovant.validate_ancestry(selected):
            metrics.log(event_type="beast_cycle_end", payload={"status": "blocked", "agent": selected}, level="ERROR", element_id=ELEMENT_ID)
            return {"status": "blocked", "agent": selected}

        staged_dir, payload = self._latest_staged(selected)
        if not staged_dir or not payload:
            metrics.log(event_type="beast_cycle_end", payload={"status": "no_staged", "agent": selected}, level="INFO", element_id=ELEMENT_ID)
            return {"status": "no_staged", "agent": selected}

        throttled = self._check_mutation_quota()
        if throttled:
            metrics.log(
                event_type="beast_cycle_end",
                payload={"status": "throttled", "agent": selected, "reason": throttled.get("reason")},
                level="WARNING",
                element_id=ELEMENT_ID,
            )
            return {"status": "throttled", "agent": selected, "reason": throttled.get("reason")}

        score = fitness.score_mutation(selected, payload)
        metrics.log(
            event_type="beast_fitness_scored",
            payload={"agent": selected, "score": score, "staged": str(staged_dir)},
            level="INFO",
            element_id=ELEMENT_ID,
        )

        if score < self.threshold:
            self._discard(staged_dir, payload, score)
            metrics.log(event_type="beast_cycle_end", payload={"status": "discarded", "agent": selected}, level="INFO", element_id=ELEMENT_ID)
            return {"status": "discarded", "agent": selected, "score": score}

        agent_dir = agent_path_from_id(selected, self.agents_root)
        cryovant.evolve_certificate(selected, agent_dir, staged_dir, get_capabilities())
        promoted = promote_offspring(staged_dir, self.lineage_dir)
        journal.write_entry(
            agent_id=selected,
            action="mutation_promoted",
            payload={"staged": str(staged_dir), "promoted": str(promoted), "score": score},
        )
        evidence = {
            "staged_path": str(staged_dir),
            "promoted_path": str(promoted),
            "fitness_score": score,
            "ledger_tail_refs": journal.read_entries(limit=5),
        }
        register_capability(
            f"agent.{selected}.mutation_quality",
            version="0.1.0",
            score=score,
            owner_element=ELEMENT_ID,
            requires=["cryovant.gate", "orchestrator.boot"],
            evidence=evidence,
        )
        metrics.log(
            event_type="mutation_promoted",
            payload={"agent": selected, "promoted_path": str(promoted), "score": score},
            level="INFO",
            element_id=ELEMENT_ID,
        )
        metrics.log(event_type="beast_cycle_end", payload={"status": "promoted", "agent": selected}, level="INFO", element_id=ELEMENT_ID)
        return {"status": "promoted", "agent": selected, "score": score, "promoted_path": str(promoted)}
