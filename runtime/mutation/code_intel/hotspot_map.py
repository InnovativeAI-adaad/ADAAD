# SPDX-License-Identifier: Apache-2.0
"""
runtime.mutation.code_intel.hotspot_map
=======================================
Ranked fragility, complexity, and churn map for source files and functions.

Invariants
----------
INTEL-DET-0  map_hash = sha256(json.dumps(scores, sort_keys=True, default=str))
INTEL-ISO-0  No imports from runtime.governance.* or runtime.ledger.*

Scoring model
-------------
All scores are bounded to [0.0, 1.0].

complexity_score  Cyclomatic-proxy: normalised branch-node count in AST.
fragility_score   Ratio of exception-handling blocks to total functions.
churn_score       External input — pass via MutationHistory or zero if absent.
hotspot_score     Weighted combination: 0.4*complexity + 0.35*fragility + 0.25*churn
"""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


# Branch AST node types that contribute to complexity proxy
_BRANCH_NODES = (
    ast.If,
    ast.For,
    ast.While,
    ast.ExceptHandler,
    ast.With,
    ast.AsyncFor,
    ast.AsyncWith,
    ast.Assert,
    ast.comprehension,
)

_COMPLEXITY_WEIGHT = 0.40
_FRAGILITY_WEIGHT = 0.35
_CHURN_WEIGHT = 0.25
_MAX_BRANCH_NORM = 50.0  # branch count normalisation ceiling


@dataclass
class FileHotspotEntry:
    """Hotspot scores for a single source file."""

    filepath: str
    complexity_score: float = 0.0
    fragility_score: float = 0.0
    churn_score: float = 0.0
    hotspot_score: float = 0.0
    branch_count: int = 0
    function_count: int = 0
    handler_count: int = 0

    def to_dict(self) -> dict:
        return {
            "filepath": self.filepath,
            "complexity_score": self.complexity_score,
            "fragility_score": self.fragility_score,
            "churn_score": self.churn_score,
            "hotspot_score": self.hotspot_score,
            "branch_count": self.branch_count,
            "function_count": self.function_count,
            "handler_count": self.handler_count,
        }


@dataclass
class HotspotMap:
    """Ranked hotspot map across a collection of source files.

    Attributes
    ----------
    entries : list[FileHotspotEntry]
        Entries sorted descending by hotspot_score.
    map_hash : str
        SHA-256 of the canonical scores JSON (INTEL-DET-0).
    top_hotspots : list[str]
        File paths of the top-N hotspot files (default N=10).
    """

    entries: List[FileHotspotEntry] = field(default_factory=list)
    map_hash: str = ""
    top_hotspots: List[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Factories
    # ------------------------------------------------------------------

    @classmethod
    def from_source_files(
        cls,
        paths: List[str],
        churn_map: Optional[Dict[str, float]] = None,
        top_n: int = 10,
    ) -> "HotspotMap":
        """Compute hotspot scores for *paths*.

        Parameters
        ----------
        paths:      List of .py source file paths.
        churn_map:  Optional dict mapping filepath → normalised churn score [0,1].
        top_n:      How many files to include in top_hotspots.
        """
        churn_map = churn_map or {}
        entries: List[FileHotspotEntry] = []

        for path in sorted(paths):
            try:
                source = Path(path).read_text(encoding="utf-8")
                entry = _score_source(source, path, churn_map.get(path, 0.0))
            except (OSError, UnicodeDecodeError, SyntaxError):
                entry = FileHotspotEntry(filepath=path)
            entries.append(entry)

        entries.sort(key=lambda e: e.hotspot_score, reverse=True)
        map_hash = _hash_entries(entries)
        top = [e.filepath for e in entries[:top_n]]

        return cls(entries=entries, map_hash=map_hash, top_hotspots=top)

    @classmethod
    def from_source_tree(
        cls,
        root_dir: str,
        churn_map: Optional[Dict[str, float]] = None,
        pattern: str = "*.py",
        top_n: int = 10,
    ) -> "HotspotMap":
        paths = [
            str(p)
            for p in sorted(Path(root_dir).rglob(pattern))
            if not any(part.startswith(".") for part in p.parts)
        ]
        return cls.from_source_files(paths, churn_map=churn_map, top_n=top_n)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def entry_for(self, filepath: str) -> Optional[FileHotspotEntry]:
        for e in self.entries:
            if e.filepath == filepath:
                return e
        return None

    def to_dict(self) -> dict:
        return {
            "entries": [e.to_dict() for e in self.entries],
            "map_hash": self.map_hash,
            "top_hotspots": self.top_hotspots,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _score_source(source: str, filepath: str, churn: float) -> FileHotspotEntry:
    tree = ast.parse(source, filename=filepath)

    branch_count = sum(1 for node in ast.walk(tree) if isinstance(node, _BRANCH_NODES))
    handler_count = sum(
        1 for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)
    )
    function_count = sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )

    complexity = _clamp(branch_count / _MAX_BRANCH_NORM)
    fragility = (
        _clamp(handler_count / function_count) if function_count > 0 else 0.0
    )
    churn_s = _clamp(churn)

    hotspot = _clamp(
        _COMPLEXITY_WEIGHT * complexity
        + _FRAGILITY_WEIGHT * fragility
        + _CHURN_WEIGHT * churn_s
    )

    return FileHotspotEntry(
        filepath=filepath,
        complexity_score=round(complexity, 6),
        fragility_score=round(fragility, 6),
        churn_score=round(churn_s, 6),
        hotspot_score=round(hotspot, 6),
        branch_count=branch_count,
        function_count=function_count,
        handler_count=handler_count,
    )


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(value)))


def _hash_entries(entries: List[FileHotspotEntry]) -> str:
    scores = {e.filepath: e.hotspot_score for e in entries}
    canonical = json.dumps(scores, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()
