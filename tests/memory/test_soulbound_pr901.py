# SPDX-License-Identifier: Apache-2.0
"""Phase 9 PR-9-01 test suite — SoulboundLedger + ContextFilterChain + SoulboundKey.

Test IDs: T9-01-01 through T9-01-25

Coverage:
  SoulboundKey       (T9-01-01..05)  — get_key / sign / verify / fail-closed
  SoulboundLedger    (T9-01-06..17)  — append / verify_chain / rotate / tamper / chain
  ContextFilterChain (T9-01-18..25)  — built-in filters / custom / edge cases
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest
pytestmark = pytest.mark.regression_standard

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_KEY = bytes.fromhex("a" * 64)   # 32 bytes — valid test key


def _audit_noop(tx_type: str, payload: Dict[str, Any]) -> None:
    """No-op audit writer for tests that don't need to inspect events."""


def _make_ledger(tmp_path: Path, *, collect_events: bool = False):
    """Build a SoulboundLedger with a fixed test key and temp storage."""
    from runtime.memory.soulbound_ledger import SoulboundLedger
    events = []
    writer = (lambda t, p: events.append((t, p))) if collect_events else _audit_noop
    ledger = SoulboundLedger(
        ledger_path=tmp_path / "ledger.json",
        audit_writer=writer,
        key_override=TEST_KEY,
    )
    return (ledger, events) if collect_events else ledger


def _valid_payload(epoch_id: str = "epoch-001", **extra) -> Dict[str, Any]:
    return {"epoch_id": epoch_id, "context_hash": "abc123", **extra}


# ============================================================================
# SoulboundKey — T9-01-01..05
# ============================================================================

class TestSoulboundKey:

    def test_T9_01_01_get_key_raises_when_env_absent(self, monkeypatch):
        """SoulboundKeyError must be raised when ADAAD_SOULBOUND_KEY is not set."""
        from runtime.memory.soulbound_key import get_key, SoulboundKeyError, ENV_VAR
        monkeypatch.delenv(ENV_VAR, raising=False)
        with pytest.raises(SoulboundKeyError, match=ENV_VAR):
            get_key()

    def test_T9_01_02_get_key_raises_on_non_hex(self, monkeypatch):
        """SoulboundKeyError must be raised if env var is not valid hex."""
        from runtime.memory.soulbound_key import get_key, SoulboundKeyError, ENV_VAR
        monkeypatch.setenv(ENV_VAR, "not-valid-hex!!")
        with pytest.raises(SoulboundKeyError):
            get_key()

    def test_T9_01_03_get_key_raises_on_too_short(self, monkeypatch):
        """SoulboundKeyError must be raised for keys shorter than 32 bytes (64 hex)."""
        from runtime.memory.soulbound_key import get_key, SoulboundKeyError, ENV_VAR, MIN_KEY_BYTES
        short_hex = "aa" * (MIN_KEY_BYTES - 1)
        monkeypatch.setenv(ENV_VAR, short_hex)
        with pytest.raises(SoulboundKeyError, match="minimum"):
            get_key()

    def test_T9_01_04_sign_and_verify_round_trip(self):
        """sign() output must be verifiable by verify() with the same key."""
        from runtime.memory.soulbound_key import sign, verify as key_verify
        data = b"ADAAD:soulbound:test:payload"
        sig = sign(data, key=TEST_KEY)
        assert key_verify(data, sig, key=TEST_KEY) is True

    def test_T9_01_05_verify_returns_false_on_tampered_data(self):
        """verify() must return False if data has been tampered after signing."""
        from runtime.memory.soulbound_key import sign, verify as key_verify
        data = b"original payload"
        sig = sign(data, key=TEST_KEY)
        tampered = b"tampered payload"
        assert key_verify(tampered, sig, key=TEST_KEY) is False


# ============================================================================
# SoulboundLedger — T9-01-06..17
# ============================================================================

