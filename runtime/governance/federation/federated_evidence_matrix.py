# SPDX-License-Identifier: Apache-2.0
"""FederatedEvidenceMatrix — Phase 5 cross-repo determinism verification gate.

The ``FederatedEvidenceMatrix`` is the constitutional gate that must pass before
any federated mutation is accepted as complete in the evidence ledger.  It
implements the ADAAD Roadmap Phase 5 requirement:

    "Federated evidence matrix — Release evidence must include cross-repo
    determinism verification before any federated mutation is accepted."

Architecture
------------
::

    FederatedEvidenceMatrix
         ├── record_local_epoch()      — register a local epoch boundary digest
         ├── record_peer_epoch()       — register a remote peer's epoch digest
         ├── verify_cross_repo()       — run all verification axes; fail-closed
         ├── generate_matrix_entry()   — produce audit record for evidence ledger
         └── gate_passes()             — Boolean: all axes green for a proposal

Verification axes
-----------------
1. ``source_chain_intact``   — source_chain_digest is non-empty and well-formed.
2. ``destination_registered`` — the destination repo registered a local epoch that
   matches the inbound proposal's ``source_epoch_id``.
3. ``digest_cross_match``    — source and destination epoch digests are both
   well-formed SHA-256 prefixed strings and neither is the zero hash.
4. ``no_divergence``         — the stored peer digest for the source repo + epoch
   matches the ``source_chain_digest`` carried in the proposal (if registered).

The matrix does **not** re-run the GovernanceGate — that is the broker's
responsibility.  The matrix is a pure evidence completeness and cross-repo
determinism check.

Invariants
----------
- ``verify_cross_repo()`` is always fail-closed: any axis failure produces a
  named error code rather than a silent pass.
- The matrix is append-only: recorded epoch digests are immutable after storage.
- Audit emit failures never block gate evaluation (fail-open on audit).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger(__name__)

_ZERO_HASH = "sha256:" + "0" * 64
_SHA256_PREFIX = "sha256:"
_SHA256_DIGEST_LENGTH = len(_SHA256_PREFIX) + 64  # "sha256:" + 64 hex chars


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------


class FederatedEvidenceMatrixError(RuntimeError):
    """Raised when a cross-repo verification axis fails (fail-closed)."""


class LocalEpochDigestConflictError(FederatedEvidenceMatrixError):
    """Raised when a local epoch is re-registered with a different digest."""


class EpochAlreadyRegisteredSameDigest(FederatedEvidenceMatrixError):
    """Raised for idempotent re-registration of an existing local epoch digest."""


@dataclass(frozen=True)
class VerificationAxisResult:
    """Result of a single cross-repo determinism verification axis."""

    axis: str
    ok: bool
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {"axis": self.axis, "ok": self.ok, "reason": self.reason}


@dataclass(frozen=True)
class CrossRepoVerificationResult:
    """Aggregated result of all verification axes for one federated proposal."""

    proposal_id: str
    source_repo: str
    source_epoch_id: str
    axes: List[VerificationAxisResult]
    passed: bool
    failure_codes: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "failure_codes": self.failure_codes,
            "passed": self.passed,
            "proposal_id": self.proposal_id,
            "source_epoch_id": self.source_epoch_id,
            "source_repo": self.source_repo,
            "verification_axes": [a.to_dict() for a in self.axes],
        }

    def matrix_digest(self) -> str:
        """SHA-256 of the canonical matrix entry — used in evidence ledger."""
        material = json.dumps(self.to_dict(), sort_keys=True,
                              separators=(",", ":"), ensure_ascii=False)
        return _SHA256_PREFIX + hashlib.sha256(material.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# FederatedEvidenceMatrix
# ---------------------------------------------------------------------------


class FederatedEvidenceMatrix:
    """Cross-repo determinism verification registry for Phase 5 federation.

    Parameters
    ----------
    local_repo:
        Canonical identifier for the repository running this matrix instance.
    audit_writer:
        Optional ``(event_type: str, payload: dict) -> None`` callable for
        appending matrix events to the evidence ledger.  Failures are logged
        but never re-raised.
    """

    def __init__(
        self,
        *,
        local_repo: str,
        audit_writer: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> None:
        self._local_repo = local_repo
        self._audit = audit_writer
        # _local_epochs[epoch_id] = chain_digest
        self._local_epochs: Dict[str, str] = {}
        # _peer_epochs[(peer_repo, epoch_id)] = chain_digest
        self._peer_epochs: Dict[tuple, str] = {}
        # _results[proposal_id] = CrossRepoVerificationResult
        self._results: Dict[str, CrossRepoVerificationResult] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def record_local_epoch(self, epoch_id: str, chain_digest: str) -> None:
        """Register a local epoch boundary digest (immutable once stored).

        Parameters
        ----------
        epoch_id:
            Stable epoch identifier.
        chain_digest:
            SHA-256 prefixed tip digest of the local lineage ledger at this epoch.

        Raises
        ------
        LocalEpochDigestConflictError
            If ``epoch_id`` was already registered with a different digest.
        EpochAlreadyRegisteredSameDigest
            If ``epoch_id`` was already registered with the same digest.
        """
        _validate_digest(chain_digest, context=f"local_epoch:{epoch_id}")
        if epoch_id in self._local_epochs:
            stored = self._local_epochs[epoch_id]
            if stored != chain_digest:
                raise LocalEpochDigestConflictError(
                    f"federated_evidence:local_epoch_digest_conflict:"
                    f"epoch={epoch_id} stored={stored[:20]} new={chain_digest[:20]}"
                )
            raise EpochAlreadyRegisteredSameDigest(
                f"federated_evidence:local_epoch_already_registered_same_digest:"
                f"epoch={epoch_id} digest={chain_digest}"
            )
        self._local_epochs[epoch_id] = chain_digest
        log.debug("FederatedEvidenceMatrix: registered local epoch=%s", epoch_id)

    def record_peer_epoch(self, peer_repo: str, epoch_id: str, chain_digest: str) -> None:
        """Register a peer repo's epoch digest received via the federation transport.

        Parameters
        ----------
        peer_repo:
            Canonical repository identifier of the peer.
        epoch_id:
            Epoch identifier in the peer's coordinate space.
        chain_digest:
            SHA-256 prefixed chain tip claimed by the peer.
        """
        _validate_digest(chain_digest, context=f"peer_epoch:{peer_repo}:{epoch_id}")
        key = (peer_repo, epoch_id)
        if key in self._peer_epochs:
            stored = self._peer_epochs[key]
            if stored != chain_digest:
                raise FederatedEvidenceMatrixError(
                    f"federated_evidence:peer_epoch_digest_conflict:"
                    f"repo={peer_repo} epoch={epoch_id}"
                )
            return
        self._peer_epochs[key] = chain_digest
        log.debug("FederatedEvidenceMatrix: registered peer epoch repo=%s epoch=%s", peer_repo, epoch_id)

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def verify_cross_repo(
        self,
        *,
        proposal_id: str,
        source_repo: str,
        source_epoch_id: str,
        source_chain_digest: str,
        destination_epoch_id: str,
    ) -> CrossRepoVerificationResult:
        """Run all cross-repo determinism verification axes.

        Parameters
        ----------
        proposal_id:
            Identifier of the ``FederatedMutationProposal`` being evaluated.
        source_repo:
            Originating repository identifier.
        source_epoch_id:
            Epoch identifier from the source repo.
        source_chain_digest:
            SHA-256 chain digest carried in the proposal envelope.
        destination_epoch_id:
            The local epoch that corresponds to / receives this mutation.

        Returns
        -------
        CrossRepoVerificationResult
            Contains per-axis results and aggregate pass/fail.

        Raises
        ------
        FederatedEvidenceMatrixError
            Never raised from this method — failures are captured in axis results.
            Callers use ``result.passed`` or ``gate_passes()``.
        """
        axes: List[VerificationAxisResult] = [
            self._axis_source_chain_intact(source_chain_digest),
            self._axis_destination_registered(destination_epoch_id),
            self._axis_digest_cross_match(source_chain_digest, destination_epoch_id),
            self._axis_no_divergence(source_repo, source_epoch_id, source_chain_digest),
        ]

        failure_codes = [a.reason for a in axes if not a.ok]
        passed = len(failure_codes) == 0

        result = CrossRepoVerificationResult(
            proposal_id=proposal_id,
            source_repo=source_repo,
            source_epoch_id=source_epoch_id,
            axes=axes,
            passed=passed,
            failure_codes=failure_codes,
        )
        self._results[proposal_id] = result

        event_type = "federated_evidence_verified" if passed else "federated_evidence_failed"
        self._emit_audit(event_type, {
            "proposal_id": proposal_id,
            "source_repo": source_repo,
            "source_epoch_id": source_epoch_id,
            "passed": passed,
            "failure_codes": failure_codes,
            "matrix_digest": result.matrix_digest(),
        })

        if passed:
            log.info(
                "FederatedEvidenceMatrix: PASS proposal=%s source=%s epoch=%s",
                proposal_id, source_repo, source_epoch_id,
            )
        else:
            log.warning(
                "FederatedEvidenceMatrix: FAIL proposal=%s codes=%s",
                proposal_id, failure_codes,
            )

        return result

    def gate_passes(
        self,
        *,
        proposal_id: str,
        source_repo: str,
        source_epoch_id: str,
        source_chain_digest: str,
        destination_epoch_id: str,
    ) -> bool:
        """Convenience wrapper: run verify_cross_repo and return bool result."""
        result = self.verify_cross_repo(
            proposal_id=proposal_id,
            source_repo=source_repo,
            source_epoch_id=source_epoch_id,
            source_chain_digest=source_chain_digest,
            destination_epoch_id=destination_epoch_id,
        )
        return result.passed

    # ------------------------------------------------------------------
    # Read-only audit view
    # ------------------------------------------------------------------

    def get_result(self, proposal_id: str) -> Optional[CrossRepoVerificationResult]:
        """Return the stored verification result for a proposal, or None."""
        return self._results.get(proposal_id)

    def all_results(self) -> List[CrossRepoVerificationResult]:
        """Return all stored verification results in registration order."""
        return list(self._results.values())

    def divergence_count(self) -> int:
        """Number of proposals that failed the ``no_divergence`` axis."""
        return sum(
            1 for r in self._results.values()
            if any(a.axis == "no_divergence" and not a.ok for a in r.axes)
        )

    # ------------------------------------------------------------------
    # Verification axes (private)
    # ------------------------------------------------------------------

    def _axis_source_chain_intact(self, source_chain_digest: str) -> VerificationAxisResult:
        try:
            _validate_digest(source_chain_digest, context="axis:source_chain_intact")
            if source_chain_digest == _ZERO_HASH:
                return VerificationAxisResult(
                    axis="source_chain_intact", ok=False,
                    reason="source_chain_intact:zero_hash_not_accepted",
                )
            return VerificationAxisResult(axis="source_chain_intact", ok=True, reason="ok")
        except FederatedEvidenceMatrixError as exc:
            return VerificationAxisResult(axis="source_chain_intact", ok=False, reason=str(exc))

    def _axis_destination_registered(self, destination_epoch_id: str) -> VerificationAxisResult:
        if destination_epoch_id in self._local_epochs:
            return VerificationAxisResult(
                axis="destination_registered", ok=True, reason="ok"
            )
        return VerificationAxisResult(
            axis="destination_registered",
            ok=False,
            reason=f"destination_registered:epoch_not_found:{destination_epoch_id}",
        )

    def _axis_digest_cross_match(
        self, source_chain_digest: str, destination_epoch_id: str
    ) -> VerificationAxisResult:
        try:
            _validate_digest(source_chain_digest, context="cross_match:source")
        except FederatedEvidenceMatrixError:
            return VerificationAxisResult(
                axis="digest_cross_match", ok=False,
                reason="digest_cross_match:source_digest_malformed",
            )

        if destination_epoch_id not in self._local_epochs:
            return VerificationAxisResult(
                axis="digest_cross_match", ok=False,
                reason=f"digest_cross_match:destination_epoch_not_registered:{destination_epoch_id}",
            )

        dest_digest = self._local_epochs[destination_epoch_id]
        if dest_digest == _ZERO_HASH:
            return VerificationAxisResult(
                axis="digest_cross_match", ok=False,
                reason="digest_cross_match:destination_zero_hash",
            )
        if source_chain_digest == _ZERO_HASH:
            return VerificationAxisResult(
                axis="digest_cross_match", ok=False,
                reason="digest_cross_match:source_zero_hash",
            )

        return VerificationAxisResult(axis="digest_cross_match", ok=True, reason="ok")

    def _axis_no_divergence(
        self,
        source_repo: str,
        source_epoch_id: str,
        source_chain_digest: str,
    ) -> VerificationAxisResult:
        """Check that the stored peer digest matches the proposal's digest (if registered)."""
        key = (source_repo, source_epoch_id)
        if key not in self._peer_epochs:
            # Peer epoch not pre-registered — pass with advisory note (not a hard failure;
            # the operator may not have pre-exchanged digests out-of-band).
            return VerificationAxisResult(
                axis="no_divergence", ok=True,
                reason="no_divergence:peer_epoch_not_pre_registered:advisory",
            )
        stored_peer_digest = self._peer_epochs[key]
        if stored_peer_digest != source_chain_digest:
            return VerificationAxisResult(
                axis="no_divergence",
                ok=False,
                reason=(
                    f"no_divergence:digest_mismatch:"
                    f"stored={stored_peer_digest[:20]} proposal={source_chain_digest[:20]}"
                ),
            )
        return VerificationAxisResult(axis="no_divergence", ok=True, reason="ok")

    def _emit_audit(self, event_type: str, payload: Dict[str, Any]) -> None:
        if self._audit is None:
            return
        try:
            self._audit(event_type, payload)
        except Exception as exc:  # noqa: BLE001
            log.warning("FederatedEvidenceMatrix: audit write failed (%s) — %s", event_type, exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_digest(digest: str, *, context: str) -> None:
    """Assert digest is a properly-formed ``sha256:<hex64>`` string."""
    if not isinstance(digest, str):
        raise FederatedEvidenceMatrixError(
            f"federated_evidence:digest_not_string:{context}"
        )
    if not digest.startswith(_SHA256_PREFIX):
        raise FederatedEvidenceMatrixError(
            f"federated_evidence:digest_missing_prefix:{context}:got={digest[:20]!r}"
        )
    if len(digest) != _SHA256_DIGEST_LENGTH:
        raise FederatedEvidenceMatrixError(
            f"federated_evidence:digest_wrong_length:{context}:"
            f"expected={_SHA256_DIGEST_LENGTH} got={len(digest)}"
        )


__all__ = [
    "CrossRepoVerificationResult",
    "FederatedEvidenceMatrix",
    "FederatedEvidenceMatrixError",
    "VerificationAxisResult",
    "_validate_digest",
]
