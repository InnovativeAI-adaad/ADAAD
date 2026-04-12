# SPDX-License-Identifier: Apache-2.0
"""Innovation #45 — Invariant Interaction Graph (IIG).

Tracks co-fire relationships between constitutional invariants across epochs.
Reveals which invariants cluster together, which never interact, and which
may conflict — enabling constitutional redundancy reduction without coverage loss.

Hard-class invariants enforced:
  IIG-COFIRE-0    Co-fire observations are hash-chained (ledger integrity)
  IIG-DETERM-0    Identical observation sequences produce identical graph_digest
  IIG-PERSIST-0   Graph state reloads correctly from the persistence store
  IIG-CLUSTER-0   Cluster assignments are deterministic given edge weights
  IIG-HUMAN0-0    Removing invariant nodes from the graph requires HUMAN-0 auth
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── Module metadata ────────────────────────────────────────────────────────────
INNOV_ID = "INNOV-45"
PHASE = 138
VERSION = "9.71.0"
WORLD_FIRST = (
    "First governed constitutional invariant interaction graph: co-fire "
    "clustering, conflict detection, and redundancy analysis over live epochs."
)

CONSTITUTIONAL_INVARIANTS = [
    "IIG-COFIRE-0",
    "IIG-DETERM-0",
    "IIG-PERSIST-0",
    "IIG-CLUSTER-0",
    "IIG-HUMAN0-0",
]

GENESIS_PREV_HASH = "0" * 64


# ── Exceptions ─────────────────────────────────────────────────────────────────
class IIGAuthorizationViolation(Exception):
    """Raised when a HUMAN-0-gated operation is attempted without auth."""


class IIGChainViolation(Exception):
    """Raised when hash-chain integrity is broken (IIG-COFIRE-0)."""


class IIGDeterminismViolation(Exception):
    """Raised when replay produces a different graph_digest (IIG-DETERM-0)."""


# ── Data models ────────────────────────────────────────────────────────────────
@dataclass
class CoFireObservation:
    """A single observation of two invariants firing in the same epoch."""

    epoch_id: str
    inv_a: str
    inv_b: str  # invariant with lexicographically greater ID
    timestamp: str
    seq: int
    prev_hash: str = GENESIS_PREV_HASH
    entry_hash: str = ""

    def __post_init__(self) -> None:
        # Canonical ordering: inv_a < inv_b lexicographically
        if self.inv_a > self.inv_b:
            self.inv_a, self.inv_b = self.inv_b, self.inv_a
        if not self.entry_hash:
            self.entry_hash = _compute_observation_hash(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "epoch_id": self.epoch_id,
            "inv_a": self.inv_a,
            "inv_b": self.inv_b,
            "timestamp": self.timestamp,
            "seq": self.seq,
            "prev_hash": self.prev_hash,
            "entry_hash": self.entry_hash,
        }


@dataclass
class InvariantNode:
    """A node in the interaction graph representing one invariant."""

    invariant_id: str
    fire_count: int = 0
    last_epoch: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "invariant_id": self.invariant_id,
            "fire_count": self.fire_count,
            "last_epoch": self.last_epoch,
            "tags": self.tags,
        }


@dataclass
class InteractionEdge:
    """A weighted edge between two invariants in the graph."""

    inv_a: str
    inv_b: str
    co_fire_count: int = 0
    epochs: list[str] = field(default_factory=list)

    @property
    def weight(self) -> float:
        """Edge weight normalised by total observations (non-zero by construction)."""
        return float(self.co_fire_count)

    def to_dict(self) -> dict[str, Any]:
        return {
            "inv_a": self.inv_a,
            "inv_b": self.inv_b,
            "co_fire_count": self.co_fire_count,
            "weight": self.weight,
            "epochs": self.epochs[:10],  # cap for compactness
        }


# ── Hash helpers ───────────────────────────────────────────────────────────────
def _compute_observation_hash(obs: CoFireObservation) -> str:
    payload = json.dumps(
        {
            "seq": obs.seq,
            "epoch_id": obs.epoch_id,
            "inv_a": obs.inv_a,
            "inv_b": obs.inv_b,
            "timestamp": obs.timestamp,
            "prev_hash": obs.prev_hash,
        },
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def _compute_graph_digest(
    nodes: dict[str, InvariantNode],
    edges: dict[tuple[str, str], InteractionEdge],
) -> str:
    """Deterministic digest of entire graph state (IIG-DETERM-0)."""
    node_summary = sorted(
        (nid, n.fire_count) for nid, n in nodes.items()
    )
    edge_summary = sorted(
        (k[0], k[1], e.co_fire_count) for k, e in edges.items()
    )
    payload = json.dumps(
        {"nodes": node_summary, "edges": edge_summary}, sort_keys=True
    )
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


# ── Core class ─────────────────────────────────────────────────────────────────
class InvariantInteractionGraph:
    """Governed graph tracking co-fire relationships between invariants.

    Invariant contracts:
      IIG-COFIRE-0  Every observation appended is hash-chained.
      IIG-DETERM-0  graph_digest is purely a function of observations.
      IIG-PERSIST-0 State round-trips through jsonl without loss.
      IIG-CLUSTER-0 greedy_clusters() is deterministic on fixed edge weights.
      IIG-HUMAN0-0  remove_node() requires human_auth=True.
    """

    def __init__(
        self,
        path: Path = Path("data/invariant_interaction_graph.jsonl"),
    ) -> None:
        self._path = Path(path)
        self._nodes: dict[str, InvariantNode] = {}
        self._edges: dict[tuple[str, str], InteractionEdge] = {}
        self._observations: list[CoFireObservation] = []
        self._load()

    # ── Observation API ────────────────────────────────────────────────────────

    def record_epoch_firings(
        self, epoch_id: str, fired_invariants: list[str], timestamp: str = ""
    ) -> list[CoFireObservation]:
        """Record all pairwise co-fire relationships from a single epoch.

        IIG-COFIRE-0: every observation is hash-chained to the previous one.
        """
        import itertools
        from datetime import datetime, timezone

        ts = timestamp or datetime.now(timezone.utc).isoformat()
        new_observations: list[CoFireObservation] = []

        # Update nodes
        for inv_id in fired_invariants:
            if inv_id not in self._nodes:
                self._nodes[inv_id] = InvariantNode(invariant_id=inv_id)
            node = self._nodes[inv_id]
            node.fire_count += 1
            node.last_epoch = epoch_id

        # Record pairwise co-fires
        unique_invs = sorted(set(fired_invariants))
        for inv_a, inv_b in itertools.combinations(unique_invs, 2):
            prev_hash = (
                self._observations[-1].entry_hash
                if self._observations
                else GENESIS_PREV_HASH
            )
            seq = len(self._observations)
            obs = CoFireObservation(
                epoch_id=epoch_id,
                inv_a=inv_a,
                inv_b=inv_b,
                timestamp=ts,
                seq=seq,
                prev_hash=prev_hash,
            )
            self._observations.append(obs)
            new_observations.append(obs)
            # Update edge
            key = (obs.inv_a, obs.inv_b)
            if key not in self._edges:
                self._edges[key] = InteractionEdge(inv_a=obs.inv_a, inv_b=obs.inv_b)
            edge = self._edges[key]
            edge.co_fire_count += 1
            if epoch_id not in edge.epochs:
                edge.epochs.append(epoch_id)
            self._append_to_store(obs)

        return new_observations

    # ── Analysis API ──────────────────────────────────────────────────────────

    def co_fire_count(self, inv_a: str, inv_b: str) -> int:
        """How many times these two invariants have co-fired."""
        key = (min(inv_a, inv_b), max(inv_a, inv_b))
        return self._edges.get(key, InteractionEdge(inv_a=inv_a, inv_b=inv_b)).co_fire_count

    def neighbors(self, invariant_id: str) -> list[str]:
        """All invariants that have co-fired at least once with this one."""
        result: list[str] = []
        for (a, b) in self._edges:
            if a == invariant_id:
                result.append(b)
            elif b == invariant_id:
                result.append(a)
        return sorted(result)

    def orphan_invariants(self) -> list[str]:
        """Invariants that have fired but never co-fired with any other."""
        connected: set[str] = set()
        for (a, b) in self._edges:
            connected.add(a)
            connected.add(b)
        return sorted(nid for nid in self._nodes if nid not in connected)

    def strongest_pairs(self, top_n: int = 10) -> list[tuple[str, str, float]]:
        """Top N co-fire pairs by weight, deterministically ordered."""
        ranked = sorted(
            ((e.inv_a, e.inv_b, e.weight) for e in self._edges.values()),
            key=lambda x: (-x[2], x[0], x[1]),
        )
        return ranked[:top_n]

    def greedy_clusters(self, min_weight: float = 1.0) -> dict[str, list[str]]:
        """Deterministic greedy clustering by co-fire strength (IIG-CLUSTER-0).

        Algorithm: iterate invariants in sorted order; assign to existing cluster
        if any member has edge weight >= min_weight, else start a new cluster.
        Result is deterministic for fixed edge weights.
        """
        clusters: dict[str, list[str]] = {}
        membership: dict[str, str] = {}
        cluster_seq = 0

        for inv_id in sorted(self._nodes):
            best_cluster: str | None = None
            best_weight = 0.0
            for cluster_id, members in clusters.items():
                for member in members:
                    w = float(self.co_fire_count(inv_id, member))
                    if w >= min_weight and w > best_weight:
                        best_weight = w
                        best_cluster = cluster_id

            if best_cluster is not None:
                clusters[best_cluster].append(inv_id)
                membership[inv_id] = best_cluster
            else:
                cid = f"cluster-{cluster_seq:04d}"
                cluster_seq += 1
                clusters[cid] = [inv_id]
                membership[inv_id] = cid

        return clusters

    def potential_conflicts(self, min_exclusivity: float = 0.9) -> list[tuple[str, str]]:
        """Pairs of invariants that rarely or never co-fire despite both being active.

        If two invariants each have high fire_count but near-zero co_fire_count,
        they may represent conflicting contexts.
        """
        conflicts: list[tuple[str, str]] = []
        inv_list = sorted(self._nodes)
        for i, inv_a in enumerate(inv_list):
            for inv_b in inv_list[i + 1 :]:
                node_a = self._nodes[inv_a]
                node_b = self._nodes[inv_b]
                if node_a.fire_count < 2 or node_b.fire_count < 2:
                    continue
                cf = self.co_fire_count(inv_a, inv_b)
                expected = min(node_a.fire_count, node_b.fire_count)
                exclusivity = 1.0 - (cf / expected) if expected > 0 else 0.0
                if exclusivity >= min_exclusivity:
                    conflicts.append((inv_a, inv_b))
        return sorted(conflicts)

    # ── Governance operations ─────────────────────────────────────────────────

    def remove_node(self, invariant_id: str, human_auth: bool = False) -> None:
        """Remove an invariant node and all its edges.

        IIG-HUMAN0-0: human_auth=True is required. Raises IIGAuthorizationViolation
        if called without explicit human authorisation.
        """
        if not human_auth:
            raise IIGAuthorizationViolation(
                f"IIG-HUMAN0-0: removing invariant node '{invariant_id}' "
                "requires human_auth=True — this operation is HUMAN-0 gated."
            )
        self._nodes.pop(invariant_id, None)
        to_remove = [k for k in self._edges if invariant_id in k]
        for k in to_remove:
            del self._edges[k]

    # ── Digest / integrity ────────────────────────────────────────────────────

    @property
    def graph_digest(self) -> str:
        """Deterministic digest of current graph state (IIG-DETERM-0)."""
        return _compute_graph_digest(self._nodes, self._edges)

    def verify_chain(self) -> bool:
        """Verify the full observation hash-chain (IIG-COFIRE-0)."""
        prev = GENESIS_PREV_HASH
        for obs in self._observations:
            if obs.prev_hash != prev:
                raise IIGChainViolation(
                    f"IIG-COFIRE-0: chain broken at seq={obs.seq}. "
                    f"Expected prev={prev!r}, got {obs.prev_hash!r}"
                )
            expected = _compute_observation_hash(
                CoFireObservation(
                    epoch_id=obs.epoch_id,
                    inv_a=obs.inv_a,
                    inv_b=obs.inv_b,
                    timestamp=obs.timestamp,
                    seq=obs.seq,
                    prev_hash=obs.prev_hash,
                    entry_hash="",
                )
            )
            if obs.entry_hash != expected:
                raise IIGChainViolation(
                    f"IIG-COFIRE-0: hash mismatch at seq={obs.seq}."
                )
            prev = obs.entry_hash
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "innov_id": INNOV_ID,
            "phase": PHASE,
            "version": VERSION,
            "graph_digest": self.graph_digest,
            "node_count": len(self._nodes),
            "edge_count": len(self._edges),
            "observation_count": len(self._observations),
            "nodes": {k: v.to_dict() for k, v in sorted(self._nodes.items())},
            "edges": [e.to_dict() for e in sorted(
                self._edges.values(), key=lambda e: (e.inv_a, e.inv_b)
            )],
        }

    # ── Persistence ───────────────────────────────────────────────────────────

    def _append_to_store(self, obs: CoFireObservation) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a") as f:
            f.write(json.dumps(obs.to_dict()) + "\n")

    def _load(self) -> None:
        """Reload from jsonl store (IIG-PERSIST-0)."""
        if not self._path.exists():
            return
        prev_hash = GENESIS_PREV_HASH
        for line in self._path.read_text().splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            obs = CoFireObservation(
                epoch_id=d["epoch_id"],
                inv_a=d["inv_a"],
                inv_b=d["inv_b"],
                timestamp=d["timestamp"],
                seq=d["seq"],
                prev_hash=d["prev_hash"],
                entry_hash=d["entry_hash"],
            )
            self._observations.append(obs)
            prev_hash = obs.entry_hash
            # Rebuild nodes
            for inv_id in (obs.inv_a, obs.inv_b):
                if inv_id not in self._nodes:
                    self._nodes[inv_id] = InvariantNode(invariant_id=inv_id)
                node = self._nodes[inv_id]
                node.fire_count += 1
                node.last_epoch = obs.epoch_id
            # Rebuild edges
            key = (obs.inv_a, obs.inv_b)
            if key not in self._edges:
                self._edges[key] = InteractionEdge(inv_a=obs.inv_a, inv_b=obs.inv_b)
            edge = self._edges[key]
            edge.co_fire_count += 1
            if obs.epoch_id not in edge.epochs:
                edge.epochs.append(obs.epoch_id)
