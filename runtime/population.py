# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


POPULATION_ROOT = Path("app/agents/lineage")
POPULATION_ROOT.mkdir(parents=True, exist_ok=True)
POPULATION_STATE = Path("reports/population.jsonl")
POPULATION_STATE.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class PopulationEntry:
    agent_id: str
    artifact: str
    classification: str
    ancestor_id: Optional[str]
    generation: Optional[int]
    fitness_score: Optional[float]
    created_at: float

    @classmethod
    def from_json(cls, payload: Dict[str, Any]) -> "PopulationEntry":
        return cls(
            agent_id=payload.get("agent_id", ""),
            artifact=payload.get("artifact", ""),
            classification=payload.get("classification", "unknown"),
            ancestor_id=payload.get("ancestor_id"),
            generation=payload.get("generation"),
            fitness_score=payload.get("fitness_score"),
            created_at=payload.get("created_at", time.time()),
        )


class PopulationManager:
    """Track multi-agent populations for Beast Loop scheduling."""

    def __init__(self, root: Path | str = POPULATION_ROOT):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _write_metadata(self, entry: PopulationEntry) -> None:
        agent_dir = self.root / entry.agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "meta.json").write_text(json.dumps(asdict(entry), indent=2), encoding="utf-8")
        (agent_dir / "dna.json").write_text(
            json.dumps(
                {
                    "ancestor_id": entry.ancestor_id,
                    "generation": entry.generation,
                    "artifact": entry.artifact,
                    "fitness_score": entry.fitness_score,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (agent_dir / "certificate.json").write_text(
            json.dumps({"agent_id": entry.agent_id, "timestamp": entry.created_at}, indent=2),
            encoding="utf-8",
        )
        with POPULATION_STATE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(entry)) + "\n")

    def record_agent(
        self,
        *,
        agent_id: str,
        artifact: str,
        classification: str,
        ancestor_id: Optional[str],
        generation: Optional[int],
        fitness_score: Optional[float],
    ) -> PopulationEntry:
        entry = PopulationEntry(
            agent_id=agent_id,
            artifact=artifact,
            classification=classification,
            ancestor_id=ancestor_id,
            generation=generation,
            fitness_score=fitness_score,
            created_at=time.time(),
        )
        self._write_metadata(entry)
        return entry

    def list_population(self) -> List[PopulationEntry]:
        population: List[PopulationEntry] = []
        for directory in self.root.glob("*"):
            if not directory.is_dir():
                continue
            meta_path = directory / "meta.json"
            if meta_path.exists():
                try:
                    payload = json.loads(meta_path.read_text(encoding="utf-8"))
                    population.append(PopulationEntry.from_json(payload))
                except json.JSONDecodeError:
                    continue
        return population

    def pick_parents(self, count: int = 2) -> List[PopulationEntry]:
        population = self.list_population()
        if not population:
            return []
        return random.sample(population, k=min(count, len(population)))

    def ensure_seed(self) -> PopulationEntry:
        existing = self.list_population()
        if existing:
            return existing[0]
        seed_id = "seed-agent"
        seed_dir = self.root / seed_id
        seed_dir.mkdir(parents=True, exist_ok=True)
        artifact = seed_dir / "artifact.py"
        if not artifact.exists():
            artifact.write_text("print(\"seed agent\")\n", encoding="utf-8")
        return self.record_agent(
            agent_id=seed_id,
            artifact=str(artifact),
            classification="seed",
            ancestor_id=None,
            generation=1,
            fitness_score=1.0,
        )


__all__ = ["PopulationEntry", "PopulationManager"]
