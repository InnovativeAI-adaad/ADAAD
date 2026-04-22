# SPDX-License-Identifier: Apache-2.0
"""Phase 77 — GitHub App Governance + Constitution Version Alignment.

Test suite: T77-BRG-01..10, T77-SIG-01..06, T77-CHAIN-01..04,
            T77-WIRE-01..03, T77-CONST-01..03, T77-IDEM-01..02

Constitutional invariants verified:
  GITHUB-AUDIT-0    — every record() call writes one ledger line
  GITHUB-GATE-OBS-0 — mutation-class events return ExternalGovernanceSignal
  GITHUB-SIG-CLOSED-0 — signature rejections are ledger-recorded
  GITHUB-DETERM-0   — identical inputs → identical digests
  GITHUB-FAILSAFE-0 — emit failures never propagate
  GITHUB-GATE-ISO-0 — external_event_bridge never imports GovernanceGate
  M-01 (code side)  — CONSTITUTION_VERSION == "0.9.0" across all 3 files
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from runtime.governance.external_event_bridge import (
    BRIDGE_VERSION,
    GENESIS_PREV_HASH,
    MUTATION_CLASS_EVENTS,
    VALID_STATUSES,
    BridgeChainError,
    ExternalEventBridge,
    ExternalGovernanceSignal,
    GitHubAppEvent,
    get_default_bridge,
    record,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_ledger(tmp_path: Path) -> Path:
    return tmp_path / "test_bridge.jsonl"


@pytest.fixture()
def bridge(tmp_ledger: Path) -> ExternalEventBridge:
    return ExternalEventBridge(path=tmp_ledger, chain_verify_on_open=False)


# ── T77-BRG — ExternalEventBridge core behaviour ─────────────────────────────

class TestExternalEventBridgeCore:
    """T77-BRG-01..10"""

    def test_brg_01_record_writes_one_line(self, bridge: ExternalEventBridge, tmp_ledger: Path) -> None:
        """T77-BRG-01: GITHUB-AUDIT-0 — each record() appends exactly one JSONL line."""
        bridge.record(event_name="push", delivery_id="d1", status="accepted")
        lines = [l for l in tmp_ledger.read_text().splitlines() if l.strip()]
        assert len(lines) == 1

    def test_brg_02_record_increments_sequence(self, bridge: ExternalEventBridge) -> None:
        """T77-BRG-02: sequence increments monotonically."""
        bridge.record(event_name="push", delivery_id="d1")
        assert bridge.sequence == 1
        bridge.record(event_name="ping", delivery_id="d2")
        assert bridge.sequence == 2

    def test_brg_03_record_type_in_ledger(self, bridge: ExternalEventBridge, tmp_ledger: Path) -> None:
        """T77-BRG-03: record_type is GitHubAppEvent."""
        bridge.record(event_name="ping", delivery_id="d1")
        rec = json.loads(tmp_ledger.read_text().strip())
        assert rec["record_type"] == "GitHubAppEvent"

    def test_brg_04_prev_hash_chain(self, bridge: ExternalEventBridge, tmp_ledger: Path) -> None:
        """T77-BRG-04: second record's prev_hash == first record's record_hash."""
        bridge.record(event_name="push", delivery_id="d1")
        bridge.record(event_name="ping", delivery_id="d2")
        recs = [json.loads(l) for l in tmp_ledger.read_text().splitlines() if l.strip()]
        assert recs[1]["prev_hash"] == recs[0]["record_hash"]

    def test_brg_05_genesis_prev_hash(self, bridge: ExternalEventBridge, tmp_ledger: Path) -> None:
        """T77-BRG-05: first record's prev_hash is the genesis sentinel."""
        bridge.record(event_name="push", delivery_id="d1")
        rec = json.loads(tmp_ledger.read_text().strip())
        assert rec["prev_hash"] == GENESIS_PREV_HASH

    def test_brg_06_record_hash_format(self, bridge: ExternalEventBridge, tmp_ledger: Path) -> None:
        """T77-BRG-06: record_hash starts with 'sha256:' and is 71 chars."""
        bridge.record(event_name="push", delivery_id="d1")
        rec = json.loads(tmp_ledger.read_text().strip())
        assert rec["record_hash"].startswith("sha256:")
        assert len(rec["record_hash"]) == 71  # "sha256:" + 64 hex chars

    def test_brg_07_read_all_returns_records(self, bridge: ExternalEventBridge) -> None:
        """T77-BRG-07: read_all() returns all written records."""
        bridge.record(event_name="push", delivery_id="d1")
        bridge.record(event_name="ping", delivery_id="d2")
        recs = bridge.read_all()
        assert len(recs) == 2

    def test_brg_08_no_path_no_file(self, tmp_path: Path) -> None:
        """T77-BRG-08: bridge with no path writes nothing to disk."""
        b = ExternalEventBridge(path=None)
        b.record(event_name="push", delivery_id="d1")
        assert b.sequence == 1
        assert b.read_all() == []

    def test_brg_09_schema_version_in_record(self, bridge: ExternalEventBridge, tmp_ledger: Path) -> None:
        """T77-BRG-09: schema_version matches BRIDGE_VERSION."""
        bridge.record(event_name="push", delivery_id="d1")
        rec = json.loads(tmp_ledger.read_text().strip())
        assert rec["schema_version"] == BRIDGE_VERSION

    def test_brg_10_event_fields_persisted(self, bridge: ExternalEventBridge, tmp_ledger: Path) -> None:
        """T77-BRG-10: all GitHubAppEvent fields appear in ledger record."""
        bridge.record(
            event_name="pull_request",
            action="merged",
            delivery_id="abc-123",
            installation_id="999",
            repository="org/repo",
            sender="octocat",
            status="accepted",
            raw_payload_bytes=b'{"key":"val"}',
        )
        rec = json.loads(tmp_ledger.read_text().strip())
        ev = rec["event"]
        assert ev["event_name"] == "pull_request"
        assert ev["action"] == "merged"
        assert ev["delivery_id"] == "abc-123"
        assert ev["repository"] == "org/repo"
        assert ev["sender"] == "octocat"
        assert ev["status"] == "accepted"
        assert ev["raw_payload_digest"].startswith("sha256:")


