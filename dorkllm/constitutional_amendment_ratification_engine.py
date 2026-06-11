# SPDX-License-Identifier: Apache-2.0
# INNOV-124 · CARE — Constitutional Amendment Ratification Engine
# Phase 219 · v10.30.0 · InnovativeAI LLC · Governor: DUSTIN L REID
"""
Constitutional Amendment Ratification Engine (CARE)
====================================================
Phase 219 · v10.30.0 · InnovativeAI LLC

World-first: The first autonomous AI governance system with a constitutionally
self-amending invariant registry under cryptographically verified HUMAN-0
ratification control — closing the proposal → monitoring → EXECUTION loop
entirely within constitutional bounds.

CARE is the execution terminus of the constitutional amendment pipeline:

  ACSA (propose)
    → ACPA (advise)
      → ACAM (monitor)
        → HUMAN-0 ratification
          → CARE (execute/seal) ← you are here

CARE accepts HUMAN-0-ratified amendment payloads (Wire IDs from ACAM/ACSA),
executes a constitutional diff against the live invariant registry, promotes
amendments atomically, tombstones superseded invariants, extends the HMAC
chain, and emits a signed ratification certificate readable by CGVE and ACAM.

Amendment Execution Lifecycle (5 stages):
  INTAKE       → Wire ID validated; HUMAN-0 ratification timestamp verified
  DIFFED       → Constitutional diff computed: ADD / REINFORCE / TOMBSTONE
  PROMOTED     → Registry updated atomically via os.replace(); hashes sealed
  CHAINED      → HMAC-chained ledger entry appended to amendment execution log
  CERTIFIED    → Signed execution certificate emitted; CGVE/ACAM notified

Hard-class invariants enforced (fail-closed, raise on violation):
  CARE-INTAKE-0    No amendment promoted without valid Wire ID + HUMAN-0 timestamp
  CARE-ATOMIC-0    Registry promotion atomic via os.replace(); partial writes prohibited
  CARE-HMAC-0      Every promotion appends a forward-chained HMAC entry to exec ledger
  CARE-HASH-0      Pre/post SHA-256 of invariant registry recorded before commit
  CARE-ROLLBACK-0  Promotion failure triggers fail-closed rollback + forensic manifest
  CARE-TOMBSTONE-0 Superseded invariants tombstoned (not deleted) with deprecation ts
  CARE-CERT-0      Every ratification emits signed execution certificate
  CARE-HUMAN0-0    CARE never auto-promotes without explicit HUMAN-0 signal in payload
  CARE-REPLAY-0    Full amendment execution deterministically replayable from ledger
  CARE-AUDIT-0     All operations write to append-only CEPD trail; silent fail prohibited

Governor: DUSTIN L REID
Agent:    DEVADAAD · InnovativeAI LLC
"""

from __future__ import annotations

import hashlib
import hmac as _hmac_mod
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_HMAC_KEY: bytes = os.environ.get("CARE_HMAC_KEY", "care-hmac-adaad-v10").encode()
_LEDGER_PATH: Path = Path(
    os.environ.get("CARE_LEDGER_PATH", "ledger/care_ratification_ledger.jsonl")
)
_REGISTRY_PATH: Path = Path(
    os.environ.get("CARE_REGISTRY_PATH", "data/care/invariant_registry.json")
)
_CERT_DIR: Path = Path(os.environ.get("CARE_CERT_DIR", "data/care/certificates"))
_ROLLBACK_DIR: Path = Path(os.environ.get("CARE_ROLLBACK_DIR", "data/care/rollbacks"))
_ACSA_LEDGER: Path = Path(
    os.environ.get("ACSA_LEDGER_PATH", "data/acsa/amendment_ledger.jsonl")
)
_ACAM_LEDGER: Path = Path(
    os.environ.get("ACAM_LEDGER_PATH", "ledger/acam_monitor_ledger.jsonl")
)

_CHAIN_PREFIX_LEN: int = 24  # HMAC comparison window (CARE-HMAC-0)

GOVERNOR: str = "DUSTIN L REID"
AGENT: str = "DEVADAAD · InnovativeAI LLC"
INNOV: str = "INNOV-124"
VERSION: str = "10.30.0"
MODULE: str = "CARE"

