# SPDX-License-Identifier: Apache-2.0
"""
runtime.mutation.code_intel.function_graph
==========================================
AST-based call graph and dependency adjacency matrix.

Invariants
----------
INTEL-DET-0  graph_hash = sha256(json.dumps(adjacency, sort_keys=True, default=str))
INTEL-ISO-0  No imports from runtime.governance.* or runtime.ledger.*
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set


# ---------------------------------------------------------------------------
# Internal AST visitor
# ---------------------------------------------------------------------------

class _CallVisitor(ast.NodeVisitor):
    """Collect (caller_function, callee_name) pairs from an AST."""

    def __init__(self) -> None:
        self._current: Optional[str] = None
        self.edges: List[tuple[str, str]] = []
        self.functions: Set[str] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        previous = self._current
        self._current = node.name
        self.functions.add(node.name)
        self.generic_visit(node)
        self._current = previous

    visit_AsyncFunctionDef = visit_FunctionDef  # noqa: N815

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if self._current is not None:
            callee = _extract_callee_name(node.func)
            if callee:
                self.edges.append((self._current, callee))
        self.generic_visit(node)


def _extract_callee_name(func_node: ast.expr) -> Optional[str]:
    if isinstance(func_node, ast.Name):
        return func_node.id
    if isinstance(func_node, ast.Attribute):
        return func_node.attr
    return None


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------

@dataclass
class FunctionCallGraph:
    """Deterministic call graph derived from AST analysis of Python sources.

    Attributes
    ----------
    adjacency : dict[str, list[str]]
        Maps each function name to its list of called function names.
    functions : list[str]
        Sorted list of all function names discovered.
    source_files : list[str]
        Sorted list of source file paths analysed.
    graph_hash : str
        SHA-256 of the canonical adjacency JSON (INTEL-DET-0).
    """

    adjacency: Dict[str, List[str]] = field(default_factory=dict)
    functions: List[str] = field(default_factory=list)
    source_files: List[str] = field(default_factory=list)
    graph_hash: str = ""

    # ------------------------------------------------------------------
    # Factories
    # ------------------------------------------------------------------

    @classmethod
    def from_source(cls, source: str, filename: str = "<string>") -> "FunctionCallGraph":
        """Build a graph from a single Python source string."""
        try:
            tree = ast.parse(source, filename=filename)
        except SyntaxError:
            return cls(source_files=[filename])

        visitor = _CallVisitor()
        visitor.visit(tree)

        adjacency: Dict[str, List[str]] = {}
        for caller, callee in visitor.edges:
            adjacency.setdefault(caller, [])
            if callee not in adjacency[caller]:
                adjacency[caller].append(callee)

        # Stable sort
        for k in adjacency:
            adjacency[k].sort()

        graph_hash = _hash_adjacency(adjacency)
        return cls(
            adjacency=adjacency,
            functions=sorted(visitor.functions),
            source_files=[filename],
            graph_hash=graph_hash,
        )

    @classmethod
    def from_source_files(cls, paths: List[str]) -> "FunctionCallGraph":
        """Build a merged graph from a list of file paths."""
        combined_adjacency: Dict[str, List[str]] = {}
        all_functions: Set[str] = set()
        valid_paths: List[str] = []

        for path in sorted(paths):
            try:
                source = Path(path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            sub = cls.from_source(source, filename=path)
            valid_paths.append(path)
            all_functions.update(sub.functions)
            for caller, callees in sub.adjacency.items():
                existing = combined_adjacency.setdefault(caller, [])
                for c in callees:
                    if c not in existing:
                        existing.append(c)

        for k in combined_adjacency:
            combined_adjacency[k].sort()

        return cls(
            adjacency=combined_adjacency,
            functions=sorted(all_functions),
            source_files=valid_paths,
            graph_hash=_hash_adjacency(combined_adjacency),
        )

    @classmethod
    def from_source_tree(cls, root_dir: str, pattern: str = "*.py") -> "FunctionCallGraph":
        """Recursively collect all matching files under *root_dir*."""
        paths = [
            str(p)
            for p in sorted(Path(root_dir).rglob(pattern))
            if not any(part.startswith(".") for part in p.parts)
        ]
        return cls.from_source_files(paths)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def callees_of(self, function_name: str) -> List[str]:
        """Return the list of functions called by *function_name*."""
        return self.adjacency.get(function_name, [])

    def callers_of(self, function_name: str) -> List[str]:
        """Return all functions that call *function_name*."""
        return sorted(
            caller
            for caller, callees in self.adjacency.items()
            if function_name in callees
        )

    def to_dict(self) -> dict:
        return {
            "adjacency": self.adjacency,
            "functions": self.functions,
            "source_files": self.source_files,
            "graph_hash": self.graph_hash,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _hash_adjacency(adjacency: Dict[str, List[str]]) -> str:
    canonical = json.dumps(adjacency, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()
