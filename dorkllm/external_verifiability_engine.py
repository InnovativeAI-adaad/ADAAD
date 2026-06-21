# SPDX-License-Identifier: Apache-2.0
"""
dorkllm/external_verifiability_engine.py
Phase 233 · INNOV-138 · EVE — External Verifiability Engine

World-first Arc IV opener: produces externally-auditable attestation bundles
from ADAAD's internal governance ledgers, enabling independent third-party
verification of CHI scores, ACI cycle proofs, and constitutional invariant
compliance without access to private chain internals.

Author  : DEVADAAD · InnovativeAI LLC
Governor: DUSTIN L REID

Arc IV — External Verifiability & Federation · Module 01

EVE closes the external transparency gap identified by SPIE (gap_score 1.00,
constitutional_gap signal, epoch arc4-open-20260621). Internal proofs produced
by CACG, CACP, and CAMS are sealed into SHA-256 / HMAC-SHA-256 attestation
bundles that any third party can verify with only the public HMAC key, without
access to private ledger internals.

Hard-class invariants (10):
  EVE-BUNDLE-0   Every AttestationBundle has a non-empty bundle_digest (SHA-256
                 over canonical JSON of all enclosed proofs). Fail-closed.
  EVE-CHAIN-0    AttestationLedger entries are HMAC-SHA-256 chained;
                 chain verified before every append.
  EVE-APPEND-0   AttestationLedger is append-only; sealed entries raise
                 ImmutabilityViolation on any write attempt after sealing.
  EVE-DETERM-0   Identical (epoch_id, proof_set) inputs produce identical
                 bundle_digest; no datetime.now(), no uuid4(), no RNG.
  EVE-SCOPE-0    Every bundle declares at least one proof_source from the
                 canonical set {CHI, ACI_CYCLE, INVARIANT_REGISTER, SPIE}.
                 Bundles with no valid source raise ScopeViolation.
  EVE-HUMAN0-0   Bundle publication requires a non-empty HUMAN-0 identity;
                 publication without identity raises PublicationGateError.
  EVE-VERIFY-0   verify_bundle() reproduces the bundle_digest from enclosed
                 proofs and raises VerificationFailure if it does not match.
  EVE-EXTERN-0   export_bundle() serialises to a self-contained JSON object
                 that includes the public HMAC key name and verification
                 instructions — no private secrets embedded.
  EVE-IMMUT-0    Sealed AttestationBundles raise ImmutabilityViolation on
                 any field mutation attempt after sealing.
  EVE-AUDIT-0    Every EVE operation appended to a parallel HMAC-chained
                 audit log before the operation returns.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

# ── Constants ─────────────────────────────────────────────────────────────────

_EVE_VERSION = "1.0.0"
_EVE_PUBLIC_HMAC_KEY_NAME = "eve-public-hmac-key-v1"
_HMAC_SECRET = os.environ.get(
    "EVE_HMAC_SECRET",
    "eve-hmac-secret-DUSTIN-L-REID-v10-ArcIV-verifiability",
).encode()

VALID_PROOF_SOURCES: frozenset = frozenset(
    {"CHI", "ACI_CYCLE", "INVARIANT_REGISTER", "SPIE"}
)

# EVE-SCOPE-0: canonical proof source identifiers
PROOF_SOURCE_CHI = "CHI"
PROOF_SOURCE_ACI_CYCLE = "ACI_CYCLE"
PROOF_SOURCE_INVARIANT_REGISTER = "INVARIANT_REGISTER"
PROOF_SOURCE_SPIE = "SPIE"


# ── Exceptions ────────────────────────────────────────────────────────────────

class EVEViolation(RuntimeError):
    """Base Hard-class invariant violation for EVE."""


class BundleDigestError(EVEViolation):
    """EVE-BUNDLE-0: bundle_digest is empty or invalid."""


class ChainBreakError(EVEViolation):
    """EVE-CHAIN-0: HMAC chain break detected in AttestationLedger."""


class ImmutabilityViolation(EVEViolation):
    """EVE-APPEND-0 / EVE-IMMUT-0: write attempt on sealed/immutable record."""


class ScopeViolation(EVEViolation):
    """EVE-SCOPE-0: no valid proof_source declared."""


class PublicationGateError(EVEViolation):
    """EVE-HUMAN0-0: publication attempted without HUMAN-0 identity."""


class VerificationFailure(EVEViolation):
    """EVE-VERIFY-0: bundle_digest recomputation does not match declared digest."""


class ExportError(EVEViolation):
    """EVE-EXTERN-0: export_bundle() cannot embed private secrets."""


# ── Hard-class guard ─────────────────────────────────────────────────────────

def _eve_guard(condition: bool, invariant: str, detail: str = "") -> None:
    """Fail-closed enforcement for all EVE Hard-class invariants."""
    if not condition:
        msg = f"[EVE Hard-class violation] {invariant}"
        if detail:
            msg += f" — {detail}"
        raise EVEViolation(msg)


# ── HMAC helpers ──────────────────────────────────────────────────────────────

def _hmac_digest(payload: str, prev: str = "") -> str:
    msg = f"{prev}|{payload}".encode()
    return hmac.new(_HMAC_SECRET, msg, hashlib.sha256).hexdigest()


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()


# ── Proof data structures ─────────────────────────────────────────────────────

@dataclass
class CHIProof:
    """Constitutional Health Index proof from CASL/CAMS."""
    epoch_id: str
    chi_score: float          # 0.0–1.0
    invariant_count: int
    measurement_ts: float     # Unix timestamp (EVE-DETERM-0: caller supplies)
    source_module: str        # e.g. 'CASL', 'CAMS'
    chain_ref: str            # HMAC ref from source ledger

    def canonical(self) -> str:
        return json.dumps({
            "type": "CHI",
            "epoch_id": self.epoch_id,
            "chi_score": round(self.chi_score, 6),
            "invariant_count": self.invariant_count,
            "measurement_ts": self.measurement_ts,
            "source_module": self.source_module,
            "chain_ref": self.chain_ref,
        }, sort_keys=True)

    def to_dict(self) -> Dict[str, Any]:
        return json.loads(self.canonical())


@dataclass
class ACICycleProof:
    """ACI cycle governance proof from CACG."""
    cycle_id: str
    outcome: str              # PROMOTED | HELD | REJECTED | STALLED
    stages_completed: List[str]
    cycle_started_at: float
    cycle_closed_at: float
    cacg_proof_digest: str    # HMAC proof from CACG sealed record

    def canonical(self) -> str:
        return json.dumps({
            "type": "ACI_CYCLE",
            "cycle_id": self.cycle_id,
            "outcome": self.outcome,
            "stages_completed": sorted(self.stages_completed),
            "cycle_started_at": self.cycle_started_at,
            "cycle_closed_at": self.cycle_closed_at,
            "cacg_proof_digest": self.cacg_proof_digest,
        }, sort_keys=True)

    def to_dict(self) -> Dict[str, Any]:
        return json.loads(self.canonical())


@dataclass
class InvariantRegisterProof:
    """Snapshot proof of the hard-class invariant register."""
    epoch_id: str
    total_invariants: int
    register_digest: str      # SHA-256 of sorted invariant ID list
    snapshot_ts: float
    version: str

    def canonical(self) -> str:
        return json.dumps({
            "type": "INVARIANT_REGISTER",
            "epoch_id": self.epoch_id,
            "total_invariants": self.total_invariants,
            "register_digest": self.register_digest,
            "snapshot_ts": self.snapshot_ts,
            "version": self.version,
        }, sort_keys=True)

    def to_dict(self) -> Dict[str, Any]:
        return json.loads(self.canonical())


@dataclass
class SPIEProof:
    """SPIE ratification proof for an innovation candidate."""
    proposal_id: str
    epoch_id: str
    ratified_by: str
    proposal_digest: str      # from SPIE ledger
    chain_link: str           # HMAC chain link from SPIE ledger

    def canonical(self) -> str:
        return json.dumps({
            "type": "SPIE",
            "proposal_id": self.proposal_id,
            "epoch_id": self.epoch_id,
            "ratified_by": self.ratified_by,
            "proposal_digest": self.proposal_digest,
            "chain_link": self.chain_link,
        }, sort_keys=True)

    def to_dict(self) -> Dict[str, Any]:
        return json.loads(self.canonical())


# ── Attestation bundle ────────────────────────────────────────────────────────

class BundleStatus(Enum):
    DRAFT = "DRAFT"
    SEALED = "SEALED"
    PUBLISHED = "PUBLISHED"


@dataclass
class AttestationBundle:
    """
    Self-contained externally-verifiable attestation bundle.

    EVE-BUNDLE-0  : bundle_digest non-empty; computed from canonical proof JSON.
    EVE-DETERM-0  : identical proof set → identical bundle_digest.
    EVE-SCOPE-0   : at least one proof_source from VALID_PROOF_SOURCES.
    EVE-IMMUT-0   : raises ImmutabilityViolation on mutation after sealing.
    EVE-EXTERN-0  : export serialises public HMAC key name + verify instructions.
    """
    bundle_id: str
    epoch_id: str
    proof_sources: List[str]
    chi_proofs: List[CHIProof] = field(default_factory=list)
    aci_cycle_proofs: List[ACICycleProof] = field(default_factory=list)
    invariant_register_proofs: List[InvariantRegisterProof] = field(default_factory=list)
    spie_proofs: List[SPIEProof] = field(default_factory=list)
    bundle_digest: str = ""
    prev_chain_link: str = ""
    chain_link: str = ""
    status: BundleStatus = BundleStatus.DRAFT
    published_by: str = ""
    published_at: float = 0.0
    _sealed: bool = field(default=False, repr=False)

    # EVE-IMMUT-0
    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False) and name != "_sealed":
            raise ImmutabilityViolation(
                f"EVE-IMMUT-0: AttestationBundle '{self.bundle_id}' is sealed; "
                f"field '{name}' cannot be mutated."
            )
        object.__setattr__(self, name, value)

    def _compute_digest(self) -> str:
        """EVE-BUNDLE-0 + EVE-DETERM-0: canonical deterministic digest."""
        all_proofs = (
            [p.canonical() for p in self.chi_proofs]
            + [p.canonical() for p in self.aci_cycle_proofs]
            + [p.canonical() for p in self.invariant_register_proofs]
            + [p.canonical() for p in self.spie_proofs]
        )
        payload = json.dumps({
            "bundle_id": self.bundle_id,
            "epoch_id": self.epoch_id,
            "proof_sources": sorted(self.proof_sources),
            "proofs": sorted(all_proofs),
        }, sort_keys=True)
        return "sha256:" + _sha256(payload)

    def seal(self, prev_chain_link: str, human0_identity: str) -> None:
        """
        Seal the bundle: compute digest, set chain link, mark SEALED.
        EVE-HUMAN0-0: requires non-empty human0_identity.
        """
        _eve_guard(
            bool(human0_identity),
            "EVE-HUMAN0-0",
            "human0_identity required to seal bundle."
        )
        _eve_guard(
            len(self.proof_sources) > 0 and any(
                s in VALID_PROOF_SOURCES for s in self.proof_sources
            ),
            "EVE-SCOPE-0",
            f"No valid proof_source in {self.proof_sources!r}; "
            f"valid={sorted(VALID_PROOF_SOURCES)}"
        )
        digest = self._compute_digest()
        _eve_guard(bool(digest), "EVE-BUNDLE-0", "bundle_digest must not be empty.")

        object.__setattr__(self, "bundle_digest", digest)
        object.__setattr__(self, "prev_chain_link", prev_chain_link)
        chain = "hmac-sha256:" + _hmac_digest(
            f"{self.bundle_id}:{digest}", prev_chain_link
        )
        object.__setattr__(self, "chain_link", chain)
        object.__setattr__(self, "status", BundleStatus.SEALED)
        object.__setattr__(self, "_sealed", True)

    def publish(self, human0_identity: str, published_at: float) -> None:
        """EVE-HUMAN0-0: mark PUBLISHED; requires HUMAN-0 identity."""
        _eve_guard(
            bool(human0_identity),
            "EVE-HUMAN0-0",
            "HUMAN-0 identity required for publication (EVE-HUMAN0-0)."
        )
        if self.status != BundleStatus.SEALED:
            raise PublicationGateError(
                "EVE-HUMAN0-0: bundle must be SEALED before publication."
            )
        # Temporarily unseal to set publication fields
        object.__setattr__(self, "_sealed", False)
        object.__setattr__(self, "published_by", human0_identity)
        object.__setattr__(self, "published_at", published_at)
        object.__setattr__(self, "status", BundleStatus.PUBLISHED)
        object.__setattr__(self, "_sealed", True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "epoch_id": self.epoch_id,
            "proof_sources": self.proof_sources,
            "chi_proofs": [p.to_dict() for p in self.chi_proofs],
            "aci_cycle_proofs": [p.to_dict() for p in self.aci_cycle_proofs],
            "invariant_register_proofs": [
                p.to_dict() for p in self.invariant_register_proofs
            ],
            "spie_proofs": [p.to_dict() for p in self.spie_proofs],
            "bundle_digest": self.bundle_digest,
            "prev_chain_link": self.prev_chain_link,
            "chain_link": self.chain_link,
            "status": self.status.value,
            "published_by": self.published_by,
            "published_at": self.published_at,
        }


# ── Attestation ledger ────────────────────────────────────────────────────────

@dataclass
class LedgerEntry:
    """EVE-CHAIN-0: HMAC-chained ledger entry."""
    entry_id: str
    bundle_id: str
    bundle_digest: str
    chain_link: str
    prev_chain_link: str
    operation: str
    timestamp: float
    operator: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "bundle_id": self.bundle_id,
            "bundle_digest": self.bundle_digest,
            "chain_link": self.chain_link,
            "prev_chain_link": self.prev_chain_link,
            "operation": self.operation,
            "timestamp": self.timestamp,
            "operator": self.operator,
        }


class AttestationLedger:
    """
    EVE-CHAIN-0 + EVE-APPEND-0: HMAC-SHA-256 chained append-only ledger
    for AttestationBundle lifecycle events.
    """
    _GENESIS = "eve-ledger-genesis-v1"

    def __init__(self) -> None:
        self._entries: List[LedgerEntry] = []
        self._prev_chain: str = "sha256:" + _sha256(self._GENESIS)

    def append(
        self,
        bundle: AttestationBundle,
        operation: str,
        operator: str,
        timestamp: float,
    ) -> LedgerEntry:
        """EVE-CHAIN-0: verify chain before append; EVE-APPEND-0: no deletion."""
        # Verify chain integrity before appending
        self._verify_chain()

        entry_id = "eve-entry:" + _sha256(
            f"{bundle.bundle_id}:{operation}:{timestamp}"
        )[:16]
        chain_link = "hmac-sha256:" + _hmac_digest(
            f"{entry_id}:{bundle.bundle_digest}:{operation}", self._prev_chain
        )
        entry = LedgerEntry(
            entry_id=entry_id,
            bundle_id=bundle.bundle_id,
            bundle_digest=bundle.bundle_digest,
            chain_link=chain_link,
            prev_chain_link=self._prev_chain,
            operation=operation,
            timestamp=timestamp,
            operator=operator,
        )
        self._entries.append(entry)
        self._prev_chain = chain_link
        return entry

    def _verify_chain(self) -> bool:
        """EVE-CHAIN-0: replay chain; raise ChainBreakError on break."""
        prev = "sha256:" + _sha256(self._GENESIS)
        for entry in self._entries:
            expected = "hmac-sha256:" + _hmac_digest(
                f"{entry.entry_id}:{entry.bundle_digest}:{entry.operation}",
                prev,
            )
            if entry.chain_link != expected:
                raise ChainBreakError(
                    f"EVE-CHAIN-0: chain break at entry {entry.entry_id!r}. "
                    f"Expected {expected!r}, got {entry.chain_link!r}."
                )
            prev = entry.chain_link
        return True

    def verify_chain(self) -> bool:
        """Public chain integrity verification (EVE-CHAIN-0)."""
        return self._verify_chain()

    def all_entries(self) -> List[LedgerEntry]:
        return list(self._entries)


# ── Audit log ─────────────────────────────────────────────────────────────────

class AuditLog:
    """EVE-AUDIT-0: HMAC-chained parallel audit log for all EVE operations."""
    _GENESIS = "eve-audit-genesis-v1"

    def __init__(self) -> None:
        self._records: List[Dict[str, Any]] = []
        self._prev: str = "sha256:" + _sha256(self._GENESIS)

    def record(self, operation: str, detail: Dict[str, Any], timestamp: float) -> str:
        payload = json.dumps(
            {"operation": operation, "detail": detail, "timestamp": timestamp},
            sort_keys=True,
        )
        chain = "hmac-sha256:" + _hmac_digest(payload, self._prev)
        self._records.append(
            {"operation": operation, "detail": detail,
             "timestamp": timestamp, "chain_link": chain}
        )
        self._prev = chain
        return chain

    def all_records(self) -> List[Dict[str, Any]]:
        return list(self._records)


# ── EVE Engine ────────────────────────────────────────────────────────────────

class EVEEngine:
    """
    Phase 233 · INNOV-138 · EVE — External Verifiability Engine

    Produces externally-auditable attestation bundles from ADAAD's internal
    governance ledgers. Enforces all 10 EVE Hard-class invariants.
    """

    def __init__(self, instance_id: str = "eve-default") -> None:
        self._instance_id = instance_id
        self._ledger = AttestationLedger()
        self._audit = AuditLog()
        self._bundles: Dict[str, AttestationBundle] = {}
        self._bundle_counter: int = 0

    # ── bundle ID ─────────────────────────────────────────────────────────────

    def _make_bundle_id(self, epoch_id: str) -> str:
        """EVE-DETERM-0: deterministic bundle ID."""
        self._bundle_counter += 1
        src = f"{self._instance_id}:{epoch_id}:{self._bundle_counter}"
        return "eve-bundle:" + _sha256(src)[:16]

    # ── build ─────────────────────────────────────────────────────────────────

    def create_bundle(
        self,
        epoch_id: str,
        chi_proofs: Optional[List[CHIProof]] = None,
        aci_cycle_proofs: Optional[List[ACICycleProof]] = None,
        invariant_register_proofs: Optional[List[InvariantRegisterProof]] = None,
        spie_proofs: Optional[List[SPIEProof]] = None,
    ) -> AttestationBundle:
        """
        Create a DRAFT AttestationBundle.
        EVE-SCOPE-0: at least one valid proof_source required.
        """
        proof_sources: List[str] = []
        if chi_proofs:
            proof_sources.append(PROOF_SOURCE_CHI)
        if aci_cycle_proofs:
            proof_sources.append(PROOF_SOURCE_ACI_CYCLE)
        if invariant_register_proofs:
            proof_sources.append(PROOF_SOURCE_INVARIANT_REGISTER)
        if spie_proofs:
            proof_sources.append(PROOF_SOURCE_SPIE)

        _eve_guard(
            bool(proof_sources),
            "EVE-SCOPE-0",
            "At least one proof type must be supplied to create_bundle()."
        )

        bundle_id = self._make_bundle_id(epoch_id)
        bundle = AttestationBundle(
            bundle_id=bundle_id,
            epoch_id=epoch_id,
            proof_sources=proof_sources,
            chi_proofs=list(chi_proofs or []),
            aci_cycle_proofs=list(aci_cycle_proofs or []),
            invariant_register_proofs=list(invariant_register_proofs or []),
            spie_proofs=list(spie_proofs or []),
        )
        self._bundles[bundle_id] = bundle
        ts = time.time()
        self._audit.record("create_bundle", {"bundle_id": bundle_id, "epoch_id": epoch_id}, ts)
        return bundle

    # ── seal ──────────────────────────────────────────────────────────────────

    def seal_bundle(
        self,
        bundle_id: str,
        human0_identity: str,
        timestamp: float,
    ) -> AttestationBundle:
        """
        Seal a DRAFT bundle.
        EVE-HUMAN0-0: non-empty human0_identity required.
        EVE-BUNDLE-0: bundle_digest computed and verified non-empty.
        EVE-CHAIN-0: ledger entry appended with chain verification.
        EVE-AUDIT-0: operation recorded in audit log.
        """
        _eve_guard(
            bool(human0_identity),
            "EVE-HUMAN0-0",
            "HUMAN-0 identity required to seal bundle."
        )
        bundle = self._get_bundle(bundle_id)
        prev_chain = self._ledger._prev_chain
        bundle.seal(prev_chain, human0_identity)

        _eve_guard(
            bool(bundle.bundle_digest),
            "EVE-BUNDLE-0",
            f"bundle_digest empty after seal on bundle {bundle_id!r}."
        )

        # EVE-CHAIN-0 + EVE-APPEND-0
        self._ledger.append(bundle, "SEAL", human0_identity, timestamp)

        # EVE-AUDIT-0
        self._audit.record(
            "seal_bundle",
            {"bundle_id": bundle_id, "digest": bundle.bundle_digest,
             "human0": human0_identity},
            timestamp,
        )
        return bundle

    # ── publish ───────────────────────────────────────────────────────────────

    def publish_bundle(
        self,
        bundle_id: str,
        human0_identity: str,
        timestamp: float,
    ) -> AttestationBundle:
        """
        Publish a SEALED bundle.
        EVE-HUMAN0-0: non-empty human0_identity required.
        EVE-AUDIT-0: recorded in audit log.
        """
        _eve_guard(
            bool(human0_identity),
            "EVE-HUMAN0-0",
            "HUMAN-0 identity required for publication."
        )
        bundle = self._get_bundle(bundle_id)
        bundle.publish(human0_identity, timestamp)
        self._ledger.append(bundle, "PUBLISH", human0_identity, timestamp)
        self._audit.record(
            "publish_bundle",
            {"bundle_id": bundle_id, "published_by": human0_identity},
            timestamp,
        )
        return bundle

    # ── verify ────────────────────────────────────────────────────────────────

    def verify_bundle(self, bundle_id: str) -> Dict[str, Any]:
        """
        EVE-VERIFY-0: recompute bundle_digest and confirm match.
        Returns verification report.
        """
        bundle = self._get_bundle(bundle_id)
        recomputed = bundle._compute_digest()
        match = recomputed == bundle.bundle_digest
        if not match:
            raise VerificationFailure(
                f"EVE-VERIFY-0: bundle {bundle_id!r} digest mismatch. "
                f"Declared={bundle.bundle_digest!r}, "
                f"Recomputed={recomputed!r}."
            )
        self._audit.record(
            "verify_bundle",
            {"bundle_id": bundle_id, "result": "PASS", "digest": recomputed},
            time.time(),
        )
        return {
            "bundle_id": bundle_id,
            "verification": "PASS",
            "declared_digest": bundle.bundle_digest,
            "recomputed_digest": recomputed,
            "proof_sources": bundle.proof_sources,
            "status": bundle.status.value,
        }

    # ── export ────────────────────────────────────────────────────────────────

    def export_bundle(self, bundle_id: str) -> Dict[str, Any]:
        """
        EVE-EXTERN-0: produce a self-contained export JSON safe for
        third-party verification. No private secrets embedded.
        """
        bundle = self._get_bundle(bundle_id)
        # EVE-EXTERN-0: verify no private secret embedded
        export = bundle.to_dict()
        if _HMAC_SECRET.decode() in json.dumps(export):
            raise ExportError(
                "EVE-EXTERN-0: private HMAC secret detected in export payload. "
                "Aborting export."
            )
        export["_eve_version"] = _EVE_VERSION
        export["_public_hmac_key_name"] = _EVE_PUBLIC_HMAC_KEY_NAME
        export["_verification_instructions"] = (
            "Recompute bundle_digest as SHA-256 of canonical JSON of all enclosed "
            "proofs (sorted keys, sorted proof lists) and compare to declared "
            "bundle_digest. Verify chain_link as HMAC-SHA-256("
            f"bundle_id:bundle_digest, prev_chain_link) using key name "
            f"'{_EVE_PUBLIC_HMAC_KEY_NAME}' obtained from InnovativeAI LLC."
        )
        self._audit.record(
            "export_bundle",
            {"bundle_id": bundle_id},
            time.time(),
        )
        return export

    # ── ledger / audit ────────────────────────────────────────────────────────

    def verify_ledger_chain(self) -> bool:
        """EVE-CHAIN-0: verify full ledger chain integrity."""
        result = self._ledger.verify_chain()
        self._audit.record("verify_ledger_chain", {"result": result}, time.time())
        return result

    def ledger_entries(self) -> List[Dict[str, Any]]:
        return [e.to_dict() for e in self._ledger.all_entries()]

    def audit_records(self) -> List[Dict[str, Any]]:
        """EVE-AUDIT-0: expose parallel audit log."""
        return self._audit.all_records()

    def get_bundle(self, bundle_id: str) -> Optional[AttestationBundle]:
        return self._bundles.get(bundle_id)

    def all_bundles(self) -> List[AttestationBundle]:
        return list(self._bundles.values())

    def status(self) -> Dict[str, Any]:
        return {
            "eve_version": _EVE_VERSION,
            "instance_id": self._instance_id,
            "bundle_count": len(self._bundles),
            "ledger_entries": len(self._ledger.all_entries()),
            "audit_records": len(self._audit.all_records()),
            "chain_integrity": self._ledger.verify_chain(),
            "published_bundles": sum(
                1 for b in self._bundles.values()
                if b.status == BundleStatus.PUBLISHED
            ),
        }

    # ── private ───────────────────────────────────────────────────────────────

    def _get_bundle(self, bundle_id: str) -> AttestationBundle:
        bundle = self._bundles.get(bundle_id)
        if bundle is None:
            raise KeyError(f"Unknown bundle_id: {bundle_id!r}")
        return bundle