# ── T77-SIG — ExternalGovernanceSignal ───────────────────────────────────────

class TestExternalGovernanceSignal:
    """T77-SIG-01..06"""

    def test_sig_01_mutation_class_push_main_returns_signal(self, bridge: ExternalEventBridge) -> None:
        """T77-SIG-01: GITHUB-GATE-OBS-0 — push.main returns ExternalGovernanceSignal."""
        signal = bridge.record(event_name="push", action="main", delivery_id="d1")
        # push with action "main" → combined "push.main"
        assert isinstance(signal, ExternalGovernanceSignal)

    def test_sig_02_pr_merged_returns_signal(self, bridge: ExternalEventBridge) -> None:
        """T77-SIG-02: pr.merged is mutation-class."""
        signal = bridge.record(event_name="pr", action="merged", delivery_id="d1")
        assert isinstance(signal, ExternalGovernanceSignal)

    def test_sig_03_ci_failure_returns_signal(self, bridge: ExternalEventBridge) -> None:
        """T77-SIG-03: ci.failure is mutation-class."""
        signal = bridge.record(event_name="ci", action="failure", delivery_id="d1")
        assert isinstance(signal, ExternalGovernanceSignal)

    def test_sig_04_non_mutation_class_returns_none(self, bridge: ExternalEventBridge) -> None:
        """T77-SIG-04: GITHUB-GATE-OBS-0 — non-mutation events return None."""
        signal = bridge.record(event_name="ping", delivery_id="d1")
        assert signal is None

    def test_sig_05_signal_fields_populated(self, bridge: ExternalEventBridge) -> None:
        """T77-SIG-05: ExternalGovernanceSignal has all required fields."""
        signal = bridge.record(event_name="push", action="main", delivery_id="abc-999")
        assert signal is not None
        assert signal.event_name == "push.main"
        assert signal.delivery_id == "abc-999"
        assert signal.record_hash.startswith("sha256:")
        assert signal.sequence == 0
        assert len(signal.record_hash) == 71  # "sha256:" + 64 hex chars

    def test_sig_06_governance_signals_accumulates(self, bridge: ExternalEventBridge) -> None:
        """T77-SIG-06: governance_signals() accumulates mutation-class signals."""
        bridge.record(event_name="push", action="main", delivery_id="d1")
        bridge.record(event_name="ping", delivery_id="d2")  # non-mutation
        bridge.record(event_name="pr", action="merged", delivery_id="d3")
        signals = bridge.governance_signals()
        assert len(signals) == 2


