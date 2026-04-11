"""
Phase 132 · INNOV-41 · DORK Living Fleet — Test Suite
30/30 Hard + functional tests covering all six constitutional invariants.
Naming convention: T132-{CATEGORY}-{SEQ}
"""

import hashlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# ── ConversationLedger (DORK-STATE-0) — 6 tests ──────────────────────────────

from dorkllm.state import (
    ConversationLedger,
    ConversationLedgerViolation,
    ProviderHealthRegistry,
    ProviderStatus,
)


class TestConversationLedger:
    """T132-LEDGER-* — ConversationLedger append-only hash-chain invariant."""

    def test_T132_LEDGER_01_append_user_entry(self):
        """T132-LEDGER-01: appending a user entry returns a sealed dict."""
        ledger = ConversationLedger()
        entry = ledger.append("user", "hello")
        assert entry["role"] == "user"
        assert entry["seq"] == 0
        assert len(entry["entry_hash"]) == 64

    def test_T132_LEDGER_02_append_assistant_entry(self):
        """T132-LEDGER-02: assistant entry seq=1 after user entry seq=0."""
        ledger = ConversationLedger()
        ledger.append("user", "hello")
        entry = ledger.append("assistant", "hi there")
        assert entry["seq"] == 1

    def test_T132_LEDGER_03_genesis_prev_hash(self):
        """T132-LEDGER-03: first entry prev_hash equals GENESIS_HASH."""
        ledger = ConversationLedger()
        entry = ledger.append("user", "start")
        assert entry["prev_hash"] == ConversationLedger.GENESIS_HASH

    def test_T132_LEDGER_04_chain_links(self):
        """T132-LEDGER-04: second entry prev_hash == first entry entry_hash."""
        ledger = ConversationLedger()
        e1 = ledger.append("user", "msg1")
        e2 = ledger.append("assistant", "msg2")
        assert e2["prev_hash"] == e1["entry_hash"]

    def test_T132_LEDGER_05_verify_valid_chain(self):
        """T132-LEDGER-05: verify() returns (True, 'chain_valid') on intact chain."""
        ledger = ConversationLedger()
        for i in range(5):
            ledger.append("user" if i % 2 == 0 else "assistant", f"msg-{i}")
        valid, reason = ledger.verify()
        assert valid is True
        assert reason == "chain_valid"

    def test_T132_LEDGER_06_invalid_role_raises(self):
        """T132-LEDGER-06: invalid role raises ConversationLedgerViolation."""
        ledger = ConversationLedger()
        with pytest.raises(ConversationLedgerViolation):
            ledger.append("robot", "hi")

    def test_T132_LEDGER_07_verify_fails_on_modified_content_digest(self):
        """T132-LEDGER-07: verify() fails if content_digest is tampered."""
        ledger = ConversationLedger()
        ledger.append("user", "hello")
        ledger._entries[0]["content_digest"] = "f" * 24
        valid, reason = ledger.verify()
        assert valid is False
        assert reason == "Chain break at seq=0: entry_hash mismatch"

    def test_T132_LEDGER_08_verify_fails_on_modified_timestamp(self):
        """T132-LEDGER-08: verify() fails if timestamp is tampered."""
        ledger = ConversationLedger()
        ledger.append("assistant", "hello")
        ledger._entries[0]["timestamp"] = "2026-01-01T00:00:00+00:00"
        valid, reason = ledger.verify()
        assert valid is False
        assert reason == "Chain break at seq=0: entry_hash mismatch"

    def test_T132_LEDGER_09_verify_fails_on_modified_entry_hash(self):
        """T132-LEDGER-09: verify() fails if entry_hash is tampered."""
        ledger = ConversationLedger()
        ledger.append("user", "hello")
        ledger._entries[0]["entry_hash"] = "0" * 64
        valid, reason = ledger.verify()
        assert valid is False
        assert reason == "Chain break at seq=0: entry_hash mismatch"

    def test_T132_LEDGER_10_verify_fails_on_broken_prev_hash_chain(self):
        """T132-LEDGER-10: verify() fails if prev_hash chain is broken."""
        ledger = ConversationLedger()
        ledger.append("user", "first")
        ledger.append("assistant", "second")
        ledger._entries[1]["prev_hash"] = "a" * 64
        valid, reason = ledger.verify()
        assert valid is False
        assert reason == "Chain break at seq=1: prev_hash mismatch"


