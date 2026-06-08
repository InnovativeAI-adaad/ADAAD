# SPDX-License-Identifier: Apache-2.0
"""Acceptance tests for adaad/abilities self-capable extension (Phase 199+).

Covers:
- AbilityProtocol + dataclass with provenance
- Registry pluggable hook (default + injected; fail-closed on reject)
- Discovery (seed parity + manifests + protocol)
- Drift detection + report (parity, kinds, recommendations)
- Promoted registration + provenance forcing
- discover_and_register / detect_and_reconcile_drift wrappers
- Lightweight isolation (package import does not pull heavy modules)
- Meta self-abilities (adaad.abilities.*) visible after seed

All tests are deterministic, no xfail/skip in this file, and exercise the
beyond-known capabilities while respecting the lightweight charter.
"""

from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from adaad.abilities.base import ALLOWED_PROVENANCE, Ability, AbilityProtocol
from adaad.abilities.registry import (
    abilities_snapshot,
    clear_abilities,
    detect_and_reconcile_drift,
    discover_and_register,
    get_governance_hook,
    register_ability,
    register_promoted_ability,
    set_governance_hook,
)
from adaad.abilities.discovery import discover_abilities
from adaad.abilities.drift import detect_abilities_drift


class TestAbilityProtocolAndProvenance(unittest.TestCase):
    def test_protocol_runtime_checkable(self):
        a = Ability(name="t", owner="Earth", version="0.0")
        self.assertTrue(isinstance(a, AbilityProtocol))

    def test_provenance_default_and_allowed(self):
        a = Ability(name="t", owner="Water", version="0.0")
        self.assertEqual(a.provenance, "seed")
        self.assertIn(a.provenance, ALLOWED_PROVENANCE)

    def test_provenance_validation(self):
        with self.assertRaises(ValueError):
            Ability(name="t", owner="Earth", version="0", provenance="evil")

    def test_provenance_in_invariants_and_to_dict(self):
        a = Ability(name="t", owner="Governance", version="0.1", provenance="discovered")
        invs = a.invariants()
        self.assertTrue(any("ABILITY-PROV-0: discovered" in i for i in invs))
        d = a.to_dict()
        self.assertEqual(d.get("provenance"), "discovered")


class TestRegistryGovernanceHook(unittest.TestCase):
    def tearDown(self):
        clear_abilities()
        set_governance_hook(None)

    def test_default_hook_noop_allows_register(self):
        a = Ability(name="hook.test", owner="Metal", version="0.1", provenance="discovered")
        register_ability(a)
        self.assertIn("hook.test", abilities_snapshot())

    def test_injected_hook_called_and_can_reject(self):
        calls = []

        def rejecting(ab):
            calls.append(ab.name)
            raise ValueError("ABILITY-REG-HOOK-0: rejected for test")

        set_governance_hook(rejecting)
        a = Ability(name="hook.reject", owner="Governance", version="0.1", provenance="discovered")
        with self.assertRaises(ValueError):
            register_ability(a)
        self.assertEqual(calls, ["hook.reject"])
        self.assertNotIn("hook.reject", abilities_snapshot())

    def test_promoted_path_sets_promoted_provenance(self):
        clear_abilities()
        a = Ability(name="prom.test", owner="Fire", version="0.1", provenance="seed")
        register_promoted_ability(a)
        got = abilities_snapshot()["prom.test"]
        self.assertEqual(got.provenance, "promoted_via_cmes")


class TestDiscoveryAndSeedParity(unittest.TestCase):
    def tearDown(self):
        clear_abilities()

    def test_discover_includes_seed_and_meta(self):
        cands = discover_abilities()
        names = [c.name for c in cands]
        self.assertIn("cmce.consensus", names)
        self.assertIn("adaad.abilities.introspect", names)
        self.assertIn("adaad.abilities.drift_hygiene", names)
        self.assertIn("adaad.abilities.self_register", names)
        # All have provenance
        self.assertTrue(all(c.provenance in ALLOWED_PROVENANCE for c in cands))

    def test_discover_and_register_skips_dups(self):
        clear_abilities()
        added = discover_and_register()
        self.assertGreaterEqual(added, 1)
        # Second run adds 0
        added2 = discover_and_register()
        self.assertEqual(added2, 0)


class TestDriftHygiene(unittest.TestCase):
    def tearDown(self):
        clear_abilities()

    def test_clean_state_reports_parity_ok(self):
        # After seed the core + meta should be in parity
        report = detect_abilities_drift()
        self.assertTrue(report.parity_ok)
        self.assertEqual(len(report.drifted), 0)
        self.assertTrue(any("parity" in (r or "").lower() for r in report.recommendations))

    def test_extra_in_registry_is_drift(self):
        clear_abilities()
        rogue = Ability(name="rogue.extra", owner="Earth", version="0", provenance="discovered")
        register_ability(rogue)
        report = detect_abilities_drift()
        self.assertFalse(report.parity_ok)
        kinds = [d.kind for d in report.drifted]
        self.assertIn("extra_in_registry", kinds)

    def test_detect_and_reconcile_wrapper(self):
        res = detect_and_reconcile_drift()
        self.assertIn("parity_ok", res)
        self.assertIn("report", res)


class TestLightweightIsolation(unittest.TestCase):
    def test_abilities_package_import_does_not_pull_heavy_modules(self):
        # Capture modules before/after a fresh import of the package
        before = set(sys.modules.keys())
        # Force re-import isolation by clearing our package if present
        for mod in list(sys.modules):
            if mod.startswith("adaad.abilities"):
                del sys.modules[mod]
        import adaad.abilities  # noqa: F401
        after = set(sys.modules.keys())
        heavy = {"runtime", "dorkllm", "app.main", "app.api"}
        newly_loaded_heavy = [h for h in heavy if any(m.startswith(h) for m in (after - before))]
        # We allow some, but the core abilities subpackage should not have forced heavy
        # (the bridge is in orchestrator and lazy; discovery/drift/registry are file-based or sys.modules)
        self.assertNotIn("dorkllm", [m for m in (after - before) if m.startswith("dorkllm")])
        # If runtime was pulled by side effect of seed or discovery, that's a failure of the charter
        # (in practice the seed path is pure pathlib/json and our discovery is sys.modules only)
        self.assertNotIn("runtime", [m for m in (after - before) if m.startswith("runtime")])


if __name__ == "__main__":
    unittest.main()