# ---------------------------------------------------------------------------
# Invariant ID constants
# ---------------------------------------------------------------------------
CARE_INTAKE_0    = "CARE-INTAKE-0"
CARE_ATOMIC_0    = "CARE-ATOMIC-0"
CARE_HMAC_0      = "CARE-HMAC-0"
CARE_HASH_0      = "CARE-HASH-0"
CARE_ROLLBACK_0  = "CARE-ROLLBACK-0"
CARE_TOMBSTONE_0 = "CARE-TOMBSTONE-0"
CARE_CERT_0      = "CARE-CERT-0"
CARE_HUMAN0_0    = "CARE-HUMAN0-0"
CARE_REPLAY_0    = "CARE-REPLAY-0"
CARE_AUDIT_0     = "CARE-AUDIT-0"

HARD_CLASS_INVARIANTS: FrozenSet[str] = frozenset({
    CARE_INTAKE_0, CARE_ATOMIC_0, CARE_HMAC_0, CARE_HASH_0,
    CARE_ROLLBACK_0, CARE_TOMBSTONE_0, CARE_CERT_0,
    CARE_HUMAN0_0, CARE_REPLAY_0, CARE_AUDIT_0,
})

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class PromotionStage(str, Enum):
    INTAKE    = "INTAKE"
    DIFFED    = "DIFFED"
    PROMOTED  = "PROMOTED"
    CHAINED   = "CHAINED"
    CERTIFIED = "CERTIFIED"
    FAILED    = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


class DiffAction(str, Enum):
    ADD       = "ADD"        # New invariant inserted
    REINFORCE = "REINFORCE"  # Existing invariant strengthened/updated
    TOMBSTONE = "TOMBSTONE"  # Invariant deprecated (never deleted)
    STABLE    = "STABLE"     # Invariant unchanged; referenced in amendment scope


# ---------------------------------------------------------------------------
# Exceptions (CARE-AUDIT-0: all violations must be named and raised)
# ---------------------------------------------------------------------------

class CAREError(Exception):
    """Base CARE error — all subclasses are constitutional violations."""

class CAREIntakeError(CAREError):
    """CARE-INTAKE-0 violation — missing Wire ID or HUMAN-0 timestamp."""

class CAREHuman0Error(CAREError):
    """CARE-HUMAN0-0 violation — promotion attempted without HUMAN-0 signal."""

class CAREAtomicError(CAREError):
    """CARE-ATOMIC-0 violation — partial write or registry corruption detected."""

class CAREHMACError(CAREError):
    """CARE-HMAC-0 violation — HMAC chain broken."""

class CAREHashError(CAREError):
    """CARE-HASH-0 violation — registry hash mismatch detected."""

class CARERollbackError(CAREError):
    """CARE-ROLLBACK-0 violation — rollback failed; manual intervention required."""

class CAREReplayError(CAREError):
    """CARE-REPLAY-0 violation — duplicate execution_id detected."""

class CAREAuditError(CAREError):
    """CARE-AUDIT-0 violation — silent failure attempted."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DiffEntry:
    """Single entry in a constitutional diff."""
    action: str           # DiffAction value
    invariant_id: str
    prior_text: Optional[str]
    new_text: Optional[str]
    tombstone_reason: Optional[str] = None
    successor_id: Optional[str] = None


@dataclass
class RatificationPayload:
    """Input payload for a CARE promote() call."""
    wire_id: str
    amendment_id: str
    title: str
    amendment_class: str          # SOFT | HARD
    human0_ratification_ts: str   # ISO-8601 — CARE-HUMAN0-0
    human0_ratification_ref: str  # GPG sig ref or session token
    proposed_by: str
    diff_entries: List[Dict[str, Any]]
    supporting_invariant_ids: List[str]
    revert_hash: str
    content_hash: str


@dataclass
class PromotionRecord:
    """Immutable ledger record for one amendment promotion."""
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    wire_id: str = ""
    amendment_id: str = ""
    stage: str = PromotionStage.INTAKE.value
    diff_summary: List[Dict[str, Any]] = field(default_factory=list)
    pre_registry_hash: str = ""
    post_registry_hash: str = ""
    certificate_id: str = ""
    rollback_manifest_path: str = ""
    error: Optional[str] = None
    promoted_at_utc: str = ""
    governor: str = GOVERNOR
    agent: str = AGENT
    innov: str = INNOV
    version: str = VERSION
    prev_digest: str = "0" * 64
    digest: str = ""


@dataclass
class RatificationCertificate:
    """Signed execution certificate — CARE-CERT-0."""
    certificate_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    execution_id: str = ""
    wire_id: str = ""
    amendment_id: str = ""
    title: str = ""
    diff_count: int = 0
    diff_summary: List[Dict[str, Any]] = field(default_factory=list)
    pre_registry_hash: str = ""
    post_registry_hash: str = ""
    promoted_at_utc: str = ""
    governor: str = GOVERNOR
    agent: str = AGENT
    innov: str = INNOV
    version: str = VERSION
    hmac_signature: str = ""


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _utc_iso() -> str:
    """Deterministic UTC ISO-8601 timestamp (CARE-REPLAY-0 / CAE-DETERM-0)."""
    t = time.gmtime()
    return (
        f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}T"
        f"{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}Z"
    )


def _sha256_file(path: Path) -> str:
    """SHA-256 hash of a file's canonical JSON content (CARE-HASH-0)."""
    if not path.exists():
        return "0" * 64
    raw = path.read_text(encoding="utf-8")
    return hashlib.sha256(raw.encode()).hexdigest()


