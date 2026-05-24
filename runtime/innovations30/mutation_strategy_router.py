"""
INNOV-95 · Mutation Strategy Router (MSR)
Phase 190 · v10.1.0

Constitutional invariants:
  MSR-ROUTE-0   Every routing decision is sealed in the HMAC-chained ledger.
  MSR-CHAIN-0   Each RoutingRecord's HMAC covers the previous record's HMAC.
  MSR-HUMAN0-0  HUMAN-0 approval required before any CRITICAL-tier strategy executes.
  MSR-SCOPE-0   A strategy may never expand its declared blast-radius scope at runtime.
  MSR-ATOMIC-0  A failed dispatch must leave ledger and state in pre-dispatch condition.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

# ── Constitutional invariant registry ────────────────────────────────────────

INVARIANTS: List[str] = [
    "MSR-ROUTE-0",
    "MSR-CHAIN-0",
    "MSR-HUMAN0-0",
    "MSR-SCOPE-0",
    "MSR-ATOMIC-0",
]

HARD_CLASS = "Hard"


# ── Domain types ─────────────────────────────────────────────────────────────

class StrategyTier(str, Enum):
    ROUTINE   = "ROUTINE"
    ELEVATED  = "ELEVATED"
    CRITICAL  = "CRITICAL"


class BlastRadius(str, Enum):
    LOCAL     = "LOCAL"      # single file / function
    MODULE    = "MODULE"     # single module
    SUBSYSTEM = "SUBSYSTEM"  # multiple modules, same domain
    GLOBAL    = "GLOBAL"     # cross-domain, full-system impact


class DispatchOutcome(str, Enum):
    DISPATCHED  = "DISPATCHED"
    BLOCKED     = "BLOCKED"
    DEFERRED    = "DEFERRED"
    ROLLED_BACK = "ROLLED_BACK"


@dataclass
class SignalVector:
    """Immutable signal bundle that drives strategy selection."""
    mutation_id: str
    entropy_score: float          # 0.0–1.0 constitutional entropy
    scope: BlastRadius
    requires_human0: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.entropy_score <= 1.0:
            raise ValueError(f"entropy_score must be in [0,1], got {self.entropy_score}")


@dataclass
class RoutingRecord:
    """Sealed, HMAC-chained record of one routing decision (MSR-ROUTE-0)."""
    record_id: str
    mutation_id: str
    strategy_name: str
    tier: StrategyTier
    scope: BlastRadius
    outcome: DispatchOutcome
    timestamp: float
    prev_hmac: str
    hmac: str = field(default="", init=False)

    def seal(self, secret: bytes) -> None:
        """Compute and set HMAC over canonical fields (MSR-CHAIN-0)."""
        payload = json.dumps({
            "record_id":     self.record_id,
            "mutation_id":   self.mutation_id,
            "strategy_name": self.strategy_name,
            "tier":          self.tier.value,
            "scope":         self.scope.value,
            "outcome":       self.outcome.value,
            "timestamp":     self.timestamp,
            "prev_hmac":     self.prev_hmac,
        }, sort_keys=True).encode()
        self.hmac = hmac.new(secret, payload, hashlib.sha256).hexdigest()

    def verify(self, secret: bytes) -> bool:
        old = self.hmac
        self.hmac = ""
        payload = json.dumps({
            "record_id":     self.record_id,
            "mutation_id":   self.mutation_id,
            "strategy_name": self.strategy_name,
            "tier":          self.tier.value,
            "scope":         self.scope.value,
            "outcome":       self.outcome.value,
            "timestamp":     self.timestamp,
            "prev_hmac":     self.prev_hmac,
        }, sort_keys=True).encode()
        expected = hmac.new(secret, payload, hashlib.sha256).hexdigest()
        self.hmac = old
        return hmac.compare_digest(old, expected)


@dataclass
class StrategyDescriptor:
    name: str
    tier: StrategyTier
    max_scope: BlastRadius
    handler: Callable[[SignalVector], DispatchOutcome]
    description: str = ""


# ── Core router ──────────────────────────────────────────────────────────────

class MutationStrategyRouter:
    """
    Routes mutation proposals to the appropriate execution strategy based on
    constitutional signal vectors.  All decisions are sealed in a hash-chained
    ledger (MSR-CHAIN-0).
    """

    _SCOPE_RANK: Dict[BlastRadius, int] = {
        BlastRadius.LOCAL:     0,
        BlastRadius.MODULE:    1,
        BlastRadius.SUBSYSTEM: 2,
        BlastRadius.GLOBAL:    3,
    }

    def __init__(self, secret: Optional[bytes] = None) -> None:
        self._secret: bytes       = secret or b"msr-default-secret"
        self._ledger: List[RoutingRecord] = []
        self._strategies: Dict[str, StrategyDescriptor] = {}
        self._human0_approved: set = set()
        self._register_builtin_strategies()

    # ── Strategy registration ─────────────────────────────────────────────

    def register_strategy(self, descriptor: StrategyDescriptor) -> None:
        self._strategies[descriptor.name] = descriptor

    def _register_builtin_strategies(self) -> None:
        self.register_strategy(StrategyDescriptor(
            name="incremental",
            tier=StrategyTier.ROUTINE,
            max_scope=BlastRadius.MODULE,
            handler=self._handle_incremental,
            description="Low-entropy routine mutations; no gate required.",
        ))
        self.register_strategy(StrategyDescriptor(
            name="staged_rollout",
            tier=StrategyTier.ELEVATED,
            max_scope=BlastRadius.SUBSYSTEM,
            handler=self._handle_staged_rollout,
            description="Elevated mutations with canary-first dispatch.",
        ))
        self.register_strategy(StrategyDescriptor(
            name="constitutional_review",
            tier=StrategyTier.CRITICAL,
            max_scope=BlastRadius.GLOBAL,
            handler=self._handle_constitutional_review,
            description="Full constitutional review; HUMAN-0 gate mandatory.",
        ))
        self.register_strategy(StrategyDescriptor(
            name="emergency_patch",
            tier=StrategyTier.ELEVATED,
            max_scope=BlastRadius.SUBSYSTEM,
            handler=self._handle_emergency_patch,
            description="Expedited path for security/availability fixes.",
        ))

    # ── Routing logic ─────────────────────────────────────────────────────

    def select_strategy(self, signal: SignalVector) -> StrategyDescriptor:
        """Select the most appropriate strategy for the given signal."""
        if signal.requires_human0 or signal.entropy_score >= 0.8:
            return self._strategies["constitutional_review"]
        if signal.scope in (BlastRadius.SUBSYSTEM, BlastRadius.GLOBAL):
            return self._strategies["staged_rollout"]
        if signal.entropy_score >= 0.5:
            return self._strategies["staged_rollout"]
        return self._strategies["incremental"]

    def dispatch(self, signal: SignalVector) -> RoutingRecord:
        """
        Route *signal* to a strategy, execute, seal ledger record, and return it.
        MSR-ATOMIC-0: any exception rolls back ledger to pre-call length.
        """
        ledger_snapshot_len = len(self._ledger)
        strategy = self.select_strategy(signal)

        # MSR-HUMAN0-0
        if strategy.tier == StrategyTier.CRITICAL and signal.mutation_id not in self._human0_approved:
            return self._seal_record(
                signal, strategy, DispatchOutcome.BLOCKED,
                reason="MSR-HUMAN0-0: CRITICAL strategy requires HUMAN-0 approval"
            )

        # MSR-SCOPE-0: strategy must not exceed its declared max scope
        if self._SCOPE_RANK[signal.scope] > self._SCOPE_RANK[strategy.max_scope]:
            return self._seal_record(
                signal, strategy, DispatchOutcome.BLOCKED,
                reason="MSR-SCOPE-0: signal scope exceeds strategy max_scope"
            )

        try:
            outcome = strategy.handler(signal)
            return self._seal_record(signal, strategy, outcome)
        except Exception:
            # MSR-ATOMIC-0: roll back any partial ledger mutations
            del self._ledger[ledger_snapshot_len:]
            return self._seal_record(signal, strategy, DispatchOutcome.ROLLED_BACK)

    def approve_human0(self, mutation_id: str) -> None:
        """HUMAN-0 grants approval for a CRITICAL-tier mutation (MSR-HUMAN0-0)."""
        self._human0_approved.add(mutation_id)

    # ── Ledger helpers ────────────────────────────────────────────────────

    def _seal_record(
        self,
        signal: SignalVector,
        strategy: StrategyDescriptor,
        outcome: DispatchOutcome,
        *,
        reason: str = "",
    ) -> RoutingRecord:
        prev_hmac = self._ledger[-1].hmac if self._ledger else "genesis"
        record = RoutingRecord(
            record_id   = str(uuid.uuid4()),
            mutation_id = signal.mutation_id,
            strategy_name = strategy.name,
            tier        = strategy.tier,
            scope       = signal.scope,
            outcome     = outcome,
            timestamp   = time.time(),
            prev_hmac   = prev_hmac,
        )
        record.seal(self._secret)
        self._ledger.append(record)
        return record

    def verify_chain(self) -> bool:
        """Verify full HMAC chain integrity (MSR-CHAIN-0)."""
        for i, rec in enumerate(self._ledger):
            if not rec.verify(self._secret):
                return False
            expected_prev = self._ledger[i - 1].hmac if i > 0 else "genesis"
            if rec.prev_hmac != expected_prev:
                return False
        return True

    @property
    def ledger(self) -> List[RoutingRecord]:
        return list(self._ledger)

    @property
    def ledger_depth(self) -> int:
        return len(self._ledger)

    # ── Built-in handlers ─────────────────────────────────────────────────

    @staticmethod
    def _handle_incremental(signal: SignalVector) -> DispatchOutcome:
        return DispatchOutcome.DISPATCHED

    @staticmethod
    def _handle_staged_rollout(signal: SignalVector) -> DispatchOutcome:
        return DispatchOutcome.DISPATCHED

    @staticmethod
    def _handle_constitutional_review(signal: SignalVector) -> DispatchOutcome:
        return DispatchOutcome.DISPATCHED

    @staticmethod
    def _handle_emergency_patch(signal: SignalVector) -> DispatchOutcome:
        return DispatchOutcome.DISPATCHED


# ── Factory helpers ───────────────────────────────────────────────────────────

def make_router(secret: Optional[bytes] = None) -> MutationStrategyRouter:
    """Create a pre-configured MutationStrategyRouter."""
    return MutationStrategyRouter(secret=secret)


def make_signal(
    mutation_id: str,
    entropy: float,
    scope: BlastRadius,
    requires_human0: bool = False,
    **meta: Any,
) -> SignalVector:
    return SignalVector(
        mutation_id=mutation_id,
        entropy_score=entropy,
        scope=scope,
        requires_human0=requires_human0,
        metadata=meta,
    )