class TestSoulboundLedger:

    def test_T9_01_06_append_returns_accepted_result(self, tmp_path):
        """append() must return AppendResult with accepted=True for valid input."""
        ledger = _make_ledger(tmp_path)
        result = ledger.append(
            epoch_id="epoch-001",
            context_type="mutation_proposal",
            payload=_valid_payload(),
        )
        assert result.accepted is True
        assert result.entry.epoch_id == "epoch-001"
        assert result.entry.context_type == "mutation_proposal"

    def test_T9_01_07_append_rejects_invalid_context_type(self, tmp_path):
        """append() must reject unknown context_type values."""
        ledger = _make_ledger(tmp_path)
        result = ledger.append(
            epoch_id="epoch-001",
            context_type="totally_invalid_type",
            payload=_valid_payload(),
        )
        assert result.accepted is False
        assert result.rejection_reason is not None
        assert "invalid_context_type" in result.rejection_reason

    def test_T9_01_08_append_rejects_empty_payload(self, tmp_path):
        """append() must reject empty payloads."""
        ledger = _make_ledger(tmp_path)
        result = ledger.append(
            epoch_id="epoch-001",
            context_type="mutation_proposal",
            payload={},
        )
        assert result.accepted is False
        assert result.rejection_reason is not None

    def test_T9_01_09_entry_has_valid_hmac_signature(self, tmp_path):
        """Every accepted entry's hmac_signature must verify against its signable_bytes."""
        from runtime.memory.soulbound_key import verify as key_verify
        ledger = _make_ledger(tmp_path)
        result = ledger.append(
            epoch_id="epoch-002",
            context_type="fitness_signal",
            payload=_valid_payload("epoch-002", score=0.78),
        )
        assert result.accepted
        entry = result.entry
        assert key_verify(entry.signable_bytes(), entry.hmac_signature, key=TEST_KEY) is True

    def test_T9_01_10_chain_hash_links_entries(self, tmp_path):
        """chain_hash of entry N must depend on chain_hash of entry N-1."""
        ledger = _make_ledger(tmp_path)
        r1 = ledger.append(epoch_id="e1", context_type="mutation_proposal",
                            payload=_valid_payload("e1"))
        r2 = ledger.append(epoch_id="e2", context_type="mutation_proposal",
                            payload=_valid_payload("e2", mutation_id="m-999"))
        # chain_hash of r2 must differ from r1 (it incorporates r1's chain_hash)
        assert r1.entry.chain_hash != r2.entry.chain_hash
        # r2's chain_hash must NOT equal genesis hash
        from runtime.memory.soulbound_ledger import GENESIS_CHAIN_HASH
        assert r2.entry.chain_hash != GENESIS_CHAIN_HASH

    def test_T9_01_11_verify_chain_returns_true_on_intact_ledger(self, tmp_path):
        """verify_chain() must return (True, []) for an unmodified ledger."""
        ledger = _make_ledger(tmp_path)
        for i in range(3):
            ledger.append(epoch_id=f"e{i}", context_type="mutation_proposal",
                          payload=_valid_payload(f"e{i}"))
        ok, failures = ledger.verify_chain()
        assert ok is True
        assert failures == []

    def test_T9_01_12_verify_chain_detects_tamper_on_modified_entry(self, tmp_path):
        """verify_chain() must detect chain_hash corruption."""
        ledger_path = tmp_path / "ledger.json"
        ledger = _make_ledger(tmp_path)
        ledger.append(epoch_id="e1", context_type="mutation_proposal",
                      payload=_valid_payload("e1"))
        # Corrupt the stored chain data
        raw = json.loads(ledger_path.read_text())
        if raw.get("entries"):
            raw["entries"][0]["payload"]["chain_hash"] = "deadbeef" * 8
            ledger_path.write_text(json.dumps(raw))
        ok, failures = ledger.verify_chain()
        assert ok is False
        assert len(failures) > 0

    def test_T9_01_13_audit_events_emitted_on_accept(self, tmp_path):
        """context_ledger_entry_accepted.v1 must be emitted on every accept."""
        ledger, events = _make_ledger(tmp_path, collect_events=True)
        ledger.append(epoch_id="e1", context_type="mutation_proposal",
                      payload=_valid_payload("e1"))
        accepted_events = [e for e in events if e[0] == "context_ledger_entry_accepted.v1"]
        assert len(accepted_events) == 1

    def test_T9_01_14_audit_events_emitted_on_reject(self, tmp_path):
        """context_ledger_entry_rejected.v1 must be emitted on every rejection."""
        ledger, events = _make_ledger(tmp_path, collect_events=True)
        ledger.append(epoch_id="e1", context_type="INVALID_TYPE",
                      payload=_valid_payload("e1"))
        rejected_events = [e for e in events if e[0] == "context_ledger_entry_rejected.v1"]
        assert len(rejected_events) == 1

    def test_T9_01_15_soulbound_key_absent_raises_and_emits_event(self, tmp_path, monkeypatch):
        """Missing ADAAD_SOULBOUND_KEY must raise SoulboundKeyError and emit event."""
        from runtime.memory.soulbound_key import SoulboundKeyError, ENV_VAR
        from runtime.memory.soulbound_ledger import SoulboundLedger
        monkeypatch.delenv(ENV_VAR, raising=False)
        events = []
        ledger = SoulboundLedger(
            ledger_path=tmp_path / "ledger.json",
            audit_writer=lambda t, p: events.append((t, p)),
            key_override=None,   # Force env lookup
        )
        with pytest.raises(SoulboundKeyError):
            ledger.append(epoch_id="e1", context_type="mutation_proposal",
                          payload=_valid_payload("e1"))
        absent_events = [e for e in events if e[0] == "soulbound_key_absent.v1"]
        assert len(absent_events) == 1

    def test_T9_01_16_entry_count_tracks_accepted_entries(self, tmp_path):
        """entry_count() must accurately reflect the number of accepted entries."""
        ledger = _make_ledger(tmp_path)
        assert ledger.entry_count() == 0
        for i in range(4):
            ledger.append(epoch_id=f"e{i}", context_type="mutation_proposal",
                          payload=_valid_payload(f"e{i}"))
        assert ledger.entry_count() == 4

    def test_T9_01_17_rotate_key_emits_rotation_event(self, tmp_path):
        """rotate_key() must emit soulbound_key_rotation.v1 journal event."""
        ledger, events = _make_ledger(tmp_path, collect_events=True)
        new_key = bytes.fromhex("b" * 64)
        ledger.rotate_key(new_key=new_key)
        rotation_events = [e for e in events if e[0] == "soulbound_key_rotation.v1"]
        assert len(rotation_events) == 1