# ── ProviderHealthRegistry (DORK-PROV-0) — 5 tests ───────────────────────────

class TestProviderHealthRegistry:
    """T132-PROV-* — ProviderHealthRegistry structured probe recording."""

    def test_T132_PROV_01_record_healthy(self):
        """T132-PROV-01: recording a healthy status makes is_healthy() True."""
        reg = ProviderHealthRegistry()
        reg.record(ProviderStatus("ollama_local", True, 12.3))
        assert reg.is_healthy("ollama_local") is True

    def test_T132_PROV_02_record_unhealthy(self):
        """T132-PROV-02: recording an unhealthy status makes is_healthy() False."""
        reg = ProviderHealthRegistry()
        reg.record(ProviderStatus("ollama_local", False, 0.0, error="refused"))
        assert reg.is_healthy("ollama_local") is False

    def test_T132_PROV_03_availability_100pct(self):
        """T132-PROV-03: all healthy probes gives availability=1.0."""
        reg = ProviderHealthRegistry()
        for _ in range(5):
            reg.record(ProviderStatus("p", True, 5.0))
        assert reg.availability("p") == 1.0

    def test_T132_PROV_04_availability_partial(self):
        """T132-PROV-04: 2 healthy out of 4 probes gives availability=0.5."""
        reg = ProviderHealthRegistry()
        for h in [True, True, False, False]:
            reg.record(ProviderStatus("p", h, 1.0))
        assert reg.availability("p") == pytest.approx(0.5)

    def test_T132_PROV_05_unknown_provider_not_healthy(self):
        """T132-PROV-05: querying unknown provider returns is_healthy=False."""
        reg = ProviderHealthRegistry()
        assert reg.is_healthy("ghost") is False


# ── CONTEXT_KEYWORD_TAXONOMY / Jaccard (DORK-CTX-0) — 5 tests ────────────────

from dorkllm.context import (
    CONTEXT_KEYWORD_TAXONOMY,
    classify_query,
    get_taxonomy_hints,
    jaccard_score,
)


class TestContextTaxonomy:
    """T132-CTX-* — Taxonomy classification and Jaccard scoring."""

    def test_T132_CTX_01_taxonomy_has_required_categories(self):
        """T132-CTX-01: taxonomy contains all 8 required categories."""
        required = {"governance", "mutation", "replay", "ledger", "agent", "fleet", "release", "sandbox"}
        assert required == set(CONTEXT_KEYWORD_TAXONOMY.keys())

    def test_T132_CTX_02_jaccard_identical_sets(self):
        """T132-CTX-02: identical sets give Jaccard score of 1.0."""
        s = {"a", "b", "c"}
        assert jaccard_score(s, s) == pytest.approx(1.0)

    def test_T132_CTX_03_jaccard_disjoint_sets(self):
        """T132-CTX-03: disjoint sets give Jaccard score of 0.0."""
        assert jaccard_score({"x", "y"}, {"a", "b"}) == pytest.approx(0.0)

    def test_T132_CTX_04_classify_governance_query(self):
        """T132-CTX-04: 'gate blocked compliance' classifies as governance."""
        cat, conf = classify_query("gate blocked compliance")
        assert cat == "governance"
        assert conf > 0.0

    def test_T132_CTX_05_taxonomy_hints_returns_top3(self):
        """T132-CTX-05: get_taxonomy_hints returns exactly top_n results."""
        hints = get_taxonomy_hints("mutation ledger replay", top_n=3)
        assert len(hints) == 3
        assert all("category" in h and "score" in h for h in hints)


# ── DorkCommandResolver (DORK-CMD-0) — 6 tests ───────────────────────────────

from runtime.dork_cmd_resolver import (
    DorkCommandResolver,
    CommandError,
    ManifestLoadError,
    CommandLedgerEntry,
)

MANIFEST_PATH = ROOT / "data" / "dork" / "slash_commands.json"


