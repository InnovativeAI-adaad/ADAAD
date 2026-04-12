# SPDX-License-Identifier: Apache-2.0
"""Innovation #4 — Intent Preservation Verifier.

After a mutation lands, measures whether what actually changed
matches the stated intent. Agents with persistent low intent
realization are flagged for calibration.
"""
from __future__ import annotations
import hashlib, json, re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import hashlib
import hmac

# Hardening scaffold — injected by fix/senior-deep-dive-hardening
INPR_INV_CHAIN: str = "INPR-INV-CHAIN"
INPR_LEDGER_DEFAULT: str = "data/intent_preservation_events.jsonl"


class IntentPreservationViolation(RuntimeError):
    """Raised when a Intent Preservation constitutional invariant is breached."""



LOW_REALIZATION_THRESHOLD: float = 0.40
CALIBRATION_TRIGGER_STREAK: int = 5  # consecutive epochs of low realization

# Keyword clusters per intent category
INTENT_VOCABULARY: dict[str, list[str]] = {
    "performance": ["speed", "throughput", "latency", "fast", "optim", "cache", "effic"],
    "reliability": ["error", "robust", "fail", "crash", "exception", "recover", "safe"],
    "readability": ["clean", "simplif", "refactor", "readable", "clarity", "document"],
    "coverage":    ["test", "cover", "spec", "assert", "verif"],
    "security":    ["secure", "auth", "encrypt", "token", "sign", "hash"],
    "complexity":  ["complex", "cyclomatic", "nesting", "coupling", "cohes"],
}


@dataclass
class IntentRealizationScore:
    mutation_id: str
    agent_id: str
    stated_intent: str
    intent_category: str
    realization_score: float     # 0–1: how well the diff matches the intent
    diff_keywords_found: list[str]
    intent_keywords_expected: list[str]
    epoch_id: str
    score_digest: str = ""

    def __post_init__(self):
        if not self.score_digest:
            payload = f"{self.mutation_id}:{self.realization_score:.4f}"
            self.score_digest = "sha256:" + hashlib.sha256(payload.encode()).hexdigest()[:16]


class IntentPreservationVerifier:
    """Measures alignment between mutation intent and what actually changed."""

    def __init__(self, ledger_path: Path = Path("data/intent_realization.jsonl")):
        self.ledger_path = Path(ledger_path)
        self._agent_streaks: dict[str, int] = {}   # agent_id → low-realization streak

    def verify(self, mutation_id: str, agent_id: str, stated_intent: str,
               diff_text: str, epoch_id: str) -> IntentRealizationScore:
        """Score how well diff_text realizes stated_intent."""
        intent_cat, intent_kws = self._classify_intent(stated_intent)
        diff_lower = diff_text.lower()
        found = [kw for kw in intent_kws if kw in diff_lower]

        if not intent_kws:
            score = 0.5  # neutral: unknown intent category
        else:
            score = len(found) / len(intent_kws)

        # Bonus: intent words appear in +lines more than -lines
        plus_lines = " ".join(l[1:] for l in diff_text.splitlines() if l.startswith("+"))
        minus_lines = " ".join(l[1:] for l in diff_text.splitlines() if l.startswith("-"))
        plus_hits = sum(1 for kw in intent_kws if kw in plus_lines.lower())
        minus_hits = sum(1 for kw in intent_kws if kw in minus_lines.lower())
        if plus_hits > minus_hits:
            score = min(1.0, score + 0.15)

        result = IntentRealizationScore(
            mutation_id=mutation_id, agent_id=agent_id,
            stated_intent=stated_intent, intent_category=intent_cat,
            realization_score=round(score, 4),
            diff_keywords_found=found,
            intent_keywords_expected=intent_kws,
            epoch_id=epoch_id,
        )

        # Track streak
        if score < LOW_REALIZATION_THRESHOLD:
            self._agent_streaks[agent_id] = self._agent_streaks.get(agent_id, 0) + 1
        else:
            self._agent_streaks[agent_id] = 0

        self._persist(result)
        return result

    def agents_needing_calibration(self) -> list[str]:
        return [aid for aid, streak in self._agent_streaks.items()
                if streak >= CALIBRATION_TRIGGER_STREAK]

    def agent_avg_realization(self, agent_id: str, last_n: int = 20) -> float:
        if not self.ledger_path.exists():
            return 1.0
        scores = []
        for line in self.ledger_path.read_text().splitlines():
            try:
                r = json.loads(line)
                if r.get("agent_id") == agent_id:
                    scores.append(r["realization_score"])
            except Exception:
                pass
        if not scores:
            return 1.0
        return round(sum(scores[-last_n:]) / len(scores[-last_n:]), 4)

    def _classify_intent(self, intent: str) -> tuple[str, list[str]]:
        intent_lower = intent.lower()
        best_cat, best_kws, best_hits = "general", [], 0
        for cat, kws in INTENT_VOCABULARY.items():
            hits = sum(1 for kw in kws if kw in intent_lower)
            if hits > best_hits:
                best_cat, best_kws, best_hits = cat, kws, hits
        return best_cat, best_kws

    def _persist(self, score: IntentRealizationScore) -> None:
        import dataclasses

        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger_path.open("a") as f:
            f.write(json.dumps(dataclasses.asdict(score)) + "\n")


# ── Chain-linkage scaffold (hardening pass — prev_digest + _append_event) ─────
import hashlib as _hashlib
import json as _json


_MODULE_PREV_DIGEST: str = "genesis"   # prev_digest chain head for this module


def _append_event(event: dict, ledger_path: str = "") -> None:
    """Module-level append-only JSONL event stub [CED-INV-AUDIT, CED-INV-CHAIN].

    Writes a chain-linked record to ledger_path (or discards if empty).
    Full integration deferred to per-module deep-dive phase.
    """
    global _MODULE_PREV_DIGEST
    if not ledger_path:
        return
    import dataclasses as _dc
    from pathlib import Path as _Path
    row = event if isinstance(event, dict) else (
        _dc.asdict(event) if hasattr(event, '__dataclass_fields__') else {}
    )
    row["prev_digest"] = _MODULE_PREV_DIGEST
    digest_payload = _json.dumps(row, sort_keys=True).encode()
    row["event_digest"] = "sha256:" + _hashlib.sha256(digest_payload).hexdigest()
    p = _Path(ledger_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(_json.dumps(row, sort_keys=True) + "\n")
    _MODULE_PREV_DIGEST = row["event_digest"]


__all__ = ["IntentPreservationVerifier", "IntentRealizationScore",
           "LOW_REALIZATION_THRESHOLD", "INTENT_VOCABULARY"]