class TestSoulboundLedgerFilterIntegration:
    def test_T9_01_26_append_rejects_missing_epoch_id_without_manual_filter(self, tmp_path):
        """append() must apply ContextFilterChain and reject payloads missing epoch_id."""
        ledger, events = _make_ledger(tmp_path, collect_events=True)
        result = ledger.append(
            epoch_id="epoch-901",
            context_type="mutation_proposal",
            payload={"context_hash": "abc123"},
        )

        assert result.accepted is False
        assert result.rejection_reason == "payload_missing_epoch_id"
        assert ledger.entry_count() == 0
        rejected_events = [e for e in events if e[0] == "context_ledger_entry_rejected.v1"]
        assert rejected_events[-1][1]["rejecting_filter"] == "epoch_id_required"

    def test_T9_01_27_append_rejects_oversized_payload_without_manual_filter(self, tmp_path):
        """append() must apply payload size limits before digesting or signing."""
        from runtime.memory.context_filter_chain import MAX_PAYLOAD_BYTES

        ledger, events = _make_ledger(tmp_path, collect_events=True)
        result = ledger.append(
            epoch_id="epoch-902",
            context_type="mutation_proposal",
            payload={"epoch_id": "epoch-902", "data": "x" * (MAX_PAYLOAD_BYTES + 1000)},
        )

        assert result.accepted is False
        assert result.rejection_reason is not None
        assert "exceeds_limit" in result.rejection_reason
        assert ledger.entry_count() == 0
        rejected_events = [e for e in events if e[0] == "context_ledger_entry_rejected.v1"]
        assert rejected_events[-1][1]["rejecting_filter"] == "payload_size_limit"

    def test_T9_01_28_append_rejects_private_key_pattern_without_manual_filter(self, tmp_path):
        """append() must apply private-key leak detection before accepting entries."""
        ledger, events = _make_ledger(tmp_path, collect_events=True)
        result = ledger.append(
            epoch_id="epoch-903",
            context_type="mutation_proposal",
            payload={"epoch_id": "epoch-903", "data": "ghp_" + "a" * 36},
        )

        assert result.accepted is False
        assert result.rejection_reason == "payload_contains_private_key_pattern"
        assert ledger.entry_count() == 0
        rejected_events = [e for e in events if e[0] == "context_ledger_entry_rejected.v1"]
        assert rejected_events[-1][1]["rejecting_filter"] == "no_private_key_leak"


# ============================================================================
# ContextFilterChain — T9-01-18..25
# ============================================================================

