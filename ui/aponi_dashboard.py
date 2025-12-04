# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
from __future__ import annotations

import json
import pathlib
from flask import Flask, jsonify
from runtime.population import PopulationManager

app = Flask(__name__)
REPORTS = pathlib.Path("reports")
population_manager = PopulationManager()
KERNEL_STATE = REPORTS / "evolution_kernel.json"
META_STATE = REPORTS / "meta_mutator.json"
POLICY_LOG = REPORTS / "policy_evolution.jsonl"


@app.get("/metrics")
def metrics():  # type: ignore[override]
    entries = []
    path = REPORTS / "metrics.jsonl"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                entries.append(json.loads(line))
            except Exception:
                continue
    return jsonify(entries)


@app.get("/lineage")
def lineage():  # type: ignore[override]
    entries = []
    path = REPORTS / "cryovant.jsonl"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                entries.append(json.loads(line))
            except Exception:
                continue
    return jsonify(entries)


@app.get("/lineage/<agent_id>")
def lineage_for_agent(agent_id: str):  # type: ignore[override]
    entries = []
    path = REPORTS / "lineage.jsonl"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                payload = json.loads(line)
            except Exception:
                continue
            if payload.get("agent_id") == agent_id or payload.get("ancestor_id") == agent_id:
                entries.append(payload)
    return jsonify(entries)


@app.get("/summary")
def summary():  # type: ignore[override]
    metrics = []
    metric_path = REPORTS / "metrics.jsonl"
    if metric_path.exists():
        for line in metric_path.read_text(encoding="utf-8").splitlines():
            try:
                metrics.append(json.loads(line))
            except Exception:
                continue
    total = len(metrics)
    success = sum(m.get("mutant_success", 0) for m in metrics)
    survival_rate = (success / total) if total else 0.0
    fitness_values = [m.get("beast_fitness") for m in metrics if m.get("beast_fitness") is not None]
    avg_fitness = sum(fitness_values) / len(fitness_values) if fitness_values else 0.0
    return jsonify({"total_cycles": total, "survival_rate": survival_rate, "avg_fitness": avg_fitness})


@app.get("/population")
def population():  # type: ignore[override]
    return jsonify([vars(entry) for entry in population_manager.list_population()])


@app.get("/fitness")
def fitness():  # type: ignore[override]
    scores = []
    path = REPORTS / "metrics.jsonl"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                scores.append(json.loads(line))
            except Exception:
                continue
    return jsonify(scores)


@app.get("/mutations")
def mutations():  # type: ignore[override]
    entries = []
    path = REPORTS / "metrics.jsonl"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                entries.append(json.loads(line))
            except Exception:
                continue
    return jsonify(entries)


@app.get("/cryovant/certifications")
def cryovant_certifications():  # type: ignore[override]
    entries = []
    path = REPORTS / "cryovant.jsonl"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                entries.append(json.loads(line))
            except Exception:
                continue
    return jsonify(entries)


@app.get("/proposals")
def proposals():  # type: ignore[override]
    exports = []
    arch_dir = REPORTS / "architect"
    if arch_dir.exists():
        for path in sorted(arch_dir.glob("architect_proposals_*.json")):
            try:
                exports.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue
        for path in sorted(arch_dir.glob("system_proposals_*.json")):
            try:
                exports.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue
    return jsonify(exports)


@app.get("/meta")
def meta():  # type: ignore[override]
    payload: dict[str, object] = {}
    if KERNEL_STATE.exists():
        payload["kernel"] = json.loads(KERNEL_STATE.read_text(encoding="utf-8"))
    if META_STATE.exists():
        payload["meta_mutator"] = json.loads(META_STATE.read_text(encoding="utf-8"))
    policy: list[object] = []
    if POLICY_LOG.exists():
        for line in POLICY_LOG.read_text(encoding="utf-8").splitlines():
            try:
                policy.append(json.loads(line))
            except Exception:
                continue
    payload["policy_evolution"] = policy
    return jsonify(payload)


def serve(host: str = "127.0.0.1", port: int = 8080) -> None:
    app.run(host=host, port=port)


if __name__ == "__main__":
    serve()
