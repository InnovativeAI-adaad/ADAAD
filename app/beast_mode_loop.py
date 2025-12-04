# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Dict

from app.architect_agent import ArchitectAgent
from app.cryovant import CryovantRegistry
from app.dream_mode import SandboxExecutor
from app.meta_mutator import MetaMutator
from app.evolution.kernel import EvolutionKernel
from runtime.logging import event
from runtime.population import PopulationManager

METRICS_PATH = Path("reports/metrics.jsonl")
BEAST_TARGET = Path("reports/beast_target.txt")


class BeastLoop:
    def __init__(
        self,
        interval_s: float = 5.0,
        registry: CryovantRegistry | None = None,
        architect: ArchitectAgent | None = None,
        population: PopulationManager | None = None,
        offspring: int = 2,
        kernel: EvolutionKernel | None = None,
        meta_mutator: MetaMutator | None = None,
    ) -> None:
        self.interval_s = interval_s
        self.registry = registry or CryovantRegistry()
        self.architect = architect or ArchitectAgent()
        self.population = population or PopulationManager()
        self.kernel = kernel or EvolutionKernel()
        self.meta_mutator = meta_mutator or MetaMutator()
        self.offspring = max(1, offspring)
        BEAST_TARGET.parent.mkdir(parents=True, exist_ok=True)
        if not BEAST_TARGET.exists():
            BEAST_TARGET.write_text("# beast-loop seed\n", encoding="utf-8")

    def _record_metrics(self, success: bool, runtime: float, fitness: float) -> None:
        entry: Dict[str, object] = {
            "mutant_total": 1,
            "mutant_success": int(success),
            "runtime_seconds": runtime,
            "beast_fitness": fitness,
        }
        METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with METRICS_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")

    def _seed_population(self) -> None:
        self.population.ensure_seed()

    def _spawn_offspring(self) -> list[dict[str, object]]:
        parents = self.population.pick_parents(self.offspring)
        if not parents:
            parents = [self.population.ensure_seed()]
        outcomes: list[dict[str, object]] = []
        for parent in parents:
            child_id = str(uuid.uuid4())
            child_dir = Path(parent.artifact).parent.parent / child_id
            child_dir.mkdir(parents=True, exist_ok=True)
            child_artifact = child_dir / "artifact.py"
            content = Path(parent.artifact).read_text(encoding="utf-8")
            child_artifact.write_text(content, encoding="utf-8")

            sandbox = SandboxExecutor()
            with sandbox:
                result = sandbox.mutate_file(
                    str(child_artifact),
                    lambda c: c + f"# tick-{int(time.time())}\n",
                    timeout=3.0,
                )
                fitness = sandbox.fitness_score()

            classification = "promoted" if result.success else "quarantine"
            payload = {
                "artifact": str(child_artifact),
                "mutation": result.details,
                "runtime_seconds": result.runtime_seconds,
                "ancestor_id": parent.agent_id,
            }
            self.kernel.persist()
            meta_snapshot = self.meta_mutator.snapshot()
            record = self.registry.register_agent(
                agent_id=child_id,
                name="beast-loop-agent",
                payload=payload,
                classification=classification,
                ancestor_id=parent.agent_id,
                generation=(parent.generation or 1) + 1,
                fitness_score=fitness,
                kernel_hash=self.kernel.fingerprint(),
                policy_hash=meta_snapshot["fingerprint"],
            )
            certified = self.registry.certify_or_quarantine(
                record.payload, record.signature, artifact_path=str(child_artifact)
            )
            self.population.record_agent(
                agent_id=child_id,
                artifact=str(child_artifact),
                classification=classification,
                ancestor_id=parent.agent_id,
                generation=(parent.generation or 1) + 1,
                fitness_score=fitness,
            )
            self._record_metrics(result.success, result.runtime_seconds, fitness)
            event(
                "beast_tick",
                success=result.success,
                fitness=fitness,
                certified=certified,
                agent_id=child_id,
                proposals=0,
                parent=parent.agent_id,
            )
            outcomes.append(
                {
                    "success": result.success,
                    "fitness": fitness,
                    "certified": certified,
                    "agent_id": child_id,
                    "parent": parent.agent_id,
                }
            )
        return outcomes

    def tick(self) -> dict[str, object]:
        self._seed_population()
        outcomes = self._spawn_offspring()
        proposals = self.architect.governance_sweep()
        if proposals:
            self.architect.export_proposals(proposals)
        system_props = self.architect.audit_system_layers()
        if system_props:
            self.architect.export_system_proposals(system_props)
        return {
            "outcomes": outcomes,
            "proposals": len(proposals),
            "system_proposals": len(system_props),
        }

    def run(self, once: bool = False) -> dict[str, object] | None:
        if once:
            return self.tick()
        while True:
            self.tick()
            time.sleep(self.interval_s)
        return None