class TestContextFilterChain:

    def _make_chain(self):
        from runtime.memory.context_filter_chain import ContextFilterChain
        return ContextFilterChain()

    def test_T9_01_18_valid_payload_passes_all_builtin_filters(self):
        """Valid payload with known context_type must pass all built-in filters."""
        chain = self._make_chain()
        result = chain.evaluate(
            payload={"epoch_id": "epoch-001", "context_hash": "abc123"},
            context_type="mutation_proposal",
        )
        assert result.accepted is True
        assert result.rejection_reason is None

    def test_T9_01_19_missing_epoch_id_is_rejected(self):
        """Payloads without epoch_id must be rejected by epoch_id_required filter."""
        chain = self._make_chain()
        result = chain.evaluate(
            payload={"context_hash": "abc123"},
            context_type="mutation_proposal",
        )
        assert result.accepted is False
        assert result.rejecting_filter == "epoch_id_required"

    def test_T9_01_20_invalid_context_type_is_rejected(self):
        """Unknown context_type must be rejected by context_type_allowlist filter."""
        chain = self._make_chain()
        result = chain.evaluate(
            payload={"epoch_id": "e1"},
            context_type="completely_unknown",
        )
        assert result.accepted is False
        assert result.rejecting_filter == "context_type_allowlist"

    def test_T9_01_21_oversized_payload_is_rejected(self):
        """Payloads exceeding MAX_PAYLOAD_BYTES must be rejected by size filter."""
        from runtime.memory.context_filter_chain import MAX_PAYLOAD_BYTES
        chain = self._make_chain()
        big_payload = {"epoch_id": "e1", "data": "x" * (MAX_PAYLOAD_BYTES + 1000)}
        result = chain.evaluate(payload=big_payload, context_type="mutation_proposal")
        assert result.accepted is False
        assert result.rejecting_filter == "payload_size_limit"

    def test_T9_01_22_private_key_pattern_is_rejected(self):
        """Payloads containing private_key patterns must be rejected."""
        chain = self._make_chain()
        # ghp_ tokens require 36+ chars in the pattern regex
        result = chain.evaluate(
            payload={"epoch_id": "e1", "data": "ghp_" + "a" * 36},
            context_type="mutation_proposal",
        )
        assert result.accepted is False
        assert result.rejecting_filter == "no_private_key_leak"

    def test_T9_01_23_custom_filter_is_applied_after_builtins(self):
        """Custom-registered filters must run after all built-in filters."""
        from runtime.memory.context_filter_chain import FilterResult
        chain = self._make_chain()
        calls = []

        def custom_filter(payload, context_type):
            calls.append(context_type)
            return FilterResult.accept("custom")

        chain.register(custom_filter)
        result = chain.evaluate(
            payload={"epoch_id": "e1"},
            context_type="mutation_proposal",
        )
        assert result.accepted is True
        assert calls == ["mutation_proposal"]

    def test_T9_01_24_first_rejection_halts_chain(self):
        """Once a filter rejects, no subsequent filters must be evaluated."""
        from runtime.memory.context_filter_chain import FilterResult
        chain = self._make_chain()
        downstream_called = []

        def should_not_run(payload, context_type):
            downstream_called.append(True)
            return FilterResult.accept("should_not_run")

        chain.register(should_not_run)
        # Trigger built-in rejection (missing epoch_id)
        result = chain.evaluate(
            payload={"context_hash": "abc"},
            context_type="mutation_proposal",
        )
        assert result.accepted is False
        assert downstream_called == [], "Downstream filter must not run after rejection"

    def test_T9_01_25_filter_count_reflects_builtins_plus_custom(self):
        """filter_count must equal number of built-in filters plus registered custom ones."""
        from runtime.memory.context_filter_chain import _BUILTIN_FILTERS, FilterResult
        chain = self._make_chain()
        base_count = len(_BUILTIN_FILTERS)
        assert chain.filter_count == base_count

        def noop_filter(payload, context_type):
            return FilterResult.accept("noop")

        chain.register(noop_filter)
        assert chain.filter_count == base_count + 1

        chain.clear_custom_filters()
        assert chain.filter_count == base_count


# ---------------------------------------------------------------------------
# Compatibility assertions from legacy test_pr9_01.py
# ---------------------------------------------------------------------------

class TestSoulboundKeyCompat:
    def test_get_key_returns_bytes_when_env_set(self, monkeypatch):
        from runtime.memory.soulbound_key import get_key, ENV_VAR
        monkeypatch.setenv(ENV_VAR, "a" * 64)
        key = get_key()
        assert isinstance(key, bytes)
        assert key == TEST_KEY

    def test_sign_returns_64_char_hex(self):
        from runtime.memory.soulbound_key import sign
        result = sign(b"test data", key=TEST_KEY)
        assert isinstance(result, str)
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)


class TestSoulboundLedgerCompat:
    def test_entry_has_64_char_context_digest(self, tmp_path):
        ledger = _make_ledger(tmp_path)
        result = ledger.append(
            epoch_id="epoch-003",
            context_type="mutation_proposal",
            payload=_valid_payload("epoch-003", details={"x": 1}),
        )
        assert result.accepted is True
        assert len(result.entry.context_digest) == 64


class TestContextFilterChainCompat:
    def test_private_key_pattern_reason_contains_private_key(self):
        from runtime.memory.context_filter_chain import ContextFilterChain
        chain = ContextFilterChain()
        payload = {
            "epoch_id": "epoch-042",
            "context_hash": "abc123",
            "secret_key": "sk-abc123def456ghi789jkl000mno111",
        }
        result = chain.evaluate(payload=payload, context_type="mutation_proposal")
        assert result.accepted is False
        assert "private_key" in (result.rejection_reason or "")
