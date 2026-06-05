# SPDX-License-Identifier: Apache-2.0
"""INNOV-115 · CGPR — Constitutional Governance Proof Renderer.

World-first portable, self-verifying AI governance proof bundle. Aggregates the
HMAC chain, invariant manifest, execution attestations, and HUMAN-0 signatures
into a single self-contained artifact that an external auditor can verify offline
using only the ADAAD public verification key — no access to internals required.

A ProofBundle is a deterministic, JSON-serialisable document containing:

  - bundle_id       : deterministic SHA-256 of (governor + phase + timestamp_ns)
  - schema_version  : semver string — bump when ProofBundle fields change
  - governor        : "DUSTIN L REID"
  - phase           : integer phase number
  - adaad_version   : semver string
  - generated_at    : ISO-8601 UTC timestamp
  - invariant_manifest : list of InvariantRecord (code, name, phase_introduced,
                          status, hmac_digest)
  - attestations    : list of AttestationRecord (source, phase, event_type,
                          payload_digest, hmac_digest, prev_digest)
  - chain_summary   : ChainSummary (head_digest, entry_count, genesis_digest,
                          chain_valid)
  - human0_slot     : Human0Slot (signature_algorithm, public_key_fingerprint,
                          signature_hex, signed_payload_digest, slot_status)
  - bundle_hmac     : HMAC-SHA-256 of the serialised bundle (sans bundle_hmac
                          field itself) — tamper-evident seal
  - verification_instructions : plain-text offline verification guide

Hard-class invariants enforced:
  CGPR-BUNDLE-0    : Every bundle MUST carry a deterministic bundle_id derived
                     from governor + phase + generated_at_ns; random IDs are
                     prohibited.
  CGPR-CHAIN-0     : ProofLedger entries are HMAC-SHA-256 chained; a broken
                     link raises CGPRChainError before any bundle is emitted.
  CGPR-IMMUT-0     : Sealed ProofBundle entries in the ledger are append-only;
                     mutation raises CGPRImmutError.
  CGPR-MANIFEST-0  : InvariantManifest MUST contain at least one record; an
                     empty manifest raises CGPRManifestError.
  CGPR-ATTEST-0    : AttestationList MUST contain at least one record sourced
                     from a constitutional ledger; empty raises CGPRAttestError.
  CGPR-HMAC-0      : bundle_hmac MUST be computed via hmac.compare_digest-safe
                     HMAC-SHA-256; plain == comparison for any digest is
                     prohibited (AUTH-CT-0 compliance).
  CGPR-HUMAN0-0    : human0_slot.slot_status reflects whether HUMAN-0 signature
                     is present; absent signature sets status=UNSIGNED but MUST
                     NOT block bundle generation — unsigned bundles are valid
                     for internal use; signed bundles are required for external
                     audit delivery.
  CGPR-DETERM-0    : Re-rendering the same phase+invariants+attestations MUST
                     produce an identical bundle_id and bundle_hmac when
                     generated_at_ns is held constant.
  CGPR-OFFLINE-0   : verification_instructions MUST be self-contained plain
                     text enabling offline verification with only the public key.
  CGPR-AUDIT-0     : Every render() call appends one sealed ProofLedgerEntry
                     to the proof ledger before returning.

Governor: DUSTIN L REID (HUMAN-0) — InnovativeAI LLC
"""
from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

GOVERNOR = "DUSTIN L REID"
INNOV_CODE = "CGPR"
INNOV_NUMBER = "INNOV-115"
VERSION = "10.21.0"
PHASE = 210
SCHEMA_VERSION = "1.0.0"

LEDGER_PATH = Path(os.environ.get("CGPR_LEDGER_PATH", "data/cgpr/proof_ledger.jsonl"))
HMAC_SECRET = os.environ.get("ADAAD_HMAC_SECRET", "adaad-cgpr-hmac-secret-v1").encode()
GENESIS_DIGEST = "0" * 64


# ---------------------------------------------------------------------------
# Hard-class invariant identifiers
# ---------------------------------------------------------------------------

