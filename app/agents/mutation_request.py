# SPDX-License-Identifier: Apache-2.0
"""
Structured mutation request emitted by Architect and consumed by the executor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class MutationRequest:
    agent_id: str
    generation_ts: str
    intent: str
    ops: List[Dict[str, Any]]
    signature: str
    nonce: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "generation_ts": self.generation_ts,
            "intent": self.intent,
            "ops": self.ops,
            "signature": self.signature,
            "nonce": self.nonce,
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "MutationRequest":
        return cls(
            agent_id=raw.get("agent_id", ""),
            generation_ts=raw.get("generation_ts", ""),
            intent=raw.get("intent", ""),
            ops=list(raw.get("ops") or []),
            signature=raw.get("signature", ""),
            nonce=raw.get("nonce", ""),
        )


__all__ = ["MutationRequest"]
