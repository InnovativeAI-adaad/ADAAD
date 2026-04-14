# SPDX-License-Identifier: Apache-2.0
"""Tests for FederatedEvidenceMatrix — Phase 5 cross-repo determinism gate.

Invariants under test
---------------------
- record_local_epoch() stores epoch digest immutably; conflict raises.
- record_peer_epoch() stores peer digest immutably; conflict raises.
- verify_cross_repo() runs all 4 axes and returns correct pass/fail.
- Axis: source_chain_intact — rejects malformed or zero-hash digest.
- Axis: destination_registered — rejects unregistered destination epoch.
- Axis: digest_cross_match — rejects zero-hash on either side.
- Axis: no_divergence — rejects proposal when pre-registered peer digest mismatches.
- Axis: no_divergence — passes (advisory) when peer epoch not pre-registered.
- gate_passes() returns bool consistent with verify_cross_repo().passed.
- divergence_count() counts only no_divergence failures.
- Audit events emitted for pass and fail; audit failure never blocks gate.
- matrix_digest() is deterministic for identical results.
- Phase 5 roadmap invariant: 0 divergences per federated epoch enforced by gate.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest
pytestmark = pytest.mark.regression_standard

from runtime.governance.federation.federated_evidence_matrix import (
    CrossRepoVerificationResult,
    EpochAlreadyRegisteredSameDigest,
    FederatedEvidenceMatrix,
    FederatedEvidenceMatrixError,
    LocalEpochDigestConflictError,
    VerificationAxisResult,
    _validate_digest,
)

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

_LOCAL = "InnovativeAI-adaad/ADAAD"
_PEER = "InnovativeAI-adaad/ADAAD-payments"
_GOOD_DIGEST = "sha256:" + "a" * 64
_GOOD_DIGEST_2 = "sha256:" + "b" * 64
_ZERO_HASH = "sha256:" + "0" * 64
_BAD_DIGEST_NO_PREFIX = "abc123"
_BAD_DIGEST_SHORT = "sha256:abc"
_PROPOSAL_ID = "prop-001"
_SOURCE_EPOCH = "epoch-src-001"
_DEST_EPOCH = "epoch-dest-001"


def _make_matrix(audit=None) -> FederatedEvidenceMatrix:
    return FederatedEvidenceMatrix(local_repo=_LOCAL, audit_writer=audit)


def _full_setup(matrix: FederatedEvidenceMatrix) -> None:
    """Register both local and peer epochs for a clean passing scenario."""
    matrix.record_local_epoch(_DEST_EPOCH, _GOOD_DIGEST_2)
    matrix.record_peer_epoch(_PEER, _SOURCE_EPOCH, _GOOD_DIGEST)


def _run_verify(matrix: FederatedEvidenceMatrix) -> CrossRepoVerificationResult:
    return matrix.verify_cross_repo(
        proposal_id=_PROPOSAL_ID,
        source_repo=_PEER,
        source_epoch_id=_SOURCE_EPOCH,
        source_chain_digest=_GOOD_DIGEST,
        destination_epoch_id=_DEST_EPOCH,
    )


# ---------------------------------------------------------------------------
# _validate_digest
# ---------------------------------------------------------------------------


class TestValidateDigest:
    def test_valid_digest_passes(self) -> None:
        _validate_digest(_GOOD_DIGEST, context="test")

    def test_missing_prefix_raises(self) -> None:
        with pytest.raises(FederatedEvidenceMatrixError, match="digest_missing_prefix"):
            _validate_digest(_BAD_DIGEST_NO_PREFIX, context="test")

    def test_short_hex_raises(self) -> None:
        with pytest.raises(FederatedEvidenceMatrixError, match="digest_wrong_length"):
            _validate_digest(_BAD_DIGEST_SHORT, context="test")

    def test_non_string_raises(self) -> None:
        with pytest.raises(FederatedEvidenceMatrixError, match="digest_not_string"):
            _validate_digest(None, context="test")  # type: ignore


# ---------------------------------------------------------------------------
# record_local_epoch / record_peer_epoch
# ---------------------------------------------------------------------------


class TestEpochRegistration:
    def test_local_epoch_registered(self) -> None:
        m = _make_matrix()
        m.record_local_epoch("ep-1", _GOOD_DIGEST)
        # No exception means success; verify indirectly via axis
        result = m.verify_cross_repo(
            proposal_id="p1",
            source_repo=_PEER,
            source_epoch_id="ep-src",
            source_chain_digest=_GOOD_DIGEST,
            destination_epoch_id="ep-1",
        )
        assert result.passed

    def test_local_epoch_idempotent(self) -> None:
        m = _make_matrix()
        m.record_local_epoch("ep-1", _GOOD_DIGEST)
        with pytest.raises(
            EpochAlreadyRegisteredSameDigest,
            match="local_epoch_already_registered_same_digest",
        ):
            m.record_local_epoch("ep-1", _GOOD_DIGEST)

    def test_local_epoch_conflict_raises(self) -> None:
        m = _make_matrix()
        m.record_local_epoch("ep-1", _GOOD_DIGEST)
        with pytest.raises(LocalEpochDigestConflictError, match="local_epoch_digest_conflict"):
            m.record_local_epoch("ep-1", _GOOD_DIGEST_2)

    def test_peer_epoch_idempotent(self) -> None:
        m = _make_matrix()
        m.record_peer_epoch(_PEER, "ep-src", _GOOD_DIGEST)
        m.record_peer_epoch(_PEER, "ep-src", _GOOD_DIGEST)  # no raise

    def test_peer_epoch_conflict_raises(self) -> None:
        m = _make_matrix()
        m.record_peer_epoch(_PEER, "ep-src", _GOOD_DIGEST)
        with pytest.raises(FederatedEvidenceMatrixError, match="peer_epoch_digest_conflict"):
            m.record_peer_epoch(_PEER, "ep-src", _GOOD_DIGEST_2)

    def test_malformed_local_epoch_digest_raises(self) -> None:
        m = _make_matrix()
        with pytest.raises(FederatedEvidenceMatrixError):
            m.record_local_epoch("ep-1", "bad-digest")


# ---------------------------------------------------------------------------
# verify_cross_repo — axis coverage
# ---------------------------------------------------------------------------


class TestVerifyAxes:
    def test_all_axes_pass_full_setup(self) -> None:
        m = _make_matrix()
        _full_setup(m)
        result = _run_verify(m)
        assert result.passed is True
        assert result.failure_codes == []
        assert len(result.axes) == 4

    def test_axis_source_chain_intact_zero_hash_fails(self) -> None:
        m = _make_matrix()
        m.record_local_epoch(_DEST_EPOCH, _GOOD_DIGEST_2)
        result = m.verify_cross_repo(
            proposal_id=_PROPOSAL_ID,
            source_repo=_PEER,
            source_epoch_id=_SOURCE_EPOCH,
            source_chain_digest=_ZERO_HASH,
            destination_epoch_id=_DEST_EPOCH,
        )
        assert result.passed is False
        assert any("source_chain_intact" in c for c in result.failure_codes)

    def test_axis_destination_registered_fails_if_epoch_missing(self) -> None:
        m = _make_matrix()
        # Do NOT register destination epoch
        result = m.verify_cross_repo(
            proposal_id=_PROPOSAL_ID,
            source_repo=_PEER,
            source_epoch_id=_SOURCE_EPOCH,
            source_chain_digest=_GOOD_DIGEST,
            destination_epoch_id="unregistered-epoch",
        )
        assert result.passed is False
        assert any("destination_registered" in c for c in result.failure_codes)

    def test_axis_digest_cross_match_fails_destination_zero_hash(self) -> None:
        m = _make_matrix()
        m.record_local_epoch(_DEST_EPOCH, _ZERO_HASH)
        result = m.verify_cross_repo(
            proposal_id=_PROPOSAL_ID,
            source_repo=_PEER,
            source_epoch_id=_SOURCE_EPOCH,
            source_chain_digest=_GOOD_DIGEST,
            destination_epoch_id=_DEST_EPOCH,
        )
        assert result.passed is False
        assert any("digest_cross_match" in c for c in result.failure_codes)

    def test_axis_no_divergence_passes_when_peer_not_registered(self) -> None:
        """Advisory pass: peer epoch not pre-registered should not block."""
        m = _make_matrix()
        m.record_local_epoch(_DEST_EPOCH, _GOOD_DIGEST_2)
        # Do NOT record peer epoch
        result = _run_verify(m)
        axis = next(a for a in result.axes if a.axis == "no_divergence")
        assert axis.ok is True
        assert "advisory" in axis.reason

    def test_axis_no_divergence_fails_on_digest_mismatch(self) -> None:
        m = _make_matrix()
        m.record_local_epoch(_DEST_EPOCH, _GOOD_DIGEST_2)
        m.record_peer_epoch(_PEER, _SOURCE_EPOCH, _GOOD_DIGEST_2)  # different from proposal
        result = _run_verify(m)  # proposal carries _GOOD_DIGEST
        assert result.passed is False
        assert any("no_divergence" in c for c in result.failure_codes)

    def test_axis_no_divergence_passes_on_matching_digest(self) -> None:
        m = _make_matrix()
        _full_setup(m)  # registers peer epoch with _GOOD_DIGEST (same as proposal)
        result = _run_verify(m)
        axis = next(a for a in result.axes if a.axis == "no_divergence")
        assert axis.ok is True
        assert axis.reason == "ok"


# ---------------------------------------------------------------------------
# gate_passes
# ---------------------------------------------------------------------------


class TestGatePasses:
    def test_returns_true_when_all_axes_pass(self) -> None:
        m = _make_matrix()
        _full_setup(m)
        ok = m.gate_passes(
            proposal_id=_PROPOSAL_ID,
            source_repo=_PEER,
            source_epoch_id=_SOURCE_EPOCH,
            source_chain_digest=_GOOD_DIGEST,
            destination_epoch_id=_DEST_EPOCH,
        )
        assert ok is True

    def test_returns_false_when_axes_fail(self) -> None:
        m = _make_matrix()
        # No epoch registration at all
        ok = m.gate_passes(
            proposal_id=_PROPOSAL_ID,
            source_repo=_PEER,
            source_epoch_id=_SOURCE_EPOCH,
            source_chain_digest=_GOOD_DIGEST,
            destination_epoch_id="missing",
        )
        assert ok is False


# ---------------------------------------------------------------------------
# divergence_count
# ---------------------------------------------------------------------------


class TestDivergenceCount:
    def test_zero_divergences_when_all_pass(self) -> None:
        m = _make_matrix()
        _full_setup(m)
        _run_verify(m)
        assert m.divergence_count() == 0

    def test_counts_no_divergence_failures_only(self) -> None:
        m = _make_matrix()
        m.record_local_epoch(_DEST_EPOCH, _GOOD_DIGEST_2)
        # Register mismatched peer digest to trigger no_divergence failure
        m.record_peer_epoch(_PEER, _SOURCE_EPOCH, _GOOD_DIGEST_2)
        _run_verify(m)  # proposal carries _GOOD_DIGEST (mismatch)
        assert m.divergence_count() == 1

    def test_roadmap_invariant_zero_divergences_per_federated_epoch(self) -> None:
        """Phase 5 roadmap requirement: 0 divergences per federated epoch."""
        m = _make_matrix()
        _full_setup(m)
        _run_verify(m)
        # The Phase 5 invariant: divergence_count must be 0 for clean acceptance
        assert m.divergence_count() == 0


# ---------------------------------------------------------------------------
# matrix_digest determinism
# ---------------------------------------------------------------------------


class TestMatrixDigest:
    def test_identical_results_produce_identical_digest(self) -> None:
        m1 = _make_matrix()
        m2 = _make_matrix()
        _full_setup(m1)
        _full_setup(m2)
        r1 = _run_verify(m1)
        r2 = _run_verify(m2)
        assert r1.matrix_digest() == r2.matrix_digest()

    def test_different_proposals_produce_different_digests(self) -> None:
        m = _make_matrix()
        _full_setup(m)
        r1 = m.verify_cross_repo(
            proposal_id="prop-A",
            source_repo=_PEER,
            source_epoch_id=_SOURCE_EPOCH,
            source_chain_digest=_GOOD_DIGEST,
            destination_epoch_id=_DEST_EPOCH,
        )
        m.record_local_epoch("epoch-dest-002", _GOOD_DIGEST_2)
        m.record_peer_epoch(_PEER, "epoch-src-002", _GOOD_DIGEST_2)
        r2 = m.verify_cross_repo(
            proposal_id="prop-B",
            source_repo=_PEER,
            source_epoch_id="epoch-src-002",
            source_chain_digest=_GOOD_DIGEST_2,
            destination_epoch_id="epoch-dest-002",
        )
        assert r1.matrix_digest() != r2.matrix_digest()


# ---------------------------------------------------------------------------
# Audit events
# ---------------------------------------------------------------------------


class TestAuditEvents:
    def test_pass_emits_verified_event(self) -> None:
        events: List[str] = []
        m = _make_matrix(audit=lambda et, _p: events.append(et))
        _full_setup(m)
        _run_verify(m)
        assert "federated_evidence_verified" in events

    def test_fail_emits_failed_event(self) -> None:
        events: List[str] = []
        m = _make_matrix(audit=lambda et, _p: events.append(et))
        _run_verify(m)  # destination epoch not registered → fail
        assert "federated_evidence_failed" in events

    def test_audit_failure_does_not_block_gate(self) -> None:
        def bad_audit(et, p):
            raise OSError("disk full")

        m = FederatedEvidenceMatrix(local_repo=_LOCAL, audit_writer=bad_audit)
        _full_setup(m)
        result = _run_verify(m)
        assert result.passed is True  # Must not raise
