# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
"""Mutation pipeline helpers with structured taxonomy logging."""
from __future__ import annotations

import ast
import time
from pathlib import Path
from typing import Callable, Iterable, Tuple

from app.dream_mode import SandboxExecutor, MutationResult
from runtime.metrics import ErrorCode, MutationStage, StageResult, record_stage_metric

ALLOWED_IMPORT_ROOTS = {"app", "runtime", "security", "data", "reports"}


def _validate_syntax(source: str) -> Tuple[bool, ast.AST | None, BaseException | None]:
    try:
        return True, ast.parse(source), None
    except BaseException as exc:  # noqa: BLE001 - explicit surfacing for taxonomy
        return False, None, exc


def _collect_modules(tree: ast.AST) -> Iterable[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                yield node.module


def validate_import_roots(tree: ast.AST, repo_root: Path | None = None) -> Tuple[bool, list[str]]:
    repo_root = repo_root or Path.cwd()
    repo_dirs = {entry.name for entry in repo_root.iterdir() if entry.is_dir()}
    violations: list[str] = []
    for module in _collect_modules(tree):
        root = module.split(".")[0]
        if root in repo_dirs and root not in ALLOWED_IMPORT_ROOTS:
            violations.append(module)
    return not violations, violations


def apply_mutation_with_checks(
    *,
    target_path: Path,
    mutate_fn: Callable[[str], str],
    sandbox: SandboxExecutor,
    cycle_id: str,
    parent_agent_id: str,
    child_candidate_id: str,
) -> bool:
    """Apply a mutation and enforce syntax/import invariants with metrics."""

    original_source = target_path.read_text(encoding="utf-8", errors="ignore")
    syntax_ok, _, syntax_exc = _validate_syntax(original_source)
    if not syntax_ok:
        record_stage_metric(
            cycle_id=cycle_id,
            parent_agent_id=parent_agent_id,
            child_candidate_id=child_candidate_id,
            stage=MutationStage.MUTATE_AST,
            result=StageResult.FAIL,
            duration_ms=0,
            error_code=ErrorCode.AST_SYNTAX_ERROR,
            exception_type=syntax_exc.__class__.__name__ if syntax_exc else None,
            exception_message=str(syntax_exc) if syntax_exc else None,
        )
        return False

    mutation_result = sandbox.mutate(mutate_fn, original_source)
    if not mutation_result.success:
        record_stage_metric(
            cycle_id=cycle_id,
            parent_agent_id=parent_agent_id,
            child_candidate_id=child_candidate_id,
            stage=MutationStage.MUTATE_AST,
            result=StageResult.FAIL,
            duration_ms=int(mutation_result.runtime_seconds * 1000),
            error_code=ErrorCode.AST_SEMANTIC_BREAK,
            exception_type=mutation_result.exception_type,
            exception_message=mutation_result.exception_message,
        )
        return False

    mutated_source = mutation_result.details.get("output", "")
    syntax_ok, tree, syntax_exc = _validate_syntax(mutated_source)
    if not syntax_ok or tree is None:
        record_stage_metric(
            cycle_id=cycle_id,
            parent_agent_id=parent_agent_id,
            child_candidate_id=child_candidate_id,
            stage=MutationStage.MUTATE_AST,
            result=StageResult.FAIL,
            duration_ms=int(mutation_result.runtime_seconds * 1000),
            error_code=ErrorCode.AST_SYNTAX_ERROR,
            exception_type=syntax_exc.__class__.__name__ if syntax_exc else None,
            exception_message=str(syntax_exc) if syntax_exc else None,
        )
        return False

    imports_ok, violations = validate_import_roots(tree, target_path.parent)
    if not imports_ok:
        record_stage_metric(
            cycle_id=cycle_id,
            parent_agent_id=parent_agent_id,
            child_candidate_id=child_candidate_id,
            stage=MutationStage.MUTATE_AST,
            result=StageResult.FAIL,
            duration_ms=int(mutation_result.runtime_seconds * 1000),
            error_code=ErrorCode.IMPORT_CANONICAL_VIOLATION,
            exception_type="ImportViolation",
            exception_message=";".join(violations),
        )
        return False

    target_path.write_text(mutated_source, encoding="utf-8")
    record_stage_metric(
        cycle_id=cycle_id,
        parent_agent_id=parent_agent_id,
        child_candidate_id=child_candidate_id,
        stage=MutationStage.MUTATE_AST,
        result=StageResult.SUCCESS,
        duration_ms=int(mutation_result.runtime_seconds * 1000),
    )
    record_stage_metric(
        cycle_id=cycle_id,
        parent_agent_id=parent_agent_id,
        child_candidate_id=child_candidate_id,
        stage=MutationStage.BUILD_CHILD,
        result=StageResult.SUCCESS,
        duration_ms=0,
    )
    return True


def run_sandbox_stage(
    *,
    sandbox: SandboxExecutor,
    target_path: Path,
    cycle_id: str,
    parent_agent_id: str,
    child_candidate_id: str,
    timeout: float = 5.0,
) -> MutationResult:
    start = time.time()
    result = sandbox.run_python_file(target_path, timeout=timeout)
    duration_ms = int((time.time() - start) * 1000)

    error_code: ErrorCode | None = None
    if not result.success:
        if result.exception_type == "TimeoutExpired":
            error_code = ErrorCode.SANDBOX_TIMEOUT
        elif result.exit_code:
            error_code = ErrorCode.TEST_FAIL

    record_stage_metric(
        cycle_id=cycle_id,
        parent_agent_id=parent_agent_id,
        child_candidate_id=child_candidate_id,
        stage=MutationStage.SANDBOX_RUN,
        result=StageResult.SUCCESS if result.success else StageResult.FAIL,
        duration_ms=duration_ms,
        error_code=error_code,
        exception_type=result.exception_type,
        exception_message=result.exception_message,
        sandbox_exit_code=result.exit_code,
    )
    return result


def record_fitness_stage(
    *,
    fitness: float,
    threshold: float,
    cycle_id: str,
    parent_agent_id: str,
    child_candidate_id: str,
) -> None:
    is_success = fitness >= threshold
    record_stage_metric(
        cycle_id=cycle_id,
        parent_agent_id=parent_agent_id,
        child_candidate_id=child_candidate_id,
        stage=MutationStage.FITNESS_EVAL,
        result=StageResult.SUCCESS if is_success else StageResult.FAIL,
        duration_ms=0,
        error_code=None if is_success else ErrorCode.FITNESS_BELOW_THRESHOLD,
        extra={"fitness": fitness, "threshold": threshold},
    )


__all__ = [
    "apply_mutation_with_checks",
    "run_sandbox_stage",
    "record_fitness_stage",
    "validate_import_roots",
    "ALLOWED_IMPORT_ROOTS",
]
