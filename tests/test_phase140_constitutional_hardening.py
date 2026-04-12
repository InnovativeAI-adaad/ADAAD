# SPDX-License-Identifier: Apache-2.0
# tests/test_phase140_constitutional_hardening.py
# Phase 140 · Constitutional P0 Sweep + P1 Hardening — 30/30 acceptance tests
#
# Invariants validated:
#   HAPG-IDENTITY-0   HumanApprovalGate GPG fingerprint binding
#   HAPG-EXPIRY-0     Approval expiry enforcement
#   REPLAY-ALGO-0     Production Ed25519 absence fails closed
#   TEST-ATTEST-0     30/30 attestation gate script
#   GRRP-KEY-0        GRRP HMAC key from env, not hardcoded

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import importlib
import tempfile
import textwrap
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest import mock

import pytest

# ─── Helpers ──────────────────────────────────────────────────────────────────

ROOT = Path(__file__).parent.parent


def _gate(tmp_path: Path):
    from runtime.governance.human_approval_gate import HumanApprovalGate
    return HumanApprovalGate(
        queue_path=tmp_path / "q.jsonl",
        audit_path=tmp_path / "a.jsonl",
        index_path=tmp_path / "i.json",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# HAPG-IDENTITY-0  (Tests 1–8)
# ═══════════════════════════════════════════════════════════════════════════════

class TestHAPGIdentity:

    def test_01_fingerprint_constant_present(self):
        """HAPG-IDENTITY-0: HUMAN0_GPG_FINGERPRINT constant must be exported."""
        from runtime.governance.human_approval_gate import HUMAN0_GPG_FINGERPRINT
        assert len(HUMAN0_GPG_FINGERPRINT) == 40
        assert HUMAN0_GPG_FINGERPRINT == "4C95E2F99A775335B1CF3DAF247B015A1CCD95F6"

    def test_02_identity_violation_error_exported(self):
        """HAPG-IDENTITY-0: IdentityViolationError must be in __all__."""
        from runtime.governance import human_approval_gate as m
        assert "IdentityViolationError" in m.__all__

    def test_03_strict_mode_rejects_unknown_operator(self, tmp_path):
        """HAPG-IDENTITY-0: Strict mode must raise IdentityViolationError for wrong operator_id."""
        from runtime.governance.human_approval_gate import (
            HumanApprovalGate, IdentityViolationError, ApprovalReason
        )
        gate = _gate(tmp_path)
        aid = gate.request_approval("mut-strict-001", "epoch-1", ApprovalReason.MUTATION_ADVANCEMENT)
        with mock.patch("runtime.governance.human_approval_gate._STRICT_HUMAN0", True):
            with pytest.raises(IdentityViolationError):
                gate.record_decision(aid, approved=True, operator_id="random-operator")

    def test_04_strict_mode_accepts_canonical_fingerprint(self, tmp_path):
        """HAPG-IDENTITY-0: Correct fingerprint passes in strict mode."""
        from runtime.governance.human_approval_gate import (
            HumanApprovalGate, ApprovalReason, HUMAN0_GPG_FINGERPRINT
        )
        gate = _gate(tmp_path)
        aid = gate.request_approval("mut-strict-002", "epoch-1", ApprovalReason.MUTATION_ADVANCEMENT)
        with mock.patch("runtime.governance.human_approval_gate._STRICT_HUMAN0", True):
            decision = gate.record_decision(aid, approved=True, operator_id=HUMAN0_GPG_FINGERPRINT)
        assert decision.status == "approved"

    def test_05_identity_violation_is_ledger_appended(self, tmp_path):
        """HAPG-IDENTITY-0: Violation must appear in audit trail before raising."""
        from runtime.governance.human_approval_gate import (
            HumanApprovalGate, IdentityViolationError, ApprovalReason
        )
        gate = _gate(tmp_path)
        aid = gate.request_approval("mut-strict-003", "epoch-1", ApprovalReason.MUTATION_ADVANCEMENT)
        with mock.patch("runtime.governance.human_approval_gate._STRICT_HUMAN0", True):
            with pytest.raises(IdentityViolationError):
                gate.record_decision(aid, approved=True, operator_id="impersonator")
        trail = gate.audit_trail()
        violations = [e for e in trail if e.get("event_type") == "identity_violation"]
        assert len(violations) == 1
        assert violations[0]["payload"]["invariant"] == "HAPG-IDENTITY-0"

    def test_06_non_strict_mode_allows_any_operator(self, tmp_path):
        """HAPG-IDENTITY-0: Non-strict (dev) mode must not enforce fingerprint."""
        from runtime.governance.human_approval_gate import HumanApprovalGate, ApprovalReason
        gate = _gate(tmp_path)
        aid = gate.request_approval("mut-dev-001", "epoch-1", ApprovalReason.MANUAL)
        with mock.patch("runtime.governance.human_approval_gate._STRICT_HUMAN0", False):
            decision = gate.record_decision(aid, approved=True, operator_id="anyone")
        assert decision.status == "approved"

    def test_07_fingerprint_in_decision_digest(self, tmp_path):
        """HAPG-IDENTITY-0: operator_id is included in decision_digest computation."""
        from runtime.governance.human_approval_gate import ApprovalDecision, HUMAN0_GPG_FINGERPRINT
        d1 = ApprovalDecision.compute_digest("a1", "mut1", "approved", HUMAN0_GPG_FINGERPRINT, "2026-01-01T00:00:00Z")
        d2 = ApprovalDecision.compute_digest("a1", "mut1", "approved", "other-op", "2026-01-01T00:00:00Z")
        assert d1 != d2

    def test_08_strict_human0_env_default_in_production(self):
        """HAPG-IDENTITY-0: _STRICT_HUMAN0 must be True when ADAAD_ENV=production."""
        with mock.patch.dict(os.environ, {"ADAAD_ENV": "production", "ADAAD_STRICT_HUMAN0": "0"}):
            import importlib
            import runtime.governance.human_approval_gate as m
            importlib.reload(m)
            assert m._STRICT_HUMAN0 is True
            importlib.reload(m)  # restore


# ═══════════════════════════════════════════════════════════════════════════════
# HAPG-EXPIRY-0  (Tests 9–15)
# ═══════════════════════════════════════════════════════════════════════════════

class TestHAPGExpiry:

    def test_09_expiry_constant_value(self):
        """HAPG-EXPIRY-0: APPROVAL_EXPIRY_S must be 7 days (604800 seconds)."""
        from runtime.governance.human_approval_gate import APPROVAL_EXPIRY_S
        assert APPROVAL_EXPIRY_S == 604800

    def test_10_fresh_approval_is_approved(self, tmp_path):
        """HAPG-EXPIRY-0: A just-created approval returns True from is_approved()."""
        from runtime.governance.human_approval_gate import HumanApprovalGate, ApprovalReason
        gate = _gate(tmp_path)
        with mock.patch("runtime.governance.human_approval_gate._STRICT_HUMAN0", False):
            aid = gate.request_approval("mut-fresh-001", "epoch-1", ApprovalReason.MANUAL)
            gate.record_decision(aid, approved=True, operator_id="dev")
        assert gate.is_approved("mut-fresh-001") is True

    def test_11_expired_approval_returns_false(self, tmp_path):
        """HAPG-EXPIRY-0: Approval with decided_at > 7 days ago returns False."""
        from runtime.governance.human_approval_gate import HumanApprovalGate, ApprovalReason, APPROVAL_EXPIRY_S
        gate = _gate(tmp_path)
        with mock.patch("runtime.governance.human_approval_gate._STRICT_HUMAN0", False):
            aid = gate.request_approval("mut-expired-001", "epoch-1", ApprovalReason.MANUAL)
            gate.record_decision(aid, approved=True, operator_id="dev")
        # Patch datetime.now at module level so is_approved sees 8 days in the future
        future = datetime.now(timezone.utc) + timedelta(days=8)
        with mock.patch(
            "runtime.governance.human_approval_gate.datetime",
            wraps=datetime,
        ) as mock_dt:
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.now.return_value = future
            result = gate.is_approved("mut-expired-001")
        assert result is False

    def test_12_expiry_emits_ledger_event(self, tmp_path):
        """HAPG-EXPIRY-0: Expiry must append approval_expired to audit trail."""
        from runtime.governance.human_approval_gate import HumanApprovalGate, ApprovalReason
        gate = _gate(tmp_path)
        with mock.patch("runtime.governance.human_approval_gate._STRICT_HUMAN0", False):
            aid = gate.request_approval("mut-expire-log", "epoch-1", ApprovalReason.MANUAL)
            gate.record_decision(aid, approved=True, operator_id="dev")
        future = datetime.now(timezone.utc) + timedelta(days=8)
        with mock.patch(
            "runtime.governance.human_approval_gate.datetime",
            wraps=datetime,
        ) as mock_dt:
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.now.return_value = future
            gate.is_approved("mut-expire-log")
        trail = gate.audit_trail("mut-expire-log")
        expired = [e for e in trail if e.get("event_type") == "approval_expired"]
        assert len(expired) == 1

    def test_13_expired_status_enum_is_reachable(self):
        """HAPG-EXPIRY-0: ApprovalStatus.EXPIRED must be a defined enum member."""
        from runtime.governance.human_approval_gate import ApprovalStatus
        assert ApprovalStatus.EXPIRED.value == "expired"

    def test_14_unapproved_mutation_returns_false(self, tmp_path):
        """HAPG-EXPIRY-0: Unknown mutation_id always returns False (fail-closed)."""
        gate = _gate(tmp_path)
        assert gate.is_approved("nonexistent-mutation") is False

    def test_15_rejected_approval_returns_false(self, tmp_path):
        """HAPG-EXPIRY-0: Rejected approval must return False from is_approved()."""
        from runtime.governance.human_approval_gate import HumanApprovalGate, ApprovalReason
        gate = _gate(tmp_path)
        with mock.patch("runtime.governance.human_approval_gate._STRICT_HUMAN0", False):
            aid = gate.request_approval("mut-rej-001", "epoch-1", ApprovalReason.MANUAL)
            gate.record_decision(aid, approved=False, operator_id="dev")
        assert gate.is_approved("mut-rej-001") is False


# ═══════════════════════════════════════════════════════════════════════════════
# REPLAY-ALGO-0  (Tests 16–21)
# ═══════════════════════════════════════════════════════════════════════════════

class TestReplayAlgo:

    def _builder(self, env: dict, monkeypatch):
        for k, v in env.items():
            monkeypatch.setenv(k, v)

    def test_16_preferred_algo_constant_is_ed25519(self):
        """REPLAY-ALGO-0: PREFERRED_PROOF_SIGNING_ALGORITHM must be 'ed25519'."""
        from runtime.evolution.replay_attestation import PREFERRED_PROOF_SIGNING_ALGORITHM
        assert PREFERRED_PROOF_SIGNING_ALGORITHM == "ed25519"

    def test_17_default_algo_constant_is_hmac(self):
        """REPLAY-ALGO-0: DEFAULT_PROOF_SIGNING_ALGORITHM must be 'hmac-sha256'."""
        from runtime.evolution.replay_attestation import DEFAULT_PROOF_SIGNING_ALGORITHM
        assert DEFAULT_PROOF_SIGNING_ALGORITHM == "hmac-sha256"

    def test_18_production_without_key_fails_closed(self, monkeypatch):
        """REPLAY-ALGO-0: Production env without Ed25519 key raises RuntimeError."""
        monkeypatch.setenv("ADAAD_ENV", "production")
        monkeypatch.delenv("ADAAD_REPLAY_PROOF_ALLOW_HMAC_FALLBACK", raising=False)
        from runtime.evolution import replay_attestation as ra
        with mock.patch.object(ra, "_has_ed25519_private_key", return_value=False):
            with pytest.raises(RuntimeError, match="REPLAY-ALGO-0"):
                ra.ReplayProofBuilder(algorithm=None)

    def test_19_production_with_explicit_fallback_env_allows_hmac(self, monkeypatch):
        """REPLAY-ALGO-0: ADAAD_REPLAY_PROOF_ALLOW_HMAC_FALLBACK=1 permits HMAC in production."""
        monkeypatch.setenv("ADAAD_ENV", "production")
        monkeypatch.setenv("ADAAD_REPLAY_PROOF_ALLOW_HMAC_FALLBACK", "1")
        from runtime.evolution import replay_attestation as ra
        with mock.patch.object(ra, "_has_ed25519_private_key", return_value=False):
            builder = ra.ReplayProofBuilder(algorithm=None)
        assert builder.algorithm == "hmac-sha256"

    def test_20_dev_env_uses_hmac_without_error(self, monkeypatch):
        """REPLAY-ALGO-0: Dev environment defaults to HMAC without raising."""
        monkeypatch.setenv("ADAAD_ENV", "dev")
        from runtime.evolution import replay_attestation as ra
        with mock.patch.object(ra, "_has_ed25519_private_key", return_value=False):
            builder = ra.ReplayProofBuilder(algorithm=None)
        assert builder.algorithm == "hmac-sha256"

    def test_21_staging_without_key_fails_closed(self, monkeypatch):
        """REPLAY-ALGO-0: Staging env also fails closed without Ed25519 key."""
        monkeypatch.setenv("ADAAD_ENV", "staging")
        monkeypatch.delenv("ADAAD_REPLAY_PROOF_ALLOW_HMAC_FALLBACK", raising=False)
        from runtime.evolution import replay_attestation as ra
        with mock.patch.object(ra, "_has_ed25519_private_key", return_value=False):
            with pytest.raises(RuntimeError, match="REPLAY-ALGO-0"):
                ra.ReplayProofBuilder(algorithm=None)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST-ATTEST-0  (Tests 22–25)
# ═══════════════════════════════════════════════════════════════════════════════

class TestTestAttest:

    def _make_state(self, tmp_path: Path, innovations: dict) -> Path:
        state = {"innovations_shipped": innovations, "current_version": "9.73.0"}
        p = tmp_path / ".adaad_agent_state.json"
        p.write_text(json.dumps(state))
        return p

    def test_22_all_pass_returns_empty_violations(self, tmp_path):
        """TEST-ATTEST-0: All innovations with tests=30/30 yields zero violations."""
        sys.path.insert(0, str(ROOT / "scripts"))
        import validate_phase_test_attestation as va
        state_p = self._make_state(tmp_path, {
            "INNOV-01": {"tests": "30/30", "phase": 87},
            "INNOV-02": {"tests": "30/30", "phase": 88},
        })
        assert va.validate(state_p) == []

    def test_23_missing_tests_field_is_violation(self, tmp_path):
        """TEST-ATTEST-0: Innovation without tests field is a violation."""
        import validate_phase_test_attestation as va
        state_p = self._make_state(tmp_path, {"INNOV-BAD": {"phase": 99}})
        violations = va.validate(state_p)
        assert len(violations) == 1
        assert violations[0]["reason"] == "missing_tests_field"

    def test_24_non_30_tests_field_is_violation(self, tmp_path):
        """TEST-ATTEST-0: Innovation with tests != 30/30 is a violation."""
        import validate_phase_test_attestation as va
        state_p = self._make_state(tmp_path, {"INNOV-FAIL": {"tests": "28/30", "phase": 99}})
        violations = va.validate(state_p)
        assert len(violations) == 1
        assert violations[0]["reason"] == "non_passing_attestation"

    def test_25_live_agent_state_all_pass(self):
        """TEST-ATTEST-0: Live .adaad_agent_state.json must have 0 violations."""
        import validate_phase_test_attestation as va
        state_p = ROOT / ".adaad_agent_state.json"
        assert state_p.exists(), "agent state not found"
        violations = va.validate(state_p)
        assert violations == [], f"Violations found: {violations}"


# ═══════════════════════════════════════════════════════════════════════════════
# GRRP-KEY-0  (Tests 26–30)
# ═══════════════════════════════════════════════════════════════════════════════

class TestGRRPKey:

    def test_26_grrp_hmac_key_resolver_exported(self):
        """GRRP-KEY-0: _resolve_grrp_hmac_key and GRRP_HMAC_KEY must exist."""
        from runtime.innovations30.red_team_response_protocol import (
            _resolve_grrp_hmac_key, GRRP_HMAC_KEY
        )
        assert callable(_resolve_grrp_hmac_key)
        assert isinstance(GRRP_HMAC_KEY, bytes)

    def test_27_dev_mode_returns_explicit_dev_key(self, monkeypatch):
        """GRRP-KEY-0: Dev env with no ADAAD_GRRP_HMAC_KEY returns dev-only bytes."""
        monkeypatch.setenv("ADAAD_ENV", "dev")
        monkeypatch.delenv("ADAAD_GRRP_HMAC_KEY", raising=False)
        from runtime.innovations30 import red_team_response_protocol as grrp
        key = grrp._resolve_grrp_hmac_key()
        assert b"dev" in key.lower() or b"not-for-production" in key

    def test_28_env_key_hex_is_decoded(self, monkeypatch):
        """GRRP-KEY-0: ADAAD_GRRP_HMAC_KEY as hex string is decoded to bytes."""
        expected = b"\xde\xad\xbe\xef"
        monkeypatch.setenv("ADAAD_GRRP_HMAC_KEY", "deadbeef")
        from runtime.innovations30 import red_team_response_protocol as grrp
        key = grrp._resolve_grrp_hmac_key()
        assert key == expected

    def test_29_production_without_key_raises(self, monkeypatch):
        """GRRP-KEY-0: Production env without ADAAD_GRRP_HMAC_KEY raises RuntimeError."""
        monkeypatch.setenv("ADAAD_ENV", "production")
        monkeypatch.delenv("ADAAD_GRRP_HMAC_KEY", raising=False)
        from runtime.innovations30 import red_team_response_protocol as grrp
        with pytest.raises(RuntimeError, match="GRRP-KEY-0"):
            grrp._resolve_grrp_hmac_key()

    def test_30_sign_verify_round_trip_with_env_key(self, monkeypatch):
        """GRRP-KEY-0: AmendmentProposal sign/verify round-trips with env-sourced key."""
        monkeypatch.setenv("ADAAD_GRRP_HMAC_KEY", "cafebabe01020304")
        from runtime.innovations30.red_team_response_protocol import (
            AmendmentProposal, _resolve_grrp_hmac_key
        )
        key = _resolve_grrp_hmac_key()
        proposal = AmendmentProposal(
            proposal_id="prop-001",
            finding_id="f-001",
            invariant_target="TEST-ATTEST-0",
            classification="ADVISORY",
            patch_description="test round-trip",
        )
        proposal.sign(key)
        assert proposal.hmac_digest.startswith("hmac-sha256:")
        assert proposal.verify(key) is True
        # Tamper check
        proposal.patch_description = "tampered"
        assert proposal.verify(key) is False
