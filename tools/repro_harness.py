"""Deterministic reproduction harness for mutation diagnostics."""
from __future__ import annotations

import argparse
import random
import uuid
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from app.dream_mode import SandboxExecutor
from app.mutation_pipeline import apply_mutation_with_checks, record_fitness_stage, run_sandbox_stage
from runtime.metrics import MutationStage, StageResult, record_stage_metric, ErrorCode
from runtime.population import PopulationManager

REPRO_ROOT = Path("reports/repro")
REPRO_ROOT.mkdir(parents=True, exist_ok=True)


def _clone_parent(parent_artifact: str, child_candidate_id: str) -> Path:
    parent_path = Path(parent_artifact)
    target = REPRO_ROOT / f"{child_candidate_id}.py"
    target.write_text(parent_path.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def run_repro(cycles: int, seed: int) -> None:
    random.seed(seed)
    population = PopulationManager()
    parent = population.ensure_seed()

    with SandboxExecutor() as sandbox:
        for idx in range(cycles):
            cycle_id = f"harness-{seed}-{idx}-{uuid.uuid4()}"
            child_id = f"candidate-{idx}-{uuid.uuid4()}"
            candidate_path = _clone_parent(parent.artifact, child_id)

            mutation_ok = apply_mutation_with_checks(
                target_path=candidate_path,
                mutate_fn=lambda src, i=idx: src + f"\n# harness-mutation-{seed}-{i}\n",
                sandbox=sandbox,
                cycle_id=cycle_id,
                parent_agent_id=parent.agent_id,
                child_candidate_id=child_id,
            )
            if not mutation_ok:
                continue

            sandbox_result = run_sandbox_stage(
                sandbox=sandbox,
                target_path=candidate_path,
                cycle_id=cycle_id,
                parent_agent_id=parent.agent_id,
                child_candidate_id=child_id,
                timeout=3.0,
            )
            record_fitness_stage(
                fitness=sandbox.fitness_score(),
                threshold=0.5,
                cycle_id=cycle_id,
                parent_agent_id=parent.agent_id,
                child_candidate_id=child_id,
            )
            record_stage_metric(
                cycle_id=cycle_id,
                parent_agent_id=parent.agent_id,
                child_candidate_id=child_id,
                stage=MutationStage.PROMOTE,
                result=StageResult.SUCCESS if sandbox_result.success else StageResult.FAIL,
                duration_ms=int(sandbox_result.runtime_seconds * 1000),
                error_code=None if sandbox_result.success else ErrorCode.PROMOTION_WRITE_FAILED,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Deterministic mutation harness")
    parser.add_argument("--cycles", type=int, default=3, help="number of mutations to attempt")
    parser.add_argument("--seed", type=int, default=42, help="seed for deterministic mutations")
    args = parser.parse_args()
    run_repro(cycles=args.cycles, seed=args.seed)


if __name__ == "__main__":
    main()
