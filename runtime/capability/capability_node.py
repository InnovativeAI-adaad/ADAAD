# SPDX-License-Identifier: Apache-2.0
"""
runtime.capability.capability_node
===================================
CapabilityNode v2 — rich, versioned, contract-bearing capability descriptor.

Invariants
----------
CAP-VERS-0   Every node carries a semantic version string (MAJOR.MINOR.PATCH).
CAP-DEP-0    dependency_set members must all be registered before acceptance.
CAP-TIER0-0  Tier-0 nodes may NOT target their own bound_modules for mutation.

Tiers
-----
0  Constitutional / governance-critical  (immutable except by amendment)
1  Core runtime                          (governed mutation allowed)
2  Extension / experimental              (relaxed gate)
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

# Semantic version pattern: MAJOR.MINOR.PATCH (no pre-release suffix required)
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


class CapabilityNodeError(Exception):
    """Raised when a CapabilityNode fails validation."""


@dataclass
class CapabilityContract:
    """Formal contract attached to a capability.

    Attributes
    ----------
    description     Human-readable statement of what the capability does.
    preconditions   List of invariant strings that must hold before invocation.
    postconditions  List of invariant strings guaranteed after successful run.
    tier            0 (constitutional), 1 (core), 2 (extension).
    sla_max_ms      Soft latency ceiling in milliseconds (0 = unconstrained).
    """

    description: str
    preconditions: List[str] = field(default_factory=list)
    postconditions: List[str] = field(default_factory=list)
    tier: int = 1
    sla_max_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "description": self.description,
            "preconditions": self.preconditions,
            "postconditions": self.postconditions,
            "tier": self.tier,
            "sla_max_ms": self.sla_max_ms,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CapabilityContract":
        return cls(
            description=d.get("description", ""),
            preconditions=d.get("preconditions", []),
            postconditions=d.get("postconditions", []),
            tier=int(d.get("tier", 1)),
            sla_max_ms=int(d.get("sla_max_ms", 0)),
        )


@dataclass
class CapabilityNode:
    """Versioned, contract-bearing capability descriptor (v2).

    Attributes
    ----------
    capability_id   Unique dotted identifier, e.g. 'governance.gate'.
    version         Semantic version string 'MAJOR.MINOR.PATCH' (CAP-VERS-0).
    contract        CapabilityContract — formal pre/post conditions + tier.
    governance_tags Set of governance invariant labels, e.g. {'GATE-0', 'DET-0'}.
    telemetry       Key-value map for runtime telemetry counters / gauges.
    bound_modules   Ordered list of runtime module paths this capability owns.
    dependency_set  Set of capability_ids this node depends on (CAP-DEP-0).
    node_hash       SHA-256 of canonical node state (excludes telemetry).
    """

    capability_id: str
    version: str
    contract: CapabilityContract
    governance_tags: FrozenSet[str] = field(default_factory=frozenset)
    telemetry: Dict[str, Any] = field(default_factory=dict)
    bound_modules: List[str] = field(default_factory=list)
    dependency_set: FrozenSet[str] = field(default_factory=frozenset)
    node_hash: str = field(default="", init=False)

    def __post_init__(self) -> None:
        self._validate()
        object.__setattr__(self, "node_hash", self._compute_hash())

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate(self) -> None:
        if not self.capability_id or not self.capability_id.strip():
            raise CapabilityNodeError("capability_id must not be empty")
        if not _SEMVER_RE.match(self.version):
            raise CapabilityNodeError(
                f"version '{self.version}' does not match MAJOR.MINOR.PATCH (CAP-VERS-0)"
            )
        if self.contract.tier not in (0, 1, 2):
            raise CapabilityNodeError(
                f"tier must be 0, 1, or 2 — got {self.contract.tier}"
            )

    # ------------------------------------------------------------------
    # CAP-TIER0-0
    # ------------------------------------------------------------------

    def tier0_self_mutation_check(self, mutation_target_module: str) -> Tuple[bool, str]:
        """Return (safe, reason). Tier-0 nodes block mutation of their own bound_modules."""
        if self.contract.tier == 0 and mutation_target_module in self.bound_modules:
            return False, (
                f"CAP-TIER0-0 violation: Tier-0 capability '{self.capability_id}' "
                f"prohibits mutation of bound module '{mutation_target_module}'"
            )
        return True, "ok"

    # ------------------------------------------------------------------
    # Hashing
    # ------------------------------------------------------------------

    def _compute_hash(self) -> str:
        state = {
            "capability_id": self.capability_id,
            "version": self.version,
            "contract": self.contract.to_dict(),
            "governance_tags": sorted(self.governance_tags),
            "bound_modules": self.bound_modules,
            "dependency_set": sorted(self.dependency_set),
        }
        canonical = json.dumps(state, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def refresh_hash(self) -> str:
        """Recompute and return node_hash (call after mutating telemetry)."""
        h = self._compute_hash()
        object.__setattr__(self, "node_hash", h)
        return h

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "version": self.version,
            "contract": self.contract.to_dict(),
            "governance_tags": sorted(self.governance_tags),
            "telemetry": self.telemetry,
            "bound_modules": self.bound_modules,
            "dependency_set": sorted(self.dependency_set),
            "node_hash": self.node_hash,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CapabilityNode":
        node = cls(
            capability_id=d["capability_id"],
            version=d["version"],
            contract=CapabilityContract.from_dict(d.get("contract", {})),
            governance_tags=frozenset(d.get("governance_tags", [])),
            telemetry=d.get("telemetry", {}),
            bound_modules=d.get("bound_modules", []),
            dependency_set=frozenset(d.get("dependency_set", [])),
        )
        return node

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def tier(self) -> int:
        return self.contract.tier

    def record_telemetry(self, key: str, value: Any) -> None:
        self.telemetry[key] = value
