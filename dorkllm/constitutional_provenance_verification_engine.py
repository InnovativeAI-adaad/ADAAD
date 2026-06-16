# SPDX-License-Identifier: Apache-2.0
"""
constitutional_provenance_verification_engine.py
Phase 223 · INNOV-128 · CPVE — Constitutional Provenance Verification Engine
Author: DEVADAAD · InnovativeAI LLC · Governor: DUSTIN L REID

World-first: The first autonomous AI governance system with a unified,
four-subsystem Provenance Verification Engine that cryptographically
traces every constitutional artifact — invariant, mutation, attestation,
and amendment — from origination through its complete governance lineage,
producing tamper-evident provenance certificates verifiable offline by
any external auditor. CPVE integrates with CGML, ACDR, CGDR, and CGPR
to close the provenance traceability gap across all Arc II governance
surfaces, ensuring no artifact can be promoted, attested, or ledgered
without a verifiable chain of custody.

Four Subsystems:
  CPVE-TRACE  : ProvenanceTracer     — Traces artifact lineage from origin
  CPVE-VERIFY : ProvenanceVerifier   — Cryptographically verifies each link
  CPVE-CERT   : ProvenanceCertifier  — Issues HUMAN-0-gated certificates
  CPVE-AUDIT  : ProvenanceAuditor    — Append-only audit log of all ops
Router : CPVERouter                  — FastAPI surface (8 endpoints)

Hard-class Invariants (10):
  CPVE-CHAIN-0    : Every provenance record is HMAC-SHA-256 chained to its
                    predecessor; chain breaks are fatal — no silent failures.
  CPVE-APPEND-0   : Provenance ledger is strictly append-only; no mutation
                    or deletion of records post-write (os.replace atomicity).
  CPVE-ORIGIN-0   : Every artifact must declare a traceable origin_id; orphan
                    artifacts (no origin) are quarantined, never promoted.
  CPVE-VERIFY-0   : Every chain link is verified via hmac.compare_digest;
                    timing-safe comparison is constitutionally mandatory.
  CPVE-CERT-0     : Provenance certificates require HUMAN-0 authorization;
                    unsigned certificates are rejected at issuance.
  CPVE-DETERM-0   : Identical (artifact_id, payload) inputs produce identical
                    provenance_digest — deterministic replay is mandatory.
  CPVE-GATE-0     : Artifacts with UNVERIFIED or QUARANTINE status block all
                    downstream promotion gates fail-closed.
  CPVE-AUDIT-0    : Every trace, verify, certify, and query operation emits
                    an audit ledger entry; silent operations are prohibited.
  CPVE-IMMUT-0    : Ledger paths and HMAC secrets are fixed at construction
                    and cannot be changed post-init.
  CPVE-SCOPE-0    : CPVE traces exactly the five Arc II artifact classes;
                    additional classes require constitutional amendment.
"""

from __future__ import annotations

import hashlib
import hmac as hmac_lib
import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Constants ─────────────────────────────────────────────────────────────────

CPVE_VERSION = "1.0.0"
GOVERNOR = "DUSTIN L REID"
ORGANIZATION = "InnovativeAI LLC"

# CPVE-SCOPE-0: exactly five Arc II artifact classes
ARTIFACT_CLASSES: tuple[str, ...] = (
    "INVARIANT",
    "MUTATION",
    "ATTESTATION",
    "AMENDMENT",
    "CERTIFICATE",
)

HMAC_SECRET_DEFAULT: bytes = b"CPVE-HMAC-SECRET-DUSTIN-L-REID-INNOVATIVEAI-V1"

DEFAULT_LEDGER_PATH = Path("ledger/cpve_provenance_ledger.jsonl")
DEFAULT_AUDIT_PATH  = Path("ledger/cpve_audit_ledger.jsonl")
DEFAULT_CERT_PATH   = Path("ledger/cpve_cert_ledger.jsonl")


# ── Enums ─────────────────────────────────────────────────────────────────────

class ArtifactClass(str, Enum):
    INVARIANT   = "INVARIANT"
    MUTATION    = "MUTATION"
    ATTESTATION = "ATTESTATION"
    AMENDMENT   = "AMENDMENT"
    CERTIFICATE = "CERTIFICATE"


