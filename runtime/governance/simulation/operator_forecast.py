# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from app.simulation_utils import stable_hash
from runtime import ROOT_DIR
from runtime import metrics

_OPERATOR_SIM_AUDIT_PATH = ROOT_DIR / "reports" / "operator_simulation_audit.jsonl"
_AUDIT_LOCK = threading.Lock()


def _clip(value: float, *, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _count_open_findings(state: dict[str, Any]) -> int:
    findings = state.get("open_findings")
    if not isinstance(findings, list):
        return 0
    unresolved = 0
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        status = str(finding.get("status", "")).strip().lower()
        if status not in {"resolved", "closed", "runbook_delivered"}:
            unresolved += 1
    return unresolved


def _baseline(state: dict[str, Any]) -> dict[str, float]:
    gate_results = state.get("last_gate_results") if isinstance(state.get("last_gate_results"), dict) else {}
    passing = sum(1 for value in gate_results.values() if str(value).strip().lower() == "pass")
    gate_ratio = (passing / 4.0) if gate_results else 0.0

    unresolved_findings = _count_open_findings(state)
    pending_rows = state.get("pending_evidence_rows")
    pending_count = len(pending_rows) if isinstance(pending_rows, list) else 0
    blocked_reason = str(state.get("blocked_reason") or "").strip()
    blocked_count = (1 if blocked_reason else 0) + unresolved_findings + pending_count

    tier2_pass = str(gate_results.get("tier_2", "")).strip().lower() == "pass"

    readiness = _clip(0.45 + (0.35 * gate_ratio) - (0.05 * blocked_count) + (0.03 if tier2_pass else -0.04))
    replay_integrity = _clip(0.55 + (0.35 if tier2_pass else 0.0) + (0.1 * gate_ratio) - (0.04 * unresolved_findings))
    queue_throughput = _clip(0.5 + (0.3 * gate_ratio) - (0.18 if blocked_reason else 0.0) - (0.03 * blocked_count))

    return {
        "readiness": readiness,
        "blocker_count": float(max(0, blocked_count)),
        "replay_integrity": replay_integrity,
        "queue_throughput": queue_throughput,
    }


def _apply_action(projection: dict[str, float], action: dict[str, Any]) -> tuple[dict[str, float], str]:
    action_type = str(action.get("type") or "").strip().lower()
    out = dict(projection)

    if action_type == "prioritize_replay_hardening":
        strength = _clip(float(action.get("strength", 0.5)))
        out["replay_integrity"] = _clip(out["replay_integrity"] + (0.2 * strength))
        out["readiness"] = _clip(out["readiness"] + (0.06 * strength))
        out["queue_throughput"] = _clip(out["queue_throughput"] - (0.05 * strength))
        out["blocker_count"] = max(0.0, out["blocker_count"] - (0.35 * strength))
        return out, "Replay-focused hardening improves integrity and slightly slows throughput."

    if action_type == "pause_mutation_lane":
        enabled = bool(action.get("enabled", True))
        if enabled:
            out["queue_throughput"] = _clip(out["queue_throughput"] * 0.35)
            out["replay_integrity"] = _clip(out["replay_integrity"] + 0.08)
            out["readiness"] = _clip(out["readiness"] - 0.05)
            out["blocker_count"] = max(0.0, out["blocker_count"] + 1.0)
            return out, "Pausing the mutation lane reduces throughput while limiting replay risk growth."
        return out, "Mutation lane remains active; no direct pause effect was applied."

    if action_type == "increase_review_strictness":
        level = _clip(float(action.get("level", 0.5)))
        out["replay_integrity"] = _clip(out["replay_integrity"] + (0.1 * level))
        out["queue_throughput"] = _clip(out["queue_throughput"] - (0.12 * level))
        out["readiness"] = _clip(out["readiness"] - (0.02 * level) + (0.01 if out["replay_integrity"] >= 0.9 else 0.0))
        out["blocker_count"] = max(0.0, out["blocker_count"] + (0.8 * level))
        return out, "Stricter reviews increase governance confidence but add queue pressure."

    return out, f"Unknown action '{action_type}' ignored (fail-closed forecast rule set)."


def _confidence(actions: list[dict[str, Any]], state: dict[str, Any]) -> float:
    missing_signals = 0
    if not isinstance(state.get("last_gate_results"), dict):
        missing_signals += 1
    if not isinstance(state.get("open_findings"), list):
        missing_signals += 1
    if not isinstance(state.get("pending_evidence_rows"), list):
        missing_signals += 1
    value = 0.9 - (0.08 * max(0, len(actions) - 1)) - (0.07 * missing_signals)
    return round(_clip(value, minimum=0.35, maximum=0.95), 3)


def run_operator_simulation(*, state: dict[str, Any], actions: list[dict[str, Any]], scenario_name: str = "") -> dict[str, Any]:
    baseline = _baseline(state)
    projected = dict(baseline)
    explanations: list[str] = []

    for action in actions:
        projected, explanation = _apply_action(projected, action)
        explanations.append(explanation)

    response = {
        "ok": True,
        "simulation": True,
        "result_label": "SIMULATED FORECAST — NOT EXECUTION",
        "scenario_name": scenario_name or "unnamed_scenario",
        "assumptions": [
            "Forecast uses deterministic heuristic rules and does not execute live governance actions.",
            "Current ADAAD state is treated as canonical input for baseline metrics.",
            "Throughput and blocker changes are near-term directional estimates, not guarantees.",
        ],
        "confidence": _confidence(actions, state),
        "current": {
            "readiness": round(baseline["readiness"], 4),
            "blocker_count": _to_int(round(baseline["blocker_count"])),
            "replay_integrity": round(baseline["replay_integrity"], 4),
            "queue_throughput": round(baseline["queue_throughput"], 4),
        },
        "predicted": {
            "readiness": round(projected["readiness"], 4),
            "blocker_count": _to_int(round(projected["blocker_count"])),
            "replay_integrity": round(projected["replay_integrity"], 4),
            "queue_throughput": round(projected["queue_throughput"], 4),
        },
        "delta": {
            "readiness": round(projected["readiness"] - baseline["readiness"], 4),
            "blocker_count": _to_int(round(projected["blocker_count"] - baseline["blocker_count"])),
            "replay_integrity": round(projected["replay_integrity"] - baseline["replay_integrity"], 4),
            "queue_throughput": round(projected["queue_throughput"] - baseline["queue_throughput"], 4),
        },
        "action_effects": explanations,
    }

    record = {
        "event_type": "operator_simulation.v1",
        "simulation_id": stable_hash({"state": state, "actions": actions, "scenario_name": response["scenario_name"]}),
        "input": {
            "scenario_name": response["scenario_name"],
            "actions": actions,
            "state_digest": stable_hash(state),
        },
        "output": {
            "predicted": response["predicted"],
            "delta": response["delta"],
            "confidence": response["confidence"],
        },
    }

    _append_audit_record(record)
    metrics.log("operator_simulation_forecast", payload=record)

    response["simulation_id"] = record["simulation_id"]
    return response


def _append_audit_record(record: dict[str, Any]) -> None:
    _OPERATOR_SIM_AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n"
    with _AUDIT_LOCK:
        with _OPERATOR_SIM_AUDIT_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line)
