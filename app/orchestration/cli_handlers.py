# SPDX-License-Identifier: Apache-2.0
"""CLI handlers for app.main facade commands."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from app import APP_ROOT
from adaad.orchestrator.runbook_composer import export_runbook_artifacts, render_runbook_summary
from adaad.orchestrator.status import build_status_report, render_human_table, report_as_json
from runtime.api.app_layer import classify_current_changes, get_operating_mode, get_required_gate_tiers
from runtime.api.runtime_services import (
    EvolutionRuntime,
    ReplayProofBuilder,
    ReplayStateMachine,
    build_replay_divergence_artifacts,
    build_replay_manifest_v1,
    canonical_json,
    normalize_replay_mode,
    now_iso,
    write_replay_manifest_v1,
)


def build_main_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ADAAD orchestrator")
    subparsers = parser.add_subparsers(dest="namespace")

    replay_parser = subparsers.add_parser("replay", help="Deterministic replay command namespace.")
    replay_subparsers = replay_parser.add_subparsers(dest="replay_command", required=True)

    verify_parser = replay_subparsers.add_parser("verify", help="Run replay verification and emit deterministic JSON.")
    verify_parser.add_argument("--epoch", default="", help="Replay a specific epoch id as the verification target.")
    verify_parser.add_argument("--mode", choices=("strict", "audit", "off"), default="strict", help="Replay verification mode.")

    manifest_parser = replay_subparsers.add_parser("manifest", help="Generate replay manifest v1 JSON.")
    manifest_parser.add_argument("--epoch", default="", help="Replay a specific epoch id as the verification target.")
    manifest_parser.add_argument("--mode", choices=("strict", "audit", "off"), default="audit", help="Replay verification mode.")
    manifest_parser.add_argument("--output", default="", help="Optional output path for manifest JSON.")

    divergence_parser = replay_subparsers.add_parser(
        "divergence-report",
        help="Generate replay divergence report artifacts and emit deterministic JSON.",
    )
    divergence_parser.add_argument("--epoch", default="", help="Replay a specific epoch id as the verification target.")
    divergence_parser.add_argument("--mode", choices=("strict", "audit", "off"), default="audit", help="Replay verification mode.")

    bundle_parser = replay_subparsers.add_parser("bundle", help="Export replay proof bundle for a resolved epoch.")
    bundle_parser.add_argument("--epoch", default="", help="Replay epoch id to export.")
    bundle_parser.add_argument("--pr-id", default="", help="Optional PR id used to resolve an epoch from ledger history.")

    parser.add_argument("--verbose", action="store_true", help="Print boot stage diagnostics to stdout.")
    parser.add_argument("--fast", action="store_true", help="Enable Dev Fast Path (skip expensive gates for non-functional changes).")
    parser.add_argument("--dry-run", action="store_true", help="Evaluate mutations without applying them.")
    parser.add_argument(
        "--replay",
        default="off",
        help=(
            "Replay mode: off (skip replay), audit (verify and continue), strict (verify and fail-close). "
            "Deprecated aliases: full->audit, true->audit, false->off."
        ),
    )
    parser.add_argument("--replay-epoch", default="", help="Replay a specific epoch id as the verification target.")
    parser.add_argument("--epoch", default="", help="Epoch identifier used for replay-proof export or replay targeting.")
    parser.add_argument("--verify-replay", action="store_true", help="Run replay verification and exit after reporting result.")
    parser.add_argument(
        "--exit-after-boot",
        action="store_true",
        help="Complete one governed boot (including replay audit) and exit before any mutation cycle.",
    )
    parser.add_argument(
        "--export-replay-proof",
        action="store_true",
        help="Export a signed replay proof bundle for --epoch and exit.",
    )
    parser.add_argument(
        "--adaad-status",
        action="store_true",
        help="Print ADAAD/DEVADAAD governance status summary and exit.",
    )
    parser.add_argument(
        "--explain-gates",
        action="store_true",
        help="Print detailed rationale for gate triggering/skipping and exit.",
    )
    parser.add_argument(
        "--adaad-runbook",
        action="store_true",
        help="Compose a scenario-aware operator runbook and export markdown/json artifacts.",
    )
    parser.add_argument(
        "--trigger-mode",
        choices=("ADAAD", "DEVADAAD"),
        default="ADAAD",
        help="Trigger mode context for --adaad-status and --adaad-runbook output.",
    )
    parser.add_argument(
        "--status-format",
        choices=("table", "json", "both"),
        default="both",
        help="Output format for --adaad-status.",
    )
    parser.add_argument(
        "--runbook-verbosity",
        choices=("compact", "full_governance"),
        default="compact",
        help="Verbosity mode for --adaad-runbook outputs.",
    )
    parser.add_argument(
        "--runbook-output-dir",
        default="security/adaad_runbooks",
        help="Directory for --adaad-runbook markdown/json artifacts.",
    )
    return parser


def _resolve_epoch_from_pr_id(*, runtime: EvolutionRuntime, pr_id: str) -> str:
    target = pr_id.strip()
    if not target:
        return ""
    matches: list[str] = []
    for epoch_id in runtime.ledger.list_epoch_ids():
        for event in runtime.ledger.read_epoch(epoch_id):
            payload = event.get("payload") or {}
            if isinstance(payload, dict) and str(payload.get("pr_id") or "").strip() == target:
                matches.append(str(epoch_id))
                break
    if not matches:
        return ""
    return sorted(set(matches))[0]


def _emit_json(payload: dict[str, Any]) -> None:
    print(canonical_json(payload))


def _run_replay_preflight(*, mode: str, epoch: str) -> tuple[EvolutionRuntime, dict[str, Any], dict[str, Any]]:
    runtime = EvolutionRuntime()
    replay_mode = normalize_replay_mode(mode)
    preflight = runtime.replay_preflight(replay_mode, epoch_id=epoch or None)
    state_machine = ReplayStateMachine.transition(
        mode=replay_mode.value,
        fail_closed=replay_mode.fail_closed,
        verify_target=str(preflight.get("verify_target") or "none"),
        events=list(preflight.get("results") or []),
    )
    return runtime, preflight, state_machine


def handle_replay_namespace(*, parser: argparse.ArgumentParser, args: argparse.Namespace) -> bool:
    if getattr(args, "namespace", "") != "replay":
        return False

    command = str(getattr(args, "replay_command", "")).strip()
    epoch = str(getattr(args, "epoch", "") or "").strip()
    mode = str(getattr(args, "mode", "") or "audit").strip()

    if command == "verify":
        _, preflight, state_machine = _run_replay_preflight(mode=mode, epoch=epoch)
        _emit_json(
            {
                "schema_version": "replay_cli.verify.v1",
                "command": "verify",
                "mode": mode,
                "epoch": epoch,
                "preflight": preflight,
                "state_machine": state_machine,
            }
        )
        return True

    if command == "manifest":
        _, preflight, state_machine = _run_replay_preflight(mode=mode, epoch=epoch)
        replay_started_at = now_iso()
        replay_finished_at = now_iso()
        manifest = build_replay_manifest_v1(
            replay_started_at=replay_started_at,
            replay_finished_at=replay_finished_at,
            preflight=preflight,
            halted=bool(preflight.get("has_divergence")) and mode == "strict",
        )
        output = str(getattr(args, "output", "") or "").strip()
        destination = Path(output) if output else None
        manifest_path = write_replay_manifest_v1(manifest, manifests_dir=destination.parent if destination else None)
        if destination:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(canonical_json(manifest) + "\n", encoding="utf-8")
            manifest_path = destination
        _emit_json(
            {
                "schema_version": "replay_cli.manifest.v1",
                "command": "manifest",
                "mode": mode,
                "epoch": epoch,
                "manifest_path": manifest_path.as_posix(),
                "manifest": manifest,
                "preflight": preflight,
                "state_machine": state_machine,
            }
        )
        return True

    if command == "divergence-report":
        runtime, preflight, state_machine = _run_replay_preflight(mode=mode, epoch=epoch)
        artifact_payload: dict[str, Any] = {}
        if bool(preflight.get("has_divergence")):
            bundle = build_replay_divergence_artifacts(
                preflight=preflight,
                replay_command=f"python -m app.main replay divergence-report --mode {mode}" + (f" --epoch {epoch}" if epoch else ""),
                replay_env_flags={},
                ledger=runtime.ledger,
                artifacts_root=APP_ROOT.parent / "security" / "replay_artifacts",
            )
            artifact_payload = {
                "artifact_dir": bundle.artifact_dir,
                "machine_report_path": bundle.machine_report_path,
                "human_report_path": bundle.human_report_path,
            }
        _emit_json(
            {
                "schema_version": "replay_cli.divergence_report.v1",
                "command": "divergence-report",
                "mode": mode,
                "epoch": epoch,
                "preflight": preflight,
                "state_machine": state_machine,
                "divergence_artifacts": artifact_payload,
            }
        )
        return True

    if command == "bundle":
        runtime = EvolutionRuntime()
        pr_id = str(getattr(args, "pr_id", "") or "").strip()
        selected_epoch = epoch or _resolve_epoch_from_pr_id(runtime=runtime, pr_id=pr_id)
        if not selected_epoch:
            parser.error("replay bundle requires --epoch <id> or resolvable --pr-id <id>")
        bundle_path = ReplayProofBuilder(ledger=runtime.ledger).write_bundle(selected_epoch)
        _emit_json(
            {
                "schema_version": "replay_cli.bundle.v1",
                "command": "bundle",
                "epoch": selected_epoch,
                "pr_id": pr_id,
                "bundle_path": bundle_path.as_posix(),
            }
        )
        return True

    parser.error(f"unsupported replay command: {command}")
    return True


def handle_export_replay_proof(*, parser: argparse.ArgumentParser, export_replay_proof: bool, selected_epoch: str) -> bool:
    if not export_replay_proof:
        return False
    if not selected_epoch:
        parser.error("--export-replay-proof requires --epoch <id>")
    proof_path = ReplayProofBuilder().write_bundle(selected_epoch)
    print(proof_path.as_posix())
    return True


def handle_status_report(*, adaad_status: bool, trigger_mode: str, status_format: str) -> bool:
    if not adaad_status:
        return False
    report = build_status_report(repo_root=APP_ROOT.parent, trigger_mode=trigger_mode)
    if status_format in {"table", "both"}:
        print(render_human_table(report))
    if status_format in {"json", "both"}:
        if status_format == "both":
            print()
        print(report_as_json(report))
    return True


def handle_runbook_composer(*, adaad_runbook: bool, trigger_mode: str, runbook_verbosity: str, runbook_output_dir: str) -> bool:
    if not adaad_runbook:
        return False
    artifacts = export_runbook_artifacts(
        repo_root=APP_ROOT.parent,
        trigger_mode=trigger_mode,
        verbosity_mode=runbook_verbosity,
        output_dir=APP_ROOT.parent / str(runbook_output_dir),
    )
    print(render_runbook_summary(artifacts))
    return True


def handle_explain_gates(*, explain_gates: bool) -> bool:
    if not explain_gates:
        return False

    
    from runtime.governance.fast_path_policy import get_operating_mode, get_required_gate_tiers
    from runtime.governance.change_classifier import classify_current_changes_decision
    
    mode = get_operating_mode()
    change_decision = classify_current_changes_decision()
    change_type = change_decision.change_type
    required_tiers = get_required_gate_tiers(mode, change_type)
    
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  ADAAD Governance Gate Explanation")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"Operating Mode: {mode.value}")
    print(f"Change Type:    {change_type.value}")
    print(f"Classifier:     {change_decision.reason}")
    print(f"Required Tiers: {sorted(required_tiers)}")
    print("------------------------------------------------------------")
    
    if mode.value == "dev_fast":
        if change_type.value == "non_functional":
            print("RATIONALE: Non-functional changes (docs/comments) in Dev Fast Path")
            print("bypass expensive gates (T1 tests, T2 replay, T3 evidence) to")
            print("increase local iteration speed while preserving static health (T0).")
        else:
            print("RATIONALE: Functional changes in Dev Fast Path skip Tier 3")
            print("(documentation completeness) but require Tier 1 (unit/lint/type)")
            print("to ensure code quality during local dev.")
    else:
        print("RATIONALE: Governed Release Path (or CI) requires the full")
        print("gate stack (T0-T3) to guarantee constitutional compliance.")
    
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return True