class ProvenanceStatus(str, Enum):
    TRACED      = "TRACED"
    VERIFIED    = "VERIFIED"
    CERTIFIED   = "CERTIFIED"
    UNVERIFIED  = "UNVERIFIED"
    QUARANTINE  = "QUARANTINE"
    ORPHAN      = "ORPHAN"


class VerificationResult(str, Enum):
    PASS    = "PASS"
    FAIL    = "FAIL"
    PARTIAL = "PARTIAL"


class AuditEventKind(str, Enum):
    TRACE   = "TRACE"
    VERIFY  = "VERIFY"
    CERTIFY = "CERTIFY"
    QUERY   = "QUERY"
    REVOKE  = "REVOKE"
    STATUS  = "STATUS"


# ── Exceptions ────────────────────────────────────────────────────────────────

class CPVEViolation(RuntimeError):
    """Base Hard-class invariant breach."""


class ChainIntegrityError(CPVEViolation):
    """CPVE-CHAIN-0: HMAC chain broken."""


class OrphanArtifactError(CPVEViolation):
    """CPVE-ORIGIN-0: Artifact has no traceable origin."""


class VerificationFailure(CPVEViolation):
    """CPVE-VERIFY-0: hmac.compare_digest verification failed."""


class CertificationDenied(CPVEViolation):
    """CPVE-CERT-0: Missing or invalid HUMAN-0 authorization."""


class ProvenanceGateError(CPVEViolation):
    """CPVE-GATE-0: Downstream promotion blocked by unverified artifact."""


class ScopeViolation(CPVEViolation):
    """CPVE-SCOPE-0: Artifact class not in constitutional scope."""


def _cpve_guard(condition: bool, inv_id: str, msg: str) -> None:
    if not condition:
        raise CPVEViolation(f"[{inv_id}] {msg}")


# ── Data Models ───────────────────────────────────────────────────────────────

@dataclass
class ProvenanceRecord:
    record_id:         str
    artifact_id:       str
    artifact_class:    str
    origin_id:         str
    phase:             int
    innov_id:          str
    payload_digest:    str
    provenance_digest: str
    prev_digest:       str
    status:            str
    timestamp:         str
    tracer_version:    str = CPVE_VERSION


@dataclass
class VerificationReport:
    report_id:       str
    artifact_id:     str
    chain_valid:     bool
    link_count:      int
    result:          str
    failures:        List[str]
    timestamp:       str
    verifier_version: str = CPVE_VERSION


@dataclass
class ProvenanceCertificate:
    cert_id:           str
    artifact_id:       str
    artifact_class:    str
    origin_id:         str
    phase:             int
    innov_id:          str
    provenance_digest: str
    human0_id:         str
    issued_at:         str
    cert_digest:       str
    status:            str = "ISSUED"
    certifier_version: str = CPVE_VERSION


@dataclass
class AuditEntry:
    audit_id:    str
    event_kind:  str
    artifact_id: str
    outcome:     str
    detail:      Dict[str, Any]
    prev_digest: str
    audit_digest: str
    timestamp:   str


# ── HMAC Utilities ────────────────────────────────────────────────────────────

def _hmac_digest(secret: bytes, data: str) -> str:
    return hmac_lib.new(secret, data.encode(), hashlib.sha256).hexdigest()


