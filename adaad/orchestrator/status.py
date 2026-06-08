# SPDX-License-Identifier: Apache-2.0
"""ADAAD governance status aggregation helpers."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


PROCESSION_PATH = Path("docs/governance/ADAAD_PR_PROCESSION_2026-03-v2.md")
STATE_PATH = Path(".adaad_agent_state.json")
CLAIMS_EVIDENCE_PATH = Path("docs/comms/claims_evidence_matrix.md")

_ALLOWED_TRIGGER_MODES = {"ADAAD", "DEVADAAD"}
_PASS_STATES = {"pass", "passed", "complete", "completed", "merged", "shipped", "ok"}


@dataclass(frozen=True)
class DependencyReadiness:
    ready: bool
    unmet_dependencies: list[str]
    blocked_reason: str | None


@dataclass(frozen=True)
class AdaadStatusReport:
    schema_version: str
    trigger_mode: str
    next_pr: str
    dependency_readiness: DependencyReadiness
    tiers: dict[str, str]
    pending_evidence_rows: list[str]
    source_files: dict[str, str]
    self_abilities: list[str]  # High-level ADAAD abilities (self-capable surface, Phase 199+ enhancement)


def _extract_expected_next_pr(procession_text: str) -> str:
    match = re.search(r"expected_next_pr:\s*\"([^\"]+)\"", procession_text)
    if not match:
        raise ValueError("procession_contract_missing_expected_next_pr")
    next_pr = match.group(1).strip()
    if not next_pr:
        raise ValueError("procession_contract_empty_expected_next_pr")
    return next_pr


def _extract_phase_status_rows(procession_text: str) -> dict[int, dict[str, str]]:
    rows: dict[int, dict[str, str]] = {}
    for line in procession_text.splitlines():
        match = re.match(r"\|\s*(\d+)\s*\|\s*[^|]+\|\s*([^|]+)\|\s*([^|]+)\|", line)
        if not match:
            continue
        phase = int(match.group(1).strip())
        depends_on = match.group(2).strip()
        status = match.group(3).strip()
        rows[phase] = {"depends_on": depends_on, "status": status}
    return rows


def _normalize_tier_status(value: str | None) -> str:
    lowered = (value or "").strip().lower()
    if lowered in _PASS_STATES:
        return "pass"
    if lowered in {"fail", "failed", "error", "blocked"}:
        return "fail"
    return "unknown"


def _read_last_gate_results(state_payload: dict[str, Any]) -> dict[str, str]:
    gate_results = state_payload.get("last_gate_results")
    raw = gate_results if isinstance(gate_results, dict) else {}
    tier_keys = ("tier_0", "tier_1", "tier_2", "tier_3", "tier_m")
    return {tier: _normalize_tier_status(str(raw.get(tier, ""))) for tier in tier_keys}


def _extract_pending_evidence_rows(claims_text: str) -> list[str]:
    pending: list[str] = []
    pattern = re.compile(r"\|\s*`([^`]+)`\s*\|.*\|\s*([^|]+)\s*\|\s*$")
    for line in claims_text.splitlines():
        match = pattern.search(line)
        if not match:
            continue
        claim_id = match.group(1).strip()
        status = match.group(2).strip().lower()
        if status != "complete":
            pending.append(claim_id)
    return pending


def _resolve_dependency_readiness(*, next_pr: str, phase_rows: dict[int, dict[str, str]], blocked_reason: str | None) -> DependencyReadiness:
    unmet_dependencies: list[str] = []
    phase_match = re.search(r"Phase\s*(\d+)", next_pr, re.IGNORECASE)
    if phase_match:
        phase = int(phase_match.group(1))
        row = phase_rows.get(phase)
        if row:
            depends_on = row.get("depends_on", "")
            dep_match = re.search(r"Phase\s*(\d+)", depends_on, re.IGNORECASE)
            if dep_match:
                dep_phase = int(dep_match.group(1))
                dep_row = phase_rows.get(dep_phase)
                dep_status = (dep_row or {}).get("status", "")
                if _normalize_tier_status(dep_status) != "pass":
                    unmet_dependencies.append(
                        f"Phase {phase} depends on Phase {dep_phase} but dependency status is '{dep_status or 'unknown'}'"
                    )
    if blocked_reason:
        unmet_dependencies.append(f"blocked_reason:{blocked_reason}")
    return DependencyReadiness(ready=not unmet_dependencies, unmet_dependencies=unmet_dependencies, blocked_reason=blocked_reason)


def build_status_report(*, repo_root: Path, trigger_mode: str = "ADAAD") -> AdaadStatusReport:
    normalized_mode = trigger_mode.strip().upper()
    if normalized_mode not in _ALLOWED_TRIGGER_MODES:
        raise ValueError(f"invalid_trigger_mode:{trigger_mode}")

    procession_path = repo_root / PROCESSION_PATH
    state_path = repo_root / STATE_PATH
    claims_path = repo_root / CLAIMS_EVIDENCE_PATH

    procession_text = procession_path.read_text(encoding="utf-8")
    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    claims_text = claims_path.read_text(encoding="utf-8")

    next_pr = _extract_expected_next_pr(procession_text)
    phase_rows = _extract_phase_status_rows(procession_text)
    blocked_reason = state_payload.get("blocked_reason")
    if blocked_reason is not None:
        blocked_reason = str(blocked_reason)

    dependency = _resolve_dependency_readiness(next_pr=next_pr, phase_rows=phase_rows, blocked_reason=blocked_reason)
    pending_rows = _extract_pending_evidence_rows(claims_text)

    self_abilities: list[str] = []
    try:
        from adaad.abilities import list_abilities  # adaad: import-boundary-ok:status-self-capabilities
        self_abilities = [a.name for a in list_abilities()]
    except Exception:
        self_abilities = ["(discovery unavailable)"]

    return AdaadStatusReport(
        schema_version="adaad_status.v1",
        trigger_mode=normalized_mode,
        next_pr=next_pr,
        dependency_readiness=dependency,
        tiers=_read_last_gate_results(state_payload),
        pending_evidence_rows=pending_rows,
        source_files={
            "procession": PROCESSION_PATH.as_posix(),
            "state": STATE_PATH.as_posix(),
            "claims_evidence": CLAIMS_EVIDENCE_PATH.as_posix(),
        },
        self_abilities=self_abilities,
    )


def render_human_table(report: AdaadStatusReport) -> str:
    readiness = "READY" if report.dependency_readiness.ready else "BLOCKED"
    pending = ", ".join(report.pending_evidence_rows) if report.pending_evidence_rows else "none"
    lines = [
        "ADAAD Status Summary",
        "====================",
        f"Trigger mode         : {report.trigger_mode}",
        f"Next PR              : {report.next_pr}",
        f"Dependency readiness : {readiness}",
    ]
    if report.dependency_readiness.unmet_dependencies:
        lines.append("Unmet dependencies   : " + "; ".join(report.dependency_readiness.unmet_dependencies))

    lines.extend(
        [
            "",
            "Gate tiers",
            "----------",
            f"Tier 0: {report.tiers['tier_0']}",
            f"Tier 1: {report.tiers['tier_1']}",
            f"Tier 2: {report.tiers['tier_2']}",
            f"Tier 3: {report.tiers['tier_3']}",
            f"Tier M: {report.tiers['tier_m']}",
            "",
            f"Pending evidence rows: {pending}",
            "",
            f"Self abilities (high-level): {', '.join(report.self_abilities) if report.self_abilities else 'none'}",
        ]
    )
    return "\n".join(lines)


def report_as_json(report: AdaadStatusReport) -> str:
    return json.dumps(asdict(report), indent=2, sort_keys=True)
