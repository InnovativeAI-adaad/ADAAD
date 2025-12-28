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

import time
from pathlib import Path
from typing import Dict, List, Optional

from app.agents.base_agent import stage_offspring
from runtime import metrics
from security import cryovant

ELEMENT_ID = "Fire"


class DreamMode:
    """
    Drives creative mutation cycles.
    """

    def __init__(self, agents_root: Path, lineage_dir: Path):
        self.agents_root = agents_root
        self.lineage_dir = lineage_dir

    def discover_tasks(self) -> List[str]:
        """
        Discover mutation-ready agents.
        """
        tasks: List[str] = []
        if not self.agents_root.exists():
            return tasks
        for agent_dir in self.agents_root.iterdir():
            if not agent_dir.is_dir():
                continue
            if agent_dir.name in {"agent_template", "lineage"}:
                continue
            tasks.append(agent_dir.name)
        metrics.log(event_type="dream_discovery", payload={"tasks": tasks}, level="INFO")
        return tasks

    def run_cycle(self, agent_id: Optional[str] = None) -> Dict[str, str]:
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

        metrics.log(event_type="evolution_cycle_decision", payload={"selected_agent": selected}, level="INFO", element_id=ELEMENT_ID)
        mutation_content = f"{selected}-mutation-{time.time()}"
        staged_path = stage_offspring(parent_id=selected, content=mutation_content, lineage_dir=self.lineage_dir)
        metrics.log(
            event_type="dream_candidate_generated",
            payload={"agent": selected, "staged_path": str(staged_path)},
            level="INFO",
            element_id=ELEMENT_ID,
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
        return {"status": "completed", "agent": selected, "staged_path": str(staged_path)}