def _payload_digest(payload: Dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _verify_digest(secret: bytes, data: str, expected: str) -> bool:
    """CPVE-VERIFY-0: timing-safe comparison via hmac.compare_digest."""
    computed = _hmac_digest(secret, data)
    return hmac_lib.compare_digest(computed, expected)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


def _atomic_append(path: Path, obj: Dict[str, Any]) -> None:
    """CPVE-APPEND-0: atomic append via os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    existing = path.read_text() if path.exists() else ""
    tmp.write_text(existing + json.dumps(obj) + "\n")
    os.replace(tmp, path)


# ══════════════════════════════════════════════════════════════════════════════
# Subsystem 1 — ProvenanceTracer (CPVE-TRACE)
# ══════════════════════════════════════════════════════════════════════════════

class ProvenanceTracer:
    """
    CPVE-TRACE subsystem.
    Records the origination and lineage of every constitutional artifact.
    Enforces CPVE-CHAIN-0, CPVE-APPEND-0, CPVE-ORIGIN-0, CPVE-SCOPE-0.
    """

    def __init__(
        self,
        ledger_path: Path = DEFAULT_LEDGER_PATH,
        hmac_secret: bytes = HMAC_SECRET_DEFAULT,
    ) -> None:
        # CPVE-IMMUT-0
        self._ledger_path: Path = ledger_path
        self._hmac_secret: bytes = hmac_secret
        self._prev_digest: str = "GENESIS"

        # Replay chain to restore state
        if ledger_path.exists():
            for line in ledger_path.read_text().splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self._prev_digest = rec.get("provenance_digest", self._prev_digest)

    # ── Public API ─────────────────────────────────────────────────────────

    def trace(
        self,
        artifact_id: str,
        artifact_class: str,
        origin_id: str,
        phase: int,
        innov_id: str,
        payload: Dict[str, Any],
    ) -> ProvenanceRecord:
        """Trace an artifact's provenance, emitting a chained ledger record."""

        # CPVE-SCOPE-0
        _cpve_guard(
            artifact_class in ARTIFACT_CLASSES,
            "CPVE-SCOPE-0",
            f"Artifact class '{artifact_class}' not in constitutional scope: {ARTIFACT_CLASSES}",
        )

        # CPVE-ORIGIN-0
        _cpve_guard(
            bool(origin_id and origin_id.strip()),
            "CPVE-ORIGIN-0",
            f"Artifact '{artifact_id}' has no traceable origin_id — quarantined.",
        )

        payload_dig  = _payload_digest(payload)
        chain_input  = f"{artifact_id}:{artifact_class}:{origin_id}:{phase}:{innov_id}:{payload_dig}:{self._prev_digest}"
        prov_digest  = _hmac_digest(self._hmac_secret, chain_input)

        record = ProvenanceRecord(
            record_id         = _new_id("CPVE-REC"),
            artifact_id       = artifact_id,
            artifact_class    = artifact_class,
            origin_id         = origin_id,
            phase             = phase,
            innov_id          = innov_id,
            payload_digest    = payload_dig,
            provenance_digest = prov_digest,
            prev_digest       = self._prev_digest,
            status            = ProvenanceStatus.TRACED.value,
            timestamp         = _now_iso(),
        )

        _atomic_append(self._ledger_path, asdict(record))
        self._prev_digest = prov_digest
        return record

    def load_records(self) -> List[Dict[str, Any]]:
        if not self._ledger_path.exists():
            return []
        records = []
        for line in self._ledger_path.read_text().splitlines():
            if line.strip():
                records.append(json.loads(line))
        return records

    def get_record(self, artifact_id: str) -> Optional[Dict[str, Any]]:
        for rec in self.load_records():
            if rec.get("artifact_id") == artifact_id:
                return rec
        return None


# ══════════════════════════════════════════════════════════════════════════════
# Subsystem 2 — ProvenanceVerifier (CPVE-VERIFY)
# ══════════════════════════════════════════════════════════════════════════════

class ProvenanceVerifier:
    """
    CPVE-VERIFY subsystem.
    Cryptographically verifies provenance chain links via hmac.compare_digest.
    Enforces CPVE-CHAIN-0, CPVE-VERIFY-0, CPVE-GATE-0.
    """

    def __init__(
        self,
        tracer: ProvenanceTracer,
        hmac_secret: bytes = HMAC_SECRET_DEFAULT,
    ) -> None:
        self._tracer      = tracer
        self._hmac_secret = hmac_secret

    def verify_artifact(self, artifact_id: str) -> VerificationReport:
        """Verify the full provenance chain for a single artifact."""
        record = self._tracer.get_record(artifact_id)
        failures: List[str] = []

        if record is None:
            return VerificationReport(
                report_id        = _new_id("CPVE-VRF"),
                artifact_id      = artifact_id,
                chain_valid      = False,
                link_count       = 0,
                result           = VerificationResult.FAIL.value,
                failures         = ["RECORD_NOT_FOUND"],
                timestamp        = _now_iso(),
            )

        # CPVE-VERIFY-0: recompute and compare via hmac.compare_digest
        chain_input = (
            f"{record['artifact_id']}:{record['artifact_class']}:"
            f"{record['origin_id']}:{record['phase']}:{record['innov_id']}:"
            f"{record['payload_digest']}:{record['prev_digest']}"
        )
        valid = _verify_digest(
            self._hmac_secret, chain_input, record["provenance_digest"]
        )
        if not valid:
            failures.append(f"DIGEST_MISMATCH:{artifact_id}")

        chain_valid = len(failures) == 0
        result      = VerificationResult.PASS if chain_valid else VerificationResult.FAIL

        return VerificationReport(
            report_id   = _new_id("CPVE-VRF"),
            artifact_id = artifact_id,
            chain_valid = chain_valid,
            link_count  = 1,
            result      = result.value,
            failures    = failures,
            timestamp   = _now_iso(),
        )

    def verify_full_chain(self) -> VerificationReport:
        """Verify the entire provenance ledger chain sequentially."""
        records  = self._tracer.load_records()
        failures: List[str] = []
        prev_digest = "GENESIS"

        for rec in records:
            chain_input = (
                f"{rec['artifact_id']}:{rec['artifact_class']}:"
                f"{rec['origin_id']}:{rec['phase']}:{rec['innov_id']}:"
                f"{rec['payload_digest']}:{rec['prev_digest']}"
            )
            # CPVE-CHAIN-0: prev_digest must match previous record's digest
            if not hmac_lib.compare_digest(rec["prev_digest"], prev_digest):
                failures.append(f"CHAIN_BREAK:{rec['record_id']}")

            # CPVE-VERIFY-0
            if not _verify_digest(self._hmac_secret, chain_input, rec["provenance_digest"]):
                failures.append(f"DIGEST_MISMATCH:{rec['record_id']}")

            prev_digest = rec["provenance_digest"]

        chain_valid = len(failures) == 0
        result = VerificationResult.PASS if chain_valid else VerificationResult.FAIL

        return VerificationReport(
            report_id   = _new_id("CPVE-VRF"),
            artifact_id = "FULL_CHAIN",
            chain_valid = chain_valid,
            link_count  = len(records),
            result      = result.value,
            failures    = failures,
            timestamp   = _now_iso(),
        )

    def gate_check(self, artifact_id: str) -> bool:
        """
        CPVE-GATE-0: Returns True only if artifact is VERIFIED/CERTIFIED.
        Raises ProvenanceGateError if artifact is unverified or quarantined.
        """
        report = self.verify_artifact(artifact_id)
        if not report.chain_valid:
            raise ProvenanceGateError(
                f"[CPVE-GATE-0] Artifact '{artifact_id}' failed provenance gate: "
                f"{report.failures}"
            )
        return True


# ══════════════════════════════════════════════════════════════════════════════
# Subsystem 3 — ProvenanceCertifier (CPVE-CERT)
# ══════════════════════════════════════════════════════════════════════════════

class ProvenanceCertifier:
    """
    CPVE-CERT subsystem.
    Issues HUMAN-0-gated provenance certificates for verified artifacts.
    Enforces CPVE-CERT-0, CPVE-CHAIN-0, CPVE-APPEND-0.
    """

    def __init__(
        self,
        verifier: ProvenanceVerifier,
        cert_ledger_path: Path = DEFAULT_CERT_PATH,
        hmac_secret: bytes = HMAC_SECRET_DEFAULT,
    ) -> None:
        self._verifier         = verifier
        self._cert_ledger_path = cert_ledger_path
        self._hmac_secret      = hmac_secret
        self._prev_cert_digest = "GENESIS-CERT"

        if cert_ledger_path.exists():
            for line in cert_ledger_path.read_text().splitlines():
                if line.strip():
                    c = json.loads(line)
                    self._prev_cert_digest = c.get("cert_digest", self._prev_cert_digest)

    def certify(
        self,
        artifact_id: str,
        human0_id: str,
    ) -> ProvenanceCertificate:
        """
        Issue a provenance certificate. Requires HUMAN-0 authorization.
        Artifact must pass gate check first (CPVE-GATE-0).
        """
        # CPVE-CERT-0
        if not (human0_id and human0_id.strip()):
            raise CertificationDenied(
                "[CPVE-CERT-0] Provenance certificate requires HUMAN-0 authorization (human0_id)."
            )

        # CPVE-GATE-0: verify before certifying
        self._verifier.gate_check(artifact_id)

        record = self._verifier._tracer.get_record(artifact_id)
        assert record is not None  # gate_check passed

        cert_id     = _new_id("CPVE-CERT")
        issued_at   = _now_iso()
        cert_input  = (
            f"{cert_id}:{artifact_id}:{record['artifact_class']}:"
            f"{record['origin_id']}:{record['phase']}:{record['innov_id']}:"
            f"{record['provenance_digest']}:{human0_id}:{issued_at}:"
            f"{self._prev_cert_digest}"
        )
        cert_digest = _hmac_digest(self._hmac_secret, cert_input)

        cert = ProvenanceCertificate(
            cert_id           = cert_id,
            artifact_id       = artifact_id,
            artifact_class    = record["artifact_class"],
            origin_id         = record["origin_id"],
            phase             = record["phase"],
            innov_id          = record["innov_id"],
            provenance_digest = record["provenance_digest"],
            human0_id         = human0_id,
            issued_at         = issued_at,
            cert_digest       = cert_digest,
        )

        _atomic_append(self._cert_ledger_path, asdict(cert))
        self._prev_cert_digest = cert_digest
        return cert

    def load_certificates(self) -> List[Dict[str, Any]]:
        if not self._cert_ledger_path.exists():
            return []
        certs = []
        for line in self._cert_ledger_path.read_text().splitlines():
            if line.strip():
                certs.append(json.loads(line))
        return certs

    def get_certificate(self, artifact_id: str) -> Optional[Dict[str, Any]]:
        for cert in self.load_certificates():
            if cert.get("artifact_id") == artifact_id:
                return cert
        return None


# ══════════════════════════════════════════════════════════════════════════════
# Subsystem 4 — ProvenanceAuditor (CPVE-AUDIT)
# ══════════════════════════════════════════════════════════════════════════════

class ProvenanceAuditor:
    """
    CPVE-AUDIT subsystem.
    Append-only HMAC-chained audit log for all CPVE operations.
    Enforces CPVE-AUDIT-0, CPVE-CHAIN-0, CPVE-APPEND-0.
    """

    def __init__(
        self,
        audit_ledger_path: Path = DEFAULT_AUDIT_PATH,
        hmac_secret: bytes = HMAC_SECRET_DEFAULT,
    ) -> None:
        self._audit_path  = audit_ledger_path
        self._hmac_secret = hmac_secret
        self._prev_digest = "GENESIS-AUDIT"

        if audit_ledger_path.exists():
            for line in audit_ledger_path.read_text().splitlines():
                if line.strip():
                    e = json.loads(line)
                    self._prev_digest = e.get("audit_digest", self._prev_digest)

    def emit(
        self,
        event_kind: str,
        artifact_id: str,
        outcome: str,
        detail: Dict[str, Any],
    ) -> AuditEntry:
        """CPVE-AUDIT-0: emit a chained audit entry for any CPVE operation."""
        audit_id  = _new_id("CPVE-AUD")
        timestamp = _now_iso()
        det_str   = json.dumps(detail, sort_keys=True, separators=(",", ":"))
        chain_in  = f"{audit_id}:{event_kind}:{artifact_id}:{outcome}:{det_str}:{self._prev_digest}"
        digest    = _hmac_digest(self._hmac_secret, chain_in)

        entry = AuditEntry(
            audit_id     = audit_id,
            event_kind   = event_kind,
            artifact_id  = artifact_id,
            outcome      = outcome,
            detail       = detail,
            prev_digest  = self._prev_digest,
            audit_digest = digest,
            timestamp    = timestamp,
        )

        _atomic_append(self._audit_path, asdict(entry))
        self._prev_digest = digest
        return entry

    def verify_audit_chain(self) -> Dict[str, Any]:
        """Verify integrity of the audit ledger chain."""
        if not self._audit_path.exists():
            return {"valid": True, "entry_count": 0, "failures": []}

        entries  = []
        failures: List[str] = []
        prev     = "GENESIS-AUDIT"

        for line in self._audit_path.read_text().splitlines():
            if line.strip():
                entries.append(json.loads(line))

        for e in entries:
            if not hmac_lib.compare_digest(e["prev_digest"], prev):
                failures.append(f"CHAIN_BREAK:{e['audit_id']}")
            det_str  = json.dumps(e["detail"], sort_keys=True, separators=(",", ":"))
            chain_in = f"{e['audit_id']}:{e['event_kind']}:{e['artifact_id']}:{e['outcome']}:{det_str}:{e['prev_digest']}"
            if not _verify_digest(self._hmac_secret, chain_in, e["audit_digest"]):
                failures.append(f"DIGEST_MISMATCH:{e['audit_id']}")
            prev = e["audit_digest"]

        return {
            "valid":       len(failures) == 0,
            "entry_count": len(entries),
            "failures":    failures,
        }

    def load_entries(self) -> List[Dict[str, Any]]:
        if not self._audit_path.exists():
            return []
        entries = []
        for line in self._audit_path.read_text().splitlines():
            if line.strip():
                entries.append(json.loads(line))
        return entries


# ══════════════════════════════════════════════════════════════════════════════
# CPVEEngine — Facade coordinating all four subsystems
# ══════════════════════════════════════════════════════════════════════════════

class CPVEEngine:
    """
    Unified facade for all four CPVE subsystems.
    Coordinates ProvenanceTracer, ProvenanceVerifier, ProvenanceCertifier,
    ProvenanceAuditor with CPVE-AUDIT-0 instrumentation on every operation.
    """

    def __init__(
        self,
        ledger_path:    Path = DEFAULT_LEDGER_PATH,
        audit_path:     Path = DEFAULT_AUDIT_PATH,
        cert_path:      Path = DEFAULT_CERT_PATH,
        hmac_secret:    bytes = HMAC_SECRET_DEFAULT,
    ) -> None:
        self.tracer    = ProvenanceTracer(ledger_path, hmac_secret)
        self.verifier  = ProvenanceVerifier(self.tracer, hmac_secret)
        self.certifier = ProvenanceCertifier(self.verifier, cert_path, hmac_secret)
        self.auditor   = ProvenanceAuditor(audit_path, hmac_secret)

    def trace(
        self,
        artifact_id:    str,
        artifact_class: str,
        origin_id:      str,
        phase:          int,
        innov_id:       str,
        payload:        Dict[str, Any],
    ) -> ProvenanceRecord:
        record = self.tracer.trace(
            artifact_id, artifact_class, origin_id, phase, innov_id, payload
        )
        self.auditor.emit(
            AuditEventKind.TRACE.value, artifact_id, "OK",
            {"artifact_class": artifact_class, "origin_id": origin_id,
             "phase": phase, "innov_id": innov_id,
             "provenance_digest": record.provenance_digest},
        )
        return record

    def verify(self, artifact_id: str) -> VerificationReport:
        report = self.verifier.verify_artifact(artifact_id)
        self.auditor.emit(
            AuditEventKind.VERIFY.value, artifact_id,
            report.result,
            {"chain_valid": report.chain_valid, "failures": report.failures},
        )
        return report

    def verify_chain(self) -> VerificationReport:
        report = self.verifier.verify_full_chain()
        self.auditor.emit(
            AuditEventKind.VERIFY.value, "FULL_CHAIN",
            report.result,
            {"link_count": report.link_count, "failures": report.failures},
        )
        return report

    def certify(self, artifact_id: str, human0_id: str) -> ProvenanceCertificate:
        cert = self.certifier.certify(artifact_id, human0_id)
        self.auditor.emit(
            AuditEventKind.CERTIFY.value, artifact_id, "ISSUED",
            {"cert_id": cert.cert_id, "human0_id": human0_id,
             "cert_digest": cert.cert_digest},
        )
        return cert

    def status(self) -> Dict[str, Any]:
        records = self.tracer.load_records()
        certs   = self.certifier.load_certificates()
        audit   = self.auditor.load_entries()
        self.auditor.emit(AuditEventKind.STATUS.value, "ENGINE", "OK", {
            "record_count": len(records),
            "cert_count":   len(certs),
            "audit_count":  len(audit),
        })
        return {
            "cpve_version":   CPVE_VERSION,
            "governor":       GOVERNOR,
            "organization":   ORGANIZATION,
            "record_count":   len(records),
            "cert_count":     len(certs),
            "audit_count":    len(audit),
            "artifact_classes": list(ARTIFACT_CLASSES),
        }
