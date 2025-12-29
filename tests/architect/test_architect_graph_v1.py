# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from app.agents.architect_graph_v1 import ArchitectGraph


def _write_agent(root: Path, name: str, imports: list[str]) -> Path:
    agent_dir = root / name
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "meta.json").write_text('{"id": "%s"}' % name, encoding="utf-8")
    (agent_dir / "dna.json").write_text('{"lineage": "seed"}', encoding="utf-8")
    (agent_dir / "certificate.json").write_text('{"status": "ok"}', encoding="utf-8")
    init = "\n".join([f"import {imp}" for imp in imports]) + "\n"
    (agent_dir / "__init__.py").write_text(init, encoding="utf-8")
    return agent_dir


def test_hidden_agents_are_excluded(tmp_path: Path) -> None:
    agents_root = tmp_path / "agents"
    _write_agent(agents_root, "alpha", ["runtime.metrics", "app.agents.base_agent"])
    _write_agent(agents_root, "beta", [])
    _write_agent(agents_root, ".hidden_agent", ["runtime.metrics"])

    graph = ArchitectGraph(agents_root=agents_root, repo_root=tmp_path).build()
    agent_ids = {node["id"] for node in graph["agents"]}

    assert agent_ids == {"alpha", "beta"}

    edges = {(edge["source"], edge["target"]) for edge in graph["edges"]}
    assert ("alpha", "runtime.metrics") in edges
    assert ("alpha", "app.agents.base_agent") in edges
    assert all(src in agent_ids for src, _ in edges)

    dot = ArchitectGraph.to_dot(graph)
    assert '"alpha"' in dot and '"beta"' in dot
    assert '-> "runtime.metrics"' in dot
