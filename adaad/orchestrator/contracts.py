# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StatusEnvelope:
    """Typed subsystem response envelope for orchestrator boundaries."""

    status: str
    reason: str = ""
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "evidence_refs": list(self.evidence_refs),
            "payload": self.payload,
        }


__all__ = ["StatusEnvelope"]
