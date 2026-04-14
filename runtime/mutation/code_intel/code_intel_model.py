# SPDX-License-Identifier: Apache-2.0
"""
runtime.mutation.code_intel.code_intel_model
============================================
Unified frozen code-intelligence snapshot consumed by the ProposalEngine.

Invariants
----------
INTEL-ISO-0  No imports from runtime.governance.* or runtime.ledger.*
INTEL-DET-0  model_hash = sha256(json.dumps(state, sort_keys=True, default=str))
INTEL-TS-0   snapshot_timestamp set via RuntimeDeterminismProvider.now_utc()
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from runtime.mutation.code_intel.function_graph import FunctionCallGraph
from runtime.mutation.code_intel.hotspot_map import HotspotMap
from runtime.mutation.code_intel.mutation_history import MutationHistory


# ---------------------------------------------------------------------------
# Determinism shim (no governance import — INTEL-ISO-0)
# ---------------------------------------------------------------------------

class _LocalDeterminismProvider:
    @staticmethod
    def now_utc() -> str:
        import datetime
        return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00","Z")


def _get_provider() -> Any:
    try:
        from runtime.determinism import RuntimeDeterminismProvider  # type: ignore
        return RuntimeDeterminismProvider
    except ImportError:
        return _LocalDeterminismProvider


# ---------------------------------------------------------------------------
# Frozen snapshot
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CodeIntelModel:
    """Immutable code-intelligence snapshot for ProposalEngine enrichment.

    Build via :meth:`build` — do not construct directly.

    Attributes
    ----------
    snapshot_timestamp : str
        ISO-8601 UTC creation time (INTEL-TS-0).
    model_hash : str
        SHA-256 of the full model state dict (INTEL-DET-0).
    call_graph : FunctionCallGraph
        AST-derived call graph and adjacency.
    hotspot_map : HotspotMap
        Ranked fragility/complexity/churn map.
    history_count : int
        Total mutation records in the history ledger at snapshot time.
    top_hotspots : tuple[str, ...]
        Immutable ordered top-hotspot file paths.
    churn_map : dict[str, float]
        Normalised per-file churn scores [0, 1].
    graph_hash : str
        Convenience alias for call_graph.graph_hash.
    hotspot_hash : str
        Convenience alias for hotspot_map.map_hash.
    """

    snapshot_timestamp: str
    model_hash: str
    call_graph: FunctionCallGraph
    hotspot_map: HotspotMap
    history_count: int
    top_hotspots: tuple
    churn_map: Dict[str, float]
    graph_hash: str
    hotspot_hash: str

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def build(
        cls,
        call_graph: FunctionCallGraph,
        hotspot_map: HotspotMap,
        history: Optional[MutationHistory] = None,
    ) -> "CodeIntelModel":
        """Construct a frozen snapshot from the three sub-components.

        Parameters
        ----------
        call_graph:  Pre-built FunctionCallGraph.
        hotspot_map: Pre-built HotspotMap.
        history:     Optional MutationHistory; used for history_count and churn_map.
        """
        provider = _get_provider()
        ts = provider.now_utc()

        history_count = history.count if history else 0
        churn_map = history.normalised_churn_map() if history else {}

        state: Dict[str, Any] = {
            "snapshot_timestamp": ts,
            "graph_hash": call_graph.graph_hash,
            "hotspot_hash": hotspot_map.map_hash,
            "history_count": history_count,
            "top_hotspots": hotspot_map.top_hotspots,
            "churn_map": churn_map,
        }
        model_hash = hashlib.sha256(
            json.dumps(state, sort_keys=True, default=str).encode()
        ).hexdigest()

        return cls(
            snapshot_timestamp=ts,
            model_hash=model_hash,
            call_graph=call_graph,
            hotspot_map=hotspot_map,
            history_count=history_count,
            top_hotspots=tuple(hotspot_map.top_hotspots),
            churn_map=churn_map,
            graph_hash=call_graph.graph_hash,
            hotspot_hash=hotspot_map.map_hash,
        )

    # ------------------------------------------------------------------
    # Serialisation (frozen dataclass needs helper — cannot mutate)
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable snapshot summary."""
        return {
            "snapshot_timestamp": self.snapshot_timestamp,
            "model_hash": self.model_hash,
            "graph_hash": self.graph_hash,
            "hotspot_hash": self.hotspot_hash,
            "history_count": self.history_count,
            "top_hotspots": list(self.top_hotspots),
            "churn_map": self.churn_map,
            "function_count": len(self.call_graph.functions),
            "source_files": self.call_graph.source_files,
            "hotspot_entries": len(self.hotspot_map.entries),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, default=str)

    # ------------------------------------------------------------------
    # Enrichment helpers for ProposalEngine
    # ------------------------------------------------------------------

    def hotspot_score_for(self, filepath: str) -> float:
        """Return the hotspot_score [0, 1] for *filepath*, or 0.0 if unknown."""
        entry = self.hotspot_map.entry_for(filepath)
        return entry.hotspot_score if entry else 0.0

    def callers_of(self, function_name: str) -> List[str]:
        """Delegate call-graph reverse lookup to the embedded graph."""
        return self.call_graph.callers_of(function_name)

    def callees_of(self, function_name: str) -> List[str]:
        return self.call_graph.callees_of(function_name)

    def is_top_hotspot(self, filepath: str) -> bool:
        return filepath in self.top_hotspots

    def churn_score_for(self, filepath: str) -> float:
        return self.churn_map.get(filepath, 0.0)
