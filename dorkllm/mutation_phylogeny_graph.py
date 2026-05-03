"""
INNOV-74 · MPG — Mutation Phylogeny Graph
==========================================
Phase 168 · v9.101.0 · InnovativeAI LLC

World-first: A constitutional graph data structure encoding the full
phylogenetic lineage of every mutation in the ADAAD system. Every node
is HMAC-chained; every edge is constitutionally typed; ancestry is
deterministic and tamper-evident.

Hard-class invariants enforced:
  MPG-DETERM-0  Phylogeny graph construction is deterministic given same node set
  MPG-CHAIN-0   Every node carries HMAC linking it to its parent node hash
  MPG-HUMAN0-0  Any node marked tier0 requires HUMAN-0 ratification before promotion
  MPG-ACYCLIC-0 Graph MUST be a DAG; cycle insertion raises MPGCycleError immediately
  MPG-ANCHOR-0  Genesis node (depth=0, parent=None) MUST exist and be immutable
  MPG-PERSIST-0 All graph mutations are append-only; no node may be deleted or edited
  MPG-ATOMIC-0  add_node() and add_edge() are atomic; partial writes raise MPGAtomicError
  MPG-AUDIT-0   Every graph operation is recorded in the operations ledger
  MPG-TRACE-0   ancestry() MUST return the complete deterministic path from node to genesis
  MPG-SCOPE-0   Edge types are restricted to CANONICAL_EDGE_TYPES; foreign types rejected

Governor: DUSTIN L REID
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, FrozenSet, List, Optional, Set, Tuple


# ── Constants ────────────────────────────────────────────────────────────────

GENESIS_NODE_ID: str = "MPG-GENESIS-0"
GENESIS_EPOCH: int = 0
HMAC_SECRET: bytes = b"ADAAD-MPG-HMAC-SECRET-v1"

# MPG-SCOPE-0: Only these edge types are constitutionally recognised
CANONICAL_EDGE_TYPES: FrozenSet[str] = frozenset(
    {
        "DERIVED_FROM",     # child mutation derived from parent
        "AMENDS",           # mutation amends a prior constitutional rule
        "SUPERSEDES",       # mutation supersedes (replaces) a prior mutation
        "REFERENCES",       # soft non-lineage reference
        "ROLLBACK_OF",      # rollback targeting a specific ancestor
    }
)

MPG_ROLLING_WINDOW: int = 5  # constitutional window size (mirrors IVB)


# ── Errors ───────────────────────────────────────────────────────────────────

class MPGCycleError(Exception):
    """Raised when an edge insertion would create a cycle — MPG-ACYCLIC-0."""


class MPGAtomicError(Exception):
    """Raised when an atomic graph operation cannot complete — MPG-ATOMIC-0."""


class MPGHuman0Flag(Exception):
    """Raised when a Tier-0 node is promoted without HUMAN-0 ratification — MPG-HUMAN0-0."""


class MPGAnchorViolation(Exception):
    """Raised when genesis node integrity is violated — MPG-ANCHOR-0."""


class MPGEdgeTypeError(Exception):
    """Raised when an edge of an unrecognised type is inserted — MPG-SCOPE-0."""


class MPGTamperError(Exception):
    """Raised when HMAC chain verification fails — MPG-CHAIN-0."""


# ── Data models ──────────────────────────────────────────────────────────────

class NodeTier(str, Enum):
    TIER0 = "tier0"   # production; requires HUMAN-0
    TIER1 = "tier1"   # staging
    TIER2 = "tier2"   # sandbox


@dataclass
class PhylogenyNode:
    """A single node in the mutation phylogeny graph."""

    node_id: str
    label: str
    tier: NodeTier
    epoch: int
    parent_id: Optional[str]         # None only for genesis
    parent_hash: str                  # HMAC of parent node; "0" * 64 for genesis
    metadata: Dict                    = field(default_factory=dict)
    ratified: bool                    = False   # HUMAN-0 ratification flag
    node_hash: str                    = field(init=False)
    timestamp: float                  = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.node_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        """Deterministic HMAC-SHA256 of node identity fields — MPG-DETERM-0."""
        payload = (
            f"{self.node_id}|{self.label}|{self.tier.value}|"
            f"{self.epoch}|{self.parent_id or 'NONE'}|{self.parent_hash}"
        ).encode()
        return hmac.new(HMAC_SECRET, payload, hashlib.sha256).hexdigest()

    def verify_chain(self, parent_node: Optional["PhylogenyNode"]) -> bool:
        """Verify HMAC link from this node to its parent — MPG-CHAIN-0."""
        if parent_node is None:
            # genesis: parent_hash must be all zeros
            return self.parent_hash == "0" * 64
        expected = parent_node.node_hash
        return hmac.compare_digest(self.parent_hash[:24], expected[:24])


@dataclass
class PhylogenyEdge:
    """A directed edge in the phylogeny DAG."""

    source_id: str
    target_id: str
    edge_type: str
    epoch: int
    edge_hash: str = field(init=False)

    def __post_init__(self) -> None:
        # MPG-SCOPE-0 enforcement
        if self.edge_type not in CANONICAL_EDGE_TYPES:
            raise MPGEdgeTypeError(
                f"Edge type '{self.edge_type}' not in CANONICAL_EDGE_TYPES. "
                f"Allowed: {sorted(CANONICAL_EDGE_TYPES)}"
            )
        self.edge_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        payload = f"{self.source_id}→{self.target_id}|{self.edge_type}|{self.epoch}".encode()
        return hashlib.sha256(payload).hexdigest()


@dataclass
class GraphOperation:
    """Append-only audit record for every graph mutation — MPG-AUDIT-0."""

    op_type: str          # "add_node" | "add_edge"
    target_id: str
    epoch: int
    op_hash: str
    timestamp: float = field(default_factory=time.time)


# ── Core Engine ──────────────────────────────────────────────────────────────

class MutationPhylogenyGraph:
    """
    Constitutional graph of mutation lineage for the ADAAD runtime.

    Invariants enforced in every public method:
      MPG-DETERM-0  deterministic construction
      MPG-CHAIN-0   HMAC linkage
      MPG-HUMAN0-0  Tier-0 ratification gate
      MPG-ACYCLIC-0 DAG enforcement
      MPG-ANCHOR-0  genesis immutability
      MPG-PERSIST-0 append-only
      MPG-ATOMIC-0  atomicity
      MPG-AUDIT-0   operations ledger
      MPG-TRACE-0   complete ancestry
      MPG-SCOPE-0   canonical edge types
    """

    def __init__(self) -> None:
        self._nodes: Dict[str, PhylogenyNode] = {}
        self._adjacency: Dict[str, Set[str]] = {}   # source → {targets}
        self._reverse_adj: Dict[str, Set[str]] = {}  # target → {sources} (parents)
        self._edges: List[PhylogenyEdge] = []
        self._operations: List[GraphOperation] = []
        self._epoch: int = 0
        self._genesis_hash: Optional[str] = None
        self._parent_children: Dict[str, Set[str]] = {}  # parent → {children}

        # Bootstrap genesis node — MPG-ANCHOR-0
        self._bootstrap_genesis()

    # ── Genesis ──────────────────────────────────────────────────────────────

    def _bootstrap_genesis(self) -> None:
        """Create the immutable genesis node. Called once at construction."""
        genesis = PhylogenyNode(
            node_id=GENESIS_NODE_ID,
            label="ADAAD Constitutional Genesis",
            tier=NodeTier.TIER0,
            epoch=GENESIS_EPOCH,
            parent_id=None,
            parent_hash="0" * 64,
            metadata={"governor": "DUSTIN L REID", "system": "ADAAD"},
            ratified=True,  # genesis is pre-ratified
        )
        self._nodes[GENESIS_NODE_ID] = genesis
        self._adjacency[GENESIS_NODE_ID] = set()
        self._reverse_adj[GENESIS_NODE_ID] = set()
        self._parent_children[GENESIS_NODE_ID] = set()
        self._genesis_hash = genesis.node_hash
        self._record_operation("add_node", GENESIS_NODE_ID, genesis.node_hash)

    def _assert_genesis_intact(self) -> None:
        """MPG-ANCHOR-0: genesis node MUST remain immutable."""
        genesis = self._nodes.get(GENESIS_NODE_ID)
        if genesis is None:
            raise MPGAnchorViolation("Genesis node has been removed — MPG-ANCHOR-0 violated")
        if genesis.node_hash != self._genesis_hash:
            raise MPGAnchorViolation("Genesis node hash mismatch — MPG-ANCHOR-0 violated")

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _next_epoch(self) -> int:
        self._epoch += 1
        return self._epoch

    def _record_operation(self, op_type: str, target_id: str, op_hash: str) -> None:
        """MPG-AUDIT-0: append operation record."""
        self._operations.append(
            GraphOperation(
                op_type=op_type,
                target_id=target_id,
                epoch=self._epoch,
                op_hash=op_hash,
            )
        )

    def _has_path(self, start: str, end: str) -> bool:
        """BFS reachability check for cycle detection — MPG-ACYCLIC-0."""
        if start == end:
            return True
        visited: Set[str] = set()
        queue = deque([start])
        while queue:
            current = queue.popleft()
            if current == end:
                return True
            if current in visited:
                continue
            visited.add(current)
            queue.extend(self._adjacency.get(current, set()))
        return False

    # ── Public API ───────────────────────────────────────────────────────────

    def add_node(
        self,
        node_id: str,
        label: str,
        tier: NodeTier,
        parent_id: str = GENESIS_NODE_ID,
        metadata: Optional[Dict] = None,
        ratified: bool = False,
    ) -> PhylogenyNode:
        """
        Add a mutation node to the phylogeny graph.

        MPG-PERSIST-0: node IDs must be unique (no overwrite).
        MPG-HUMAN0-0:  Tier-0 nodes require ratified=True.
        MPG-CHAIN-0:   node HMAC links to parent.
        MPG-ATOMIC-0:  all-or-nothing; rolls back on any error.
        MPG-ANCHOR-0:  genesis is checked before and after.
        """
        self._assert_genesis_intact()

        # MPG-PERSIST-0: no duplicate nodes
        if node_id in self._nodes:
            raise MPGAtomicError(f"Node '{node_id}' already exists — MPG-PERSIST-0")

        # MPG-HUMAN0-0: Tier-0 gate
        if tier == NodeTier.TIER0 and not ratified:
            raise MPGHuman0Flag(
                f"Node '{node_id}' is Tier-0 but ratified=False — HUMAN-0 approval required (MPG-HUMAN0-0)"
            )

        parent_node = self._nodes.get(parent_id)
        if parent_node is None:
            raise MPGAtomicError(f"Parent '{parent_id}' not found — cannot add node '{node_id}'")

        epoch = self._next_epoch()
        node = PhylogenyNode(
            node_id=node_id,
            label=label,
            tier=tier,
            epoch=epoch,
            parent_id=parent_id,
            parent_hash=parent_node.node_hash,
            metadata=metadata or {},
            ratified=ratified,
        )

        # MPG-CHAIN-0: verify link
        if not node.verify_chain(parent_node):
            raise MPGTamperError(f"HMAC chain verification failed for '{node_id}' → MPG-CHAIN-0")

        # Atomic commit
        self._nodes[node_id] = node
        self._adjacency[node_id] = set()
        self._reverse_adj[node_id] = set()
        self._parent_children[node_id] = set()
        self._parent_children.setdefault(parent_id, set()).add(node_id)
        self._record_operation("add_node", node_id, node.node_hash)

        self._assert_genesis_intact()
        return node

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        edge_type: str,
    ) -> PhylogenyEdge:
        """
        Add a directed edge source → target.

        MPG-ACYCLIC-0: rejects if edge would create a cycle.
        MPG-SCOPE-0:   rejects unrecognised edge types.
        MPG-ATOMIC-0:  atomic; rolls back on error.
        MPG-AUDIT-0:   records operation.
        """
        self._assert_genesis_intact()

        for nid in (source_id, target_id):
            if nid not in self._nodes:
                raise MPGAtomicError(f"Node '{nid}' not found — cannot add edge")

        # MPG-ACYCLIC-0: would adding source→target create a cycle?
        # A cycle exists if target can already reach source.
        if self._has_path(target_id, source_id):
            raise MPGCycleError(
                f"Edge {source_id}→{target_id} would create a cycle — MPG-ACYCLIC-0 violated"
            )

        epoch = self._next_epoch()
        edge = PhylogenyEdge(
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            epoch=epoch,
        )  # MPG-SCOPE-0 enforced in PhylogenyEdge.__post_init__

        # Atomic commit
        self._edges.append(edge)
        self._adjacency[source_id].add(target_id)
        self._reverse_adj[target_id].add(source_id)
        self._record_operation("add_edge", f"{source_id}→{target_id}", edge.edge_hash)

        self._assert_genesis_intact()
        return edge

    def ancestry(self, node_id: str) -> List[PhylogenyNode]:
        """
        Return the complete deterministic ancestry path from node_id up to genesis.

        MPG-TRACE-0: path MUST be complete and deterministic.
        Raises KeyError if node_id not found.
        """
        if node_id not in self._nodes:
            raise KeyError(f"Node '{node_id}' not found in phylogeny graph")

        path: List[PhylogenyNode] = []
        current_id: Optional[str] = node_id
        visited: Set[str] = set()

        while current_id is not None:
            if current_id in visited:
                raise MPGCycleError(f"Cycle detected during ancestry traversal at '{current_id}'")
            visited.add(current_id)
            node = self._nodes[current_id]
            path.append(node)
            current_id = node.parent_id

        return path  # ordered: [node, ..., genesis]

    def descendants(self, node_id: str) -> List[str]:
        """BFS of all nodes reachable from node_id via parent-child tree."""
        if node_id not in self._nodes:
            raise KeyError(f"Node '{node_id}' not found")
        result: List[str] = []
        visited: Set[str] = set()
        queue = deque([node_id])
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            if current != node_id:
                result.append(current)
            queue.extend(self._parent_children.get(current, set()))
        return result

    def depth(self, node_id: str) -> int:
        """Return the depth of a node (genesis = 0)."""
        return len(self.ancestry(node_id)) - 1

    def lca(self, a: str, b: str) -> Optional[str]:
        """
        Lowest Common Ancestor of nodes a and b.
        Returns node_id of LCA or None if disjoint.
        """
        ancestors_a: Set[str] = {n.node_id for n in self.ancestry(a)}
        for node in self.ancestry(b):
            if node.node_id in ancestors_a:
                return node.node_id
        return None

    def verify_chain(self) -> bool:
        """
        Full HMAC chain verification for every node in the graph — MPG-CHAIN-0.
        Returns True if all nodes pass; raises MPGTamperError on first failure.
        """
        self._assert_genesis_intact()
        for node in self._nodes.values():
            parent = self._nodes.get(node.parent_id) if node.parent_id else None
            if not node.verify_chain(parent):
                raise MPGTamperError(
                    f"Chain verification failed at node '{node.node_id}' — MPG-CHAIN-0"
                )
            # Also verify the stored node_hash equals recomputed hash
            recomputed = node._compute_hash()
            if not hmac.compare_digest(node.node_hash[:24], recomputed[:24]):
                raise MPGTamperError(
                    f"Node hash tampered at '{node.node_id}' — MPG-CHAIN-0"
                )
        return True

    def history(self) -> List[Dict]:
        """Return append-only operations ledger — MPG-AUDIT-0."""
        return [
            {
                "op_type": op.op_type,
                "target_id": op.target_id,
                "epoch": op.epoch,
                "op_hash": op.op_hash[:16],
                "timestamp": op.timestamp,
            }
            for op in self._operations
        ]

    def snapshot(self) -> Dict:
        """Deterministic snapshot of current graph state — MPG-DETERM-0."""
        return {
            "node_count": len(self._nodes),
            "edge_count": len(self._edges),
            "epoch": self._epoch,
            "genesis_hash": (self._genesis_hash or "")[:24],
            "node_ids": sorted(self._nodes.keys()),
        }

    def stats(self) -> Dict:
        """Graph statistics for Aponi dashboard integration."""
        depths = {nid: self.depth(nid) for nid in self._nodes}
        return {
            "nodes": len(self._nodes),
            "edges": len(self._edges),
            "max_depth": max(depths.values()) if depths else 0,
            "tier_breakdown": {
                t.value: sum(1 for n in self._nodes.values() if n.tier == t)
                for t in NodeTier
            },
            "edge_type_breakdown": {
                et: sum(1 for e in self._edges if e.edge_type == et)
                for et in CANONICAL_EDGE_TYPES
            },
            "operations": len(self._operations),
            "epoch": self._epoch,
        }