class TestDorkCommandResolver:
    """T132-CMD-* — DORK-CMD-0 slash command validation and chain ledger."""

    def test_T132_CMD_01_resolve_known_command(self):
        """T132-CMD-01: known command resolves with status='ok'."""
        resolver = DorkCommandResolver(MANIFEST_PATH)
        result = resolver.resolve("/dork:gate")
        assert result["status"] == "ok"
        assert result["intent"] == "show_gate_status"

    def test_T132_CMD_02_unknown_command_is_error_not_forwarded(self):
        """T132-CMD-02: DORK-CMD-0 — unknown command returns status='error' never forwarded."""
        resolver = DorkCommandResolver(MANIFEST_PATH)
        result = resolver.resolve("/dork:unknown_xyz")
        assert result["status"] == "error"
        assert "DORK-CMD-0" in result["error"]

    def test_T132_CMD_03_bad_prefix_rejected(self):
        """T132-CMD-03: command without /dork: prefix is rejected."""
        resolver = DorkCommandResolver(MANIFEST_PATH)
        result = resolver.resolve("gate")
        assert result["status"] == "error"

    def test_T132_CMD_04_ledger_grows_on_each_call(self):
        """T132-CMD-04: ledger length increments on every resolve() call."""
        resolver = DorkCommandResolver(MANIFEST_PATH)
        resolver.resolve("/dork:gate")
        resolver.resolve("/dork:brief")
        assert resolver.ledger_len() == 2

    def test_T132_CMD_05_ledger_chain_valid_after_commands(self):
        """T132-CMD-05: verify_ledger() returns True after multiple dispatches."""
        resolver = DorkCommandResolver(MANIFEST_PATH)
        for cmd in ["/dork:gate", "/dork:brief", "/dork:fleet", "/dork:unknown"]:
            resolver.resolve(cmd)
        valid, reason = resolver.verify_ledger()
        assert valid is True

    def test_T132_CMD_06_args_parsed_from_input(self):
        """T132-CMD-06: --key value args are parsed into result['args'] dict."""
        resolver = DorkCommandResolver(MANIFEST_PATH)
        result = resolver.resolve("/dork:ledger --tail 5")
        assert result["args"].get("tail") == "5"

    def test_T132_CMD_07_verify_fails_on_tampered_intent(self):
        """T132-CMD-07: verify_ledger() fails if an entry intent is tampered."""
        resolver = DorkCommandResolver(MANIFEST_PATH)
        resolver.resolve("/dork:gate")
        resolver._ledger[0].intent = "tampered_intent"
        valid, reason = resolver.verify_ledger()
        assert valid is False
        assert reason == "Chain break at seq=0: entry_hash mismatch"

    def test_T132_CMD_08_verify_fails_on_tampered_status(self):
        """T132-CMD-08: verify_ledger() fails if an entry status is tampered."""
        resolver = DorkCommandResolver(MANIFEST_PATH)
        resolver.resolve("/dork:brief")
        resolver._ledger[0].status = "tampered_status"
        valid, reason = resolver.verify_ledger()
        assert valid is False
        assert reason == "Chain break at seq=0: entry_hash mismatch"

    def test_T132_CMD_09_verify_passes_for_untampered_chain(self):
        """T132-CMD-09: verify_ledger() still passes for an intact chain."""
        resolver = DorkCommandResolver(MANIFEST_PATH)
        resolver.resolve("/dork:gate")
        resolver.resolve("/dork:brief")
        resolver.resolve("/dork:fleet")
        valid, reason = resolver.verify_ledger()
        assert valid is True
        assert reason == "chain_valid"


# ── DORKLivingFleet (DORK-FLEET-0) — 8 tests ─────────────────────────────────

from runtime.innovations30.dork_living_fleet import (
    DORKLivingFleet,
    FleetEngine,
    FleetRouter,
    FleetBlockedError,
    FleetMutationBlockedError,
    INNOV_ID,
    PHASE,
    VERSION,
)


@pytest.fixture
def stub_engine():
    """A stub engine that reports healthy without a network probe."""
    engine = FleetEngine(
        name="stub", provider_type="stub", url="http://stub", model="dork-stub", priority=1
    )
    engine._healthy = True
    return engine


@pytest.fixture
def fleet(stub_engine):
    """A DORKLivingFleet with a stub engine."""
    return DORKLivingFleet(engines=[stub_engine], manifest_path=MANIFEST_PATH)