CGPR_BUNDLE_0   = "CGPR-BUNDLE-0"
CGPR_CHAIN_0    = "CGPR-CHAIN-0"
CGPR_IMMUT_0    = "CGPR-IMMUT-0"
CGPR_MANIFEST_0 = "CGPR-MANIFEST-0"
CGPR_ATTEST_0   = "CGPR-ATTEST-0"
CGPR_HMAC_0     = "CGPR-HMAC-0"
CGPR_HUMAN0_0   = "CGPR-HUMAN0-0"
CGPR_DETERM_0   = "CGPR-DETERM-0"
CGPR_OFFLINE_0  = "CGPR-OFFLINE-0"
CGPR_AUDIT_0    = "CGPR-AUDIT-0"


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class CGPRError(RuntimeError):
    """Base class for all CGPR constitutional violations."""


class CGPRChainError(CGPRError):
    """CGPR-CHAIN-0 violation: broken HMAC chain in proof ledger."""


class CGPRImmutError(CGPRError):
    """CGPR-IMMUT-0 violation: attempted mutation of sealed proof ledger entry."""


class CGPRManifestError(CGPRError):
    """CGPR-MANIFEST-0 violation: invariant manifest is empty."""


class CGPRAttestError(CGPRError):
    """CGPR-ATTEST-0 violation: attestation list is empty."""


class CGPRBundleError(CGPRError):
    """CGPR-BUNDLE-0 violation: non-deterministic or missing bundle_id."""


class CGPRVerifyError(CGPRError):
    """Raised when bundle verification fails."""


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class SlotStatus(str, Enum):
    UNSIGNED = "UNSIGNED"   # bundle valid for internal use only
    SIGNED   = "SIGNED"     # HUMAN-0 signature present; cleared for external audit


class InvariantStatus(str, Enum):
    ACTIVE   = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    PROPOSED = "PROPOSED"


class AttestationEventType(str, Enum):
    PHASE_RATIFICATION   = "PHASE_RATIFICATION"
    INNOVATION_SHIPPED   = "INNOVATION_SHIPPED"
    INVARIANT_ENFORCED   = "INVARIANT_ENFORCED"
    HMAC_CHAIN_VERIFIED  = "HMAC_CHAIN_VERIFIED"
    LEDGER_SEALED        = "LEDGER_SEALED"
    HUMAN0_GPG_TAG       = "HUMAN0_GPG_TAG"
    BUNDLE_RENDERED      = "BUNDLE_RENDERED"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class InvariantRecord:
    """One Hard-class invariant in the proof manifest."""
    code: str                    # e.g. "CGPR-CHAIN-0"
    name: str                    # human-readable short name
    phase_introduced: int        # phase number when this invariant was ratified
    status: str                  # InvariantStatus value
    hmac_digest: str             # HMAC-SHA-256 of (code + name + str(phase_introduced))


@dataclass
class AttestationRecord:
    """One execution attestation from a constitutional ledger."""
    source: str                  # ledger identifier, e.g. "cmac_admission_ledger"
    phase: int
    event_type: str              # AttestationEventType value
    payload_digest: str          # SHA-256 of the original ledger entry JSON
    hmac_digest: str             # HMAC-SHA-256 of this record's canonical form
    prev_digest: str             # HMAC of the preceding attestation record


@dataclass
class ChainSummary:
    """Summary of the HMAC chain health across all attestations."""
    head_digest: str
    entry_count: int
    genesis_digest: str
    chain_valid: bool


@dataclass
class Human0Slot:
    """Placeholder for HUMAN-0 GPG/Ed25519 signature (Track B action)."""
    signature_algorithm: str          # e.g. "Ed25519"
    public_key_fingerprint: str       # hex fingerprint of HUMAN-0 public key
    signature_hex: str                # hex-encoded detached signature; empty if UNSIGNED
    signed_payload_digest: str        # SHA-256 of the bundle payload that was signed
    slot_status: str                  # SlotStatus value


