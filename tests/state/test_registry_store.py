# SPDX-License-Identifier: Apache-2.0

import time

from runtime.state.registry_store import CryovantRegistryStore


def _sample(index: int) -> dict[str, object]:
    return {
        "name": f"cap-{index}",
        "version": "v1",
        "score": float(index),
        "owner": "Earth",
        "requires": [],
        "evidence": {},
        "updated_at": "2024-01-01T00:00:00Z",
    }


def test_registry_store_json_sqlite_parity(tmp_path) -> None:
    json_path = tmp_path / "capabilities.json"
    sqlite_path = tmp_path / "capabilities.sqlite"

    json_store = CryovantRegistryStore(json_path, backend="json")
    sqlite_store = CryovantRegistryStore(json_path, sqlite_path=sqlite_path, backend="sqlite")

    payload = {"a": _sample(1), "b": _sample(2)}
    json_store.save_registry(payload)
    sqlite_store.save_registry(payload)

    assert json_store.load_registry() == sqlite_store.load_registry()


def test_registry_store_large_query_latency_target(tmp_path) -> None:
    json_path = tmp_path / "large_registry.json"
    store = CryovantRegistryStore(json_path, backend="json")
    payload = {f"cap-{i:05d}": _sample(i) for i in range(5000)}
    store.save_registry(payload)

    start = time.perf_counter()
    loaded = store.load_registry()
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    assert len(loaded) == 5000
    assert elapsed_ms < 750.0
