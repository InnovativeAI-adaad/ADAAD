from __future__ import annotations

from adaad.core.cryovant import deterministic_source_hash


def test_deterministic_source_hash_smoke() -> None:
    digest = deterministic_source_hash("runtime.manifest.generator")
    assert len(digest) == 64