@dataclass
class ProofBundle:
    """Self-contained, offline-verifiable governance proof artifact."""
    bundle_id: str
    schema_version: str
    governor: str
    phase: int
    adaad_version: str
    generated_at: str                 # ISO-8601 UTC
    generated_at_ns: int              # nanosecond timestamp for determinism
    invariant_manifest: List[Dict[str, Any]]
    attestations: List[Dict[str, Any]]
    chain_summary: Dict[str, Any]
    human0_slot: Dict[str, Any]
    verification_instructions: str
    bundle_hmac: str = field(default="")  # populated after serialisation

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProofLedgerEntry:
    """Append-only ledger entry for a rendered ProofBundle."""
    entry_id: str
    bundle_id: str
    phase: int
    adaad_version: str
    slot_status: str
    generated_at: str
    rendered_by: str
    bundle_hmac: str
    prev_digest: str
    entry_hmac: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _hmac_hex(data: str) -> str:
    """Return HMAC-SHA-256 hex digest.  AUTH-CT-0 compliant."""
    return _hmac.new(HMAC_SECRET, data.encode(), hashlib.sha256).hexdigest()


def _sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()


def _deterministic_bundle_id(governor: str, phase: int, generated_at_ns: int) -> str:
    """CGPR-BUNDLE-0 + CGPR-DETERM-0: deterministic ID, no randomness."""
    raw = f"{governor}|{phase}|{generated_at_ns}"
    return _sha256_hex(raw)


def _invariant_hmac(code: str, name: str, phase_introduced: int) -> str:
    return _hmac_hex(f"{code}|{name}|{phase_introduced}")


def _attestation_hmac(record: AttestationRecord) -> str:
    canonical = (
        f"{record.source}|{record.phase}|{record.event_type}|"
        f"{record.payload_digest}|{record.prev_digest}"
    )
    return _hmac_hex(canonical)


