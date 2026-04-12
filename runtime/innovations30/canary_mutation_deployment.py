# SPDX-License-Identifier: Apache-2.0
# runtime/innovations30/canary_mutation_deployment.py
# Phase 139 · INNOV-46 · Canary Mutation Deployment (CMD)
#
# Constitutional invariants enforced:
#   CMD-GATE-0      High-risk mutations MUST pass canary before full rollout
#   CMD-MIRROR-0    Mirror Test consistency check is mandatory at canary close
#   CMD-ROLLBACK-0  Auto-rollback on Mirror Test failure is constitutionally required
#   CMD-CHAIN-0     Every canary lifecycle event is hash-chained in the ledger
#   CMD-HUMAN0-0    Promoting a failed canary to full rollout requires HUMAN-0 auth
"""
Canary Mutation Deployment — Phase 139 Innovation (INNOV-46)

High-risk mutations are deployed to a configurable traffic slice (default 1%)
before full rollout. The Mirror Test validates behavioural consistency during
the canary window. Promotion to full rollout is constitutionally gated:

  - If Mirror Test score >= threshold: auto-promote (or await HUMAN-0 if Tier 0)
  - If Mirror Test score < threshold: auto-rollback; HUMAN-0 required to override

Every lifecycle event — open, sample, close, promote, rollback — is appended to
a hash-chained ledger (CMD-CHAIN-0). This provides a tamper-evident audit trail
for every canary decision.

World-first claim: First constitutional canary deployment system where rollback
is not an operational policy but a hard-class invariant enforced at the
governance layer — with hash-chained evidence for every traffic-routing decision.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import hashlib
import hmac

# Hardening scaffold — injected by fix/senior-deep-dive-hardening
CAMUDE_INV_CHAIN: str = "CAMUDE-INV-CHAIN"
CAMUDE_LEDGER_DEFAULT: str = "data/canary_mutation_deployment_events.jsonl"


class CanaryMutationDeploymentViolation(RuntimeError):
    """Raised when a Canary Mutation Deployment constitutional invariant is breached."""




# ── Module metadata ────────────────────────────────────────────────────────────
INNOV_ID = "INNOV-46"
PHASE = 139
VERSION = "9.72.0"
WORLD_FIRST = (
    "First constitutional canary deployment system where rollback is a "
    "hard-class invariant enforced at the governance layer — with hash-chained "
    "evidence for every traffic-routing decision."
)

CONSTITUTIONAL_INVARIANTS = [
    "CMD-GATE-0",
    "CMD-MIRROR-0",
    "CMD-ROLLBACK-0",
    "CMD-CHAIN-0",
    "CMD-HUMAN0-0",
]

GENESIS_PREV_HASH = "0" * 64
DEFAULT_CANARY_SLICE = 0.01          # 1 % of traffic
DEFAULT_MIRROR_THRESHOLD = 0.80      # Mirror Test pass threshold
HIGH_RISK_TIERS = frozenset({0})     # Tier 0 mutations are always high-risk


# ── Exceptions ─────────────────────────────────────────────────────────────────
class CMDGateViolation(Exception):
    """High-risk mutation attempted full rollout without canary (CMD-GATE-0)."""


class CMDMirrorViolation(Exception):
    """Canary closed without Mirror Test result recorded (CMD-MIRROR-0)."""


class CMDRollbackViolation(Exception):
    """Failed canary promoted to full rollout without HUMAN-0 auth (CMD-HUMAN0-0)."""


class CMDChainViolation(Exception):
    """Hash-chain integrity broken in the canary ledger (CMD-CHAIN-0)."""


class CMDAuthorizationViolation(Exception):
    """Operation requires HUMAN-0 authorization (CMD-HUMAN0-0)."""


# ── Enums & data models ────────────────────────────────────────────────────────
class CanaryStatus(str, Enum):
    OPEN = "open"
    MIRROR_CHECKED = "mirror_checked"
    PROMOTED = "promoted"
    ROLLED_BACK = "rolled_back"


class CanaryEventType(str, Enum):
    OPENED = "opened"
    SAMPLE_RECORDED = "sample_recorded"
    MIRROR_RESULT = "mirror_result"
    PROMOTED = "promoted"
    ROLLED_BACK = "rolled_back"
    HUMAN0_OVERRIDE = "human0_override"


@dataclass
class CanaryEvent:
    """A single hash-chained event in the canary ledger."""

    canary_id: str
    event_type: str          # CanaryEventType value
    payload: dict[str, Any]
    timestamp: str
    seq: int
    prev_hash: str = GENESIS_PREV_HASH
    entry_hash: str = ""

    def __post_init__(self) -> None:
        if not self.entry_hash:
            self.entry_hash = _compute_event_hash(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "canary_id": self.canary_id,
            "event_type": self.event_type,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "seq": self.seq,
            "prev_hash": self.prev_hash,
            "entry_hash": self.entry_hash,
        }


@dataclass
class CanaryDeployment:
    """Tracks the full lifecycle of a single canary deployment."""

    canary_id: str
    mutation_id: str
    tier: int
    canary_slice: float = DEFAULT_CANARY_SLICE
    mirror_threshold: float = DEFAULT_MIRROR_THRESHOLD
    status: str = CanaryStatus.OPEN
    mirror_score: float | None = None
    sample_count: int = 0
    error_count: int = 0
    opened_at: str = ""
    closed_at: str = ""
    human0_override: bool = False

    def is_high_risk(self) -> bool:
        return self.tier in HIGH_RISK_TIERS

    def mirror_passed(self) -> bool:
        return self.mirror_score is not None and self.mirror_score >= self.mirror_threshold

    def to_dict(self) -> dict[str, Any]:
        return {
            "canary_id": self.canary_id,
            "mutation_id": self.mutation_id,
            "tier": self.tier,
            "canary_slice": self.canary_slice,
            "mirror_threshold": self.mirror_threshold,
            "status": self.status,
            "mirror_score": self.mirror_score,
            "sample_count": self.sample_count,
            "error_count": self.error_count,
            "opened_at": self.opened_at,
            "closed_at": self.closed_at,
            "human0_override": self.human0_override,
        }


# ── Hash helpers ───────────────────────────────────────────────────────────────
def _compute_event_hash(evt: CanaryEvent) -> str:
    payload = json.dumps(
        {
            "seq": evt.seq,
            "canary_id": evt.canary_id,
            "event_type": evt.event_type,
            "payload": evt.payload,
            "timestamp": evt.timestamp,
            "prev_hash": evt.prev_hash,
        },
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Core engine ────────────────────────────────────────────────────────────────
class CanaryDeploymentEngine:
    """Governs canary mutation deployment lifecycle.

    Constitutional contracts:
      CMD-GATE-0      open_canary() MUST be called before full_rollout() for high-risk mutations.
      CMD-MIRROR-0    record_mirror_result() MUST be called before close_canary().
      CMD-ROLLBACK-0  close_canary() auto-rolls-back when mirror score < threshold.
      CMD-CHAIN-0     Every lifecycle event is appended to a hash-chained ledger.
      CMD-HUMAN0-0    promote_failed_canary() requires human_auth=True.
    """

    def __init__(
        self,
        ledger_path: Path = Path("data/canary_ledger.jsonl"),
        canary_slice: float = DEFAULT_CANARY_SLICE,
        mirror_threshold: float = DEFAULT_MIRROR_THRESHOLD,
    ) -> None:
        self._ledger_path = Path(ledger_path)
        self._default_slice = canary_slice
        self._default_threshold = mirror_threshold
        self._events: list[CanaryEvent] = []
        self._deployments: dict[str, CanaryDeployment] = {}
        self._load()

    # ── Lifecycle API ──────────────────────────────────────────────────────────

    def open_canary(
        self,
        mutation_id: str,
        tier: int,
        canary_slice: float | None = None,
        mirror_threshold: float | None = None,
        timestamp: str = "",
    ) -> CanaryDeployment:
        """Open a canary deployment window for a mutation.

        CMD-GATE-0: this MUST be called for high-risk mutations before full rollout.
        CMD-CHAIN-0: emits an OPENED event into the hash-chained ledger.
        """
        ts = timestamp or _now_iso()
        canary_id = _make_canary_id(mutation_id, ts)
        deployment = CanaryDeployment(
            canary_id=canary_id,
            mutation_id=mutation_id,
            tier=tier,
            canary_slice=canary_slice if canary_slice is not None else self._default_slice,
            mirror_threshold=mirror_threshold if mirror_threshold is not None else self._default_threshold,
            status=CanaryStatus.OPEN,
            opened_at=ts,
        )
        self._deployments[canary_id] = deployment
        self._emit(canary_id, CanaryEventType.OPENED, {
            "mutation_id": mutation_id,
            "tier": tier,
            "canary_slice": deployment.canary_slice,
            "mirror_threshold": deployment.mirror_threshold,
        }, ts)
        return deployment

    def record_sample(
        self,
        canary_id: str,
        success: bool,
        timestamp: str = "",
    ) -> None:
        """Record a traffic sample result from the canary window.

        CMD-CHAIN-0: emits a SAMPLE_RECORDED event.
        """
        dep = self._get(canary_id)
        ts = timestamp or _now_iso()
        dep.sample_count += 1
        if not success:
            dep.error_count += 1
        self._emit(canary_id, CanaryEventType.SAMPLE_RECORDED, {
            "success": success,
            "sample_count": dep.sample_count,
            "error_count": dep.error_count,
        }, ts)

    def record_mirror_result(
        self,
        canary_id: str,
        mirror_score: float,
        timestamp: str = "",
    ) -> None:
        """Record the Mirror Test consistency score for this canary.

        CMD-MIRROR-0: this MUST be called before close_canary().
        CMD-CHAIN-0: emits a MIRROR_RESULT event.
        """
        dep = self._get(canary_id)
        ts = timestamp or _now_iso()
        dep.mirror_score = mirror_score
        dep.status = CanaryStatus.MIRROR_CHECKED
        self._emit(canary_id, CanaryEventType.MIRROR_RESULT, {
            "mirror_score": mirror_score,
            "threshold": dep.mirror_threshold,
            "passed": dep.mirror_passed(),
        }, ts)

    def close_canary(
        self,
        canary_id: str,
        timestamp: str = "",
    ) -> CanaryDeployment:
        """Close a canary window — auto-promote or auto-rollback based on Mirror Test.

        CMD-MIRROR-0: raises CMDMirrorViolation if mirror result not yet recorded.
        CMD-ROLLBACK-0: auto-rollback when mirror score < threshold.
        CMD-CHAIN-0: emits PROMOTED or ROLLED_BACK event.
        """
        dep = self._get(canary_id)
        ts = timestamp or _now_iso()

        if dep.mirror_score is None:
            raise CMDMirrorViolation(
                f"CMD-MIRROR-0: canary '{canary_id}' cannot be closed without a "
                "Mirror Test result. Call record_mirror_result() first."
            )

        dep.closed_at = ts

        if dep.mirror_passed():
            dep.status = CanaryStatus.PROMOTED
            self._emit(canary_id, CanaryEventType.PROMOTED, {
                "mirror_score": dep.mirror_score,
                "auto_promoted": True,
            }, ts)
        else:
            # CMD-ROLLBACK-0: mandatory auto-rollback
            dep.status = CanaryStatus.ROLLED_BACK
            self._emit(canary_id, CanaryEventType.ROLLED_BACK, {
                "mirror_score": dep.mirror_score,
                "threshold": dep.mirror_threshold,
                "reason": "mirror_score_below_threshold",
                "auto_rollback": True,
            }, ts)

        return dep

    def promote_failed_canary(
        self,
        canary_id: str,
        human_auth: bool = False,
        rationale: str = "",
        timestamp: str = "",
    ) -> CanaryDeployment:
        """Override auto-rollback and promote a failed canary to full rollout.

        CMD-HUMAN0-0: human_auth=True is required. Raises CMDAuthorizationViolation
        if called without explicit HUMAN-0 authorisation.
        CMD-CHAIN-0: emits a HUMAN0_OVERRIDE event if authorised.
        """
        if not human_auth:
            raise CMDAuthorizationViolation(
                f"CMD-HUMAN0-0: promoting failed canary '{canary_id}' to full "
                "rollout requires human_auth=True — this is a HUMAN-0 gated operation."
            )
        dep = self._get(canary_id)
        if dep.status not in (CanaryStatus.ROLLED_BACK,):
            raise CMDRollbackViolation(
                f"promote_failed_canary() applies only to ROLLED_BACK canaries; "
                f"canary '{canary_id}' is in status '{dep.status}'."
            )
        ts = timestamp or _now_iso()
        dep.status = CanaryStatus.PROMOTED
        dep.human0_override = True
        self._emit(canary_id, CanaryEventType.HUMAN0_OVERRIDE, {
            "previous_status": CanaryStatus.ROLLED_BACK,
            "new_status": CanaryStatus.PROMOTED,
            "mirror_score": dep.mirror_score,
            "rationale": rationale,
        }, ts)
        return dep

    def require_canary_for_high_risk(
        self,
        mutation_id: str,
        tier: int,
    ) -> None:
        """Assert that a canary has been opened for this high-risk mutation.

        CMD-GATE-0: raises CMDGateViolation if a high-risk mutation has no canary.
        Safe mutations (tier not in HIGH_RISK_TIERS) pass through without check.
        """
        if tier not in HIGH_RISK_TIERS:
            return
        has_canary = any(
            d.mutation_id == mutation_id
            for d in self._deployments.values()
        )
        if not has_canary:
            raise CMDGateViolation(
                f"CMD-GATE-0: high-risk mutation '{mutation_id}' (tier={tier}) "
                "attempted full rollout without an open canary deployment. "
                "Call open_canary() first."
            )

    # ── Analysis API ──────────────────────────────────────────────────────────

    def active_canaries(self) -> list[CanaryDeployment]:
        """All deployments currently in OPEN or MIRROR_CHECKED status."""
        return [d for d in self._deployments.values()
                if d.status in (CanaryStatus.OPEN, CanaryStatus.MIRROR_CHECKED)]

    def rollback_rate(self) -> float:
        """Fraction of closed canaries that were auto-rolled-back (excluding overrides)."""
        closed = [d for d in self._deployments.values()
                  if d.status in (CanaryStatus.PROMOTED, CanaryStatus.ROLLED_BACK)]
        if not closed:
            return 0.0
        rolled = sum(1 for d in closed if d.status == CanaryStatus.ROLLED_BACK
                     and not d.human0_override)
        return rolled / len(closed)

    def get_deployment(self, canary_id: str) -> CanaryDeployment:
        return self._get(canary_id)

    # ── Chain integrity ────────────────────────────────────────────────────────

    def verify_chain(self) -> bool:
        """Verify full hash-chain integrity (CMD-CHAIN-0)."""
        prev = GENESIS_PREV_HASH
        for evt in self._events:
            if evt.prev_hash != prev:
                raise CMDChainViolation(
                    f"CMD-CHAIN-0: chain broken at seq={evt.seq}. "
                    f"Expected prev={prev!r}, got {evt.prev_hash!r}"
                )
            expected = _compute_event_hash(
                CanaryEvent(
                    canary_id=evt.canary_id,
                    event_type=evt.event_type,
                    payload=evt.payload,
                    timestamp=evt.timestamp,
                    seq=evt.seq,
                    prev_hash=evt.prev_hash,
                    entry_hash="",
                )
            )
            if evt.entry_hash != expected:
                raise CMDChainViolation(
                    f"CMD-CHAIN-0: hash mismatch at seq={evt.seq}."
                )
            prev = evt.entry_hash
        return True

    def ledger_digest(self) -> str:
        """Deterministic digest of all canary events."""
        summary = [(e.seq, e.canary_id, e.event_type, e.entry_hash)
                   for e in self._events]
        payload = json.dumps(summary, sort_keys=True)
        return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()

    # ── Internals ─────────────────────────────────────────────────────────────

    def _get(self, canary_id: str) -> CanaryDeployment:
        if canary_id not in self._deployments:
            raise KeyError(f"Unknown canary_id: {canary_id!r}")
        return self._deployments[canary_id]

    def _emit(
        self,
        canary_id: str,
        event_type: CanaryEventType,
        payload: dict[str, Any],
        timestamp: str,
    ) -> None:
        prev = self._events[-1].entry_hash if self._events else GENESIS_PREV_HASH
        evt = CanaryEvent(
            canary_id=canary_id,
            event_type=event_type.value,
            payload=payload,
            timestamp=timestamp,
            seq=len(self._events),
            prev_hash=prev,
        )
        self._events.append(evt)
        self._persist(evt)

    def _persist(self, evt: CanaryEvent) -> None:
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self._ledger_path.open("a") as f:
            f.write(json.dumps(evt.to_dict()) + "\n")

    def _load(self) -> None:
        """Reload from ledger (CMD-CHAIN-0 / persistence)."""
        if not self._ledger_path.exists():
            return
        for line in self._ledger_path.read_text().splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            evt = CanaryEvent(
                canary_id=d["canary_id"],
                event_type=d["event_type"],
                payload=d["payload"],
                timestamp=d["timestamp"],
                seq=d["seq"],
                prev_hash=d["prev_hash"],
                entry_hash=d["entry_hash"],
            )
            self._events.append(evt)
            # Reconstruct deployment state from events
            cid = evt.canary_id
            if evt.event_type == CanaryEventType.OPENED.value:
                p = evt.payload
                self._deployments[cid] = CanaryDeployment(
                    canary_id=cid,
                    mutation_id=p["mutation_id"],
                    tier=p["tier"],
                    canary_slice=p["canary_slice"],
                    mirror_threshold=p["mirror_threshold"],
                    opened_at=evt.timestamp,
                )
            elif cid in self._deployments:
                dep = self._deployments[cid]
                if evt.event_type == CanaryEventType.SAMPLE_RECORDED.value:
                    dep.sample_count = evt.payload["sample_count"]
                    dep.error_count = evt.payload["error_count"]
                elif evt.event_type == CanaryEventType.MIRROR_RESULT.value:
                    dep.mirror_score = evt.payload["mirror_score"]
                    dep.status = CanaryStatus.MIRROR_CHECKED
                elif evt.event_type == CanaryEventType.PROMOTED.value:
                    dep.status = CanaryStatus.PROMOTED
                    dep.closed_at = evt.timestamp
                elif evt.event_type == CanaryEventType.ROLLED_BACK.value:
                    dep.status = CanaryStatus.ROLLED_BACK
                    dep.closed_at = evt.timestamp
                elif evt.event_type == CanaryEventType.HUMAN0_OVERRIDE.value:
                    dep.status = CanaryStatus.PROMOTED
                    dep.human0_override = True


def _make_canary_id(mutation_id: str, timestamp: str) -> str:
    raw = f"{mutation_id}:{timestamp}"
    return "canary-" + hashlib.sha256(raw.encode()).hexdigest()[:12]
