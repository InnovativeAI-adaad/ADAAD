"""Main orchestration loop for evaluating agents."""
from __future__ import annotations

from pathlib import Path
from time import monotonic
from typing import Iterable

from adad_core.eval.fitness import evaluate_agent, log_fitness, record_metric
from adad_core.eval.iq_tasks import run_iq_tasks
from adad_core.evolve.selector import select_action, summarize
from adad_core.io.atomic import append_jsonl
from adad_core.runtime.sandbox import list_scripts, run_script

AGENTS = Path("adad_core/agents")
LOGS = Path("data/logs")
QUAR = Path("data/quarantine")


def _log_lineage(path: Path, action: str, fitness: float) -> None:
    append_jsonl(LOGS / "lineage.jsonl", {"path": str(path), "action": action, "fitness": fitness})


def _quarantine(path: Path) -> None:
    QUAR.mkdir(parents=True, exist_ok=True)
    qp = QUAR / path.name
    qp.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")


def evaluate_scripts(scripts: Iterable[Path]) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    selections = []
    for script in scripts:
        start = monotonic()
        result = run_script(str(script))
        iq_scores = run_iq_tasks(script.name)
        fitness = evaluate_agent(script.name, result["ok"], iq_scores)
        runtime = monotonic() - start
        log_fitness(script.name, fitness, runtime)
        record_metric(
            "evaluation",
            {
                "agent_id": script.name,
                "ok": result["ok"],
                "runtime": runtime,
                "fitness": fitness,
            },
        )
        _log_lineage(script, "eval", fitness)
        selection = select_action(script, fitness)
        selections.append(selection)
        _log_lineage(script, selection.action, fitness)
        if selection.action == "quarantine":
            _quarantine(script)
    if selections:
        record_metric("cycle_summary", summarize(selections))


def cycle_once() -> None:
    scripts = list_scripts(AGENTS)
    evaluate_scripts(scripts)
