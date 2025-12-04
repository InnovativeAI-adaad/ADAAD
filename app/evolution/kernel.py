# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
"""Evolution Kernel governs Phase V recursive evolution parameters."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List


KERNEL_STATE = Path("reports/evolution_kernel.json")
KERNEL_STATE.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class EvolutionKernel:
    population_size: int = 10
    strategy_pool: List[str] = field(default_factory=lambda: ["ast", "semantic", "template"])
    mutation_rate: float = 0.3
    selection_mode: str = "tournament"
    max_fail_rate: float = 0.4

    def to_dict(self) -> Dict[str, object]:
        return {
            "population_size": self.population_size,
            "strategy_pool": self.strategy_pool,
            "mutation_rate": self.mutation_rate,
            "selection_mode": self.selection_mode,
            "max_fail_rate": self.max_fail_rate,
        }

    def fingerprint(self) -> str:
        serialized = json.dumps(self.to_dict(), sort_keys=True).encode()
        return hashlib.sha256(serialized).hexdigest()

    def persist(self) -> None:
        KERNEL_STATE.write_text(
            json.dumps({"kernel": self.to_dict(), "fingerprint": self.fingerprint()}, indent=2),
            encoding="utf-8",
        )

    def adjust(self, metrics: Dict[str, float] | None = None) -> None:
        metrics = metrics or {}
        survival = metrics.get("survival_rate")
        if survival is not None and survival < 0.5:
            self.mutation_rate = min(1.0, self.mutation_rate + 0.05)
        elif survival is not None and survival > 0.8:
            self.mutation_rate = max(0.05, self.mutation_rate - 0.05)
        self.persist()
