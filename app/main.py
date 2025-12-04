# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
"""ADAAD Orchestrator entry point.

This script stitches together the Cryovant registry, Dream Mode
sandboxing, and Architect Agent governance to demonstrate a successful
mutation cycle. It favors deterministic, offline-friendly behavior so it
can run inside constrained CI environments.
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Any, Dict

if __package__ is None:  # Allow running via `python app/main.py`
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.architect_agent import ArchitectAgent
from app.beast_mode_loop import BeastLoop
from app.cryovant import CryovantRegistry
from app.dream_mode import SandboxExecutor
from app.meta_mutator import MetaMutator
from app.evolution.kernel import EvolutionKernel
from runtime.boot import boot_sequence
from runtime.earth_init import init_earth
from runtime.logging import event


METRICS_PATH = Path("reports/metrics.jsonl")
METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)


class DemoAgent:
    """Minimal agent with the required API surface."""

    def __init__(self, name: str, version: int = 1) -> None:
        self.name = name
        self.version = version

    def info(self) -> Dict[str, Any]:
        return {"name": self.name, "version": self.version}

    def run(self, input: Any = None) -> Dict[str, Any]:  # noqa: A003 - aligning with agent contract
        return {"status": "ok", "echo": input}

    def mutate(self, src: str) -> str:
        return src + f"\n# mutation-version-{self.version + 1}"

    def score(self, output: Dict[str, Any]) -> float:
        return 1.0 if output.get("status") == "ok" else 0.0


class Orchestrator:
    def __init__(self) -> None:
        self.earth_status = init_earth()
        self.boot_status = boot_sequence()
        self.registry = CryovantRegistry()
        self.architect_agent = ArchitectAgent()
        self.evolution_kernel = EvolutionKernel()
        self.meta_mutator = MetaMutator()
        self.health_green = self.boot_status["structure_ok"] and self.boot_status["cryovant_ledger_writable"]
        self.allow_mutation = self.health_green and self.boot_status["mutation_enabled"]
        event("boot", status=self.boot_status, earth=self.earth_status)

    def _record_metrics(self, success: bool, runtime: float) -> None:
        entry = {
            "mutant_total": 1,
            "mutant_success": int(success),
            "runtime_seconds": runtime,
            "orchestrator": "health-first",
        }
        with METRICS_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")

    def run_cycle(self) -> None:
        if not self.allow_mutation:
            event("mutation_blocked", reason="health_first_gate")
            print("mutation_success", False)
            return

        agent = DemoAgent(name="demo-agent", version=1)
        sandbox = SandboxExecutor()
        with sandbox:
            mutation_result = sandbox.mutate(agent.mutate, "print('hello world')")
            registry_payload = {
                "agent": agent.info(),
                "mutation": mutation_result.details,
                "sandbox_runtime": mutation_result.runtime_seconds,
            }
            agent_id = str(uuid.uuid4())
            self.evolution_kernel.persist()
            meta_snapshot = self.meta_mutator.snapshot()
            record = self.registry.register_agent(
                agent_id=agent_id,
                name=agent.name,
                payload=registry_payload,
                classification="active" if mutation_result.success else "mutant",
                generation=1,
                fitness_score=sandbox.fitness_score(),
                kernel_hash=self.evolution_kernel.fingerprint(),
                policy_hash=meta_snapshot["fingerprint"],
            )
            self._record_metrics(success=mutation_result.success, runtime=mutation_result.runtime_seconds)
            cryovant_ok = self.registry.certify_or_quarantine(record.payload, record.signature)
            event("cryovant_check", ok=cryovant_ok, agent_id=record.agent_id)
            if not cryovant_ok:
                raise RuntimeError("Cryovant integrity check failed")

        proposals = self.architect_agent.governance_sweep()
        if proposals:
            export_path = self.architect_agent.export_proposals(proposals)
            event("architect_proposals", count=len(proposals), path=str(export_path))

        event("mutation_cycle", success=mutation_result.success, runtime=mutation_result.runtime_seconds)
        beast = BeastLoop(
            registry=self.registry,
            architect=self.architect_agent,
            kernel=self.evolution_kernel,
            meta_mutator=self.meta_mutator,
        )
        beast.tick()
        print("mutation_success", mutation_result.success)


def main() -> None:
    orchestrator = Orchestrator()
    orchestrator.run_cycle()


if __name__ == "__main__":
    main()
