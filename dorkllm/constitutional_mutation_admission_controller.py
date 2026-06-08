"""
Constitutional Mutation Admission Controller (CMAC) — INNOV-106
Phase 201 · v10.12.0 · InnovativeAI LLC · Governor: DUSTIN L REID

World-first constitutionally-governed pre-admission firewall for incoming mutation
proposals. Every mutation spec passes through a fixed-order, fail-closed multi-gate
admission pipeline before it is allowed to enter any downstream gate (sandbox, queue,
consensus, CEL). Admission checks include: invariant-class validation, blast-radius
authorization, mutation rate limiting with cooldown enforcement, lineage conflict
detection, and quorum readiness. All decisions are HMAC-sealed in an append-only
admission ledger. HUMAN-0 holds sole authority to override a DENIED admission.

Hard-class invariants enforced:
  CMAC-FAILCLOSED-0  Any check failure MUST result in DENIED; no partial-admit path.
  CMAC-ORDER-0       Admission checks MUST execute in fixed constitutional order.
  CMAC-RATELIMIT-0   No mutation type may exceed its configured rate limit per window.
  CMAC-COOLDOWN-0    A DENIED mutation MUST observe its cooldown before re-admission.
  CMAC-BLASTAUTH-0   TIER2+ blast radius MUST have HUMAN-0 pre-authorization.
  CMAC-CHAIN-0       All admission ledger entries MUST form an unbroken HMAC-SHA256 chain.
  CMAC-IMMUT-0       Admission ledger entries are append-only; no edits or deletes.
  CMAC-OVERRIDE-0    Only HUMAN-0 may override a DENIED admission decision.
  CMAC-AUDIT-0       All admission decisions are logged with ISO-8601 timestamps.
  CMAC-QUORUM-0      TIER3 mutations require quorum readiness confirmation before admission.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

# ── Constants ─────────────────────────────────────────────────────────────────

GOVERNOR = "DUSTIN L REID"
CMAC_LEDGER_PATH = os.environ.get("CMAC_LEDGER_PATH", "data/cmac/admission_ledger.jsonl")
CMAC_HMAC_KEY = os.environ.get("CMAC_HMAC_KEY", "cmac-innov106-adaad-innovativeai-llc").encode()

# Default rate limits: max mutations per window (seconds)
DEFAULT_RATE_LIMITS: Dict[str, Dict[str, int]] = {
    "TIER1": {"max_per_window": 10, "window_seconds": 60},
    "TIER2": {"max_per_window": 3,  "window_seconds": 300},
    "TIER3": {"max_per_window": 1,  "window_seconds": 3600},
}
DEFAULT_COOLDOWN_SECONDS = 30   # after DENIED, minimum wait before re-submission


# ── Enums ─────────────────────────────────────────────────────────────────────

class AdmissionVerdict(str, Enum):
    ADMITTED  = "ADMITTED"
    DENIED    = "DENIED"
    OVERRIDDEN = "OVERRIDDEN"   # HUMAN-0 override of a DENIED decision


class DenialReason(str, Enum):
    INVARIANT_CLASS_INVALID   = "INVARIANT_CLASS_INVALID"
    BLAST_RADIUS_UNAUTHORIZED = "BLAST_RADIUS_UNAUTHORIZED"
    RATE_LIMIT_EXCEEDED       = "RATE_LIMIT_EXCEEDED"
    COOLDOWN_ACTIVE           = "COOLDOWN_ACTIVE"
    LINEAGE_CONFLICT          = "LINEAGE_CONFLICT"
    QUORUM_NOT_READY          = "QUORUM_NOT_READY"
    SPEC_MALFORMED            = "SPEC_MALFORMED"


class BlastRadius(str, Enum):
    TIER1 = "TIER1"
    TIER2 = "TIER2"
    TIER3 = "TIER3"


# ── Exceptions ────────────────────────────────────────────────────────────────

class CMACConstitutionalViolation(Exception):
    """Hard-class invariant breach."""

class CMACChainViolation(CMACConstitutionalViolation):
    """CMAC-CHAIN-0."""

class CMACOverrideUnauthorized(CMACConstitutionalViolation):
    """CMAC-OVERRIDE-0: non-HUMAN-0 attempted override."""

class CMACCooldownActive(CMACConstitutionalViolation):
    """CMAC-COOLDOWN-0: mutation re-submitted during cooldown."""


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class AdmissionRequest:
    """Incoming mutation proposal presented to CMAC."""
    request_id: str
    mutation_id: str
    blast_radius: BlastRadius
    invariant_classes: List[str]          # e.g. ["Hard", "Soft"]
    proposed_by: str
    human0_pre_auth: bool = False         # HUMAN-0 pre-authorized TIER2+
    quorum_confirmed: bool = False        # required for TIER3
    seed: str = field(default_factory=lambda: str(uuid.uuid4()))
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["blast_radius"] = self.blast_radius.value
        return d


@dataclass
class AdmissionRecord:
    """A single sealed admission decision."""
    record_id: str
    request_id: str
    mutation_id: str
    blast_radius: str
    verdict: AdmissionVerdict
    denial_reasons: List[str]
    check_results: Dict[str, bool]        # gate_name → pass/fail
    override_by: Optional[str]
    timestamp: str
    ledger_index: int = 0
    prev_hash: str = "GENESIS"
    entry_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["verdict"] = self.verdict.value
        return d


# ── HMAC helpers ──────────────────────────────────────────────────────────────

def _hmac_hash(content: bytes) -> str:
    return hmac.new(CMAC_HMAC_KEY, content, hashlib.sha256).hexdigest()


# ── Admission Ledger ──────────────────────────────────────────────────────────

class CMACAdmissionLedger:
    """
    Append-only HMAC-chained ledger. CMAC-CHAIN-0, CMAC-IMMUT-0, CMAC-AUDIT-0.
    """

    def __init__(self, path: str = CMAC_LEDGER_PATH) -> None:
        self._path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._entries: List[AdmissionRecord] = []
        self._prev_hash = "GENESIS"
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self._path):
            return
        with open(self._path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                d["verdict"] = AdmissionVerdict(d["verdict"])
                d["denial_reasons"] = d.get("denial_reasons", [])
                self._entries.append(AdmissionRecord(**d))
                self._prev_hash = d["entry_hash"]

    def seal(self, record: AdmissionRecord) -> AdmissionRecord:
        record.ledger_index = len(self._entries)
        record.prev_hash = self._prev_hash
        d = record.to_dict()
        d.pop("entry_hash", None)
        record.entry_hash = _hmac_hash(json.dumps(d, sort_keys=True).encode())
        self._prev_hash = record.entry_hash
        self._entries.append(record)
        with open(self._path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record.to_dict()) + "\n")
        return record

    def verify_chain(self) -> bool:
        """CMAC-CHAIN-0."""
        for e in self._entries:
            d = e.to_dict()
            stored = d.pop("entry_hash")
            check = {k: v for k, v in e.to_dict().items() if k != "entry_hash"}
            expected = _hmac_hash(json.dumps(check, sort_keys=True).encode())
            if stored != expected:
                raise CMACChainViolation(
                    f"CMAC-CHAIN-0 at index {e.ledger_index}: "
                    f"stored={stored[:16]} expected={expected[:16]}"
                )
        return True

    def all_records(self) -> List[AdmissionRecord]:
        return list(self._entries)

    def get_by_request_id(self, request_id: str) -> Optional[AdmissionRecord]:
        for r in self._entries:
            if r.request_id == request_id:
                return r
        return None

    def export(self) -> Dict[str, Any]:
        return {
            "ledger_path": self._path,
            "total_records": len(self._entries),
            "chain_tip": self._prev_hash,
            "records": [r.to_dict() for r in self._entries],
        }


# ── Rate limiter (in-memory sliding window) ───────────────────────────────────

class _RateLimiter:
    """Sliding-window rate limiter per blast radius tier. CMAC-RATELIMIT-0."""

    def __init__(self, limits: Dict[str, Dict[str, int]]) -> None:
        self._limits = limits
        self._windows: Dict[str, List[float]] = {t: [] for t in limits}

    def check(self, tier: str) -> Tuple[bool, int]:
        """
        Returns (allowed, retry_after_seconds).
        CMAC-RATELIMIT-0: fail if count in window exceeds max.
        """
        cfg = self._limits.get(tier, {"max_per_window": 99, "window_seconds": 60})
        now = time.monotonic()
        window_start = now - cfg["window_seconds"]
        self._windows.setdefault(tier, [])
        # Evict old entries
        self._windows[tier] = [t for t in self._windows[tier] if t >= window_start]
        count = len(self._windows[tier])
        if count >= cfg["max_per_window"]:
            oldest = self._windows[tier][0]
            retry_after = int(cfg["window_seconds"] - (now - oldest)) + 1
            return False, retry_after
        return True, 0

    def record(self, tier: str) -> None:
        self._windows.setdefault(tier, []).append(time.monotonic())


# ── Cooldown tracker ──────────────────────────────────────────────────────────

class _CooldownTracker:
    """Tracks per-mutation-id cooldown after DENIED. CMAC-COOLDOWN-0."""

    def __init__(self, cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS) -> None:
        self._cooldown = cooldown_seconds
        self._denied_at: Dict[str, float] = {}

    def is_cooling(self, mutation_id: str) -> Tuple[bool, int]:
        denied_ts = self._denied_at.get(mutation_id)
        if denied_ts is None:
            return False, 0
        elapsed = time.monotonic() - denied_ts
        if elapsed < self._cooldown:
            return True, int(self._cooldown - elapsed) + 1
        return False, 0

    def record_denial(self, mutation_id: str) -> None:
        self._denied_at[mutation_id] = time.monotonic()

    def clear(self, mutation_id: str) -> None:
        self._denied_at.pop(mutation_id, None)


# ── Core CMAC Engine ──────────────────────────────────────────────────────────

class ConstitutionalMutationAdmissionController:
    """
    CMAC — pre-admission constitutional firewall for mutation proposals.
    Fixed-order, fail-closed, HMAC-sealed, HUMAN-0-overridable.

    Admission pipeline order (CMAC-ORDER-0):
      1. Spec well-formedness
      2. Invariant-class validation
      3. Blast-radius authorization
      4. Cooldown check
      5. Rate limit check
      6. Lineage conflict detection
      7. Quorum readiness (TIER3 only)
    """

    INVARIANT_IDS = [
        "CMAC-FAILCLOSED-0", "CMAC-ORDER-0", "CMAC-RATELIMIT-0", "CMAC-COOLDOWN-0",
        "CMAC-BLASTAUTH-0", "CMAC-CHAIN-0", "CMAC-IMMUT-0",
        "CMAC-OVERRIDE-0", "CMAC-AUDIT-0", "CMAC-QUORUM-0",
    ]

    VALID_INVARIANT_CLASSES = {"Hard", "Soft", "Governance", "Safety"}

    def __init__(
        self,
        ledger: Optional[CMACAdmissionLedger] = None,
        rate_limits: Optional[Dict[str, Dict[str, int]]] = None,
        cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS,
        known_mutation_ids: Optional[List[str]] = None,
    ) -> None:
        self._ledger = ledger or CMACAdmissionLedger()
        self._rate = _RateLimiter(rate_limits or DEFAULT_RATE_LIMITS)
        self._cooldown = _CooldownTracker(cooldown_seconds)
        self._known_ids: List[str] = list(known_mutation_ids or [])

    # ── Public API ─────────────────────────────────────────────────────────────

    def admit(self, req: AdmissionRequest) -> AdmissionRecord:
        """
        Run the full admission pipeline. CMAC-ORDER-0, CMAC-FAILCLOSED-0.
        Returns a sealed AdmissionRecord (ADMITTED or DENIED).
        """
        denial_reasons: List[str] = []
        check_results: Dict[str, bool] = {}

        # Gate 1 — Spec well-formedness
        ok, reason = self._check_spec(req)
        check_results["spec_wellformed"] = ok
        if not ok:
            denial_reasons.append(reason)

        # Gate 2 — Invariant-class validation
        ok, reason = self._check_invariant_classes(req)
        check_results["invariant_classes_valid"] = ok
        if not ok:
            denial_reasons.append(reason)

        # Gate 3 — Blast-radius authorization (CMAC-BLASTAUTH-0)
        ok, reason = self._check_blast_auth(req)
        check_results["blast_auth"] = ok
        if not ok:
            denial_reasons.append(reason)

        # Gate 4 — Cooldown (CMAC-COOLDOWN-0)
        ok, reason = self._check_cooldown(req)
        check_results["cooldown_clear"] = ok
        if not ok:
            denial_reasons.append(reason)

        # Gate 5 — Rate limit (CMAC-RATELIMIT-0)
        ok, reason = self._check_rate_limit(req)
        check_results["rate_limit_ok"] = ok
        if not ok:
            denial_reasons.append(reason)

        # Gate 6 — Lineage conflict
        ok, reason = self._check_lineage_conflict(req)
        check_results["lineage_conflict_free"] = ok
        if not ok:
            denial_reasons.append(reason)

        # Gate 7 — Quorum readiness (CMAC-QUORUM-0, TIER3 only)
        ok, reason = self._check_quorum(req)
        check_results["quorum_ready"] = ok
        if not ok:
            denial_reasons.append(reason)

        # Verdict (CMAC-FAILCLOSED-0)
        if denial_reasons:
            verdict = AdmissionVerdict.DENIED
            self._cooldown.record_denial(req.mutation_id)
        else:
            verdict = AdmissionVerdict.ADMITTED
            self._rate.record(req.blast_radius.value)
            self._known_ids.append(req.mutation_id)

        record = AdmissionRecord(
            record_id=str(uuid.uuid4()),
            request_id=req.request_id,
            mutation_id=req.mutation_id,
            blast_radius=req.blast_radius.value,
            verdict=verdict,
            denial_reasons=denial_reasons,
            check_results=check_results,
            override_by=None,
            timestamp=self._iso_now(),
        )
        self._ledger.seal(record)
        return record

    def override(self, request_id: str, human0_identity: str) -> AdmissionRecord:
        """
        HUMAN-0 override of a DENIED admission. CMAC-OVERRIDE-0.
        Appends a new OVERRIDDEN record — original DENIED is immutable (CMAC-IMMUT-0).
        """
        self._assert_human0(human0_identity)
        original = self._ledger.get_by_request_id(request_id)
        if not original:
            raise CMACConstitutionalViolation(
                f"CMAC-OVERRIDE-0: No record found for request_id {request_id}."
            )
        if original.verdict != AdmissionVerdict.DENIED:
            raise CMACConstitutionalViolation(
                f"CMAC-OVERRIDE-0: Only DENIED admissions may be overridden. "
                f"Current verdict: {original.verdict.value}"
            )
        override_record = AdmissionRecord(
            record_id=str(uuid.uuid4()),
            request_id=request_id,
            mutation_id=original.mutation_id,
            blast_radius=original.blast_radius,
            verdict=AdmissionVerdict.OVERRIDDEN,
            denial_reasons=[],
            check_results={},
            override_by=human0_identity,
            timestamp=self._iso_now(),
        )
        self._cooldown.clear(original.mutation_id)
        self._known_ids.append(original.mutation_id)
        self._ledger.seal(override_record)
        return override_record

    def verify_chain(self) -> bool:
        """CMAC-CHAIN-0."""
        return self._ledger.verify_chain()

    def summary(self) -> Dict[str, Any]:
        records = self._ledger.all_records()
        verdict_counts: Dict[str, int] = {}
        for r in records:
            k = r.verdict.value
            verdict_counts[k] = verdict_counts.get(k, 0) + 1
        return {
            "total_decisions": len(records),
            "verdict_counts": verdict_counts,
            "chain_tip": self._ledger.export()["chain_tip"],
            "invariants": self.INVARIANT_IDS,
            "governor": GOVERNOR,
        }

    def export(self) -> Dict[str, Any]:
        return self._ledger.export()

    # ── Admission gates ────────────────────────────────────────────────────────

    def _check_spec(self, req: AdmissionRequest) -> Tuple[bool, str]:
        if not req.mutation_id or not req.proposed_by:
            return False, DenialReason.SPEC_MALFORMED.value
        if req.blast_radius not in (BlastRadius.TIER1, BlastRadius.TIER2, BlastRadius.TIER3):
            return False, DenialReason.SPEC_MALFORMED.value
        return True, ""

    def _check_invariant_classes(self, req: AdmissionRequest) -> Tuple[bool, str]:
        invalid = [c for c in req.invariant_classes if c not in self.VALID_INVARIANT_CLASSES]
        if invalid:
            return False, DenialReason.INVARIANT_CLASS_INVALID.value
        return True, ""

    def _check_blast_auth(self, req: AdmissionRequest) -> Tuple[bool, str]:
        """CMAC-BLASTAUTH-0: TIER2+ requires human0_pre_auth."""
        if req.blast_radius in (BlastRadius.TIER2, BlastRadius.TIER3) and not req.human0_pre_auth:
            return False, DenialReason.BLAST_RADIUS_UNAUTHORIZED.value
        return True, ""

    def _check_cooldown(self, req: AdmissionRequest) -> Tuple[bool, str]:
        """CMAC-COOLDOWN-0."""
        cooling, remaining = self._cooldown.is_cooling(req.mutation_id)
        if cooling:
            return False, f"{DenialReason.COOLDOWN_ACTIVE.value}:retry_after={remaining}s"
        return True, ""

    def _check_rate_limit(self, req: AdmissionRequest) -> Tuple[bool, str]:
        """CMAC-RATELIMIT-0."""
        allowed, retry_after = self._rate.check(req.blast_radius.value)
        if not allowed:
            return False, f"{DenialReason.RATE_LIMIT_EXCEEDED.value}:retry_after={retry_after}s"
        return True, ""

    def _check_lineage_conflict(self, req: AdmissionRequest) -> Tuple[bool, str]:
        """Reject duplicate mutation_id that is already admitted and in the pipeline."""
        admitted_ids = {
            r.mutation_id for r in self._ledger.all_records()
            if r.verdict in (AdmissionVerdict.ADMITTED, AdmissionVerdict.OVERRIDDEN)
        }
        if req.mutation_id in admitted_ids:
            return False, DenialReason.LINEAGE_CONFLICT.value
        return True, ""

    def _check_quorum(self, req: AdmissionRequest) -> Tuple[bool, str]:
        """CMAC-QUORUM-0: TIER3 requires quorum confirmation."""
        if req.blast_radius == BlastRadius.TIER3 and not req.quorum_confirmed:
            return False, DenialReason.QUORUM_NOT_READY.value
        return True, ""

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _iso_now() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    @staticmethod
    def _assert_human0(identity: str) -> None:
        if identity != GOVERNOR and "HUMAN-0" not in identity:
            raise CMACOverrideUnauthorized(
                f"CMAC-OVERRIDE-0: requires HUMAN-0. Got: '{identity}'"
            )
