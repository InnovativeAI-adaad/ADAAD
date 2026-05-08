# SPDX-License-Identifier: Apache-2.0
"""Deterministic seed controls for reproducible mutation workflows."""

from __future__ import annotations

import hashlib
import os
import random
from dataclasses import dataclass

_HASH_SEED_ENV = "PYTHONHASHSEED"


@dataclass(frozen=True)
class SeedMaterial:
    """Derived deterministic seed metadata."""

    namespace: str
    seed: int
    hex_digest: str


class DeterministicSeedManager:
    """Derive reproducible namespace-specific seeds from a global seed."""

    def __init__(self, global_seed: int | str) -> None:
        self._global_seed = str(global_seed)

    @property
    def global_seed(self) -> str:
        return self._global_seed

    def derive(self, namespace: str) -> SeedMaterial:
        payload = f"{self._global_seed}:{namespace}".encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        # Use lower 64-bit window for compatibility with random.Random.
        seed = int(digest[-16:], 16)
        return SeedMaterial(namespace=namespace, seed=seed, hex_digest=digest)

    def rng(self, namespace: str) -> random.Random:
        return random.Random(self.derive(namespace).seed)

    def enforce_hash_seed_env(self) -> None:
        os.environ.setdefault(_HASH_SEED_ENV, self._global_seed)
