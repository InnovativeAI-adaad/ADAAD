# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from ui.features.whaledic_cache import WhaleDicCachePolicy, WhaleDicIntegrationCache


def test_normalization_and_hit_miss_behavior() -> None:
    cache = WhaleDicIntegrationCache[str](
        WhaleDicCachePolicy(ttl_ms=30_000, max_entries=4, offline_read_through=False, mode="live")
    )
    calls = {"count": 0}

    def loader() -> str:
        calls["count"] += 1
        return "value-1"

    miss = cache.get_or_load(query="  Replay   Score ", now_ms=1_000, loader=loader)
    hit = cache.get_or_load(query="replay score", now_ms=2_000, loader=loader)

    assert miss.cache_hit is False
    assert miss.source == "loader"
    assert hit.cache_hit is True
    assert hit.source == "cache"
    assert calls["count"] == 1


def test_stale_invalidation_without_offline_read_through() -> None:
    cache = WhaleDicIntegrationCache[str](WhaleDicCachePolicy(ttl_ms=100, max_entries=4, offline_read_through=False))
    values = iter(["old", "new"])

    first = cache.get_or_load(query="governance status", now_ms=0, loader=lambda: next(values))
    second = cache.get_or_load(query=" governance   status ", now_ms=150, loader=lambda: next(values))

    assert first.value == "old"
    assert second.value == "new"
    assert second.cache_hit is False
    assert second.stale is False


def test_offline_read_through_returns_stale_value() -> None:
    cache = WhaleDicIntegrationCache[str](WhaleDicCachePolicy(ttl_ms=100, max_entries=4, offline_read_through=True))
    calls = {"count": 0}

    def loader() -> str:
        calls["count"] += 1
        return "live"

    _ = cache.get_or_load(query="epoch current", now_ms=0, loader=loader)
    stale = cache.get_or_load(query="epoch  current", now_ms=101, loader=loader)

    assert stale.cache_hit is True
    assert stale.stale is True
    assert stale.source == "stale_cache"
    assert stale.value == "live"
    assert calls["count"] == 1


def test_lru_eviction_for_mobile_constraints() -> None:
    cache = WhaleDicIntegrationCache[str](WhaleDicCachePolicy(ttl_ms=10_000, max_entries=2))

    cache.get_or_load(query="a", now_ms=0, loader=lambda: "A")
    cache.get_or_load(query="b", now_ms=0, loader=lambda: "B")
    cache.get_or_load(query="a", now_ms=1, loader=lambda: "A2")  # touch A
    cache.get_or_load(query="c", now_ms=2, loader=lambda: "C")

    snapshot_keys = [entry["key"] for entry in cache.snapshot()]
    assert snapshot_keys == ["a", "c"]


def test_deterministic_snapshots_for_replay_and_testing_modes() -> None:
    replay_cache = WhaleDicIntegrationCache[str](WhaleDicCachePolicy(ttl_ms=5_000, max_entries=3, mode="replay"))
    testing_cache = WhaleDicIntegrationCache[str](WhaleDicCachePolicy(ttl_ms=5_000, max_entries=3, mode="testing"))

    for cache in (replay_cache, testing_cache):
        cache.get_or_load(query="Replay  Score", now_ms=1_000, loader=lambda: "98")
        cache.get_or_load(query="Epoch Current", now_ms=1_100, loader=lambda: "65")

    assert replay_cache.snapshot() == testing_cache.snapshot()