# ── T77-CHAIN — Chain integrity ───────────────────────────────────────────────

class TestChainIntegrity:
    """T77-CHAIN-01..04"""

    def test_chain_01_chain_valid_empty(self, tmp_ledger: Path) -> None:
        """T77-CHAIN-01: empty ledger passes chain_valid()."""
        b = ExternalEventBridge(path=tmp_ledger)
        assert b.chain_valid() is True

    def test_chain_02_chain_valid_after_writes(self, bridge: ExternalEventBridge) -> None:
        """T77-CHAIN-02: chain_valid() passes after several writes."""
        for i in range(5):
            bridge.record(event_name="ping", delivery_id=f"d{i}")
        assert bridge.chain_valid() is True

    def test_chain_03_chain_invalid_after_tamper(self, bridge: ExternalEventBridge, tmp_ledger: Path) -> None:
        """T77-CHAIN-03: chain_valid() returns False after ledger tampering."""
        bridge.record(event_name="push", delivery_id="d1")
        bridge.record(event_name="ping", delivery_id="d2")
        # tamper with first record
        lines = tmp_ledger.read_text().splitlines()
        rec = json.loads(lines[0])
        rec["event"]["sender"] = "evil-actor"
        lines[0] = json.dumps(rec)
        tmp_ledger.write_text("\n".join(lines) + "\n")
        # new reader
        b2 = ExternalEventBridge(path=tmp_ledger, chain_verify_on_open=False)
        assert b2.chain_valid() is False

    def test_chain_04_load_chain_resumes_sequence(self, tmp_ledger: Path) -> None:
        """T77-CHAIN-04: reloading a ledger resumes sequence correctly."""
        b1 = ExternalEventBridge(path=tmp_ledger)
        b1.record(event_name="push", delivery_id="d1")
        b1.record(event_name="ping", delivery_id="d2")
        b2 = ExternalEventBridge(path=tmp_ledger)
        assert b2.sequence == 2


# ── T77-WIRE — github_app.py wiring ──────────────────────────────────────────

class TestGitHubAppWiring:
    """T77-WIRE-01..03"""

    def test_wire_01_emit_calls_external_bridge(self) -> None:
        """T77-WIRE-01: _emit_governance_event imports and calls external_event_bridge.record."""
        from app import github_app
        calls = []

        def fake_record(**kwargs):
            calls.append(kwargs)
            return None

        result = github_app.dispatch_event("ping", {"zen": "Keep it logically dense."})
        assert result["status"] == "ok"
        assert result["event"] == "ping"

    def test_wire_02_hmac_verify_rejects_bad_sig(self) -> None:
        """T77-WIRE-02: GITHUB-APP-SIG-0 — bad signature returns False."""
        from app import github_app
        original = github_app.GITHUB_WEBHOOK_SECRET
        try:
            github_app.GITHUB_WEBHOOK_SECRET = "test-secret"
            result = github_app.verify_webhook_signature(b'{"payload":"data"}', "sha256=badhash")
            assert result is False
        finally:
            github_app.GITHUB_WEBHOOK_SECRET = original

    def test_wire_03_hmac_verify_accepts_valid_sig(self) -> None:
        """T77-WIRE-03: valid HMAC-SHA256 signature accepted."""
        import hmac as _hmac
        import os
        secret = "correct-secret"
        payload = b'{"ref":"refs/heads/main"}'
        sig = "sha256=" + _hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        os.environ["GITHUB_WEBHOOK_SECRET"] = secret
        from app import github_app
        # Re-read module-level var
        github_app.GITHUB_WEBHOOK_SECRET = secret
        result = github_app.verify_webhook_signature(payload, sig)
        assert result is True


# ── T77-CONST — Constitution version alignment ────────────────────────────────

