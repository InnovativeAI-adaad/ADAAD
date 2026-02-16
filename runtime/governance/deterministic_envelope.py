# SPDX-License-Identifier: Apache-2.0
"""Deterministic envelope enforcement for governance paths.

Entropy unit costs are intentionally non-zero for all repeated operations,
including deterministic provider operations, to avoid hot-loop abuse in
fail-closed governance paths.
"""

from __future__ import annotations

import threading
import traceback
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Generator

from runtime.governance.foundation import RuntimeDeterminismProvider, default_provider
from runtime.timeutils import now_iso


class EntropySource(Enum):
    """Categorized entropy sources with budget costs."""

    RANDOM = "random"
    TIME = "time"
    UUID = "uuid"
    NETWORK = "network"
    FILESYSTEM = "filesystem"
    PROVIDER = "provider"


ENTROPY_COSTS: dict[EntropySource, int] = {
    EntropySource.RANDOM: 10,
    EntropySource.TIME: 5,
    EntropySource.UUID: 10,
    EntropySource.NETWORK: 50,
    EntropySource.FILESYSTEM: 3,
    # Minimal non-zero tax prevents unbounded provider-call loops.
    EntropySource.PROVIDER: 1,
}


@dataclass
class EntropyConsumption:
    """Single entropy event record."""

    source: EntropySource
    cost: int
    context: str
    timestamp: str
    stack_trace: str


@dataclass
class EntropyLedger:
    """Per-envelope entropy budget tracker."""

    epoch_id: str
    budget: int
    consumed: int = 0
    events: list[EntropyConsumption] = field(default_factory=list)
    overflow: bool = False

    def charge(self, source: EntropySource, context: str, stack_trace: str) -> bool:
        """Charge entropy budget for an operation."""
        cost = _get_entropy_cost(source)
        if self.consumed + cost > self.budget:
            self.overflow = True
            return False

        event = EntropyConsumption(
            source=source,
            cost=cost,
            context=context,
            timestamp=now_iso(),
            stack_trace=stack_trace,
        )
        self.events.append(event)
        self.consumed += cost
        return True

    def remaining(self) -> int:
        return max(0, self.budget - self.consumed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "epoch_id": self.epoch_id,
            "budget": self.budget,
            "consumed": self.consumed,
            "remaining": self.remaining(),
            "overflow": self.overflow,
            "event_count": len(self.events),
            "events": [
                {
                    "source": item.source.value,
                    "cost": item.cost,
                    "context": item.context,
                    "timestamp": item.timestamp,
                    "stack_trace": item.stack_trace,
                }
                for item in self.events
            ],
        }


class EntropyBudgetExceeded(RuntimeError):
    """Raised when entropy consumption exceeds envelope budget."""


_thread_local = threading.local()


def _get_entropy_cost(source: EntropySource) -> int:
    return ENTROPY_COSTS[source]


@contextmanager
def deterministic_envelope(
    epoch_id: str,
    budget: int = 100,
    provider: RuntimeDeterminismProvider | None = None,
) -> Generator[EntropyLedger, None, None]:
    """Create an entropy-tracked deterministic governance scope."""
    if hasattr(_thread_local, "envelope"):
        raise RuntimeError("nested_deterministic_envelope_not_supported")

    ledger = EntropyLedger(epoch_id=epoch_id, budget=max(0, int(budget)))
    _thread_local.envelope = ledger
    _thread_local.provider = provider or default_provider()

    try:
        yield ledger
    finally:
        if ledger.overflow:
            _log_entropy_overflow(ledger)
        del _thread_local.envelope
        del _thread_local.provider


def _log_entropy_overflow(ledger: EntropyLedger) -> None:
    from runtime import metrics

    metrics.log(
        event_type="entropy_budget_overflow",
        payload=ledger.to_dict(),
        level="ERROR",
    )


def _log_untracked_entropy(source: EntropySource, context: str) -> None:
    from runtime import metrics

    metrics.log(
        event_type="entropy_untracked",
        payload={"source": source.value, "context": context},
        level="WARN",
    )


def get_current_ledger() -> EntropyLedger | None:
    return getattr(_thread_local, "envelope", None)


def charge_entropy(source: EntropySource, context: str) -> bool:
    """Charge entropy budget for current envelope."""
    ledger = get_current_ledger()
    if ledger is None:
        _log_untracked_entropy(source, context)
        return True

    stack_trace = "".join(traceback.format_stack(limit=4)[:-1])
    if not ledger.charge(source, context, stack_trace):
        raise EntropyBudgetExceeded(
            f"entropy_budget_exceeded:{ledger.epoch_id}:{ledger.consumed}/{ledger.budget}:{source.value}"
        )
    return True


__all__ = [
    "EntropySource",
    "ENTROPY_COSTS",
    "EntropyConsumption",
    "EntropyLedger",
    "EntropyBudgetExceeded",
    "deterministic_envelope",
    "get_current_ledger",
    "charge_entropy",
]
