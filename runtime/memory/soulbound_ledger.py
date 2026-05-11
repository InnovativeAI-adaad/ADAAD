# SPDX-License-Identifier: Apache-2.0
"""
SoulboundLedger — tamper-evident, append-only context history for the ADAAD
mutation pipeline.

Purpose:
    Records every context snapshot accepted into the AI mutation pipeline as
    an immutable, HMAC-signed chain.  Any subsequent tamper attempt is detected
    by the chain-hash verification pass (verify_chain).

Architecture:
    - Persisted via VersionedMemoryStore (JSON backend, same pattern as memory layer).
    - Each entry carries: epoch_id, context_type, context_digest (SHA-256 of payload),
      HMAC signature over the canonical JSON, and a chain_hash linking to the
      previous entry (Merkle-chain structure).
    - Verification is O(n) and deterministic: a replayed sequence must produce
      identical chain hashes.
    - Key management delegated to SoulboundKey (ADAAD_SOULBOUND_KEY env var).
    - Fail-closed: any entry rejection emits a journal event and raises.

Journal events emitted:
    context_ledger_entry_accepted.v1  — on every successful append
    context_ledger_entry_rejected.v1  — on schema / HMAC validation failure
    context_ledger_tamper_detected.v1 — on chain verification failure
    soulbound_key_absent.v1           — when key env var is missing at append time

Constitutional invariants:
    - GovernanceGate retains sole mutation approval authority; the ledger is
      an audit/context layer only.
    - Fail-closed: missing ADAAD_SOULBOUND_KEY blocks ledger writes (never silently
      accepted without a signature).
    - Deterministic: given identical inputs, append produces identical chain hashes.
    - Append-only: no entry can be modified or deleted — only verify_chain detects
      tampering after the fact.

Android/Pydroid3 compatibility:
    - Pure Python stdlib only. No compiled extensions.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from memory.versionedstore import VersionedMemoryStore
from runtime.governance.foundation import canonical_json
from runtime.memory.context_filter_chain import ContextFilterChain
from runtime.memory.context_types import VALID_CONTEXT_TYPES
from runtime.memory.soulbound_key import SoulboundKeyError, sign, verify

# Journal imports — graceful no-op if not available (test environments)
try:
    from security.ledger.journal import append_tx as _journal_append_tx
except ImportError:  # pragma: no cover
    def _journal_append_tx(tx_type: str, payload: Dict[str, Any], **kw: Any) -> Dict[str, Any]:  # type: ignore[misc]
        return {}


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LEDGER_SCHEMA_VERSION: str = "1.0"

DEFAULT_LEDGER_PATH = Path("data/soulbound_ledger.json")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LedgerEntry:
    """Immutable record of a single soulbound context entry."""
    entry_id:        str
    epoch_id:        str
    context_type:    str
    context_digest:  str   # SHA-256 hex of canonical JSON payload bytes
    chain_hash:      str   # SHA-256(prev_chain_hash + context_digest)
    hmac_signature:  str   # HMAC-SHA256(canonical_json(entry fields)) using SoulboundKey
    schema_version:  str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "entry_id":       self.entry_id,
            "epoch_id":       self.epoch_id,
            "context_type":   self.context_type,
            "context_digest": self.context_digest,
            "chain_hash":     self.chain_hash,
            "hmac_signature": self.hmac_signature,
            "schema_version": self.schema_version,
        }

    def signable_bytes(self) -> bytes:
        """Canonical bytes over which the HMAC is computed.

        Excludes hmac_signature itself (computed after the fact).
        """
        signable = {
            "entry_id":       self.entry_id,
            "epoch_id":       self.epoch_id,
            "context_type":   self.context_type,
            "context_digest": self.context_digest,
            "chain_hash":     self.chain_hash,
            "schema_version": self.schema_version,
        }
        return canonical_json(signable).encode("utf-8")


@dataclass(frozen=True)
class AppendResult:
    """Result returned from SoulboundLedger.append()."""
    entry:        LedgerEntry
    accepted:     bool
    rejection_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _compute_context_digest(payload: Dict[str, Any]) -> str:
    """SHA-256 of canonical JSON representation of the context payload."""
    return _sha256_hex(canonical_json(payload).encode("utf-8"))


def _compute_chain_hash(prev_chain_hash: str, context_digest: str) -> str:
    """Chain link: SHA-256(prev_chain_hash + context_digest)."""
    combined = (prev_chain_hash + context_digest).encode("utf-8")
    return _sha256_hex(combined)


GENESIS_CHAIN_HASH: str = _sha256_hex(b"ADAAD:soulbound:genesis")


# ---------------------------------------------------------------------------
# SoulboundLedger
# ---------------------------------------------------------------------------

class SoulboundLedger:
    """Tamper-evident, append-only context ledger for the ADAAD mutation pipeline.

    Usage::

        ledger = SoulboundLedger()
        result = ledger.append(
            epoch_id="epoch-042",
            context_type="mutation_proposal",
            payload={"file_count": 7, "context_hash": "a1b2c3d4"},
        )
        # result.accepted == True

        ok, failures = ledger.verify_chain()
        # ok == True, failures == []

    Args:
        ledger_path:  Path for JSON persistence of entries.
        audit_writer: Optional callable(tx_type, payload) for journal writes.
                      Defaults to the real journal; pass a no-op in tests.
        key_override: Raw HMAC key bytes for testing.  If provided, bypasses
                      ADAAD_SOULBOUND_KEY env var — NEVER use in production.
        filter_chain: Optional ContextFilterChain. Defaults to the built-in
                      chain that fail-closed screens payloads before signing.
    """

    def __init__(
        self,
        ledger_path: Path = DEFAULT_LEDGER_PATH,
        audit_writer: Optional[Any] = None,
        key_override: Optional[bytes] = None,
        filter_chain: Optional[ContextFilterChain] = None,
    ) -> None:
        self._store = VersionedMemoryStore(path=ledger_path, backend="json")
        self._audit = audit_writer or _journal_append_tx
        self._key_override = key_override
        self._filter_chain = filter_chain or ContextFilterChain()
        self._last_chain_hash: str = self._recover_chain_tip()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def append(
        self,
        *,
        epoch_id: str,
        context_type: str,
        payload: Dict[str, Any],
    ) -> AppendResult:
        """Append a context snapshot to the ledger.

        Validates context_type, signs the entry, and writes to VersionedMemoryStore.
        Emits ``context_ledger_entry_accepted.v1`` on success,
        ``context_ledger_entry_rejected.v1`` on any validation failure,
        ``soulbound_key_absent.v1`` if the HMAC key is missing.

        Args:
            epoch_id:      Epoch identifier from the evolution loop.
            context_type:  Must be one of VALID_CONTEXT_TYPES.
            payload:       Arbitrary context data dict (must be JSON-serialisable).

        Returns:
            AppendResult with accepted=True and the LedgerEntry, or
            accepted=False with a rejection_reason.

        Raises:
            Never raises directly — all errors are captured into AppendResult
            and emitted as journal events, except SoulboundKeyError which is
            re-raised to preserve the fail-closed contract.
        """
        # --- Evaluate context filter chain before digesting or signing ---
        filter_result = self._filter_chain.evaluate(payload=payload, context_type=context_type)
        if not filter_result.accepted:
            reason = filter_result.rejection_reason or "context_filter_rejected"
            self._emit_rejected(
                epoch_id,
                context_type,
                reason,
                rejecting_filter=filter_result.rejecting_filter,
            )
            return AppendResult(
                entry=self._null_entry(epoch_id, context_type),
                accepted=False,
                rejection_reason=reason,
            )

        # --- Compute digests ---
        context_digest = _compute_context_digest(payload)
        chain_hash     = _compute_chain_hash(self._last_chain_hash, context_digest)
        entry_id       = str(uuid.uuid4())

        # --- Build unsigned entry (for HMAC computation) ---
        unsigned = LedgerEntry(
            entry_id       = entry_id,
            epoch_id       = str(epoch_id),
            context_type   = context_type,
            context_digest = context_digest,
            chain_hash     = chain_hash,
            hmac_signature = "",
            schema_version = LEDGER_SCHEMA_VERSION,
        )

        # --- Sign (fail-closed) ---
        try:
            hmac_sig = sign(unsigned.signable_bytes(), key=self._key_override)
        except SoulboundKeyError as exc:
            self._emit_key_absent(epoch_id, str(exc))
            raise  # Re-raise: fail-closed contract — caller must not continue

        # --- Assemble final entry ---
        entry = LedgerEntry(
            entry_id       = entry_id,
            epoch_id       = str(epoch_id),
            context_type   = context_type,
            context_digest = context_digest,
            chain_hash     = chain_hash,
            hmac_signature = hmac_sig,
            schema_version = LEDGER_SCHEMA_VERSION,
        )

        # --- Persist ---
        store_payload = {**entry.as_dict(), "context_payload": payload}
        self._store.append(payload=store_payload, confidence=1.0)
        self._last_chain_hash = chain_hash

        # --- Audit ---
        self._emit_accepted(entry)
        return AppendResult(entry=entry, accepted=True)

    def verify_chain(self) -> tuple[bool, List[str]]:
        """Verify tamper-evidence of the full ledger chain.

        Re-derives every chain_hash and HMAC from stored data. Any mismatch
        indicates tampering; emits ``context_ledger_tamper_detected.v1``.

        Returns:
            (ok: bool, failures: List[str]) — ok=True iff chain is intact.
        """
        entries = self._all_entries()
        if not entries:
            return True, []

        failures: List[str] = []
        prev_chain_hash = GENESIS_CHAIN_HASH

        for raw in entries:
            entry_id      = str(raw.get("entry_id", ""))
            context_digest = str(raw.get("context_digest", ""))
            expected_chain = _compute_chain_hash(prev_chain_hash, context_digest)
            stored_chain   = str(raw.get("chain_hash", ""))

            if stored_chain != expected_chain:
                reason = f"chain_hash_mismatch:entry_id={entry_id}"
                failures.append(reason)
                self._emit_tamper(entry_id, reason)
            else:
                # Verify HMAC
                unsigned_check = LedgerEntry(
                    entry_id       = entry_id,
                    epoch_id       = str(raw.get("epoch_id", "")),
                    context_type   = str(raw.get("context_type", "")),
                    context_digest = context_digest,
                    chain_hash     = stored_chain,
                    hmac_signature = "",
                    schema_version = str(raw.get("schema_version", LEDGER_SCHEMA_VERSION)),
                )
                stored_sig = str(raw.get("hmac_signature", ""))
                try:
                    sig_ok = verify(
                        unsigned_check.signable_bytes(),
                        stored_sig,
                        key=self._key_override,
                    )
                except SoulboundKeyError:
                    sig_ok = False

                if not sig_ok:
                    reason = f"hmac_mismatch:entry_id={entry_id}"
                    failures.append(reason)
                    self._emit_tamper(entry_id, reason)

            prev_chain_hash = stored_chain if not failures else prev_chain_hash

        return len(failures) == 0, failures

    def rotate_key(self, *, new_key: Optional[bytes] = None) -> None:
        """Rotate the HMAC signing key (operator action).

        After rotation, all new entries are signed with the new key.
        Existing entries retain their old signatures — historical verification
        requires the old key (governance responsibility of the operator).

        Emits ``soulbound_key_rotation.v1``.

        Args:
            new_key: New raw key bytes. If None, reads from ADAAD_SOULBOUND_KEY.
        """
        self._key_override = new_key  # None = read from env next call
        self._emit(
            "soulbound_key_rotation.v1",
            {
                "reason": "operator_key_rotation",
                "key_source": "env" if new_key is None else "caller_provided",
            },
        )

    def entry_count(self) -> int:
        """Return the number of entries in the ledger."""
        return len(self._all_entries())

    def last_chain_hash(self) -> str:
        """Return the current chain tip hash."""
        return self._last_chain_hash

    def current_chain_hash(self) -> str:
        """Return the current chain tip hash (Phase 12 / Track 11-C alias).

        Equivalent to ``last_chain_hash()``.  Introduced to give
        ``ContextReplayInterface.verify_replay_digest()`` a semantically
        unambiguous read point that does not imply 'past' state.
        """
        return self._last_chain_hash

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _all_entries(self) -> List[Dict[str, Any]]:
        """Read all raw entry dicts from the VersionedMemoryStore."""
        try:
            state = self._store._read_json_state()  # noqa: SLF001
            entries = []
            for versioned in state.get("entries", []):
                p = versioned.get("payload", {})
                entries.append(p)
            return entries
        except Exception:  # noqa: BLE001
            return []

    def _recover_chain_tip(self) -> str:
        """Recover the chain tip from persisted state on startup."""
        entries = self._all_entries()
        if not entries:
            return GENESIS_CHAIN_HASH
        last = entries[-1]
        return str(last.get("chain_hash", GENESIS_CHAIN_HASH))

    @staticmethod
    def _null_entry(epoch_id: str, context_type: str) -> LedgerEntry:
        return LedgerEntry(
            entry_id       = "",
            epoch_id       = epoch_id,
            context_type   = context_type,
            context_digest = "",
            chain_hash     = "",
            hmac_signature = "",
            schema_version = LEDGER_SCHEMA_VERSION,
        )

    def _emit(self, tx_type: str, payload: Dict[str, Any]) -> None:
        try:
            self._audit(tx_type, payload)
        except Exception:  # noqa: BLE001
            pass  # Audit failure must never block ledger operations

    def _emit_accepted(self, entry: LedgerEntry) -> None:
        self._emit(
            "context_ledger_entry_accepted.v1",
            {
                "entry_id":       entry.entry_id,
                "epoch_id":       entry.epoch_id,
                "context_type":   entry.context_type,
                "context_digest": entry.context_digest,
                "chain_hash":     entry.chain_hash,
            },
        )

    def _emit_rejected(
        self,
        epoch_id: str,
        context_type: str,
        reason: str,
        *,
        rejecting_filter: Optional[str] = None,
    ) -> None:
        payload = {
            "epoch_id":     epoch_id,
            "context_type": context_type,
            "reason":       reason,
        }
        if rejecting_filter is not None:
            payload["rejecting_filter"] = rejecting_filter
        self._emit("context_ledger_entry_rejected.v1", payload)

    def _emit_key_absent(self, epoch_id: str, error: str) -> None:
        self._emit(
            "soulbound_key_absent.v1",
            {
                "epoch_id": epoch_id,
                "error":    error,
            },
        )

    def _emit_tamper(self, entry_id: str, reason: str) -> None:
        self._emit(
            "context_ledger_tamper_detected.v1",
            {
                "entry_id": entry_id,
                "reason":   reason,
            },
        )


__all__ = [
    "LEDGER_SCHEMA_VERSION",
    "VALID_CONTEXT_TYPES",
    "DEFAULT_LEDGER_PATH",
    "GENESIS_CHAIN_HASH",
    "LedgerEntry",
    "AppendResult",
    "SoulboundLedger",
]
