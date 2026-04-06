# SPDX-License-Identifier: Apache-2.0
"""Strategy capability synthesis for ADAAD operational guidance.

The capability is advisory-only and deterministic. It never emits bypass guidance;
all recommendations explicitly require constitutional gates and replay integrity.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

from runtime.metrics import METRICS_PATH


@dataclass(frozen=True)
class AgentSignal:
    """Normalized per-agent health/workload state used for prioritization."""

    agent_id: str
    health: float
    workload: float
    readiness: float
    source: str


class StrategyCapability:
    """Build an action-priority stack with constitutional guardrails."""

    _REPLAY_STABILIZE_THRESHOLD = 0.65
    _BLOCKER_THRESHOLD = 0.70
    _MUTATION_STAGE_THRESHOLD = 0.62

    def build(self, *, epoch_id: str, routing_health: Mapping[str, Any], governance_health_score: float) -> dict[str, Any]:
        signals = self._collect_signals()
        readiness = self._compute_readiness(signals=signals, routing_health=routing_health, governance_health_score=governance_health_score)
        priority_stack = self._priority_stack(epoch_id=epoch_id, signals=signals, readiness=readiness)
        jump_links = self._jump_links(epoch_id)
        digest_payload = {
            "epoch_id": epoch_id,
            "signals": [s.__dict__ for s in signals],
            "readiness": readiness,
            "priority_ids": [item["action_id"] for item in priority_stack],
        }
        report_digest = sha256(json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        return {
            "version": "1.0",
            "epoch_id": str(epoch_id or "current"),
            "readiness": readiness,
            "agent_signals": [s.__dict__ for s in signals],
            "action_priority_stack": priority_stack,
            "constitutional_constraints": [
                "fail_closed_enforced",
                "governance_gate_required",
                "replay_integrity_required",
                "no_bypass_recommendations",
            ],
            "jump_links": jump_links,
            "report_digest": report_digest,
        }

    def _priority_stack(self, *, epoch_id: str, signals: tuple[AgentSignal, ...], readiness: dict[str, float | str]) -> list[dict[str, Any]]:
        replay_risk = max(0.0, 1.0 - float(readiness["overall_score"]))
        blocker_pressure = max(0.0, float(readiness["workload_pressure"]) - float(readiness["overall_score"]))
        mutation_readiness = max(0.0, float(readiness["overall_score"]) - float(readiness["workload_pressure"]))

        candidates = [
            {
                "action_id": "stabilize_replay",
                "priority_score": round(0.70 * replay_risk + 0.30 * (1.0 - float(readiness["constitutional_clearance"])), 6),
                "recommended": replay_risk >= self._REPLAY_STABILIZE_THRESHOLD,
                "why_now": (
                    f"Epoch {epoch_id}: replay risk is {replay_risk:.2f}; deterministic replay should be stabilized before new mutations."
                ),
                "readiness_gate": "requires_replay_digest_match",
                "jump_link": f"/governance/health?epoch_id={epoch_id}",
            },
            {
                "action_id": "clear_blockers",
                "priority_score": round(0.60 * blocker_pressure + 0.40 * float(readiness["workload_pressure"]), 6),
                "recommended": blocker_pressure >= self._BLOCKER_THRESHOLD,
                "why_now": (
                    f"Epoch {epoch_id}: workload pressure is {float(readiness['workload_pressure']):.2f}; clearing blockers protects constitutional lane throughput."
                ),
                "readiness_gate": "requires_governance_checks_green",
                "jump_link": f"/governance/review-pressure?epoch_id={epoch_id}",
            },
            {
                "action_id": "stage_mutation_batch",
                "priority_score": round(0.65 * mutation_readiness + 0.35 * float(readiness["overall_score"]), 6),
                "recommended": mutation_readiness >= self._MUTATION_STAGE_THRESHOLD,
                "why_now": (
                    f"Epoch {epoch_id}: readiness is {float(readiness['overall_score']):.2f}; staging a mutation batch is safe only after gate preconditions are satisfied."
                ),
                "readiness_gate": "requires_constitutional_preflight_pass",
                "jump_link": "/api/ui/dork/event",
            },
        ]
        return sorted(candidates, key=lambda item: (-float(item["priority_score"]), item["action_id"]))

    def _compute_readiness(
        self,
        *,
        signals: tuple[AgentSignal, ...],
        routing_health: Mapping[str, Any],
        governance_health_score: float,
    ) -> dict[str, float | str]:
        if not signals:
            return {
                "overall_score": 0.0,
                "workload_pressure": 1.0,
                "constitutional_clearance": 0.0,
                "status": "red",
            }
        mean_health = sum(signal.health for signal in signals) / len(signals)
        mean_workload = sum(signal.workload for signal in signals) / len(signals)
        routing_score = self._clamp(float(routing_health.get("health_score", 1.0)))
        constitutional_clearance = self._clamp(min(governance_health_score, routing_score))
        overall_score = self._clamp(0.45 * mean_health + 0.35 * constitutional_clearance + 0.20 * (1.0 - mean_workload))

        status = "green"
        if overall_score < 0.60:
            status = "red"
        elif overall_score < 0.80:
            status = "amber"

        return {
            "overall_score": round(overall_score, 6),
            "workload_pressure": round(mean_workload, 6),
            "constitutional_clearance": round(constitutional_clearance, 6),
            "status": status,
        }

    def _collect_signals(self) -> tuple[AgentSignal, ...]:
        metrics = self._read_recent_metrics(limit=400)
        architect_health = self._latest_architect_health(metrics)
        architect_workload = self._latest_architect_workload(metrics)
        dream_health, dream_workload = self._latest_dream_signals(metrics)
        beast_health, beast_workload = self._latest_beast_signals(metrics)

        signals = (
            AgentSignal("architect", architect_health, architect_workload, self._clamp(architect_health * (1.0 - architect_workload)), "metrics"),
            AgentSignal("dream", dream_health, dream_workload, self._clamp(dream_health * (1.0 - dream_workload)), "metrics"),
            AgentSignal("beast", beast_health, beast_workload, self._clamp(beast_health * (1.0 - beast_workload)), "metrics"),
        )
        return signals

    def _read_recent_metrics(self, *, limit: int) -> list[dict[str, Any]]:
        path = Path(METRICS_PATH)
        if not path.exists():
            return []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return []
        records: list[dict[str, Any]] = []
        for line in lines[-max(0, int(limit)):]:
            try:
                payload = json.loads(line)
            except Exception:
                continue
            if isinstance(payload, dict):
                records.append(payload)
        return records

    @staticmethod
    def _latest_architect_health(metrics: list[dict[str, Any]]) -> float:
        for entry in reversed(metrics):
            if entry.get("event") != "architect_scan":
                continue
            payload = entry.get("payload")
            if isinstance(payload, dict):
                return 1.0 if bool(payload.get("valid", False)) else 0.0
        return 0.5

    @staticmethod
    def _latest_architect_workload(metrics: list[dict[str, Any]]) -> float:
        for entry in reversed(metrics):
            if entry.get("event") != "architect_proposals":
                continue
            payload = entry.get("payload")
            if isinstance(payload, dict):
                count = float(payload.get("count", 0.0) or 0.0)
                return StrategyCapability._clamp(count / 10.0)
        return 0.0

    @staticmethod
    def _latest_dream_signals(metrics: list[dict[str, Any]]) -> tuple[float, float]:
        for entry in reversed(metrics):
            if entry.get("event") != "dream_discovery":
                continue
            payload = entry.get("payload")
            if isinstance(payload, dict):
                task_count = float(payload.get("task_count", 0.0) or 0.0)
                health = 1.0 if task_count > 0 else 0.4
                workload = StrategyCapability._clamp(task_count / 8.0)
                return health, workload
        return 0.6, 0.0

    @staticmethod
    def _latest_beast_signals(metrics: list[dict[str, Any]]) -> tuple[float, float]:
        for entry in reversed(metrics):
            if entry.get("event") != "beast_cycle_end":
                continue
            payload = entry.get("payload")
            if not isinstance(payload, dict):
                continue
            status = str(payload.get("status") or "")
            if status in {"promoted", "discarded", "no_staged"}:
                health = 1.0
            elif status in {"throttled", "sandboxed", "skipped"}:
                health = 0.7
            else:
                health = 0.4
            workload = 0.8 if status in {"throttled", "sandboxed"} else 0.4 if status == "no_staged" else 0.6
            return health, workload
        return 0.7, 0.2

    @staticmethod
    def _jump_links(epoch_id: str) -> list[dict[str, str]]:
        return [
            {"label": "Governance Health", "href": f"/governance/health?epoch_id={epoch_id}"},
            {"label": "Routing Health", "href": "/governance/routing-health"},
            {"label": "Review Pressure", "href": f"/governance/review-pressure?epoch_id={epoch_id}"},
            {"label": "Telemetry Analytics", "href": "/telemetry/analytics?window_size=200"},
            {"label": "UI Event Intake", "href": "/api/ui/dork/event"},
        ]

    @staticmethod
    def _clamp(value: float) -> float:
        return min(max(round(float(value), 6), 0.0), 1.0)
