"""
Beast mode evaluates mutations and enforces ancestry validation.
"""

from pathlib import Path
from typing import Dict, List, Optional

from runtime import metrics
from security import cryovant

ELEMENT_ID = "Fire"


class BeastModeLoop:
    """
    Executes evaluation cycles against mutated offspring.
    """

    def __init__(self, agents_root: Path, lineage_dir: Path):
        self.agents_root = agents_root
        self.lineage_dir = lineage_dir

    def _available_agents(self) -> List[str]:
        agents: List[str] = []
        if not self.agents_root.exists():
            return agents
        for agent_dir in self.agents_root.iterdir():
            if not agent_dir.is_dir():
                continue
            if agent_dir.name in {"agent_template", "lineage"}:
                continue
            agents.append(agent_dir.name)
        return agents

    def run_cycle(self, agent_id: Optional[str] = None) -> Dict[str, str]:
        metrics.log(event_type="beast_cycle_start", payload={"agent": agent_id}, level="INFO", element_id=ELEMENT_ID)
        agents = self._available_agents()
        if not agents:
            metrics.log(event_type="beast_cycle_end", payload={"status": "skipped"}, level="WARNING", element_id=ELEMENT_ID)
            return {"status": "skipped", "reason": "no agents"}

        selected = agent_id or agents[0]
        metrics.log(event_type="beast_cycle_decision", payload={"agent": selected}, level="INFO", element_id=ELEMENT_ID)
        if not cryovant.validate_ancestry(selected):
            metrics.log(event_type="beast_cycle_end", payload={"status": "blocked", "agent": selected}, level="ERROR", element_id=ELEMENT_ID)
            return {"status": "blocked", "agent": selected}

        payload = {"agent": selected, "lineage_dir": str(self.lineage_dir)}
        metrics.log(event_type="beast_cycle_validation", payload=payload, level="INFO", element_id=ELEMENT_ID)
        metrics.log(event_type="beast_cycle_end", payload={"status": "completed", "agent": selected}, level="INFO", element_id=ELEMENT_ID)
        return {"status": "completed", "agent": selected}
