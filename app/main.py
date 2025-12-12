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
import time
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
from app.mutation_pipeline import apply_mutation_with_checks, record_fitness_stage, run_sandbox_stage
from runtime.boot import boot_sequence
from runtime.earth_init import init_earth
from runtime.logging import event
from runtime.metrics import ErrorCode, MutationStage, StageResult, record_stage_metric
from reports.metrics_logger import log_mutation_cycle, log_mutation_stage
from runtime.failure_taxonomy import ErrorCode as TaxonomyErrorCode, Stage, classify_exception


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

    def run_cycle(self) -> None:
        if not self.allow_mutation:
            event("mutation_blocked", reason="health_first_gate")
            print("mutation_success", False)
            return

        cycle_id = str(uuid.uuid4())
        agent = DemoAgent(name="demo-agent", version=1)
        parent_agent_id = agent.name
        child_candidate_id = "demo-child"
        dominant_stage: str | None = None
        dominant_error: str | None = None
        cycle_logged = False
        t0 = time.time()

        def mark_failure(
            stage: str,
            exc: BaseException | None = None,
            *,
            error_code: str | None = None,
            duration_ms: int | None = None,
            sandbox_exit_code: int | None = None,
            notes: Dict[str, Any] | None = None,
        ) -> None:
            nonlocal dominant_stage, dominant_error
            classification = classify_exception(exc) if exc else None
            dominant_stage = stage
            dominant_error = error_code or (classification.error_code if classification else TaxonomyErrorCode.UNKNOWN)
            log_mutation_stage(
                cycle_id=cycle_id,
                parent_agent_id=parent_agent_id,
                child_candidate_id=child_candidate_id,
                stage=stage,
                result="FAIL",
                error_code=dominant_error,
                exception_type=classification.exception_type if classification else None,
                exception_msg_hash=classification.exception_msg_hash if classification else None,
                duration_ms=duration_ms,
                sandbox_exit_code=sandbox_exit_code,
                notes=notes,
            )

        sandbox_result = None
        current_stage = Stage.MUTATE_AST
        sandbox = SandboxExecutor()
        with sandbox:
            candidate_path = Path("reports/demo_candidate.py")
            candidate_path.parent.mkdir(parents=True, exist_ok=True)
            candidate_path.write_text("print('hello world')\n", encoding="utf-8")

            try:
                s0 = time.time()
                mutation_ok = apply_mutation_with_checks(
                    target_path=candidate_path,
                    mutate_fn=agent.mutate,
                    sandbox=sandbox,
                    cycle_id=cycle_id,
                    parent_agent_id=parent_agent_id,
                    child_candidate_id=child_candidate_id,
                )
                if not mutation_ok:
                    mark_failure(Stage.MUTATE_AST, error_code=TaxonomyErrorCode.UNKNOWN, duration_ms=int((time.time() - s0) * 1000))
                    log_mutation_cycle(
                        cycle_id=cycle_id,
                        parent_agent_id=parent_agent_id,
                        child_candidate_id=child_candidate_id,
                        final_result="FAIL",
                        dominant_stage=dominant_stage,
                        dominant_error_code=dominant_error,
                        duration_ms=int((time.time() - t0) * 1000),
                    )
                    cycle_logged = True
                    return
                log_mutation_stage(
                    cycle_id=cycle_id,
                    parent_agent_id=parent_agent_id,
                    child_candidate_id=child_candidate_id,
                    stage=Stage.MUTATE_AST,
                    result="SUCCESS",
                    duration_ms=int((time.time() - s0) * 1000),
                )

                current_stage = Stage.SANDBOX_RUN
                s1 = time.time()
                sandbox_result = run_sandbox_stage(
                    sandbox=sandbox,
                    target_path=candidate_path,
                    cycle_id=cycle_id,
                    parent_agent_id=parent_agent_id,
                    child_candidate_id=child_candidate_id,
                    timeout=3.0,
                )
                sandbox_duration = int((time.time() - s1) * 1000)
                sandbox_error = None
                if not sandbox_result.success:
                    if sandbox_result.exception_type == "TimeoutExpired":
                        sandbox_error = TaxonomyErrorCode.SANDBOX_TIMEOUT
                    elif sandbox_result.exit_code:
                        sandbox_error = TaxonomyErrorCode.TEST_FAIL
                if not sandbox_result.success:
                    mark_failure(
                        Stage.SANDBOX_RUN,
                        error_code=sandbox_error or TaxonomyErrorCode.UNKNOWN,
                        duration_ms=sandbox_duration,
                        sandbox_exit_code=sandbox_result.exit_code,
                        notes={"exception_type": sandbox_result.exception_type},
                    )
                    log_mutation_cycle(
                        cycle_id=cycle_id,
                        parent_agent_id=parent_agent_id,
                        child_candidate_id=child_candidate_id,
                        final_result="FAIL",
                        dominant_stage=dominant_stage,
                        dominant_error_code=dominant_error,
                        duration_ms=int((time.time() - t0) * 1000),
                    )
                    cycle_logged = True
                    return
                log_mutation_stage(
                    cycle_id=cycle_id,
                    parent_agent_id=parent_agent_id,
                    child_candidate_id=child_candidate_id,
                    stage=Stage.SANDBOX_RUN,
                    result="SUCCESS",
                    duration_ms=sandbox_duration,
                    error_code=sandbox_error,
                    sandbox_exit_code=sandbox_result.exit_code,
                )

                current_stage = Stage.FITNESS_EVAL
                fitness = sandbox.fitness_score()
                record_fitness_stage(
                    fitness=fitness,
                    threshold=0.5,
                    cycle_id=cycle_id,
                    parent_agent_id=parent_agent_id,
                    child_candidate_id=child_candidate_id,
                )
                log_mutation_stage(
                    cycle_id=cycle_id,
                    parent_agent_id=parent_agent_id,
                    child_candidate_id=child_candidate_id,
                    stage=Stage.FITNESS_EVAL,
                    result="SUCCESS",
                    duration_ms=0,
                    notes={"fitness": fitness, "threshold": 0.5},
                )
                if fitness < 0.5:
                    mark_failure(Stage.FITNESS_EVAL, error_code=TaxonomyErrorCode.FITNESS_BELOW_THRESHOLD)
                    log_mutation_cycle(
                        cycle_id=cycle_id,
                        parent_agent_id=parent_agent_id,
                        child_candidate_id=child_candidate_id,
                        final_result="FAIL",
                        dominant_stage=dominant_stage,
                        dominant_error_code=dominant_error,
                        duration_ms=int((time.time() - t0) * 1000),
                    )
                    cycle_logged = True
                    return

                current_stage = Stage.CRYOVANT_CERT
                registry_payload = {
                    "agent": agent.info(),
                    "mutation": getattr(sandbox_result, "details", {}),
                    "sandbox_runtime": getattr(sandbox_result, "runtime_seconds", 0.0),
                    "artifact": str(candidate_path),
                }
                agent_id = str(uuid.uuid4())
                self.evolution_kernel.persist()
                meta_snapshot = self.meta_mutator.snapshot()
                record = self.registry.register_agent(
                    agent_id=agent_id,
                    name=agent.name,
                    payload=registry_payload,
                    classification="active" if sandbox_result and sandbox_result.success else "mutant",
                    generation=1,
                    fitness_score=fitness,
                    kernel_hash=self.evolution_kernel.fingerprint(),
                    policy_hash=meta_snapshot["fingerprint"],
                )
                cryovant_start = time.time()
                cryovant_ok = self.registry.certify_or_quarantine(record.payload, record.signature, artifact_path=str(candidate_path))
                cryovant_duration = int((time.time() - cryovant_start) * 1000)
                record_stage_metric(
                    cycle_id=cycle_id,
                    parent_agent_id=agent.name,
                    child_candidate_id=child_candidate_id,
                    stage=MutationStage.CRYOVANT_CERT,
                    result=StageResult.SUCCESS if cryovant_ok else StageResult.FAIL,
                    duration_ms=cryovant_duration,
                    error_code=None if cryovant_ok else ErrorCode.CRYOVANT_SIGNING_FAILED,
                )
                event("cryovant_check", ok=cryovant_ok, agent_id=record.agent_id)
                if not cryovant_ok:
                    mark_failure(Stage.CRYOVANT_CERT, error_code=TaxonomyErrorCode.CRYOVANT_SIGNING_FAILED, duration_ms=cryovant_duration)
                    log_mutation_cycle(
                        cycle_id=cycle_id,
                        parent_agent_id=parent_agent_id,
                        child_candidate_id=child_candidate_id,
                        final_result="FAIL",
                        dominant_stage=dominant_stage,
                        dominant_error_code=dominant_error,
                        duration_ms=int((time.time() - t0) * 1000),
                    )
                    cycle_logged = True
                    raise RuntimeError("Cryovant integrity check failed")
                log_mutation_stage(
                    cycle_id=cycle_id,
                    parent_agent_id=parent_agent_id,
                    child_candidate_id=child_candidate_id,
                    stage=Stage.CRYOVANT_CERT,
                    result="SUCCESS",
                    duration_ms=cryovant_duration,
                )

                current_stage = Stage.PROMOTE
                log_mutation_stage(
                    cycle_id=cycle_id,
                    parent_agent_id=parent_agent_id,
                    child_candidate_id=child_candidate_id,
                    stage=Stage.PROMOTE,
                    result="SUCCESS",
                    duration_ms=0,
                )

                log_mutation_cycle(
                    cycle_id=cycle_id,
                    parent_agent_id=parent_agent_id,
                    child_candidate_id=child_candidate_id,
                    final_result="SUCCESS",
                    dominant_stage=dominant_stage,
                    dominant_error_code=dominant_error,
                    duration_ms=int((time.time() - t0) * 1000),
                )
                cycle_logged = True

            except BaseException as exc:
                classification = classify_exception(exc)
                failing_stage = dominant_stage or current_stage or Stage.MUTATE_AST
                log_mutation_stage(
                    cycle_id=cycle_id,
                    parent_agent_id=parent_agent_id,
                    child_candidate_id=child_candidate_id,
                    stage=failing_stage,
                    result="FAIL",
                    error_code=dominant_error or classification.error_code,
                    exception_type=classification.exception_type,
                    exception_msg_hash=classification.exception_msg_hash,
                    notes={"traceback_tail": classification.traceback_tail},
                )
                if not cycle_logged:
                    log_mutation_cycle(
                        cycle_id=cycle_id,
                        parent_agent_id=parent_agent_id,
                        child_candidate_id=child_candidate_id,
                        final_result="FAIL",
                        dominant_stage=dominant_stage or failing_stage,
                        dominant_error_code=dominant_error or classification.error_code,
                        duration_ms=int((time.time() - t0) * 1000),
                    )
                    cycle_logged = True
                raise

        proposals = self.architect_agent.governance_sweep()
        if proposals:
            export_path = self.architect_agent.export_proposals(proposals)
            event("architect_proposals", count=len(proposals), path=str(export_path))

        event(
            "mutation_cycle",
            success=bool(sandbox_result and sandbox_result.success),
            runtime=getattr(sandbox_result, "runtime_seconds", 0.0),
        )
        beast = BeastLoop(
            registry=self.registry,
            architect=self.architect_agent,
            kernel=self.evolution_kernel,
            meta_mutator=self.meta_mutator,
        )
        beast.tick()
        print("mutation_success", bool(sandbox_result and sandbox_result.success))


def main() -> None:
    orchestrator = Orchestrator()
    orchestrator.run_cycle()


if __name__ == "__main__":
    main()
