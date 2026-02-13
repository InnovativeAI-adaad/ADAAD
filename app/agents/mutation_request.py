# SPDX-License-Identifier: Apache-2.0
"""
Structured mutation request emitted by Architect and consumed by the executor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class MutationTarget:
    agent_id: str
    path: str
    target_type: str
    ops: List[Dict[str, Any]]
    # hash_preimage is optional: empty string implies legacy/unverified targets.
    hash_preimage: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "path": self.path,
            "target_type": self.target_type,
            "ops": self.ops,
            "hash_preimage": self.hash_preimage,
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "MutationTarget":
        return cls(
            agent_id=raw.get("agent_id", ""),
            path=raw.get("path", ""),
            target_type=raw.get("target_type", ""),
            ops=list(raw.get("ops") or []),
            hash_preimage=raw.get("hash_preimage", ""),
        )


@dataclass
class MutationRequest:
    agent_id: str
    generation_ts: str
    intent: str
    ops: List[Dict[str, Any]]
    signature: str
    nonce: str
    targets: List[MutationTarget] = field(default_factory=list)
    epoch_id: str = ""
    bundle_id: str = ""
    random_seed: int = 0
    capability_scopes: List[str] = field(default_factory=list)
    authority_level: str = "low-impact"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "generation_ts": self.generation_ts,
            "intent": self.intent,
            "ops": self.ops,
            "targets": [target.to_dict() for target in self.targets],
            "signature": self.signature,
            "nonce": self.nonce,
            "epoch_id": self.epoch_id,
            "bundle_id": self.bundle_id,
            "random_seed": self.random_seed,
            "capability_scopes": self.capability_scopes,
            "authority_level": self.authority_level,
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "MutationRequest":
        return cls(
            agent_id=raw.get("agent_id", ""),
            generation_ts=raw.get("generation_ts", ""),
            intent=raw.get("intent", ""),
            ops=list(raw.get("ops") or []),
            targets=[MutationTarget.from_dict(t) for t in raw.get("targets") or []],
            signature=raw.get("signature", ""),
            nonce=raw.get("nonce", ""),
            epoch_id=raw.get("epoch_id", ""),
            bundle_id=raw.get("bundle_id", ""),
            random_seed=int(raw.get("random_seed", 0) or 0),
            capability_scopes=list(raw.get("capability_scopes") or []),
            authority_level=raw.get("authority_level", "low-impact"),
        )


__all__ = ["MutationRequest", "MutationTarget"]