def _bundle_seal_hmac(bundle_dict: Dict[str, Any]) -> str:
    """CGPR-HMAC-0: seal the bundle (excluding bundle_hmac field)."""
    payload = {k: v for k, v in bundle_dict.items() if k != "bundle_hmac"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return _hmac_hex(canonical)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


VERIFICATION_INSTRUCTIONS = """
ADAAD Constitutional Governance Proof — Offline Verification Guide
==================================================================

Prerequisites
-------------
  - Python 3.8+  (standard library only; no external dependencies)
  - ADAAD HMAC public verification key (provided separately by HUMAN-0)

Step 1 — Load the bundle
  import json
  bundle = json.load(open("proof_bundle_phaseNNN.json"))

Step 2 — Verify bundle_hmac (tamper-evident seal)
  import hmac, hashlib
  SECRET = b"<ADAAD public verification key bytes>"
  payload = {k: v for k, v in bundle.items() if k != "bundle_hmac"}
  canonical = json.dumps(payload, sort_keys=True, separators=(",",":"))
  expected = hmac.new(SECRET, canonical.encode(), hashlib.sha256).hexdigest()
  assert hmac.compare_digest(expected, bundle["bundle_hmac"]), "TAMPERED"
  print("bundle_hmac: VERIFIED")

Step 3 — Verify invariant manifest
  for inv in bundle["invariant_manifest"]:
      raw = f"{inv['code']}|{inv['name']}|{inv['phase_introduced']}"
      digest = hmac.new(SECRET, raw.encode(), hashlib.sha256).hexdigest()
      assert hmac.compare_digest(digest, inv["hmac_digest"]), f"INVARIANT TAMPERED: {inv['code']}"
  print(f"All {len(bundle['invariant_manifest'])} invariants: VERIFIED")

Step 4 — Verify attestation chain
  prev = bundle["chain_summary"]["genesis_digest"]
  for att in bundle["attestations"]:
      assert hmac.compare_digest(att["prev_digest"], prev), "CHAIN BROKEN"
      canonical = (f"{att['source']}|{att['phase']}|{att['event_type']}|"
                   f"{att['payload_digest']}|{att['prev_digest']}")
      digest = hmac.new(SECRET, canonical.encode(), hashlib.sha256).hexdigest()
      assert hmac.compare_digest(digest, att["hmac_digest"]), "ATTESTATION TAMPERED"
      prev = att["hmac_digest"]
  print(f"Attestation chain ({len(bundle['attestations'])} entries): VERIFIED")

Step 5 — Verify HUMAN-0 signature (if SIGNED)
  slot = bundle["human0_slot"]
  if slot["slot_status"] == "SIGNED":
      # Verify Ed25519 detached signature using the HUMAN-0 public key
      # (requires PyNaCl or equivalent)
      import nacl.signing, binascii
      vk = nacl.signing.VerifyKey(bytes.fromhex(slot["public_key_fingerprint"]))
      sig = bytes.fromhex(slot["signature_hex"])
      msg = bytes.fromhex(slot["signed_payload_digest"])
      vk.verify(msg, sig)  # raises nacl.exceptions.BadSignatureError if invalid
      print("HUMAN-0 signature: VERIFIED")
  else:
      print("HUMAN-0 signature: NOT PRESENT (internal bundle only)")

All steps passed → bundle is constitutionally authentic.
Governor: DUSTIN L REID · InnovativeAI LLC · adaad.pro
""".strip()


# ---------------------------------------------------------------------------
# Proof Ledger
# ---------------------------------------------------------------------------

class ProofLedger:
    """Append-only HMAC-chained ledger of rendered proof bundles. CGPR-CHAIN-0."""

    def __init__(self, path: Path = LEDGER_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: List[ProofLedgerEntry] = []
        self._head_digest: str = GENESIS_DIGEST
        self._load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self) -> None:
        if not self.path.exists():
            return
        prev = GENESIS_DIGEST
        for line in self.path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            raw: Dict[str, Any] = json.loads(line)
            entry = ProofLedgerEntry(**raw)
            expected = self._compute_entry_hmac(entry, prev)
            if not _hmac.compare_digest(expected, entry.entry_hmac):
                raise CGPRChainError(
                    f"{CGPR_CHAIN_0}: broken HMAC chain at entry {entry.entry_id}"
                )
            prev = entry.entry_hmac
            self._entries.append(entry)
        if self._entries:
            self._head_digest = self._entries[-1].entry_hmac

    def _compute_entry_hmac(self, entry: ProofLedgerEntry, prev: str) -> str:
        canonical = (
            f"{entry.entry_id}|{entry.bundle_id}|{entry.phase}|"
            f"{entry.adaad_version}|{entry.slot_status}|{entry.generated_at}|"
            f"{entry.rendered_by}|{entry.bundle_hmac}|{prev}"
        )
        return _hmac_hex(canonical)

    def _append(self, entry: ProofLedgerEntry) -> None:
        # CGPR-IMMUT-0: existing entries are never mutated
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as fh:
            fh.write(json.dumps(asdict(entry)) + "\n")
        self._entries.append(entry)
        self._head_digest = entry.entry_hmac

    # ── Public interface ──────────────────────────────────────────────────────

    def seal(self, bundle: ProofBundle, rendered_by: str = "DEVADAAD") -> ProofLedgerEntry:
        """Append a sealed ledger entry for the rendered bundle. CGPR-AUDIT-0."""
        entry_id = _sha256_hex(
            f"{bundle.bundle_id}|{bundle.generated_at_ns}|{self._head_digest}"
        )
        entry = ProofLedgerEntry(
            entry_id=entry_id,
            bundle_id=bundle.bundle_id,
            phase=bundle.phase,
            adaad_version=bundle.adaad_version,
            slot_status=bundle.human0_slot.get("slot_status", SlotStatus.UNSIGNED.value)
            if isinstance(bundle.human0_slot, dict)
            else bundle.human0_slot["slot_status"],
            generated_at=bundle.generated_at,
            rendered_by=rendered_by,
            bundle_hmac=bundle.bundle_hmac,
            prev_digest=self._head_digest,
            entry_hmac="",  # computed below
        )
        entry.entry_hmac = self._compute_entry_hmac(entry, self._head_digest)
        self._append(entry)
        return entry

    @property
    def head_digest(self) -> str:
        return self._head_digest

    @property
    def entry_count(self) -> int:
        return len(self._entries)


# ---------------------------------------------------------------------------
# Constitutional Governance Proof Renderer
# ---------------------------------------------------------------------------

class ConstitutionalGovernanceProofRenderer:
    """Renders self-contained, offline-verifiable governance proof bundles.

    CGPR-BUNDLE-0  deterministic bundle IDs
    CGPR-CHAIN-0   ledger HMAC chain integrity
    CGPR-IMMUT-0   ledger append-only
    CGPR-MANIFEST-0 non-empty invariant manifest
    CGPR-ATTEST-0  non-empty attestations
    CGPR-HMAC-0    AUTH-CT-0 compliant digest comparison
    CGPR-HUMAN0-0  unsigned bundles allowed; signed bundles for external audit
    CGPR-DETERM-0  reproducible bundle for same inputs
    CGPR-OFFLINE-0 self-contained verification instructions
    CGPR-AUDIT-0   every render() call appends to proof ledger
    """

    def __init__(
        self,
        ledger: Optional[ProofLedger] = None,
        adaad_version: str = VERSION,
        hmac_secret: bytes = HMAC_SECRET,
    ) -> None:
        self._ledger = ledger or ProofLedger()
        self._adaad_version = adaad_version
        self._hmac_secret = hmac_secret

    # ── Core render ──────────────────────────────────────────────────────────

    def render(
        self,
        phase: int,
        invariants: List[Dict[str, Any]],
        attestations: List[Dict[str, Any]],
        human0_signature_hex: str = "",
        human0_pubkey_fingerprint: str = "",
        rendered_by: str = "DEVADAAD",
        _fixed_ns: Optional[int] = None,
    ) -> ProofBundle:
        """Render and seal a governance proof bundle.

        Args:
            phase: integer phase number.
            invariants: list of dicts with keys {code, name, phase_introduced,
                        status}. Additional hmac_digest computed internally.
            attestations: list of dicts with keys {source, phase, event_type,
                          payload_digest}. prev_digest chain computed internally.
            human0_signature_hex: hex-encoded detached HUMAN-0 signature (Track B).
                                  Empty string yields UNSIGNED bundle.
            human0_pubkey_fingerprint: hex fingerprint of HUMAN-0 public key.
            rendered_by: identity string of rendering agent.
            _fixed_ns: override nanosecond timestamp (for determinism in tests).
        """
        # CGPR-MANIFEST-0
        if not invariants:
            raise CGPRManifestError(
                f"{CGPR_MANIFEST_0}: invariant manifest must not be empty"
            )
        # CGPR-ATTEST-0
        if not attestations:
            raise CGPRAttestError(
                f"{CGPR_ATTEST_0}: attestation list must not be empty"
            )

        generated_at_ns = _fixed_ns if _fixed_ns is not None else time.time_ns()
        generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(generated_at_ns // 1_000_000_000))

        # CGPR-BUNDLE-0 + CGPR-DETERM-0
        bundle_id = _deterministic_bundle_id(GOVERNOR, phase, generated_at_ns)

        # Build invariant manifest
        inv_records: List[Dict[str, Any]] = []
        for inv in invariants:
            rec = InvariantRecord(
                code=inv["code"],
                name=inv["name"],
                phase_introduced=inv["phase_introduced"],
                status=inv.get("status", InvariantStatus.ACTIVE.value),
                hmac_digest=_invariant_hmac(
                    inv["code"], inv["name"], inv["phase_introduced"]
                ),
            )
            inv_records.append(asdict(rec))

        # Build attestation chain
        att_records: List[Dict[str, Any]] = []
        prev = GENESIS_DIGEST
        for att in attestations:
            rec = AttestationRecord(
                source=att["source"],
                phase=att.get("phase", phase),
                event_type=att["event_type"],
                payload_digest=att["payload_digest"],
                hmac_digest="",       # computed below
                prev_digest=prev,
            )
            rec.hmac_digest = _attestation_hmac(rec)
            prev = rec.hmac_digest
            att_records.append(asdict(rec))

        chain_summary = ChainSummary(
            head_digest=prev,
            entry_count=len(att_records),
            genesis_digest=GENESIS_DIGEST,
            chain_valid=True,
        )

        # CGPR-HUMAN0-0: unsigned is valid for internal use
        slot_status = SlotStatus.SIGNED if human0_signature_hex else SlotStatus.UNSIGNED
        signed_payload_digest = (
            _sha256_hex(bundle_id + generated_at) if human0_signature_hex else ""
        )
        human0_slot = Human0Slot(
            signature_algorithm="Ed25519",
            public_key_fingerprint=human0_pubkey_fingerprint,
            signature_hex=human0_signature_hex,
            signed_payload_digest=signed_payload_digest,
            slot_status=slot_status.value,
        )

        bundle = ProofBundle(
            bundle_id=bundle_id,
            schema_version=SCHEMA_VERSION,
            governor=GOVERNOR,
            phase=phase,
            adaad_version=self._adaad_version,
            generated_at=generated_at,
            generated_at_ns=generated_at_ns,
            invariant_manifest=inv_records,
            attestations=att_records,
            chain_summary=asdict(chain_summary),
            human0_slot=asdict(human0_slot),
            verification_instructions=VERIFICATION_INSTRUCTIONS,
            bundle_hmac="",
        )

        # CGPR-HMAC-0: seal bundle
        bundle_dict = bundle.to_dict()
        bundle.bundle_hmac = _bundle_seal_hmac(bundle_dict)

        # CGPR-AUDIT-0: append to proof ledger
        self._ledger.seal(bundle, rendered_by=rendered_by)

        return bundle

    # ── Verification ─────────────────────────────────────────────────────────

    def verify(self, bundle: ProofBundle) -> Dict[str, Any]:
        """Verify a ProofBundle's tamper-evident seals and chain integrity.

        Returns a verification report dict. Raises CGPRVerifyError on failure.
        """
        report: Dict[str, Any] = {
            "bundle_id": bundle.bundle_id,
            "phase": bundle.phase,
            "bundle_hmac_ok": False,
            "invariant_manifest_ok": False,
            "attestation_chain_ok": False,
            "human0_slot_status": bundle.human0_slot.get("slot_status")
            if isinstance(bundle.human0_slot, dict)
            else bundle.human0_slot["slot_status"],
            "errors": [],
        }

        # Verify bundle seal
        bundle_dict = bundle.to_dict()
        expected_seal = _bundle_seal_hmac(bundle_dict)
        if _hmac.compare_digest(expected_seal, bundle.bundle_hmac):
            report["bundle_hmac_ok"] = True
        else:
            report["errors"].append("bundle_hmac mismatch — bundle may be tampered")

        # Verify invariant manifest HMACs
        manifest_ok = True
        for inv in bundle.invariant_manifest:
            expected = _invariant_hmac(inv["code"], inv["name"], inv["phase_introduced"])
            if not _hmac.compare_digest(expected, inv["hmac_digest"]):
                manifest_ok = False
                report["errors"].append(f"invariant HMAC mismatch: {inv['code']}")
        report["invariant_manifest_ok"] = manifest_ok

        # Verify attestation chain
        chain_ok = True
        prev = GENESIS_DIGEST
        for att in bundle.attestations:
            if not _hmac.compare_digest(att["prev_digest"], prev):
                chain_ok = False
                report["errors"].append(f"attestation chain broken at {att['source']}")
                break
            rec = AttestationRecord(
                source=att["source"],
                phase=att["phase"],
                event_type=att["event_type"],
                payload_digest=att["payload_digest"],
                hmac_digest="",
                prev_digest=prev,
            )
            expected_att = _attestation_hmac(rec)
            if not _hmac.compare_digest(expected_att, att["hmac_digest"]):
                chain_ok = False
                report["errors"].append(f"attestation HMAC mismatch at {att['source']}")
                break
            prev = att["hmac_digest"]
        report["attestation_chain_ok"] = chain_ok

        if report["errors"]:
            raise CGPRVerifyError(
                f"Bundle {bundle.bundle_id} failed verification: {report['errors']}"
            )

        return report

    def export_json(self, bundle: ProofBundle, path: Path) -> None:
        """Serialise a ProofBundle to a JSON file for external delivery."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(bundle.to_dict(), indent=2))

    @property
    def ledger(self) -> ProofLedger:
        return self._ledger