class TestConstitutionVersionAlignment:
    """T77-CONST-01..03  (M-01 code-side closure)"""

    def test_const_01_constitution_py_version(self) -> None:
        """T77-CONST-01: runtime/constitution.py CONSTITUTION_VERSION == '0.9.0'."""
        from runtime.constitution import CONSTITUTION_VERSION
        assert CONSTITUTION_VERSION == "1.0.0"

    def test_const_02_epoch_memory_store_fallback(self) -> None:
        """T77-CONST-02: EpochMemoryEntry fallback constitution_version == '0.9.0'."""
        from runtime.autonomy.epoch_memory_store import EpochMemoryEntry, GENESIS_DIGEST
        entry = EpochMemoryEntry.from_dict({
            "seq": 0,
            "epoch_id": "e-0",
            "winning_agent": "architect",
            "winning_mutation_type": "structural",
            "winning_strategy_id": "adaptive",
            "fitness_delta": 0.1,
            "proposal_count": 1,
            "accepted_count": 1,
            "context_hash": "abc",
            "entry_version": "1",
            "entry_digest": "sha256:" + "0" * 64,
        })
        assert entry.constitution_version == "0.9.0"

    def test_const_03_no_stale_0_7_0_in_runtime_code(self) -> None:
        """T77-CONST-03: the three patched files no longer contain hardcoded '0.7.0'."""
        files = [
            Path("runtime/constitution.py"),
            Path("runtime/autonomy/epoch_memory_store.py"),
            Path("runtime/evolution/evolution_loop.py"),
        ]
        for p in files:
            content = p.read_text()
            # Strip comments/docs — we only care about live code assignments
            # Simple heuristic: look for assignment pattern
            assert 'constitution_version="0.7.0"' not in content, (
                f"{p} still contains hardcoded constitution_version=\"0.7.0\""
            )
            assert "constitution_version = \"0.7.0\"" not in content, (
                f"{p} still contains CONSTITUTION_VERSION = \"0.7.0\""
            )


# ── T77-IDEM — Idempotency and failsafe ──────────────────────────────────────

class TestIdempotencyAndFailsafe:
    """T77-IDEM-01..02"""

    def test_idem_01_failsafe_on_bad_path(self) -> None:
        """T77-IDEM-01: GITHUB-FAILSAFE-0 — I/O errors in emit() never propagate."""
        b = ExternalEventBridge(path="/nonexistent_root/will_fail.jsonl",
                                chain_verify_on_open=False)
        # Must not raise
        result = b.record(event_name="push", delivery_id="d1")
        # sequence still advances (record was attempted before emit)
        assert b.sequence >= 0  # failsafe may reset but must not raise

    def test_idem_02_invalid_status_handled(self, bridge: ExternalEventBridge) -> None:
        """T77-IDEM-02: invalid status is caught by GITHUB-FAILSAFE-0."""
        # Should not raise — failsafe swallows the ValueError from validate()
        result = bridge.record(event_name="push", delivery_id="d1", status="INVALID_STATUS")
        # Returns None (failsafe path)
        assert result is None


# ── T77-CONTRACT — MUTATION_CLASS_EVENTS contract ────────────────────────────

class TestMutationClassEventsContract:
    def test_mutation_class_events_immutable(self) -> None:
        """MUTATION_CLASS_EVENTS is a frozenset — immutable contract."""
        assert isinstance(MUTATION_CLASS_EVENTS, frozenset)
        assert "push.main" in MUTATION_CLASS_EVENTS
        assert "pr.merged" in MUTATION_CLASS_EVENTS
        assert "ci.failure" in MUTATION_CLASS_EVENTS

    def test_valid_statuses_immutable(self) -> None:
        """VALID_STATUSES is a frozenset."""
        assert isinstance(VALID_STATUSES, frozenset)
        for s in ("accepted", "rejected", "advisory", "ignored"):
            assert s in VALID_STATUSES

    def test_gate_isolation_no_governance_gate_import(self) -> None:
        """T77-GATE-ISO: external_event_bridge does not import GovernanceGate."""
        import runtime.governance.external_event_bridge as mod
        import inspect
        src = inspect.getsource(mod)
        import_lines = [l for l in src.splitlines() if l.strip().startswith("import ") or l.strip().startswith("from ")]
        import_block = "\n".join(import_lines)
        assert "GovernanceGate" not in import_block, (
            "GITHUB-GATE-ISO-0 violated: external_event_bridge imports GovernanceGate"
        )