class TestDORKLivingFleet:
    """T132-FLEET-* — DORK-FLEET-0 orchestrator invariant enforcement."""

    def test_T132_FLEET_01_metadata_correct(self):
        """T132-FLEET-01: INNOV_ID, PHASE, VERSION constants are correct."""
        assert INNOV_ID == "INNOV-41"
        assert PHASE == 132
        assert VERSION == "9.64.0"

    def test_T132_FLEET_02_six_constitutional_invariants(self):
        """T132-FLEET-02: fleet declares exactly 6 Hard constitutional invariants."""
        assert len(DORKLivingFleet.CONSTITUTIONAL_INVARIANTS) == 6

    def test_T132_FLEET_03_fleet_status_always_queryable(self, fleet):
        """T132-FLEET-03: DORK-FLEET-0 — fleet_status() never raises, always returns dict."""
        status = fleet.fleet_status()
        assert isinstance(status, dict)
        assert "blocked" in status
        assert "healthy_provider_count" in status

    def test_T132_FLEET_04_fleet_blocked_when_no_healthy(self):
        """T132-FLEET-04: FleetBlockedError raised when no healthy providers."""
        dead_engine = FleetEngine("dead", "stub", "http://dead", "dork", 1)
        dead_engine._healthy = False
        router = FleetRouter([dead_engine])
        with pytest.raises(FleetBlockedError):
            router.select()

    def test_T132_FLEET_05_healthy_engine_selected(self, stub_engine):
        """T132-FLEET-05: FleetRouter selects healthy engine successfully."""
        router = FleetRouter([stub_engine])
        selected = router.select()
        assert selected.name == "stub"

    def test_T132_FLEET_06_slash_dispatch_ok(self, fleet):
        """T132-FLEET-06: known slash command dispatched via fleet returns status='ok'."""
        result = fleet.dispatch_slash("/dork:gate")
        assert result["status"] == "ok"

    def test_T132_FLEET_07_mutation_blocked_without_resolver_pass(self, fleet):
        """T132-FLEET-07: DORK-FLEET-0 — assert_promotion_allowed raises on error result."""
        bad_result = {"status": "error", "error": "DORK-CMD-0: unknown command"}
        with pytest.raises(FleetMutationBlockedError):
            fleet.assert_promotion_allowed(bad_result)

    def test_T132_FLEET_08_dispatch_ledger_chain_valid(self, fleet):
        """T132-FLEET-08: dispatch chain ledger verifies after multiple dispatches."""
        fleet.dispatch_slash("/dork:gate")
        fleet.dispatch_slash("/dork:brief")
        fleet.query("what is gate status?")
        valid, reason = fleet.verify_dispatch_ledger()
        assert valid is True

    def test_T132_FLEET_09_non_slash_dispatch_uses_provider_adapter(self, monkeypatch):
        """T132-FLEET-09: non-slash query dispatches through selected provider adapter."""
        engine = FleetEngine("engine", "dork_engine", "", "dork-model", 1)
        engine._healthy = True
        fleet = DORKLivingFleet(engines=[engine], manifest_path=MANIFEST_PATH)

        monkeypatch.setattr(
            fleet,
            "_dispatch_via_dork_engine",
            lambda text, eng: "adapter-response-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
        fleet._provider_dispatchers["dork_engine"] = fleet._dispatch_via_dork_engine

        result = fleet.query("tell me something")
        assert result.status == "ok"
        assert "[hash-redacted]" in result.response
        tail = fleet.conversation_ledger_tail(2)
        assert [e["role"] for e in tail] == ["user", "assistant"]

    def test_T132_FLEET_10_provider_failure_respects_fallback_policy(self, monkeypatch):
        """T132-FLEET-10: first provider failover dispatches to second healthy provider deterministically."""
        p1 = FleetEngine("p1", "dork_engine", "", "m1", 1)
        p2 = FleetEngine("p2", "dork_engine", "", "m2", 2)
        p1._healthy = True
        p2._healthy = True
        fleet = DORKLivingFleet(engines=[p1, p2], manifest_path=MANIFEST_PATH)

        seen = []

        def dispatch(_text, eng):
            seen.append(eng.name)
            if eng.name == "p1":
                raise RuntimeError("p1 down")
            return "p2 ok aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

        monkeypatch.setattr(fleet, "_dispatch_provider", dispatch)

        result = fleet.query("status please")
        assert result.status == "ok"
        assert result.engine_used == "p2"
        assert seen == ["p1", "p2"]
        summary = fleet._provider_registry.summary()
        assert summary["p1"]["healthy"] is False
        assert summary["p1"]["last_error"] == "p1 down"

    def test_T132_FLEET_11_all_provider_failures_preserve_fail_closed_and_fallback(self, monkeypatch):
        """T132-FLEET-11: all failed retries return error unless deterministic fallback is explicitly enabled."""
        p1 = FleetEngine("p1", "dork_engine", "", "m1", 1)
        p2 = FleetEngine("p2", "dork_engine", "", "m2", 2)
        p1._healthy = True
        p2._healthy = True
        fleet = DORKLivingFleet(engines=[p1, p2], manifest_path=MANIFEST_PATH)

        def always_fail(_text, eng):
            raise RuntimeError(f"{eng.name} down")

        monkeypatch.setattr(fleet, "_dispatch_provider", always_fail)

        monkeypatch.delenv("ADAAD_DORK_FLEET_ALLOW_DETERMINISTIC_FALLBACK", raising=False)
        result_error = fleet.query("status please")
        assert result_error.status == "error"
        assert result_error.error is not None
        assert '"attempted_providers": ["p1", "p2"]' in result_error.error
        assert '"fallback_applied": false' in result_error.error

        monkeypatch.setenv("ADAAD_DORK_FLEET_ALLOW_DETERMINISTIC_FALLBACK", "true")
        p1._healthy = True
        p2._healthy = True
        result_fallback = fleet.query("status please")
        assert result_fallback.status == "ok"
        assert "[DORK-FLEET deterministic fallback]" in result_fallback.response
        assert result_fallback.error is not None
        assert '"fallback_applied": true' in result_fallback.error

    def test_T132_FLEET_12_deterministic_order_and_retry_bound(self, monkeypatch):
        """T132-FLEET-12: retry sequence is priority-ordered and bounded to min(3, total providers)."""
        providers = [
            FleetEngine("p1", "dork_engine", "", "m1", 1),
            FleetEngine("p2", "dork_engine", "", "m2", 2),
            FleetEngine("p3", "dork_engine", "", "m3", 3),
            FleetEngine("p4", "dork_engine", "", "m4", 4),
        ]
        for provider in providers:
            provider._healthy = True
        fleet = DORKLivingFleet(engines=providers, manifest_path=MANIFEST_PATH)

        seen = []

        def always_fail(_text, eng):
            seen.append(eng.name)
            raise RuntimeError(f"{eng.name} failed")

        monkeypatch.setattr(fleet, "_dispatch_provider", always_fail)
        monkeypatch.delenv("ADAAD_DORK_FLEET_ALLOW_DETERMINISTIC_FALLBACK", raising=False)

        result = fleet.query("bounded retries")
        assert result.status == "error"
        assert seen == ["p1", "p2", "p3"]
        assert result.error is not None
        assert '"max_attempts": 3' in result.error
        assert '"attempted_providers": ["p1", "p2", "p3"]' in result.error

    def test_T132_FLEET_13_output_sanitization_applied_on_success_and_failure(self, monkeypatch):
        """T132-FLEET-13: OPT-005 sanitizer is always applied for provider output and error payloads."""
        engine = FleetEngine("engine", "dork_engine", "", "dork-model", 1)
        engine._healthy = True
        fleet = DORKLivingFleet(engines=[engine], manifest_path=MANIFEST_PATH)

        monkeypatch.setattr(
            fleet,
            "_dispatch_via_dork_engine",
            lambda _text, _eng: "ok cccccccccccccccccccccccccccccccc",
        )
        fleet._provider_dispatchers["dork_engine"] = fleet._dispatch_via_dork_engine
        ok_result = fleet.query("normal")
        assert "[hash-redacted]" in ok_result.response

        def boom(_text, _eng):
            raise RuntimeError("bad dddddddddddddddddddddddddddddddd")

        monkeypatch.setattr(fleet, "_dispatch_via_dork_engine", boom)
        fleet._provider_dispatchers["dork_engine"] = fleet._dispatch_via_dork_engine
        monkeypatch.delenv("ADAAD_DORK_FLEET_ALLOW_DETERMINISTIC_FALLBACK", raising=False)
        err_result = fleet.query("normal")
        assert "[hash-redacted]" in err_result.response
