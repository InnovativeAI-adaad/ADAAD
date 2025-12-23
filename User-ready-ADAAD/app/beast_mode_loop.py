"""
Beast mode evaluates mutations and promotes approved staged candidates.
"""

import json
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.agents.base_agent import promote_offspring
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

        agent_dir = self.agents_root / selected
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
