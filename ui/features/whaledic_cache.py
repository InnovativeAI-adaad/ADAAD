# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

V = TypeVar("V")


@dataclass(frozen=True)
class WhaleDicCachePolicy:
    """Deterministic cache policy for Whale.Dic route/query integration."""

    ttl_ms: int = 30_000
    max_entries: int = 64
    offline_read_through: bool = False
    mode: str = "live"  # live | replay | testing


@dataclass(frozen=True)
class WhaleDicCacheResult(Generic[V]):
    key: str
    value: V
    cache_hit: bool
    stale: bool
    source: str  # cache | loader | stale_cache


class WhaleDicIntegrationCache(Generic[V]):
    """Small-footprint LRU+TTL cache with deterministic behavior.

    Designed for Whale.Dic mobile constraints and replay/testing determinism.
    """

    def __init__(self, policy: WhaleDicCachePolicy | None = None) -> None:
        self.policy = policy or WhaleDicCachePolicy()
        self._entries: OrderedDict[str, tuple[int, V]] = OrderedDict()

    @staticmethod
    def normalize_key(query: str) -> str:
        """Normalize equivalent query strings into a canonical key."""
        collapsed = " ".join(query.strip().lower().split())
        return collapsed

    def invalidate(self, query: str) -> bool:
        key = self.normalize_key(query)
        return self._entries.pop(key, None) is not None

    def invalidate_all(self) -> None:
        self._entries.clear()

    def _is_stale(self, *, created_ms: int, now_ms: int) -> bool:
        return (now_ms - created_ms) >= self.policy.ttl_ms

    def _store(self, *, key: str, now_ms: int, value: V) -> None:
        self._entries[key] = (now_ms, value)
        self._entries.move_to_end(key)
        while len(self._entries) > self.policy.max_entries:
            self._entries.popitem(last=False)

    def get_or_load(self, *, query: str, now_ms: int, loader: Callable[[], V]) -> WhaleDicCacheResult[V]:
        key = self.normalize_key(query)
        existing = self._entries.get(key)
        if existing is not None:
            created_ms, value = existing
            stale = self._is_stale(created_ms=created_ms, now_ms=now_ms)
            if not stale:
                self._entries.move_to_end(key)
                return WhaleDicCacheResult(key=key, value=value, cache_hit=True, stale=False, source="cache")
            if self.policy.offline_read_through:
                # Keep stale entry, return deterministic stale fallback for offline mode.
                return WhaleDicCacheResult(key=key, value=value, cache_hit=True, stale=True, source="stale_cache")

        loaded = loader()
        self._store(key=key, now_ms=now_ms, value=loaded)
        return WhaleDicCacheResult(key=key, value=loaded, cache_hit=False, stale=False, source="loader")

    def snapshot(self) -> list[dict[str, object]]:
        """Deterministic representation for replay/testing assertions."""
        return [
            {"key": key, "created_ms": created_ms, "value": value}
            for key, (created_ms, value) in self._entries.items()
        ]
