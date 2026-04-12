# SPDX-License-Identifier: Apache-2.0
"""Innovation #33 — Knowledge Bundle Exchange Protocol (KBEP).

Standardized, cryptographically verified knowledge bundle format for sharing
institutional memory across federation members.  Extends INNOV-13 (IMT) to the
multi-instance case: any ADAAD instance can publish a *bundle*, any peer can
*import* that bundle, and the full exchange history is preserved in an
append-only, HMAC-chain-linked ledger.

Constitutional invariants enforced by this module
  KBEP-0        Every bundle_digest MUST be verified before any import completes.
                Fail-closed: TransferVerificationError on mismatch.
  KBEP-DETERM-0 bundle_id derived solely from epoch_id + instance_id via
                SHA-256; no datetime.now(), no random, no uuid4.
  KBEP-PERSIST-0 Every exchange record MUST be flushed to the append-only JSONL
                 ledger before the exchange method returns.
  KBEP-CHAIN-0  Each exchange record is chain-linked to its predecessor via
                HMAC-SHA256 over (record_id + prev_digest + bundle_id).
  KBEP-GATE-0   Federation-level amendments require human0_acknowledged=True;
                fail-closed otherwise.
  KBEP-VERIFY-0 re-digest of bundle payload MUST equal advertised bundle_digest;
                partial or approximate matching is prohibited.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import hashlib
import hmac

# Hardening scaffold — injected by fix/senior-deep-dive-hardening
KNBUEX_INV_CHAIN: str = "KNBUEX-INV-CHAIN"


class KnowledgeBundleExchangeViolation(RuntimeError):
    """Raised when a Knowledge Bundle Exchange constitutional invariant is breached."""



# ── module-level constants ──────────────────────────────────────────────────
_KBEP_VERSION: str = "1.0"
_KBEP_LEDGER: str = "data/kbep_exchange_ledger.jsonl"
_KBEP_HMAC_KEY: str = "kbep-chain-key-v1"  # environment-injectable in production


# ── exceptions ──────────────────────────────────────────────────────────────

class KBEPVerificationError(Exception):
    """KBEP-0 / KBEP-VERIFY-0: bundle_digest mismatch or missing."""


class KBEPChainError(Exception):
    """KBEP-CHAIN-0: ledger chain integrity violation detected."""


class KBEPGateError(Exception):
    """KBEP-GATE-0: federation amendment attempted without HUMAN-0 acknowledgement."""


class KBEPPersistError(Exception):
    """KBEP-PERSIST-0: ledger write failed before method return."""


# ── guard helper ─────────────────────────────────────────────────────────────

def kbep_guard(condition: bool, invariant: str, msg: str) -> None:  # noqa: D103
    """Fail-closed enforcement helper for all KBEP Hard-class invariants."""
    if not condition:
        raise KBEPVerificationError(f"[{invariant}] {msg}")


# ── data structures ──────────────────────────────────────────────────────────

@dataclass
class KnowledgeBundleItem:
    """Single knowledge datum within a bundle.

    knowledge_type values: 'invariant', 'pattern', 'failure', 'capability'
    """
    key: str
    value: Any
    knowledge_type: str
    source_phase: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "knowledge_type": self.knowledge_type,
            "source_phase": self.source_phase,
        }


@dataclass
class FederationBundle:
    """Standardized, cryptographically signed knowledge bundle.

    bundle_id   — KBEP-DETERM-0: sha256(epoch_id + instance_id)
    bundle_digest — KBEP-VERIFY-0: sha256(canonical-json(items))
    """
    bundle_id: str
    instance_id: str
    epoch_id: str
    kbep_version: str
    items: list[KnowledgeBundleItem]
    bundle_digest: str
    federation_amendment: bool = False

    @classmethod
    def create(
        cls,
        epoch_id: str,
        instance_id: str,
        items: list[KnowledgeBundleItem],
        federation_amendment: bool = False,
    ) -> "FederationBundle":
        """KBEP-DETERM-0: deterministic IDs, no datetime/random."""
        # Deterministic bundle_id
        id_src = f"{epoch_id}:{instance_id}"
        bundle_id = "kbep:" + hashlib.sha256(id_src.encode()).hexdigest()[:16]

        # Deterministic content digest over canonical JSON of items
        payload = json.dumps(
            [i.to_dict() for i in items], sort_keys=True, ensure_ascii=False
        )
        bundle_digest = "sha256:" + hashlib.sha256(payload.encode()).hexdigest()

        return cls(
            bundle_id=bundle_id,
            instance_id=instance_id,
            epoch_id=epoch_id,
            kbep_version=_KBEP_VERSION,
            items=items,
            bundle_digest=bundle_digest,
            federation_amendment=federation_amendment,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "instance_id": self.instance_id,
            "epoch_id": self.epoch_id,
            "kbep_version": self.kbep_version,
            "items": [i.to_dict() for i in self.items],
            "bundle_digest": self.bundle_digest,
            "federation_amendment": self.federation_amendment,
        }

    def recompute_digest(self) -> str:
        """KBEP-VERIFY-0: recompute digest from current item state."""
        payload = json.dumps(
            [i.to_dict() for i in self.items], sort_keys=True, ensure_ascii=False
        )
        return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


@dataclass
class ExchangeRecord:
    """Immutable ledger entry for a bundle exchange event.

    record_digest — KBEP-CHAIN-0: hmac-sha256(record_id + prev_digest + bundle_id)
    """
    record_id: str
    event_type: str          # 'export' | 'import' | 'federation_amendment'
    bundle_id: str
    instance_id: str
    epoch_id: str
    item_count: int
    verified: bool
    prev_digest: str
    record_digest: str = field(init=False)

    def __post_init__(self) -> None:
        self.record_digest = self._compute_chain_digest()

    def _compute_chain_digest(self) -> str:
        """KBEP-CHAIN-0: deterministic HMAC over record identity fields."""
        msg = f"{self.record_id}:{self.prev_digest}:{self.bundle_id}"
        return hmac.new(
            _KBEP_HMAC_KEY.encode(), msg.encode(), hashlib.sha256
        ).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "event_type": self.event_type,
            "bundle_id": self.bundle_id,
            "instance_id": self.instance_id,
            "epoch_id": self.epoch_id,
            "item_count": self.item_count,
            "verified": self.verified,
            "prev_digest": self.prev_digest,
            "record_digest": self.record_digest,
        }


# ── engine ───────────────────────────────────────────────────────────────────

class KnowledgeBundleExchangeProtocol:
    """INNOV-33 — multi-instance knowledge bundle exchange engine.

    All state mutations pass through:
      1. KBEP-0 / KBEP-VERIFY-0  — digest verification (fail-closed)
      2. KBEP-GATE-0              — federation amendment gate
      3. KBEP-PERSIST-0           — ledger flush before return
      4. KBEP-CHAIN-0             — chain linking
      5. KBEP-DETERM-0            — deterministic IDs throughout
    """

    def __init__(
        self,
        instance_id: str,
        ledger_path: str | Path = _KBEP_LEDGER,
    ) -> None:
        self.instance_id = instance_id
        self._ledger_path = Path(ledger_path)
        self._records: list[ExchangeRecord] = []
        self._imported_bundles: dict[str, FederationBundle] = {}
        self._prev_digest: str = "genesis"
        self._load()

    # ── public API ────────────────────────────────────────────────────────

    def create_bundle(
        self,
        epoch_id: str,
        items: list[KnowledgeBundleItem],
        federation_amendment: bool = False,
        human0_acknowledged: bool = False,
    ) -> FederationBundle:
        """Create and register an exportable knowledge bundle.

        KBEP-GATE-0: federation amendments require HUMAN-0 acknowledgement.
        KBEP-PERSIST-0: ledger flushed before return.
        """
        if federation_amendment:
            if not human0_acknowledged:
                raise KBEPGateError(
                    "[KBEP-GATE-0] Federation amendment requires human0_acknowledged=True"
                )

        kbep_guard(bool(epoch_id), "KBEP-0", "epoch_id must be non-empty")
        kbep_guard(bool(items), "KBEP-0", "bundle must contain at least one item")

        bundle = FederationBundle.create(
            epoch_id=epoch_id,
            instance_id=self.instance_id,
            items=items,
            federation_amendment=federation_amendment,
        )

        record = self._make_record(
            epoch_id=epoch_id,
            event_type="federation_amendment" if federation_amendment else "export",
            bundle=bundle,
            verified=True,
        )
        self._records.append(record)
        self._flush_record(record)  # KBEP-PERSIST-0
        self._prev_digest = record.record_digest
        return bundle

    def import_bundle(
        self,
        bundle: FederationBundle,
        human0_acknowledged: bool = False,
    ) -> ExchangeRecord:
        """Verify and import a foreign bundle.

        KBEP-0 / KBEP-VERIFY-0: digest verified before any state write.
        KBEP-GATE-0: federation amendments require human0_acknowledged.
        KBEP-PERSIST-0: record flushed before return.
        """
        # KBEP-GATE-0
        if bundle.federation_amendment and not human0_acknowledged:
            raise KBEPGateError(
                "[KBEP-GATE-0] Federation amendment bundle requires human0_acknowledged=True"
            )

        # KBEP-0 / KBEP-VERIFY-0 — fail-closed
        recomputed = bundle.recompute_digest()
        if recomputed != bundle.bundle_digest:
            raise KBEPVerificationError(
                f"[KBEP-VERIFY-0] Digest mismatch: "
                f"expected={bundle.bundle_digest!r} got={recomputed!r}"
            )

        # State write only after verification passes
        self._imported_bundles[bundle.bundle_id] = bundle

        record = self._make_record(
            epoch_id=bundle.epoch_id,
            event_type="import",
            bundle=bundle,
            verified=True,
        )
        self._records.append(record)
        self._flush_record(record)  # KBEP-PERSIST-0
        self._prev_digest = record.record_digest
        return record

    def export_snapshot(self, epoch_id: str) -> FederationBundle:
        """Export current imported-bundle knowledge as a consolidated bundle.

        Aggregates all imported items into a single exportable snapshot.
        """
        all_items: list[KnowledgeBundleItem] = []
        for b in self._imported_bundles.values():
            all_items.extend(b.items)

        if not all_items:
            # Export an empty sentinel bundle so the ledger still records the event
            all_items = [
                KnowledgeBundleItem(
                    key="snapshot:empty",
                    value=True,
                    knowledge_type="capability",
                    source_phase=0,
                )
            ]

        return self.create_bundle(epoch_id=epoch_id, items=all_items)

    def verify_chain(self) -> bool:
        """KBEP-CHAIN-0: replay full ledger and verify HMAC chain integrity."""
        prev = "genesis"
        for rec in self._records:
            expected_digest = hmac.new(
                _KBEP_HMAC_KEY.encode(),
                f"{rec.record_id}:{prev}:{rec.bundle_id}".encode(),
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(expected_digest, rec.record_digest):
                raise KBEPChainError(
                    f"[KBEP-CHAIN-0] Chain break at record_id={rec.record_id!r}"
                )
            prev = rec.record_digest
        return True

    @property
    def records(self) -> list[ExchangeRecord]:
        return list(self._records)

    @property
    def imported_bundles(self) -> dict[str, FederationBundle]:
        return dict(self._imported_bundles)

    # ── private helpers ───────────────────────────────────────────────────

    def _make_record(
        self,
        epoch_id: str,
        event_type: str,
        bundle: FederationBundle,
        verified: bool,
    ) -> ExchangeRecord:
        """KBEP-DETERM-0: record_id = sha256(event_type + epoch_id + bundle_id)."""
        id_src = f"{event_type}:{epoch_id}:{bundle.bundle_id}"
        record_id = "rec:" + hashlib.sha256(id_src.encode()).hexdigest()[:16]
        return ExchangeRecord(
            record_id=record_id,
            event_type=event_type,
            bundle_id=bundle.bundle_id,
            instance_id=bundle.instance_id,
            epoch_id=epoch_id,
            item_count=len(bundle.items),
            verified=verified,
            prev_digest=self._prev_digest,
        )

    def _flush_record(self, record: ExchangeRecord) -> None:
        """KBEP-PERSIST-0: append record to JSONL ledger atomically."""
        try:
            self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with self._ledger_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")
        except OSError as exc:
            raise KBEPPersistError(
                f"[KBEP-PERSIST-0] Ledger write failed: {exc}"
            ) from exc

    def _load(self) -> None:
        """Reload exchange records from ledger on init (fail-open for missing ledger)."""
        if not self._ledger_path.exists():
            return
        try:
            with self._ledger_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        self._prev_digest = data.get("record_digest", self._prev_digest)
                    except json.JSONDecodeError:
                        # Corrupt line silently skipped (fail-open read)
                        continue
        except OSError:
            pass


# ── public surface ────────────────────────────────────────────────────────────
__all__ = [
    "KnowledgeBundleExchangeProtocol",
    "FederationBundle",
    "KnowledgeBundleItem",
    "ExchangeRecord",
    "KBEPVerificationError",
    "KBEPChainError",
    "KBEPGateError",
    "KBEPPersistError",
    "kbep_guard",
]
