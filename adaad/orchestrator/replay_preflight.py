# SPDX-License-Identifier: Apache-2.0
"""Replay preflight orchestration extracted from app.main."""

from __future__ import annotations

from typing import Any, Callable, Dict

from adaad import APP_ROOT
from runtime.api.runtime_services import (
    REPLAY_MANIFESTS_DIR,
    build_replay_divergence_artifacts,
    build_replay_manifest_v1,
    dump,
    metrics,
    now_iso,
    write_replay_manifest_v1,
)
from security.ledger import journal


def aggregate_replay_score(results: list[Dict[str, Any]]) -> float:
    if not results:
        return 1.0
    scores = [float(result.get("replay_score", 0.0)) for result in results]
    return round(sum(scores) / len(scores), 4)


def write_replay_manifest(manifest: Dict[str, Any]) -> str:
    return str(write_replay_manifest_v1(manifest, manifests_dir=REPLAY_MANIFESTS_DIR))


def execute_replay_preflight(
    orchestrator: Any,
    dump_func: Any,
    *,
    verify_only: bool = False,
    replay_env_flags: Callable[[], Dict[str, str]],
) -> Dict[str, Any]:
    replay_started_at = now_iso()
    mode = orchestrator.replay_mode
    preflight = orchestrator.evolution_runtime.replay_preflight(mode, epoch_id=orchestrator.replay_epoch or None)
    replay_finished_at = now_iso()
    has_divergence = bool(preflight.get("has_divergence"))
    orchestrator.state["replay_mode"] = mode.value
    orchestrator.state["replay_target"] = preflight.get("verify_target")
    orchestrator.state["replay_decision"] = preflight.get("decision")
    orchestrator.state["replay_results"] = preflight.get("results", [])
    orchestrator.state["replay_divergence"] = has_divergence
    orchestrator.state["status"] = "replay_warning" if has_divergence else "replay_verified"
    replay_score = aggregate_replay_score(preflight.get("results", []))
    orchestrator.state["replay_score"] = replay_score
    outcome = {
        "mode": mode.value,
        "verify_only": verify_only,
        "ok": not has_divergence,
        "decision": preflight.get("decision"),
        "target": preflight.get("verify_target"),
        "divergence": has_divergence,
        "results": preflight.get("results", []),
        "divergence_details": preflight.get("divergence_details", []),
        "diagnostics": preflight.get("fail_closed_payload", {}),
        "replay_score": replay_score,
        "ts": replay_finished_at,
    }
    journal.write_entry(agent_id="system", action="replay_verified", payload=outcome)
    try:
        manifest = build_replay_manifest_v1(
            replay_started_at=replay_started_at,
            replay_finished_at=replay_finished_at,
            preflight=preflight,
            halted=has_divergence and mode.fail_closed,
        )
        manifest_path = write_replay_manifest(manifest)
        orchestrator._v(f"Replay manifest written: {manifest_path}")
    except Exception as exc:
        metrics.log(
            event_type="replay_manifest_write_failed",
            payload={"error": str(exc), "mode": outcome["mode"], "target": outcome.get("target")},
            level="WARN",
        )
    if has_divergence:
        replay_command = f"python -m app.main --verify-replay --replay {mode.value}"
        if orchestrator.replay_epoch:
            replay_command += f" --replay-epoch {orchestrator.replay_epoch}"
        try:
            bundle = build_replay_divergence_artifacts(
                preflight=preflight,
                replay_command=replay_command,
                replay_env_flags=replay_env_flags(),
                ledger=orchestrator.evolution_runtime.ledger,
                artifacts_root=APP_ROOT.parent / "security" / "replay_artifacts",
            )
            outcome["divergence_artifacts"] = {
                "artifact_dir": bundle.artifact_dir,
                "machine_report": bundle.machine_report_path,
                "human_report": bundle.human_report_path,
            }
            orchestrator._v("Replay divergence artifacts:")
            orchestrator._v(f"  Dir: {bundle.artifact_dir}")
            orchestrator._v(f"  JSON: {bundle.machine_report_path}")
            orchestrator._v(f"  MD: {bundle.human_report_path}")
        except Exception as exc:
            metrics.log(
                event_type="replay_divergence_artifact_failed",
                payload={"error": str(exc), "mode": outcome["mode"], "target": outcome.get("target")},
                level="WARN",
            )
    if has_divergence and mode.fail_closed:
        orchestrator._fail(
            "replay_divergence",
            payload={
                "artifacts": outcome.get("divergence_artifacts") or {},
                "decision_payload": preflight.get("fail_closed_payload", {}),
            },
        )
    orchestrator._v("Replay Summary:")
    orchestrator._v(f"  Mode: {mode.value}")
    orchestrator._v(f"  Target: {preflight.get('verify_target')}")
    orchestrator._v(f"  Divergence: {has_divergence}")
    orchestrator._v(f"  Score: {replay_score}")
    if verify_only:
        dump_func()
        return {"verify_only": True, **outcome}
    return {"verify_only": False, **outcome}
