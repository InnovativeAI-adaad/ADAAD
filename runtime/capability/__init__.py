# SPDX-License-Identifier: Apache-2.0
"""
runtime.capability — Capability Layer v2
=========================================
Identity layer for ADAAD v8.  Every runtime module is bound to a
CapabilityNode that carries a formal contract, version, governance tags,
and dependency declarations.

Public API
----------
CapabilityNode              Versioned, contract-bearing node (v2)
CapabilityContract          Pre/post condition + tier descriptor
CapabilityRegistry          In-memory registry with CAP-DEP-0 enforcement
CapabilityTargetDiscovery   Maps mutation targets to owning capabilities
BOOTSTRAP_REGISTRY          Pre-built registry with the 10 base contracts
"""

from runtime.capability.capability_node import (  # noqa: F401
    CapabilityNode,
    CapabilityContract,
    CapabilityNodeError,
)
from runtime.capability.capability_registry import (  # noqa: F401
    CapabilityRegistry,
    RegistryError,
)
from runtime.capability.capability_target_discovery import (  # noqa: F401
    CapabilityTargetDiscovery,
    DiscoveryResult,
)
from runtime.capability.contracts import BOOTSTRAP_REGISTRY  # noqa: F401

__all__ = [
    "CapabilityNode",
    "CapabilityContract",
    "CapabilityNodeError",
    "CapabilityRegistry",
    "RegistryError",
    "CapabilityTargetDiscovery",
    "DiscoveryResult",
    "BOOTSTRAP_REGISTRY",
]
