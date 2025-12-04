# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
"""Meta-mutation helpers for evolving mutation strategies.

This layer keeps the Phase V requirement lightweight by tracking mutation
operators and emitting fingerprints that Cryovant can certify. Future
iterations can plug in AST-aware or probabilistic operators without
changing the public surface.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List


META_STATE = Path("reports/meta_mutator.json")
META_STATE.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class MetaMutationState:
    operators: List[str] = field(default_factory=lambda: ["ast", "semantic", "template"])
    mutation_rate: float = 0.3
    selection_mode: str = "tournament"

    def to_dict(self) -> Dict[str, object]:
        return {
            "operators": self.operators,
            "mutation_rate": self.mutation_rate,
            "selection_mode": self.selection_mode,
        }

    def fingerprint(self) -> str:
        serialized = json.dumps(self.to_dict(), sort_keys=True).encode()
        return hashlib.sha256(serialized).hexdigest()


class MetaMutator:
    """Minimal placeholder for recursive evolution of mutators."""

    def __init__(self) -> None:
        self.state = MetaMutationState()
        self.persist()

    def register_operator(self, name: str, fn: Callable[[str], str] | None = None) -> None:
        if name not in self.state.operators:
            self.state.operators.append(name)
            self.persist()

    def adjust_rate(self, delta: float) -> None:
        self.state.mutation_rate = max(0.0, min(1.0, self.state.mutation_rate + delta))
        self.persist()

    def adjust_selection(self, mode: str) -> None:
        self.state.selection_mode = mode
        self.persist()

    def persist(self) -> None:
        META_STATE.write_text(json.dumps({"state": self.state.to_dict(), "fingerprint": self.state.fingerprint()}, indent=2), encoding="utf-8")

    def snapshot(self) -> Dict[str, object]:
        return {"state": self.state.to_dict(), "fingerprint": self.state.fingerprint()}
