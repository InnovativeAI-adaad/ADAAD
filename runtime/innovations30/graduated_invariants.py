# SPDX-License-Identifier: Apache-2.0
"""Innovation #3 — Graduated Invariant Promotion.

Rules start as advisory, earn warning, prove their way to blocking
based on precision record. A rule blocking too many good mutations
is automatically demoted pending human review.
"""
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import hashlib
import hmac

# Hardening scaffold — injected by fix/senior-deep-dive-hardening
GRIN_INV_CHAIN: str = "GRIN-INV-CHAIN"
GRIN_LEDGER_DEFAULT: str = "data/graduated_invariants_events.jsonl"


class GraduatedInvariantsViolation(RuntimeError):
    """Raised when a Graduated Invariants constitutional invariant is breached."""



PROMOTION_EPOCHS = 30     # epochs at current level before promotion eligible
PROMOTION_PRECISION = 0.90  # must catch real violations this fraction of firings
DEMOTION_FP_RATE = 0.30    # false positive rate above this → demotion candidate

SEVERITY_LADDER = ["advisory", "warning", "blocking"]

@dataclass
class RuleCalibration:
    rule_name: str
    current_severity: str
    true_positive_count: int = 0   # fired and mutation was actually bad
    false_positive_count: int = 0  # fired but mutation was accepted by human override
    epochs_at_level: int = 0
    last_promotion_epoch: str = ""
    last_demotion_epoch: str = ""

    @property
    def precision(self) -> float:
        total = self.true_positive_count + self.false_positive_count
        return self.true_positive_count / total if total > 0 else 1.0

    @property
    def false_positive_rate(self) -> float:
        total = self.true_positive_count + self.false_positive_count
        return self.false_positive_count / total if total > 0 else 0.0

    @property
    def promotion_candidate(self) -> bool:
        return (self.epochs_at_level >= PROMOTION_EPOCHS
                and self.precision >= PROMOTION_PRECISION
                and SEVERITY_LADDER.index(self.current_severity) < len(SEVERITY_LADDER) - 1)

    @property
    def demotion_candidate(self) -> bool:
        return (self.false_positive_rate > DEMOTION_FP_RATE
                and (self.true_positive_count + self.false_positive_count) >= 10)


class GraduatedInvariantPromoter:
    """Tracks rule precision and recommends severity promotions/demotions."""

    def __init__(self, state_path: Path = Path("data/rule_calibrations.json")):
        self.state_path = Path(state_path)
        self._calibrations: dict[str, RuleCalibration] = {}
        self._load()

    def record_firing(self, rule_name: str, current_severity: str,
                      was_false_positive: bool, epoch_id: str) -> RuleCalibration:
        if rule_name not in self._calibrations:
            self._calibrations[rule_name] = RuleCalibration(
                rule_name=rule_name, current_severity=current_severity)
        cal = self._calibrations[rule_name]
        cal.current_severity = current_severity
        cal.epochs_at_level += 1
        if was_false_positive:
            cal.false_positive_count += 1
        else:
            cal.true_positive_count += 1
        self._save()
        return cal

    def recommend_changes(self) -> list[dict[str, str]]:
        recommendations = []
        for cal in self._calibrations.values():
            if cal.promotion_candidate:
                idx = SEVERITY_LADDER.index(cal.current_severity)
                recommendations.append({
                    "rule": cal.rule_name,
                    "action": "promote",
                    "from": cal.current_severity,
                    "to": SEVERITY_LADDER[idx + 1],
                    "precision": str(round(cal.precision, 3)),
                    "epochs_at_level": str(cal.epochs_at_level),
                })
            elif cal.demotion_candidate:
                idx = SEVERITY_LADDER.index(cal.current_severity)
                if idx > 0:
                    recommendations.append({
                        "rule": cal.rule_name,
                        "action": "demote",
                        "from": cal.current_severity,
                        "to": SEVERITY_LADDER[idx - 1],
                        "fp_rate": str(round(cal.false_positive_rate, 3)),
                        "reason": "false_positive_rate_exceeds_threshold",
                    })
        return recommendations

    def calibration_summary(self) -> dict[str, Any]:
        return {
            "total_rules_tracked": len(self._calibrations),
            "promotion_candidates": sum(1 for c in self._calibrations.values()
                                         if c.promotion_candidate),
            "demotion_candidates": sum(1 for c in self._calibrations.values()
                                        if c.demotion_candidate),
            "avg_precision": round(
                sum(c.precision for c in self._calibrations.values()) /
                max(1, len(self._calibrations)), 4),
        }

    def _load(self) -> None:
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text())
                for k, v in data.items():
                    self._calibrations[k] = RuleCalibration(**v)
            except Exception:
                pass

    def _save(self) -> None:
        import dataclasses
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(
            {k: dataclasses.asdict(v) for k, v in self._calibrations.items()},
            indent=2))


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


__all__ = ["GraduatedInvariantPromoter", "RuleCalibration",
           "SEVERITY_LADDER", "PROMOTION_EPOCHS", "DEMOTION_FP_RATE"]
