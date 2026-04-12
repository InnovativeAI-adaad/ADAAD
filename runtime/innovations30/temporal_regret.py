# SPDX-License-Identifier: Apache-2.0
"""Innovation #5 — Temporal Regret Scorer.

Computes regret_score at epoch+10, +25, +50 for every accepted mutation:
difference between predicted fitness at acceptance and measured contribution later.
Feeds back into WeightAdaptor to calibrate criteria that produce regret.
"""
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import hashlib
import hmac

# Hardening scaffold — injected by fix/senior-deep-dive-hardening
TERE_INV_CHAIN: str = "TERE-INV-CHAIN"
TERE_LEDGER_DEFAULT: str = "data/temporal_regret_events.jsonl"


class TemporalRegretViolation(RuntimeError):
    """Raised when a Temporal Regret constitutional invariant is breached."""



REGRET_CHECKPOINTS = (10, 25, 50)
HIGH_REGRET_THRESHOLD = 0.30

@dataclass
class RegretRecord:
    mutation_id: str
    accepted_epoch_seq: int
    predicted_fitness: float
    checkpoints: dict[int, float] = field(default_factory=dict)  # offset → measured
    regret_scores: dict[int, float] = field(default_factory=dict)  # offset → regret

    def update(self, current_epoch_seq: int, measured_fitness: float) -> float | None:
        offset = current_epoch_seq - self.accepted_epoch_seq
        if offset in REGRET_CHECKPOINTS:
            regret = abs(self.predicted_fitness - measured_fitness)
            self.checkpoints[offset] = measured_fitness
            self.regret_scores[offset] = round(regret, 4)
            return regret
        return None

    @property
    def latest_regret(self) -> float:
        if not self.regret_scores:
            return 0.0
        return self.regret_scores[max(self.regret_scores)]

    @property
    def digest(self) -> str:
        payload = json.dumps({"id": self.mutation_id, "scores": self.regret_scores},
                              sort_keys=True)
        return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()[:16]


class TemporalRegretScorer:
    """Tracks how well mutation fitness predictions age."""

    def __init__(self, state_path: Path = Path("data/temporal_regret.jsonl")):
        self.state_path = Path(state_path)
        self._records: dict[str, RegretRecord] = {}
        self._load()

    def register_acceptance(self, mutation_id: str, epoch_seq: int,
                             predicted_fitness: float) -> None:
        self._records[mutation_id] = RegretRecord(
            mutation_id=mutation_id,
            accepted_epoch_seq=epoch_seq,
            predicted_fitness=round(predicted_fitness, 4),
        )

    def tick(self, current_epoch_seq: int,
             fitness_fn) -> list[tuple[str, int, float]]:
        """Called every epoch. fitness_fn(mutation_id) → current fitness float."""
        fired = []
        for mid, record in self._records.items():
            for offset in REGRET_CHECKPOINTS:
                if record.accepted_epoch_seq + offset == current_epoch_seq:
                    try:
                        measured = fitness_fn(mid)
                        regret = record.update(current_epoch_seq, measured)
                        if regret is not None:
                            fired.append((mid, offset, regret))
                    except Exception:
                        pass
        if fired:
            self._save()
        return fired

    def high_regret_mutations(self, offset: int = 25) -> list[RegretRecord]:
        return [r for r in self._records.values()
                if r.regret_scores.get(offset, 0) > HIGH_REGRET_THRESHOLD]

    def avg_regret(self, offset: int = 25) -> float:
        scores = [r.regret_scores[offset] for r in self._records.values()
                  if offset in r.regret_scores]
        return round(sum(scores) / len(scores), 4) if scores else 0.0

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        for line in self.state_path.read_text().splitlines():
            try:
                d = json.loads(line)
                mid = d["mutation_id"]
                r = RegretRecord(**{k: v for k, v in d.items()
                                    if k in RegretRecord.__dataclass_fields__})
                self._records[mid] = r
            except Exception:
                pass

    def _save(self) -> None:
        import dataclasses

        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with self.state_path.open("w") as f:
            for r in self._records.values():
                f.write(json.dumps(dataclasses.asdict(r)) + "\n")


__all__ = ["TemporalRegretScorer", "RegretRecord",
           "REGRET_CHECKPOINTS", "HIGH_REGRET_THRESHOLD"]
