# SPDX-License-Identifier: Apache-2.0
"""
runtime.capability.capability_registry
=======================================
In-memory capability registry with contract enforcement and dependency
validation.  Replaces the flat dict model in capability_graph.py.

Invariants
----------
CAP-VERS-0   Version string validated on every register call.
CAP-DEP-0    All dependency_set members must be registered before acceptance.
CAP-TIER0-0  Mutation-target safety check delegated to CapabilityNode.
"""

from __future__ import annotations

import hashlib
import json
from typing import Dict, FrozenSet, Iterator, List, Optional, Tuple

from runtime.capability.capability_node import CapabilityNode, CapabilityNodeError


class RegistryError(Exception):
    """Raised on dependency or version violations at the registry level."""


class CapabilityRegistry:
    """Thread-unsafe in-memory registry of CapabilityNode v2 entries.

    For persistence, call :meth:`to_dict` / :meth:`from_dict`.

    Usage
    -----
    registry = CapabilityRegistry()
    registry.register(node)
    node = registry.get("governance.gate")
    safe, reason = registry.mutation_safe("governance.gate", "runtime/governance/gate.py")
    """

    def __init__(self) -> None:
        self._nodes: Dict[str, CapabilityNode] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, node: CapabilityNode) -> Tuple[bool, str]:
        """Register a CapabilityNode.

        Enforces CAP-DEP-0: all dependency_set members must already be present.
        Enforces CAP-VERS-0: validated inside CapabilityNode.__post_init__.
        Returns (success, reason).
        """
        missing = [d for d in node.dependency_set if d not in self._nodes]
        if missing:
            return False, f"CAP-DEP-0 violation: unregistered dependencies {missing}"

        existing = self._nodes.get(node.capability_id)
        if existing is not None:
            # Monotonic version: only allow upgrades
            if not _version_gte(node.version, existing.version):
                return False, (
                    f"version regression prevented: existing={existing.version} "
                    f"proposed={node.version}"
                )

        self._nodes[node.capability_id] = node
        return True, "ok"

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, capability_id: str) -> Optional[CapabilityNode]:
        return self._nodes.get(capability_id)

    def contains(self, capability_id: str) -> bool:
        return capability_id in self._nodes

    def list_ids(self) -> List[str]:
        return sorted(self._nodes)

    def list_nodes(self) -> List[CapabilityNode]:
        return [self._nodes[k] for k in sorted(self._nodes)]

    def count(self) -> int:
        return len(self._nodes)

    def __iter__(self) -> Iterator[CapabilityNode]:
        return iter(self.list_nodes())

    # ------------------------------------------------------------------
    # CAP-TIER0-0 safety check
    # ------------------------------------------------------------------

    def mutation_safe(
        self, capability_id: str, mutation_target_module: str
    ) -> Tuple[bool, str]:
        """Check if mutating *mutation_target_module* is safe for *capability_id*.

        Delegates to CapabilityNode.tier0_self_mutation_check (CAP-TIER0-0).
        Returns (safe, reason).
        """
        node = self._nodes.get(capability_id)
        if node is None:
            return False, f"capability '{capability_id}' not found in registry"
        return node.tier0_self_mutation_check(mutation_target_module)

    def tier0_nodes(self) -> List[CapabilityNode]:
        return [n for n in self._nodes.values() if n.tier == 0]

    def tier0_protected_modules(self) -> FrozenSet[str]:
        """Return all modules protected by any Tier-0 capability."""
        protected = set()
        for node in self.tier0_nodes():
            protected.update(node.bound_modules)
        return frozenset(protected)

    # ------------------------------------------------------------------
    # Dependency graph helpers
    # ------------------------------------------------------------------

    def dependents_of(self, capability_id: str) -> List[str]:
        """Return capability_ids that directly depend on *capability_id*."""
        return sorted(
            nid
            for nid, node in self._nodes.items()
            if capability_id in node.dependency_set
        )

    def transitive_deps(self, capability_id: str) -> FrozenSet[str]:
        """Return the full transitive dependency closure for *capability_id*."""
        visited: set = set()
        stack = list(self._nodes[capability_id].dependency_set) if capability_id in self._nodes else []
        while stack:
            dep = stack.pop()
            if dep in visited:
                continue
            visited.add(dep)
            node = self._nodes.get(dep)
            if node:
                stack.extend(node.dependency_set)
        return frozenset(visited)

    # ------------------------------------------------------------------
    # Registry hash
    # ------------------------------------------------------------------

    def registry_hash(self) -> str:
        """SHA-256 of all node hashes, sorted by capability_id."""
        state = {nid: self._nodes[nid].node_hash for nid in sorted(self._nodes)}
        canonical = json.dumps(state, sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "nodes": {nid: node.to_dict() for nid, node in self._nodes.items()},
            "registry_hash": self.registry_hash(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CapabilityRegistry":
        reg = cls()
        # Load in sorted order to satisfy deps declared within the set
        for nid in sorted(d.get("nodes", {})):
            try:
                node = CapabilityNode.from_dict(d["nodes"][nid])
                reg._nodes[nid] = node  # bypass dep check on reload
            except (CapabilityNodeError, KeyError):
                continue
        return reg


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _version_tuple(v: str):
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return (0, 0, 0)


def _version_gte(a: str, b: str) -> bool:
    return _version_tuple(a) >= _version_tuple(b)
