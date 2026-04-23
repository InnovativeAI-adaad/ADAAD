# SPDX-License-Identifier: Apache-2.0
"""Runbook composition helpers for live ADAAD governance state."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from adaad.orchestrator.status import AdaadStatusReport


@dataclass(frozen=True)
class RunbookStep:
    index: int
    title: str
    action: str
    endpoints_panels: list[str]
    evidence_requirements: list[str]


@dataclass(frozen=True)
class RunbookDocument:
    schema_version: str
    generated_at_utc: str
    trigger_mode: str
    verbosity_mode: str
    scenario_class: str
    scenario_reason: str
    next_pr: str
    blocked_reason: str | None
    steps: list[RunbookStep]


@dataclass(frozen=True)
class RunbookArtifacts:
    runbook: RunbookDocument
    markdown_path: str
    json_path: str


_VALID_VERBOSITY = {"compact", "full_governance"}


def detect_scenario_class(report: AdaadStatusReport) -> tuple[str, str]:
    blocked_reason = report.dependency_readiness.blocked_reason
    if blocked_reason:
        lowered = blocked_reason.lower()
        if "replay" in lowered or "diverg" in lowered:
            return "replay_incident", f"blocked_reason={blocked_reason}"
        return "blocker_escalation", f"blocked_reason={blocked_reason}"

    if report.tiers.get("tier_2") == "fail":
        return "replay_incident", "tier_2 gate reported fail"

    any_failed = any(value == "fail" for value in report.tiers.values())
    if any_failed or not report.dependency_readiness.ready:
        return "blocker_escalation", "gate/dependency readiness failure"

    if report.trigger_mode == "DEVADAAD" and report.tiers.get("tier_0") == "pass" and report.tiers.get("tier_1") == "pass":
        return "pre_release", "merge-authority readiness checks active"

    return "normal_ops", "default healthy operational state"


def _step(
    index: int,
    title: str,
    action: str,
    *,
    endpoints_panels: list[str],
    evidence: list[str],
) -> RunbookStep:
    return RunbookStep(
        index=index,
        title=title,
        action=action,
        endpoints_panels=endpoints_panels,
        evidence_requirements=evidence,
    )


def compose_runbook(*, report: "AdaadStatusReport", verbosity_mode: str) -> RunbookDocument:
    normalized = verbosity_mode.strip().lower()
    if normalized not in _VALID_VERBOSITY:
        raise ValueError(f"invalid_verbosity_mode:{verbosity_mode}")

    scenario_class, reason = detect_scenario_class(report)

    baseline_steps = [
        _step(
            1,
            "Capture current governance snapshot",
            f"Record trigger mode={report.trigger_mode}, next_pr={report.next_pr}, and gate tiers before remediation.",
            endpoints_panels=[
                "CLI: python -m app.main --adaad-status --status-format both",
                "Aponi panel: ui/aponi/index.html",
                "Aponi replay inspector: ui/aponi/replay_inspector.js",
            ],
            evidence=[
                "Persist ADAAD status JSON in operator handoff package",
                "Reference claims matrix pending rows from docs/comms/claims_evidence_matrix.md",
            ],
        ),
    ]

    scenario_steps: dict[str, list[RunbookStep]] = {
        "normal_ops": [
            _step(
                2,
                "Run Tier 0 preflight",
                "Execute Tier 0 gates before any change and attach outputs.",
                endpoints_panels=[
                    "script: python scripts/validate_governance_schemas.py",
                    "script: python scripts/validate_architecture_snapshot.py",
                    "script: python tools/lint_import_paths.py",
                ],
                evidence=["Attach Tier 0 command outputs to handoff notes"],
            ),
            _step(
                3,
                "Update evidence ledger row",
                "Ensure evidence row is complete for staged PR scope.",
                endpoints_panels=["File: docs/comms/claims_evidence_matrix.md"],
                evidence=["scripts/validate_release_evidence.py --require-complete passes"],
            ),
        ],
        "replay_incident": [
            _step(
                2,
                "Execute strict replay diagnostics",
                "Run strict replay verification against the target epoch/sha and capture divergence artifacts.",
                endpoints_panels=[
                    "CLI: python -m app.main replay verify --mode strict",
                    "CLI: python -m app.main replay divergence-report --mode audit",
                    "Runbook: docs/governance/fail_closed_recovery_runbook.md",
                ],
                evidence=[
                    "Replay manifest and divergence report artifacts stored under security/replay_artifacts",
                    "Incident timeline note linked in governance docs",
                ],
            ),
            _step(
                3,
                "Escalate with fail-closed state",
                "Do not mutate source until replay divergence is resolved and validated.",
                endpoints_panels=[
                    "Endpoint: /api/v1/admin/runbooks/production/complete",
                    "Aponi panel: ui/aponi/replay_inspector.js",
                ],
                evidence=["Document blocked reason and operator owner in handoff markdown"],
            ),
        ],
        "blocker_escalation": [
            _step(
                2,
                "Classify blocker and owner",
                "Map blocker to dependency, evidence, or gate failure and assign explicit owner.",
                endpoints_panels=[
                    "CLI: python -m app.main --adaad-status --status-format json",
                    "Script: python scripts/validate_release_evidence.py --require-complete",
                ],
                evidence=["Blocked reason and remediation owner recorded"],
            ),
            _step(
                3,
                "Re-run required gates after fix",
                "Re-run Tier 0 and Tier 1 gates to confirm blocker removal.",
                endpoints_panels=[
                    "script: python scripts/validate_governance_schemas.py",
                    "script: PYTHONPATH=. pytest tests/ -q",
                ],
                evidence=["Attach gate rerun outputs and update claims matrix status"],
            ),
        ],
        "pre_release": [
            _step(
                2,
                "Validate release gates",
                "Run full Tier 1 and Tier 3 release evidence checks in merge-ready context.",
                endpoints_panels=[
                    "script: PYTHONPATH=. pytest tests/ -q",
                    "script: python scripts/verify_critical_artifacts.py",
                    "script: python scripts/validate_release_evidence.py --require-complete",
                ],
                evidence=["All release checks recorded with zero failures"],
            ),
            _step(
                3,
                "Finalize operator handoff",
                "Export runbook bundle and include governance references for reviewer/approver traceability.",
                endpoints_panels=[
                    "Endpoint: /api/admin/runbooks/production/complete",
                    "Governance contract: docs/governance/ADAAD_PR_PROCESSION_2026-03-v2.md",
                ],
                evidence=["Handoff bundle includes markdown + json runbook artifacts"],
            ),
        ],
    }

    steps = baseline_steps + scenario_steps[scenario_class]

    if normalized == "full_governance":
        steps.append(
            _step(
                index=len(steps) + 1,
                title="Governance completeness attest",
                action="Confirm lane, CI tier, prerequisites, and evidence completeness before stage/merge.",
                endpoints_panels=[
                    "Governance doc: docs/governance/ci-gating.md",
                    "Claims matrix: docs/comms/claims_evidence_matrix.md",
                    "Procession contract: docs/governance/ADAAD_PR_PROCESSION_2026-03-v2.md",
                ],
                evidence=[
                    "Lane and CI tier captured in handoff",
                    "Prerequisite dependency readiness confirmed",
                    "Evidence row status marked Complete",
                ],
            )
        )

    return RunbookDocument(
        schema_version="adaad_runbook.v1",
        generated_at_utc=datetime.now(timezone.utc).isoformat(),
        trigger_mode=report.trigger_mode,
        verbosity_mode=normalized,
        scenario_class=scenario_class,
        scenario_reason=reason,
        next_pr=report.next_pr,
        blocked_reason=report.dependency_readiness.blocked_reason,
        steps=steps,
    )


def render_runbook_markdown(runbook: RunbookDocument) -> str:
    lines = [
        "# ADAAD Live Runbook",
        "",
        f"- Generated at (UTC): `{runbook.generated_at_utc}`",
        f"- Trigger mode: `{runbook.trigger_mode}`",
        f"- Verbosity mode: `{runbook.verbosity_mode}`",
        f"- Scenario class: `{runbook.scenario_class}`",
        f"- Scenario reason: {runbook.scenario_reason}",
        f"- Next PR: `{runbook.next_pr}`",
        f"- Blocked reason: `{runbook.blocked_reason or 'none'}`",
        "",
        "## Step-by-step actions",
    ]
    for step in runbook.steps:
        lines.extend(
            [
                f"### {step.index}. {step.title}",
                f"{step.action}",
                "",
                "**Endpoints / Panels**",
                *[f"- {entry}" for entry in step.endpoints_panels],
                "",
                "**Evidence requirements**",
                *[f"- {entry}" for entry in step.evidence_requirements],
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def export_runbook_artifacts(
    *,
    runbook: RunbookDocument,
    output_dir: Path,
) -> RunbookArtifacts:
    output_dir.mkdir(parents=True, exist_ok=True)

    stamp = runbook.generated_at_utc.replace(":", "-").replace("+00:00", "Z")
    base_name = f"adaad_runbook_{runbook.scenario_class}_{stamp}"
    markdown_path = output_dir / f"{base_name}.md"
    json_path = output_dir / f"{base_name}.json"

    markdown_path.write_text(render_runbook_markdown(runbook), encoding="utf-8")
    json_path.write_text(json.dumps(asdict(runbook), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return RunbookArtifacts(
        runbook=runbook,
        markdown_path=markdown_path.as_posix(),
        json_path=json_path.as_posix(),
    )


def render_runbook_summary(artifacts: RunbookArtifacts) -> str:
    runbook = artifacts.runbook
    lines = [
        "ADAAD Runbook Composer",
        "======================",
        f"Scenario class : {runbook.scenario_class}",
        f"Verbosity mode : {runbook.verbosity_mode}",
        f"Next PR        : {runbook.next_pr}",
        f"Markdown       : {artifacts.markdown_path}",
        f"JSON           : {artifacts.json_path}",
    ]
    return "\n".join(lines)
