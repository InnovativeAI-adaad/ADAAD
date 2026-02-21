# SPDX-License-Identifier: Apache-2.0
"""Deterministic mutation-cycle metrics artifacts for evolution runtime."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Mapping

from runtime import ROOT_DIR
from runtime.evolution.lineage_v2 import LineageLedgerV2
from runtime.governance.foundation import canonical_json

METRICS_SCHEMA_VERSION = "v1"
METRICS_STATE_DIR = ROOT_DIR / "runtime" / "evolution" / "state" / "metrics"


class EvolutionMetricsEmitter:
    """Emit deterministic per-cycle and rolling metrics artifacts."""

    def __init__(
        self,
        ledger: LineageLedgerV2,
        *,
        metrics_dir: Path | None = None,
        history_filename: str = "history.json",
        history_limit: int = 200,
        ewma_alpha: float = 0.3,
    ) -> None:
        self.ledger = ledger
        self.metrics_dir = metrics_dir or METRICS_STATE_DIR
        self.history_path = self.metrics_dir / history_filename
        self.history_limit = max(1, int(history_limit))
        self.ewma_alpha = max(0.01, min(0.99, float(ewma_alpha)))

    def emit_cycle_metrics(self, *, epoch_id: str, cycle_id: str, result: Dict[str, Any] | None = None) -> Dict[str, Any]:
        payload = self._build_cycle_payload(epoch_id=epoch_id, cycle_id=cycle_id, result=result or {})
        epoch_dir = self.metrics_dir / epoch_id
        epoch_dir.mkdir(parents=True, exist_ok=True)
        cycle_path = epoch_dir / f"{cycle_id}.json"
        cycle_path.write_text(canonical_json(payload) + "\n", encoding="utf-8")

        history = self._read_history()
        history = [item for item in history if not (item.get("epoch_id") == epoch_id and item.get("cycle_id") == cycle_id)]
        history.append(payload)
        history.sort(key=lambda item: (str(item.get("epoch_id") or ""), str(item.get("cycle_id") or "")))
        if len(history) > self.history_limit:
            history = history[-self.history_limit :]
        history_payload = {
            "schema_version": METRICS_SCHEMA_VERSION,
            "history_limit": self.history_limit,
            "entries": history,
        }
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        self.history_path.write_text(canonical_json(history_payload) + "\n", encoding="utf-8")

        epoch_summary = self._write_epoch_summary(epoch_id=epoch_id, history_entries=history)
        self._write_patterns(history_entries=history)
        self._write_epoch_summary_history(history_entries=history)

        _ = epoch_summary
        return payload

    def _build_cycle_payload(self, *, epoch_id: str, cycle_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
        epoch_events = self.ledger.read_epoch(epoch_id)
        decision_events = [
            entry.get("payload", {}) for entry in epoch_events if entry.get("type") == "GovernanceDecisionEvent"
        ]
        mutation_events = [entry.get("payload", {}) for entry in epoch_events if entry.get("type") == "MutationBundleEvent"]

        total_decisions = len(decision_events)
        accepted_decisions = sum(1 for payload in decision_events if bool(payload.get("accepted")))
        acceptance_rate = accepted_decisions / total_decisions if total_decisions else 0.0

        rejection_reasons: Dict[str, int] = {}
        for payload in decision_events:
            if bool(payload.get("accepted")):
                continue
            reason = str(payload.get("reason") or "unknown")
            rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1

        consumed_values = [int(p.get("entropy_consumed", 0) or 0) for p in decision_events if "entropy_consumed" in p]
        budget_values = [int(p.get("entropy_budget", 0) or 0) for p in decision_events if "entropy_budget" in p]
        entropy_consumed = sum(consumed_values)
        entropy_budget = sum(budget_values)
        entropy_utilization = (entropy_consumed / entropy_budget) if entropy_budget else 0.0

        goal_score_delta = float(result.get("goal_score_delta", 0.0) or 0.0)
        if "goal_score_before" in result and "goal_score_after" in result:
            goal_score_delta = float(result.get("goal_score_after", 0.0) or 0.0) - float(result.get("goal_score_before", 0.0) or 0.0)

        impact_scores = [float(p.get("impact_score", 0.0) or 0.0) for p in decision_events if "impact_score" in p]
        avg_impact_score = sum(impact_scores) / len(impact_scores) if impact_scores else 0.0

        efficiency_score = float(result.get("efficiency_score", acceptance_rate) or acceptance_rate)
        estimated_cost_units = float(result.get("cost_units", entropy_consumed) or entropy_consumed)
        entropy_spent = float(result.get("entropy_spent", entropy_consumed) or entropy_consumed)
        efficiency_ratio = float(goal_score_delta / entropy_spent) if entropy_spent > 0 else 0.0

        mutation_operator = str(result.get("mutation_operator") or result.get("operator") or "unknown")

        return {
            "schema_version": METRICS_SCHEMA_VERSION,
            "epoch_id": epoch_id,
            "cycle_id": cycle_id,
            "status": str(result.get("status") or "unknown"),
            "mutation_id": str(result.get("mutation_id") or ""),
            "mutation_operator": mutation_operator,
            "mutation_acceptance_rate": acceptance_rate,
            "policy_rejection_reasons": dict(sorted(rejection_reasons.items())),
            "entropy": {
                "consumed": entropy_consumed,
                "budget": entropy_budget,
                "utilization": entropy_utilization,
                "spent": entropy_spent,
            },
            "goal_score_delta": goal_score_delta,
            "efficiency_ratio": efficiency_ratio,
            "efficiency_cost_signals": {
                "efficiency_score": efficiency_score,
                "cost_units": estimated_cost_units,
                "average_impact_score": avg_impact_score,
                "accepted_mutation_count": len(mutation_events),
                "decision_count": total_decisions,
            },
            "fitness_component_scores": dict(result.get("fitness_component_scores") or {}),
        }

    def _write_epoch_summary(self, *, epoch_id: str, history_entries: List[Dict[str, Any]]) -> Dict[str, Any]:
        rows = [item for item in history_entries if str(item.get("epoch_id") or "") == epoch_id]
        acceptance = [float(item.get("mutation_acceptance_rate", 0.0) or 0.0) for item in rows]
        goal_delta = [float(item.get("goal_score_delta", 0.0) or 0.0) for item in rows]
        efficiency = [float(item.get("efficiency_ratio", 0.0) or 0.0) for item in rows]

        summary = {
            "schema_version": METRICS_SCHEMA_VERSION,
            "epoch_id": epoch_id,
            "cycle_count": len(rows),
            "acceptance_rate_mean": _mean(acceptance),
            "goal_score_delta_mean": _mean(goal_delta),
            "efficiency_ratio_mean": _mean(efficiency),
            "ewma": {
                "acceptance_rate": _ewma(acceptance, self.ewma_alpha),
                "goal_score_delta": _ewma(goal_delta, self.ewma_alpha),
                "efficiency_ratio": _ewma(efficiency, self.ewma_alpha),
            },
            "volatility": {
                "acceptance_rate": _stddev(acceptance),
                "goal_score_delta": _stddev(goal_delta),
                "efficiency_ratio": _stddev(efficiency),
            },
        }
        summary["local_optima_risk"] = bool(
            summary["volatility"]["goal_score_delta"] < 0.02 and abs(summary["ewma"]["goal_score_delta"]) < 0.01
        )

        path = self.metrics_dir / epoch_id / "summary.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(canonical_json(summary) + "\n", encoding="utf-8")
        return summary

    def _write_epoch_summary_history(self, *, history_entries: List[Dict[str, Any]]) -> None:
        epoch_ids = sorted({str(item.get("epoch_id") or "") for item in history_entries if str(item.get("epoch_id") or "")})
        entries: List[Dict[str, Any]] = []
        for epoch_id in epoch_ids:
            summary_path = self.metrics_dir / epoch_id / "summary.json"
            if not summary_path.exists():
                continue
            try:
                entries.append(json.loads(summary_path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                continue
        payload = {
            "schema_version": METRICS_SCHEMA_VERSION,
            "entries": entries[-self.history_limit :],
        }
        out_path = self.metrics_dir / "epoch_summaries.json"
        out_path.write_text(canonical_json(payload) + "\n", encoding="utf-8")

    def _write_patterns(self, *, history_entries: List[Dict[str, Any]]) -> None:
        patterns: Dict[str, Dict[str, float]] = {}
        for row in history_entries:
            op = str(row.get("mutation_operator") or "unknown")
            entry = patterns.setdefault(op, {"count": 0.0, "efficiency_ratio_total": 0.0})
            entry["count"] += 1.0
            entry["efficiency_ratio_total"] += float(row.get("efficiency_ratio", 0.0) or 0.0)
        ranked: List[Dict[str, Any]] = []
        max_avg = 0.0
        for op, stats in sorted(patterns.items()):
            count = max(1.0, stats["count"])
            avg_eff = stats["efficiency_ratio_total"] / count
            max_avg = max(max_avg, avg_eff)
            ranked.append({"mutation_operator": op, "count": int(stats["count"]), "average_efficiency_ratio": avg_eff})
        for item in ranked:
            base = float(item["average_efficiency_ratio"])
            item["selection_hint"] = (base / max_avg) if max_avg > 0 else 0.0

        payload = {
            "schema_version": METRICS_SCHEMA_VERSION,
            "patterns": ranked,
        }
        path = self.metrics_dir / "patterns.json"
        path.write_text(canonical_json(payload) + "\n", encoding="utf-8")

    def _read_history(self) -> List[Dict[str, Any]]:
        if not self.history_path.exists():
            return []
        try:
            raw = json.loads(self.history_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        if not isinstance(raw, dict):
            return []
        entries = raw.get("entries")
        if not isinstance(entries, list):
            return []
        return [item for item in entries if isinstance(item, dict)]



def _mean(values: List[float]) -> float:
    if not values:
        return 0.0
    return float(sum(values) / len(values))


def _stddev(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    variance = sum((v - m) ** 2 for v in values) / len(values)
    return float(math.sqrt(max(0.0, variance)))


def _ewma(values: List[float], alpha: float) -> float:
    if not values:
        return 0.0
    current = float(values[0])
    for value in values[1:]:
        current = (alpha * float(value)) + ((1.0 - alpha) * current)
    return float(current)


__all__ = ["EvolutionMetricsEmitter", "METRICS_SCHEMA_VERSION", "METRICS_STATE_DIR"]
