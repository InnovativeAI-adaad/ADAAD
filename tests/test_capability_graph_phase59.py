# SPDX-License-Identifier: Apache-2.0
"""
tests/test_capability_graph_phase59.py
=======================================
Phase 59 — Capability Graph v2 — T59-CAP-01..10

Coverage
--------
T59-CAP-01  CapabilityNode v2 — construction, validation, CAP-VERS-0
T59-CAP-02  CapabilityNode node_hash determinism
T59-CAP-03  CapabilityContract serialisation roundtrip
T59-CAP-04  CapabilityRegistry — register / get / list
T59-CAP-05  CapabilityRegistry CAP-DEP-0 enforcement
T59-CAP-06  CapabilityRegistry CAP-TIER0-0 mutation safety
T59-CAP-07  CapabilityRegistry version monotonicity
T59-CAP-08  CapabilityTargetDiscovery — file resolution + enrichment
T59-CAP-09  CapabilityTargetDiscovery — bulk helpers
T59-CAP-10  BOOTSTRAP_REGISTRY — 10 contracts, Tier-0 gates, roundtrip
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import FrozenSet

import pytest

REPO_ROOT = Path(__file__).parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.capability.capability_node import (
    CapabilityContract,
    CapabilityNode,
    CapabilityNodeError,
)
from runtime.capability.capability_registry import CapabilityRegistry, RegistryError
from runtime.capability.capability_target_discovery import (
    CapabilityTargetDiscovery,
    DiscoveryResult,
)
from runtime.capability.contracts import BOOTSTRAP_REGISTRY, build_bootstrap_registry


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _contract(tier: int = 1) -> CapabilityContract:
    return CapabilityContract(
        description="Test capability",
        preconditions=["pre-1"],
        postconditions=["post-1"],
        tier=tier,
        sla_max_ms=100,
    )


def _node(
    cap_id: str = "test.cap",
    version: str = "1.0.0",
    tier: int = 1,
    bound_modules=None,
    dependency_set=None,
    governance_tags=None,
) -> CapabilityNode:
    return CapabilityNode(
        capability_id=cap_id,
        version=version,
        contract=_contract(tier),
        governance_tags=frozenset(governance_tags or []),
        bound_modules=bound_modules or [],
        dependency_set=frozenset(dependency_set or []),
    )


def _registry_with(*nodes: CapabilityNode) -> CapabilityRegistry:
    reg = CapabilityRegistry()
    for node in nodes:
        ok, reason = reg.register(node)
        assert ok, reason
    return reg


# ===========================================================================
# T59-CAP-01  CapabilityNode v2 construction and CAP-VERS-0
# ===========================================================================

class TestT59Cap01CapabilityNodeConstruction:

    def test_valid_node_constructs(self):
        n = _node()
        assert n.capability_id == "test.cap"
        assert n.version == "1.0.0"
        assert n.tier == 1

    def test_node_hash_populated_on_init(self):
        n = _node()
        assert len(n.node_hash) == 64

    def test_empty_capability_id_raises(self):
        with pytest.raises(CapabilityNodeError):
            CapabilityNode(
                capability_id="",
                version="1.0.0",
                contract=_contract(),
            )

    def test_invalid_semver_raises(self):
        with pytest.raises(CapabilityNodeError, match="CAP-VERS-0"):
            CapabilityNode(
                capability_id="bad.ver",
                version="1.0",  # missing PATCH
                contract=_contract(),
            )

    def test_invalid_tier_raises(self):
        with pytest.raises(CapabilityNodeError):
            CapabilityNode(
                capability_id="bad.tier",
                version="1.0.0",
                contract=CapabilityContract(description="x", tier=99),
            )

    def test_governance_tags_are_frozenset(self):
        n = _node(governance_tags=["TAG-A", "TAG-B"])
        assert isinstance(n.governance_tags, frozenset)
        assert "TAG-A" in n.governance_tags

    def test_dependency_set_is_frozenset(self):
        n = _node(dependency_set=["dep.one"])
        assert isinstance(n.dependency_set, frozenset)

    def test_to_dict_json_serialisable(self):
        n = _node()
        assert json.dumps(n.to_dict())

    def test_from_dict_roundtrip(self):
        n = _node(version="2.3.4", governance_tags=["X"])
        restored = CapabilityNode.from_dict(n.to_dict())
        assert restored.capability_id == n.capability_id
        assert restored.version == n.version
        assert "X" in restored.governance_tags


# ===========================================================================
# T59-CAP-02  node_hash determinism
# ===========================================================================

class TestT59Cap02NodeHashDeterminism:

    def test_same_node_same_hash(self):
        n1 = _node("a.cap", "1.0.0")
        n2 = _node("a.cap", "1.0.0")
        assert n1.node_hash == n2.node_hash

    def test_different_version_different_hash(self):
        n1 = _node("a.cap", "1.0.0")
        n2 = _node("a.cap", "1.0.1")
        assert n1.node_hash != n2.node_hash

    def test_different_id_different_hash(self):
        n1 = _node("a.cap")
        n2 = _node("b.cap")
        assert n1.node_hash != n2.node_hash

    def test_hash_excludes_telemetry(self):
        n = _node()
        h_before = n.node_hash
        n.record_telemetry("counter", 5)
        # Hash not auto-updated — still the init hash (telemetry excluded from state)
        assert n.node_hash == h_before

    def test_refresh_hash_after_telemetry_unchanged(self):
        n = _node()
        h_before = n.node_hash
        n.record_telemetry("k", "v")
        h_after = n.refresh_hash()
        # telemetry excluded from hash state, so same hash expected
        assert h_after == h_before


# ===========================================================================
# T59-CAP-03  CapabilityContract serialisation
# ===========================================================================

class TestT59Cap03ContractSerialisation:

    def test_to_dict_has_required_keys(self):
        c = _contract(tier=0)
        d = c.to_dict()
        for key in ("description", "preconditions", "postconditions", "tier", "sla_max_ms"):
            assert key in d

    def test_from_dict_roundtrip(self):
        c = CapabilityContract(
            description="governance contract",
            preconditions=["pre"],
            postconditions=["post"],
            tier=0,
            sla_max_ms=250,
        )
        restored = CapabilityContract.from_dict(c.to_dict())
        assert restored.tier == 0
        assert restored.sla_max_ms == 250
        assert restored.description == "governance contract"

    def test_missing_keys_use_defaults(self):
        c = CapabilityContract.from_dict({})
        assert c.tier == 1
        assert c.sla_max_ms == 0
        assert c.description == ""


# ===========================================================================
# T59-CAP-04  CapabilityRegistry register / get / list
# ===========================================================================

class TestT59Cap04RegistryBasics:

    def test_register_and_get(self):
        reg = CapabilityRegistry()
        n = _node("alpha.cap")
        ok, reason = reg.register(n)
        assert ok
        assert reg.get("alpha.cap") is n

    def test_get_unknown_returns_none(self):
        reg = CapabilityRegistry()
        assert reg.get("nope") is None

    def test_contains(self):
        reg = _registry_with(_node("x.cap"))
        assert reg.contains("x.cap")
        assert not reg.contains("y.cap")

    def test_list_ids_sorted(self):
        reg = _registry_with(_node("b.cap"), _node("a.cap"), _node("c.cap"))
        assert reg.list_ids() == ["a.cap", "b.cap", "c.cap"]

    def test_count(self):
        reg = _registry_with(_node("a.cap"), _node("b.cap"))
        assert reg.count() == 2

    def test_registry_hash_is_64_hex(self):
        reg = _registry_with(_node("a.cap"))
        h = reg.registry_hash()
        assert len(h) == 64
        int(h, 16)

    def test_to_dict_from_dict_roundtrip(self):
        reg = _registry_with(_node("r.cap", version="3.2.1"))
        d = reg.to_dict()
        restored = CapabilityRegistry.from_dict(d)
        assert restored.contains("r.cap")
        assert restored.get("r.cap").version == "3.2.1"

    def test_iteration_yields_all_nodes(self):
        reg = _registry_with(_node("a.cap"), _node("b.cap"))
        ids = {n.capability_id for n in reg}
        assert ids == {"a.cap", "b.cap"}


# ===========================================================================
# T59-CAP-05  CAP-DEP-0 enforcement
# ===========================================================================

class TestT59Cap05DepEnforcement:

    def test_register_with_satisfied_dep(self):
        base = _node("base.cap")
        dependent = _node("dep.cap", dependency_set=["base.cap"])
        reg = CapabilityRegistry()
        reg.register(base)
        ok, reason = reg.register(dependent)
        assert ok

    def test_register_with_missing_dep_fails(self):
        reg = CapabilityRegistry()
        dependent = _node("dep.cap", dependency_set=["missing.cap"])
        ok, reason = reg.register(dependent)
        assert not ok
        assert "CAP-DEP-0" in reason

    def test_transitive_deps_resolved(self):
        a = _node("a.cap")
        b = _node("b.cap", dependency_set=["a.cap"])
        c = _node("c.cap", dependency_set=["b.cap"])
        reg = _registry_with(a, b, c)
        tdeps = reg.transitive_deps("c.cap")
        assert "a.cap" in tdeps
        assert "b.cap" in tdeps

    def test_dependents_of(self):
        a = _node("a.cap")
        b = _node("b.cap", dependency_set=["a.cap"])
        c = _node("c.cap", dependency_set=["a.cap"])
        reg = _registry_with(a, b, c)
        deps = reg.dependents_of("a.cap")
        assert set(deps) == {"b.cap", "c.cap"}


# ===========================================================================
# T59-CAP-06  CAP-TIER0-0 mutation safety
# ===========================================================================

class TestT59Cap06Tier0Safety:

    def test_tier0_node_blocks_own_module_mutation(self):
        n = _node("gov.gate", tier=0, bound_modules=["runtime/governance/gate.py"])
        reg = _registry_with(n)
        safe, reason = reg.mutation_safe("gov.gate", "runtime/governance/gate.py")
        assert not safe
        assert "CAP-TIER0-0" in reason

    def test_tier0_node_allows_other_module_mutation(self):
        n = _node("gov.gate", tier=0, bound_modules=["runtime/governance/gate.py"])
        reg = _registry_with(n)
        safe, reason = reg.mutation_safe("gov.gate", "runtime/other.py")
        assert safe

    def test_tier1_node_allows_own_module_mutation(self):
        n = _node("evo.loop", tier=1, bound_modules=["runtime/evolution/evolution_loop.py"])
        reg = _registry_with(n)
        safe, reason = reg.mutation_safe("evo.loop", "runtime/evolution/evolution_loop.py")
        assert safe

    def test_unknown_capability_returns_unsafe(self):
        reg = CapabilityRegistry()
        safe, reason = reg.mutation_safe("unknown.cap", "any/module.py")
        assert not safe

    def test_tier0_protected_modules(self):
        n1 = _node("g.gate", tier=0, bound_modules=["runtime/governance/gate.py"])
        n2 = _node("g.policy", tier=0, bound_modules=["runtime/governance/policy.py"])
        n3 = _node("evo.loop", tier=1, bound_modules=["runtime/evolution/loop.py"])
        reg = _registry_with(n1, n2, n3)
        protected = reg.tier0_protected_modules()
        assert "runtime/governance/gate.py" in protected
        assert "runtime/governance/policy.py" in protected
        assert "runtime/evolution/loop.py" not in protected


# ===========================================================================
# T59-CAP-07  Version monotonicity
# ===========================================================================

class TestT59Cap07VersionMonotonicity:

    def test_upgrade_allowed(self):
        reg = CapabilityRegistry()
        reg.register(_node("x.cap", version="1.0.0"))
        ok, reason = reg.register(_node("x.cap", version="1.0.1"))
        assert ok
        assert reg.get("x.cap").version == "1.0.1"

    def test_same_version_allowed(self):
        reg = CapabilityRegistry()
        reg.register(_node("x.cap", version="1.0.0"))
        ok, _ = reg.register(_node("x.cap", version="1.0.0"))
        assert ok

    def test_downgrade_rejected(self):
        reg = CapabilityRegistry()
        reg.register(_node("x.cap", version="2.0.0"))
        ok, reason = reg.register(_node("x.cap", version="1.9.9"))
        assert not ok
        assert "regression" in reason

    def test_major_upgrade_allowed(self):
        reg = CapabilityRegistry()
        reg.register(_node("x.cap", version="1.0.0"))
        ok, _ = reg.register(_node("x.cap", version="2.0.0"))
        assert ok


# ===========================================================================
# T59-CAP-08  CapabilityTargetDiscovery — file resolution + enrichment
# ===========================================================================

class TestT59Cap08TargetDiscoveryResolution:

    def _setup(self):
        n = _node("evo.loop", tier=1, bound_modules=["runtime/evolution/evolution_loop.py"])
        n0 = _node("gov.gate", tier=0, bound_modules=["runtime/governance/gate.py"])
        reg = _registry_with(n0, n)
        return CapabilityTargetDiscovery(reg), reg

    def test_resolve_known_file_returns_capability_id(self):
        disc, _ = self._setup()
        result = disc.resolve_file("runtime/evolution/evolution_loop.py")
        assert result.capability_id == "evo.loop"

    def test_resolve_unknown_file_returns_none_id(self):
        disc, _ = self._setup()
        result = disc.resolve_file("runtime/unknown.py")
        assert result.capability_id is None
        assert result.mutation_safe is True

    def test_resolve_tier0_file_returns_unsafe(self):
        disc, _ = self._setup()
        result = disc.resolve_file("runtime/governance/gate.py")
        assert result.capability_id == "gov.gate"
        assert not result.mutation_safe
        assert "CAP-TIER0-0" in result.safety_reason

    def test_resolve_tier1_file_is_safe(self):
        disc, _ = self._setup()
        result = disc.resolve_file("runtime/evolution/evolution_loop.py")
        assert result.mutation_safe

    def test_result_to_dict_serialisable(self):
        disc, _ = self._setup()
        result = disc.resolve_file("runtime/evolution/evolution_loop.py")
        assert json.dumps(result.to_dict())

    def test_repr_contains_counts(self):
        disc, _ = self._setup()
        r = repr(disc)
        assert "capabilities=2" in r
        assert "modules_indexed=2" in r


# ===========================================================================
# T59-CAP-09  CapabilityTargetDiscovery — bulk helpers
# ===========================================================================

class TestT59Cap09BulkHelpers:

    def _setup(self):
        n0 = _node("gov.gate", tier=0, bound_modules=["runtime/governance/gate.py"])
        n1 = _node("evo.loop", tier=1, bound_modules=["runtime/evolution/loop.py"])
        reg = _registry_with(n0, n1)
        return CapabilityTargetDiscovery(reg)

    def test_mutation_safe_targets_excludes_tier0(self):
        disc = self._setup()
        safe = disc.mutation_safe_targets()
        assert "runtime/evolution/loop.py" in safe
        assert "runtime/governance/gate.py" not in safe

    def test_unclaimed_files(self):
        disc = self._setup()
        all_files = [
            "runtime/governance/gate.py",
            "runtime/evolution/loop.py",
            "runtime/other.py",
        ]
        unclaimed = disc.unclaimed_files(all_files)
        assert unclaimed == ["runtime/other.py"]

    def test_coverage_ratio(self):
        disc = self._setup()
        all_files = [
            "runtime/governance/gate.py",
            "runtime/evolution/loop.py",
            "runtime/other.py",
            "runtime/extra.py",
        ]
        ratio = disc.coverage_ratio(all_files)
        assert ratio == 0.5

    def test_coverage_ratio_empty_list(self):
        disc = self._setup()
        assert disc.coverage_ratio([]) == 0.0

    def test_tier0_protected_modules(self):
        disc = self._setup()
        protected = disc.tier0_protected_modules()
        assert "runtime/governance/gate.py" in protected
        assert "runtime/evolution/loop.py" not in protected


# ===========================================================================
# T59-CAP-10  BOOTSTRAP_REGISTRY — 10 contracts, Tier-0 gates, roundtrip
# ===========================================================================

class TestT59Cap10BootstrapRegistry:

    def test_exactly_10_capabilities(self):
        assert BOOTSTRAP_REGISTRY.count() == 10

    def test_three_tier0_capabilities(self):
        tier0 = BOOTSTRAP_REGISTRY.tier0_nodes()
        assert len(tier0) == 3
        tier0_ids = {n.capability_id for n in tier0}
        assert tier0_ids == {"governance.gate", "governance.policy", "determinism.provider"}

    def test_all_capabilities_have_valid_semver(self):
        import re
        pattern = re.compile(r"^\d+\.\d+\.\d+$")
        for node in BOOTSTRAP_REGISTRY:
            assert pattern.match(node.version), f"{node.capability_id} has invalid version"

    def test_governance_gate_blocks_own_module(self):
        safe, reason = BOOTSTRAP_REGISTRY.mutation_safe(
            "governance.gate", "runtime/governance/gate.py"
        )
        assert not safe
        assert "CAP-TIER0-0" in reason

    def test_evolution_loop_allows_own_module(self):
        safe, reason = BOOTSTRAP_REGISTRY.mutation_safe(
            "evolution.loop", "runtime/evolution/evolution_loop.py"
        )
        assert safe

    def test_dependency_chain_satisfied(self):
        # evolution.proposal depends on evolution.loop which depends on governance.gate
        assert BOOTSTRAP_REGISTRY.contains("evolution.loop")
        evo_prop = BOOTSTRAP_REGISTRY.get("evolution.proposal")
        assert "evolution.loop" in evo_prop.dependency_set

    def test_registry_hash_is_deterministic(self):
        reg1 = build_bootstrap_registry()
        reg2 = build_bootstrap_registry()
        assert reg1.registry_hash() == reg2.registry_hash()

    def test_to_dict_roundtrip(self):
        d = BOOTSTRAP_REGISTRY.to_dict()
        restored = CapabilityRegistry.from_dict(d)
        assert restored.count() == BOOTSTRAP_REGISTRY.count()
        for node in BOOTSTRAP_REGISTRY:
            r = restored.get(node.capability_id)
            assert r is not None
            assert r.version == node.version

    def test_all_nodes_have_governance_tags(self):
        for node in BOOTSTRAP_REGISTRY:
            assert len(node.governance_tags) > 0, (
                f"{node.capability_id} has no governance_tags"
            )

    def test_build_bootstrap_registry_is_idempotent(self):
        r1 = build_bootstrap_registry()
        r2 = build_bootstrap_registry()
        assert r1.count() == r2.count() == 10
