# SPDX-License-Identifier: Apache-2.0
"""Deterministic entropy ceiling policy enforcement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from runtime.governance.foundation import sha256_prefixed_digest


@dataclass(frozen=True)
class EntropyPolicy:
    policy_id: str
    per_mutation_ceiling_bits: int
    per_epoch_ceiling_bits: int

    @property
    def policy_hash(self) -> str:
        return sha256_prefixed_digest(
            {
                "policy_id": self.policy_id,
                "per_mutation_ceiling_bits": self.per_mutation_ceiling_bits,
                "per_epoch_ceiling_bits": self.per_epoch_ceiling_bits,
            }
        )


def enforce_entropy_policy(
    *,
    policy: EntropyPolicy,
    mutation_bits: int,
    epoch_bits: int,
    declared_bits: int | None = None,
    observed_bits: int = 0,
) -> Dict[str, Any]:
    effective_declared_bits = int(mutation_bits if declared_bits is None else declared_bits)
    effective_observed_bits = max(0, int(observed_bits))
    mutation_total_bits = effective_declared_bits + effective_observed_bits
    mutation_ok = mutation_total_bits <= int(policy.per_mutation_ceiling_bits)
    epoch_ok = int(epoch_bits) <= int(policy.per_epoch_ceiling_bits)
    return {
        "passed": bool(mutation_ok and epoch_ok),
        "declared_bits": effective_declared_bits,
        "observed_bits": effective_observed_bits,
        "mutation_bits": mutation_total_bits,
        "epoch_bits": int(epoch_bits),
        "policy_id": policy.policy_id,
        "policy_hash": policy.policy_hash,
        "reason": "ok" if mutation_ok and epoch_ok else "entropy_ceiling_exceeded",
    }


__all__ = ["EntropyPolicy", "enforce_entropy_policy"]
