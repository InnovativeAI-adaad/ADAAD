from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Set

from app.agents import AGENTS_ROOT
from app.agents.discovery import iter_agent_dirs, resolve_agent_id


GraphDict = Dict[str, object]


def _read_json(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _collect_imports(py_file: Path) -> Set[str]:
    imports: Set[str] = set()
    if not py_file.exists():
        return imports

    try:
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
    except Exception:
        return imports

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
    return imports


@dataclass
class ArchitectGraph:
    agents_root: Path = AGENTS_ROOT
    repo_root: Path = field(default_factory=lambda: Path(__file__).resolve().parents[2])
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def _agent_nodes(self) -> Iterable[Dict[str, object]]:
        for agent_dir in iter_agent_dirs(self.agents_root):
            agent_id = resolve_agent_id(agent_dir, self.agents_root)
            meta = _read_json(agent_dir / "meta.json")
            dna = _read_json(agent_dir / "dna.json")
            init_py = agent_dir / "__init__.py"
            imports = sorted(_collect_imports(init_py))

            yield {
                "id": agent_id,
                "path": str(agent_dir.relative_to(self.repo_root)),
                "meta": meta,
                "dna": dna,
                "imports": imports,
            }

    def build(self) -> GraphDict:
        nodes = list(self._agent_nodes())
        edges: List[Dict[str, str]] = []
        for node in nodes:
            for target in node["imports"]:
                edges.append({"source": node["id"], "target": target, "type": "import"})

        metadata = {
            "generated_at": self.generated_at.isoformat(),
            "agents_root": str(self.agents_root),
            "repo_root": str(self.repo_root),
            "node_count": len(nodes),
            "edge_count": len(edges),
        }
        return {"metadata": metadata, "agents": nodes, "edges": edges}

    @staticmethod
    def to_dot(graph: GraphDict) -> str:
        lines: List[str] = ["digraph architect {", '  node [shape=box];']
        for node in sorted(graph.get("agents", []), key=lambda n: n["id"]):
            lines.append(f'  "{node["id"]}" [label="{node["id"]}"];')
        for edge in sorted(graph.get("edges", []), key=lambda e: (e["source"], e["target"])):
            lines.append(f'  "{edge["source"]}" -> "{edge["target"]}" [label="{edge["type"]}"];')
        lines.append("}")
        return "\n".join(lines)

    def write(self, path: Path, as_dot: bool = False) -> Path:
        graph = self.build()
        payload = self.to_dot(graph) if as_dot else json.dumps(graph, ensure_ascii=False, indent=2)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
        return path


def _parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate ADAAD architect dependency graph.")
    parser.add_argument("--output", "-o", type=Path, default=Path("reports") / "system_dependency_graph.json")
    parser.add_argument("--format", "-f", choices=["json", "dot"], default="json")
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    graph = ArchitectGraph()
    graph.write(args.output, as_dot=args.format == "dot")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