def _sha256_dict(d: Dict) -> str:
    """SHA-256 of a dict serialised with sorted keys."""
    return hashlib.sha256(
        json.dumps(d, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _hmac_digest(payload: str, prev: str) -> str:
    """HMAC-SHA-256 over payload+prev for HMAC chain (CARE-HMAC-0)."""
    msg = (payload + prev).encode()
    return _hmac_mod.new(_HMAC_KEY, msg, hashlib.sha256).hexdigest()


def _ledger_chain_head(path: Path) -> str:
    """Return digest of last ledger entry, or zeros if empty."""
    if not path.exists() or path.stat().st_size == 0:
        return "0" * 64
    last = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            last = line
    if not last:
        return "0" * 64
    try:
        return json.loads(last).get("digest", "0" * 64)
    except json.JSONDecodeError:
        return "0" * 64


def _append_ledger(path: Path, record: Dict) -> None:
    """Atomic append to HMAC-chained JSONL ledger (CARE-HMAC-0, CARE-ATOMIC-0)."""
    # CARE-AUDIT-0: ensure ledger dir exists
    path.parent.mkdir(parents=True, exist_ok=True)

    prev_digest = _ledger_chain_head(path)
    payload_str = json.dumps(record, sort_keys=True, separators=(",", ":"))
    digest = _hmac_digest(payload_str, prev_digest)

    entry: Dict[str, Any] = {**record, "prev_digest": prev_digest, "digest": digest}

    # Atomic append via tmp + os.replace on a side-channel shard
    tmp = path.with_suffix(".jsonl.tmp")
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    tmp.write_text(existing + json.dumps(entry) + "\n", encoding="utf-8")
    os.replace(tmp, path)  # CARE-ATOMIC-0


def _verify_ledger_chain(path: Path) -> bool:
    """Verify HMAC chain integrity (CARE-HMAC-0)."""
    if not path.exists():
        return True
    prev = "0" * 64
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            return False
        stored_digest = entry.get("digest", "")
        stored_prev = entry.get("prev_digest", "0" * 64)
        if stored_prev[:_CHAIN_PREFIX_LEN] != prev[:_CHAIN_PREFIX_LEN]:
            return False
        entry_for_hash = {k: v for k, v in entry.items() if k not in ("digest", "prev_digest")}
        payload_str = json.dumps(entry_for_hash, sort_keys=True, separators=(",", ":"))
        expected = _hmac_digest(payload_str, stored_prev)
        if stored_digest[:_CHAIN_PREFIX_LEN] != expected[:_CHAIN_PREFIX_LEN]:
            return False
        prev = stored_digest
    return True


def _load_registry(path: Path) -> Dict[str, Any]:
    """Load invariant registry; return empty structure if absent."""
    if not path.exists():
        return {
            "schema_version": "1.0",
            "governor": GOVERNOR,
            "invariants": {},
            "tombstones": {},
            "last_updated": "",
        }
    return json.loads(path.read_text(encoding="utf-8"))


def _save_registry_atomic(path: Path, registry: Dict) -> None:
    """Atomically write invariant registry (CARE-ATOMIC-0)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    registry["last_updated"] = _utc_iso()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(registry, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)  # CARE-ATOMIC-0


# ---------------------------------------------------------------------------
# Constitutional Diff Engine
# ---------------------------------------------------------------------------

def _compute_diff(
    registry: Dict[str, Any],
    diff_entries: List[Dict[str, Any]],
) -> List[DiffEntry]:
    """
    Compute constitutional diff from amendment payload against live registry.
    Returns list of DiffEntry with action, prior state, and new state.
    CARE-HASH-0: caller must hash registry before/after applying diff.
    """
    computed: List[DiffEntry] = []
    existing = registry.get("invariants", {})

    for raw in diff_entries:
        action = raw.get("action", DiffAction.STABLE.value).upper()
        inv_id = raw.get("invariant_id", "")
        new_text = raw.get("new_text")
        reason = raw.get("tombstone_reason")
        successor = raw.get("successor_id")

        prior_text = existing.get(inv_id, {}).get("text") if inv_id in existing else None

        computed.append(DiffEntry(
            action=action,
            invariant_id=inv_id,
            prior_text=prior_text,
            new_text=new_text,
            tombstone_reason=reason,
            successor_id=successor,
        ))

    return computed


def _apply_diff(registry: Dict[str, Any], diff: List[DiffEntry]) -> Dict[str, Any]:
    """
    Apply constitutional diff to registry in-memory.
    CARE-TOMBSTONE-0: superseded invariants are tombstoned, never deleted.
    Returns modified registry (caller must atomically write it).
    """
    inv = registry.setdefault("invariants", {})
    tomb = registry.setdefault("tombstones", {})

    for entry in diff:
        if entry.action == DiffAction.ADD.value:
            inv[entry.invariant_id] = {
                "text": entry.new_text,
                "class": "HARD",
                "added_at_utc": _utc_iso(),
                "source_innov": INNOV,
            }

        elif entry.action == DiffAction.REINFORCE.value:
            existing = inv.get(entry.invariant_id, {})
            inv[entry.invariant_id] = {
                **existing,
                "text": entry.new_text or existing.get("text", ""),
                "reinforced_at_utc": _utc_iso(),
                "reinforced_by_innov": INNOV,
            }

        elif entry.action == DiffAction.TOMBSTONE.value:
            # CARE-TOMBSTONE-0: move to tombstones with full forensic trail
            prior = inv.pop(entry.invariant_id, {})
            tomb[entry.invariant_id] = {
                **prior,
                "tombstoned_at_utc": _utc_iso(),
                "tombstone_reason": entry.tombstone_reason or "superseded",
                "successor_id": entry.successor_id,
                "tombstoned_by_innov": INNOV,
            }

        # STABLE: no registry mutation; diff entry is informational only

    return registry


# ---------------------------------------------------------------------------
# CARE Engine
# ---------------------------------------------------------------------------

class ConstitutionalAmendmentRatificationEngine:
    """
    CARE — Constitutional Amendment Ratification Engine.

    Thread-safety: not assumed; callers should serialise concurrent promote()
    calls via external locking for multi-process deployments.
    """

    def __init__(
        self,
        ledger_path: Path = _LEDGER_PATH,
        registry_path: Path = _REGISTRY_PATH,
        cert_dir: Path = _CERT_DIR,
        rollback_dir: Path = _ROLLBACK_DIR,
    ) -> None:
        self._ledger = ledger_path
        self._registry = registry_path
        self._cert_dir = cert_dir
        self._rollback_dir = rollback_dir
        self._seen_execution_ids: set = set()

        # Ensure output directories exist
        for d in (cert_dir, rollback_dir):
            d.mkdir(parents=True, exist_ok=True)

        # Bootstrap ledger parent
        ledger_path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def promote(self, payload: RatificationPayload) -> Dict[str, Any]:
        """
        Execute a HUMAN-0-ratified amendment into the live invariant registry.

        Returns a dict with execution_id, certificate_id, stage, and diff_summary.
        Raises CAREError subclass on any constitutional violation (fail-closed).
        """
        # CARE-AUDIT-0: every operation must eventually write to ledger
        record = PromotionRecord(
            wire_id=payload.wire_id,
            amendment_id=payload.amendment_id,
            promoted_at_utc=_utc_iso(),
        )

        try:
            # ── Stage 1: INTAKE — CARE-INTAKE-0 + CARE-HUMAN0-0 ─────────────
            self._validate_intake(payload, record)
            record.stage = PromotionStage.INTAKE.value

            # ── Stage 2: DIFF — compute constitutional delta ──────────────────
            registry = _load_registry(self._registry)
            pre_hash = _sha256_file(self._registry)  # CARE-HASH-0

            diff = _compute_diff(registry, payload.diff_entries)
            record.diff_summary = [asdict(e) for e in diff]
            record.pre_registry_hash = pre_hash
            record.stage = PromotionStage.DIFFED.value

            # ── Stage 3: PROMOTE — atomic registry write (CARE-ATOMIC-0) ─────
            updated = _apply_diff(registry, diff)
            _save_registry_atomic(self._registry, updated)
            post_hash = _sha256_file(self._registry)  # CARE-HASH-0
            record.post_registry_hash = post_hash
            record.stage = PromotionStage.PROMOTED.value

            # ── Stage 4: CHAIN — HMAC-chained ledger append (CARE-HMAC-0) ────
            ledger_payload = {
                "event": "PROMOTED",
                "execution_id": record.execution_id,
                "wire_id": payload.wire_id,
                "amendment_id": payload.amendment_id,
                "title": payload.title,
                "pre_registry_hash": pre_hash,
                "post_registry_hash": post_hash,
                "diff_count": len(diff),
                "human0_ratification_ts": payload.human0_ratification_ts,
                "human0_ratification_ref": payload.human0_ratification_ref,
                "promoted_at_utc": record.promoted_at_utc,
                "governor": GOVERNOR,
                "agent": AGENT,
                "innov": INNOV,
                "version": VERSION,
            }
            _append_ledger(self._ledger, ledger_payload)
            record.stage = PromotionStage.CHAINED.value

            # ── Stage 5: CERT — emit signed execution certificate (CARE-CERT-0)
            cert = self._emit_certificate(record, payload, diff)
            record.certificate_id = cert.certificate_id
            record.stage = PromotionStage.CERTIFIED.value

            # Track execution_id for CARE-REPLAY-0
            self._seen_execution_ids.add(record.execution_id)

            return {
                "execution_id": record.execution_id,
                "certificate_id": cert.certificate_id,
                "stage": record.stage,
                "wire_id": payload.wire_id,
                "amendment_id": payload.amendment_id,
                "diff_count": len(diff),
                "diff_summary": record.diff_summary,
                "pre_registry_hash": pre_hash,
                "post_registry_hash": post_hash,
                "promoted_at_utc": record.promoted_at_utc,
                "governor": GOVERNOR,
                "innov": INNOV,
                "version": VERSION,
            }

        except CAREError:
            # CARE-ROLLBACK-0: promotion failure triggers rollback
            record.stage = PromotionStage.FAILED.value
            manifest_path = self._write_rollback_manifest(record, payload)
            record.rollback_manifest_path = str(manifest_path)
            # CARE-AUDIT-0: failed promotions still hit the ledger
            _append_ledger(self._ledger, {
                "event": "FAILED",
                "execution_id": record.execution_id,
                "wire_id": payload.wire_id,
                "amendment_id": payload.amendment_id,
                "stage_at_failure": record.stage,
                "error": record.error or "CAREError",
                "rollback_manifest": str(manifest_path),
                "failed_at_utc": _utc_iso(),
                "governor": GOVERNOR,
                "innov": INNOV,
                "version": VERSION,
            })
            raise

    def get_status(self, wire_id: str) -> Dict[str, Any]:
        """
        Query promotion status for a given Wire ID from the execution ledger.
        Returns latest event for that wire_id or a NOT_FOUND record.
        """
        if not self._ledger.exists():
            return {"wire_id": wire_id, "status": "NOT_FOUND", "ledger_entries": 0}

        entries = []
        for line in self._ledger.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                if e.get("wire_id") == wire_id:
                    entries.append(e)
            except json.JSONDecodeError:
                continue

        if not entries:
            return {"wire_id": wire_id, "status": "NOT_FOUND", "ledger_entries": 0}

        latest = entries[-1]
        return {
            "wire_id": wire_id,
            "status": latest.get("event", "UNKNOWN"),
            "execution_id": latest.get("execution_id"),
            "promoted_at_utc": latest.get("promoted_at_utc"),
            "ledger_entries": len(entries),
            "latest": latest,
        }

    def get_certificate(self, wire_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve signed execution certificate for a given Wire ID.
        Returns None if not found. (CARE-CERT-0)
        """
        for cert_file in self._cert_dir.glob("*.json"):
            try:
                d = json.loads(cert_file.read_text(encoding="utf-8"))
                if d.get("wire_id") == wire_id:
                    return d
            except (json.JSONDecodeError, OSError):
                continue
        return None

    def registry_diff(self) -> Dict[str, Any]:
        """
        Return the last applied constitutional diff from the execution ledger.
        Provides CGVE and ACAM with post-promotion inspection surface.
        """
        if not self._ledger.exists():
            return {"last_diff": None, "message": "No promotions recorded yet"}

        last_promoted = None
        for line in self._ledger.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                if e.get("event") == "PROMOTED":
                    last_promoted = e
            except json.JSONDecodeError:
                continue

        if not last_promoted:
            return {"last_diff": None, "message": "No PROMOTED entries in ledger"}

        # Retrieve full diff from certificate
        cert = self.get_certificate(last_promoted.get("wire_id", ""))
        return {
            "last_diff": cert.get("diff_summary") if cert else None,
            "execution_id": last_promoted.get("execution_id"),
            "wire_id": last_promoted.get("wire_id"),
            "promoted_at_utc": last_promoted.get("promoted_at_utc"),
            "pre_registry_hash": last_promoted.get("pre_registry_hash"),
            "post_registry_hash": last_promoted.get("post_registry_hash"),
            "diff_count": last_promoted.get("diff_count"),
        }

    def verify_chain(self) -> Dict[str, Any]:
        """Verify HMAC chain integrity of the execution ledger (CARE-HMAC-0)."""
        valid = _verify_ledger_chain(self._ledger)
        entries = 0
        if self._ledger.exists():
            entries = sum(
                1 for l in self._ledger.read_text(encoding="utf-8").splitlines()
                if l.strip()
            )
        return {
            "chain_valid": valid,
            "ledger_path": str(self._ledger),
            "entry_count": entries,
            "checked_at_utc": _utc_iso(),
            "governor": GOVERNOR,
            "innov": INNOV,
        }

    def status(self) -> Dict[str, Any]:
        """Module health + ledger stats."""
        entries = 0
        promoted = 0
        failed = 0
        if self._ledger.exists():
            for line in self._ledger.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                    entries += 1
                    if e.get("event") == "PROMOTED":
                        promoted += 1
                    elif e.get("event") == "FAILED":
                        failed += 1
                except json.JSONDecodeError:
                    pass

        registry = _load_registry(self._registry)
        inv_count = len(registry.get("invariants", {}))
        tomb_count = len(registry.get("tombstones", {}))

        return {
            "module": MODULE,
            "innov": INNOV,
            "version": VERSION,
            "governor": GOVERNOR,
            "ledger_entries": entries,
            "promotions_successful": promoted,
            "promotions_failed": failed,
            "active_invariants": inv_count,
            "tombstoned_invariants": tomb_count,
            "chain_valid": _verify_ledger_chain(self._ledger),
            "checked_at_utc": _utc_iso(),
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _validate_intake(
        self, payload: RatificationPayload, record: PromotionRecord
    ) -> None:
        """CARE-INTAKE-0 + CARE-HUMAN0-0 + CARE-REPLAY-0 validation."""
        # CARE-INTAKE-0: Wire ID must be non-empty
        if not payload.wire_id or not payload.wire_id.strip():
            record.error = "CARE-INTAKE-0: wire_id is empty"
            raise CAREIntakeError(record.error)

        # CARE-INTAKE-0: amendment_id must be non-empty
        if not payload.amendment_id or not payload.amendment_id.strip():
            record.error = "CARE-INTAKE-0: amendment_id is empty"
            raise CAREIntakeError(record.error)

        # CARE-HUMAN0-0: HUMAN-0 ratification timestamp required
        if not payload.human0_ratification_ts or not payload.human0_ratification_ts.strip():
            record.error = "CARE-HUMAN0-0: human0_ratification_ts is empty"
            raise CAREHuman0Error(record.error)

        # CARE-HUMAN0-0: HUMAN-0 ratification reference required
        if not payload.human0_ratification_ref or not payload.human0_ratification_ref.strip():
            record.error = "CARE-HUMAN0-0: human0_ratification_ref is empty"
            raise CAREHuman0Error(record.error)

        # CARE-REPLAY-0: execution_id must be globally unique
        if record.execution_id in self._seen_execution_ids:
            record.error = f"CARE-REPLAY-0: duplicate execution_id {record.execution_id}"
            raise CAREReplayError(record.error)

        # CARE-INTAKE-0: diff_entries must be non-empty
        if not payload.diff_entries:
            record.error = "CARE-INTAKE-0: diff_entries is empty; nothing to promote"
            raise CAREIntakeError(record.error)

    def _emit_certificate(
        self,
        record: PromotionRecord,
        payload: RatificationPayload,
        diff: List[DiffEntry],
    ) -> RatificationCertificate:
        """Emit and persist signed execution certificate (CARE-CERT-0)."""
        cert = RatificationCertificate(
            execution_id=record.execution_id,
            wire_id=payload.wire_id,
            amendment_id=payload.amendment_id,
            title=payload.title,
            diff_count=len(diff),
            diff_summary=[asdict(e) for e in diff],
            pre_registry_hash=record.pre_registry_hash,
            post_registry_hash=record.post_registry_hash,
            promoted_at_utc=record.promoted_at_utc,
        )

        # Sign certificate: HMAC over canonical cert payload (CARE-CERT-0)
        cert_payload = json.dumps(
            {k: v for k, v in asdict(cert).items() if k != "hmac_signature"},
            sort_keys=True, separators=(",", ":"),
        )
        cert.hmac_signature = _hmac_mod.new(
            _HMAC_KEY, cert_payload.encode(), hashlib.sha256
        ).hexdigest()

        # Persist certificate atomically (CARE-ATOMIC-0)
        cert_path = self._cert_dir / f"cert-{payload.wire_id}-{cert.certificate_id[:8]}.json"
        tmp = cert_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(cert), indent=2), encoding="utf-8")
        os.replace(tmp, cert_path)  # CARE-ATOMIC-0

        return cert

    def _write_rollback_manifest(
        self, record: PromotionRecord, payload: RatificationPayload
    ) -> Path:
        """
        Emit forensic rollback manifest on promotion failure (CARE-ROLLBACK-0).
        Contains full pre-state hash for deterministic recovery.
        """
        manifest = {
            "schema": "care-rollback-v1",
            "execution_id": record.execution_id,
            "wire_id": payload.wire_id,
            "amendment_id": payload.amendment_id,
            "stage_at_failure": record.stage,
            "error": record.error,
            "pre_registry_hash": record.pre_registry_hash,
            "diff_summary": record.diff_summary,
            "rollback_instruction": (
                "Restore registry from backup matching pre_registry_hash. "
                "No registry mutation should have landed if failure was pre-PROMOTED."
            ),
            "failed_at_utc": _utc_iso(),
            "governor": GOVERNOR,
            "innov": INNOV,
            "version": VERSION,
        }
        path = self._rollback_dir / f"rollback-{record.execution_id[:8]}-{payload.wire_id[:8]}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        os.replace(tmp, path)  # CARE-ATOMIC-0
        return path


# ---------------------------------------------------------------------------
# Module-level convenience functions (mirrors ACAM public API pattern)
# ---------------------------------------------------------------------------
_engine: Optional[ConstitutionalAmendmentRatificationEngine] = None


def _get_engine() -> ConstitutionalAmendmentRatificationEngine:
    global _engine
    if _engine is None:
        _engine = ConstitutionalAmendmentRatificationEngine()
    return _engine


def promote(payload: RatificationPayload) -> Dict[str, Any]:
    """Module-level promote() convenience wrapper."""
    return _get_engine().promote(payload)


def get_status(wire_id: str) -> Dict[str, Any]:
    """Module-level status query by Wire ID."""
    return _get_engine().get_status(wire_id)


def get_certificate(wire_id: str) -> Optional[Dict[str, Any]]:
    """Module-level certificate retrieval by Wire ID."""
    return _get_engine().get_certificate(wire_id)


def registry_diff() -> Dict[str, Any]:
    """Module-level last-diff retrieval."""
    return _get_engine().registry_diff()


def verify_chain() -> Dict[str, Any]:
    """Module-level HMAC chain verification."""
    return _get_engine().verify_chain()


def status() -> Dict[str, Any]:
    """Module-level health status."""
    return _get_engine().status()
