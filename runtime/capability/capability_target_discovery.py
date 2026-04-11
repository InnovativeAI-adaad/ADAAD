# SPDX-License-Identifier: Apache-2.0
"""
runtime.capability.capability_target_discovery
===============================================
Maps function-level mutation targets to owning CapabilityNodes using the
CodeIntelModel from Phase 58.

Design
------
CapabilityTargetDiscovery accepts a CapabilityRegistry and an optional
CodeIntelModel snapshot.  Given a function name or source file path, it
resolves which capability owns that target and whether mutation is permitted.

Invariants
----------
CAP-TIER0-0  Propagated: Tier-0 nodes block self-mutation of bound modules.
CAP-DEP-0    Propagated: resolution honours registered dependency graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from runtime.capability.capability_node import CapabilityNode
from runtime.capability.capability_registry import CapabilityRegistry


@dataclass
class DiscoveryResult:
    """Result of a capability target lookup.

    Attributes
    ----------
    capability_id       Owning capability, or None if unresolved.
    capability_node     Full CapabilityNode, or None.
    mutation_safe       True if mutation of the target is allowed.
    safety_reason       Reason string from CAP-TIER0-0 check.
    hotspot_score       Hotspot score [0, 1] from CodeIntelModel (0.0 if absent).
    churn_score         Normalised churn score [0, 1] from CodeIntelModel.
    callers             Functions that call the target (from call graph).
    callees             Functions called by the target.
    is_top_hotspot      Whether the file is in the top-hotspot list.
    """

    capability_id: Optional[str] = None
    capability_node: Optional[CapabilityNode] = None
    mutation_safe: bool = True
    safety_reason: str = "ok"
    hotspot_score: float = 0.0
    churn_score: float = 0.0
    callers: List[str] = field(default_factory=list)
    callees: List[str] = field(default_factory=list)
    is_top_hotspot: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "mutation_safe": self.mutation_safe,
            "safety_reason": self.safety_reason,
            "hotspot_score": self.hotspot_score,
            "churn_score": self.churn_score,
            "callers": self.callers,
            "callees": self.callees,
            "is_top_hotspot": self.is_top_hotspot,
        }


class CapabilityTargetDiscovery:
    """Resolves mutation targets to owning capabilities with enrichment.

    Parameters
    ----------
    registry:     CapabilityRegistry to query.
    code_intel:   Optional CodeIntelModel snapshot for structural enrichment.

    Usage
    -----
    discovery = CapabilityTargetDiscovery(registry, model)
    result = discovery.resolve_file("runtime/governance/gate.py")
    result = discovery.resolve_function("run_epoch")
    all_safe = discovery.mutation_safe_targets()
    """

    def __init__(
        self,
        registry: CapabilityRegistry,
        code_intel: Optional[Any] = None,
    ) -> None:
        self._registry = registry
        self._intel = code_intel
        # Build reverse index: module_path → capability_id
        self._module_index: Dict[str, str] = {}
        for node in registry:
            for module in node.bound_modules:
                self._module_index[module] = node.capability_id

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve_file(self, filepath: str) -> DiscoveryResult:
        """Resolve *filepath* to its owning capability and enrichment data."""
        result = DiscoveryResult()

        # Capability ownership via bound_modules index
        cap_id = self._module_index.get(filepath)
        if cap_id:
            result.capability_id = cap_id
            result.capability_node = self._registry.get(cap_id)
            safe, reason = self._registry.mutation_safe(cap_id, filepath)
            result.mutation_safe = safe
            result.safety_reason = reason

        # CodeIntelModel enrichment
        if self._intel is not None:
            result.hotspot_score = self._intel.hotspot_score_for(filepath)
            result.churn_score = self._intel.churn_score_for(filepath)
            result.is_top_hotspot = self._intel.is_top_hotspot(filepath)

        return result

    def resolve_function(self, function_name: str) -> DiscoveryResult:
        """Resolve a *function_name* to capability + call-graph enrichment."""
        result = DiscoveryResult()

        # Call-graph enrichment
        if self._intel is not None:
            result.callers = self._intel.callers_of(function_name)
            result.callees = self._intel.callees_of(function_name)

        return result

    def resolve(self, filepath: str, function_name: Optional[str] = None) -> DiscoveryResult:
        """Combined file + function resolution."""
        file_result = self.resolve_file(filepath)
        if function_name and self._intel is not None:
            file_result.callers = self._intel.callers_of(function_name)
            file_result.callees = self._intel.callees_of(function_name)
        return file_result

    # ------------------------------------------------------------------
    # Bulk queries
    # ------------------------------------------------------------------

    def mutation_safe_targets(self) -> List[str]:
        """Return all registered module paths that pass CAP-TIER0-0."""
        safe: List[str] = []
        for module_path, cap_id in sorted(self._module_index.items()):
            ok, _ = self._registry.mutation_safe(cap_id, module_path)
            if ok:
                safe.append(module_path)
        return safe

    def tier0_protected_modules(self):
        """Delegate to registry for Tier-0 protected module set."""
        return self._registry.tier0_protected_modules()

    def unclaimed_files(self, all_files: List[str]) -> List[str]:
        """Return files from *all_files* not bound to any capability."""
        return [f for f in all_files if f not in self._module_index]

    def coverage_ratio(self, all_files: List[str]) -> float:
        """Fraction of *all_files* bound to a capability [0.0, 1.0]."""
        if not all_files:
            return 0.0
        claimed = sum(1 for f in all_files if f in self._module_index)
        return claimed / len(all_files)

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"CapabilityTargetDiscovery("
            f"capabilities={self._registry.count()}, "
            f"modules_indexed={len(self._module_index)}, "
            f"intel={'yes' if self._intel else 'no'})"
        )
