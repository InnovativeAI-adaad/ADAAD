#!/usr/bin/env python3
"""Validate governance runbook references to reduce documentation drift."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

ENDPOINT_SOURCE = REPO_ROOT / "ui" / "aponi_dashboard.py"
DOC_SOURCE = REPO_ROOT / "docs" / "governance" / "incident_playbooks" / "scenario_narratives.md"

ENDPOINTS = (
    "/alerts/evaluate",
    "/risk/instability",
    "/risk/summary",
    "/replay/divergence",
    "/replay/diff",
    "/policy/simulate",
    "/metrics/review-quality",
)

ARTIFACT_PATHS = (
    "docs/governance/fail_closed_recovery_runbook.md",
    "docs/governance/APONI_ALERT_RUNBOOK.md",
    "docs/governance/mutation_lifecycle.md",
    "docs/governance/APONI_V2_FORENSICS_AND_HEALTH_MODEL.md",
    "runtime/evolution/lineage_v2.py",
    "runtime/evolution/governor.py",
    "runtime/constitution.py",
    "security/ledger",
    "tests/test_lineage_v2_integrity.py",
)


def _fail(message: str) -> None:
    print(f"[drift-check] ERROR: {message}")


def main() -> int:
    ok = True

    if not ENDPOINT_SOURCE.exists():
        _fail(f"missing endpoint source: {ENDPOINT_SOURCE.relative_to(REPO_ROOT)}")
        return 1

    endpoint_text = ENDPOINT_SOURCE.read_text(encoding="utf-8")

    for endpoint in ENDPOINTS:
        if endpoint not in endpoint_text:
            ok = False
            _fail(f"endpoint not found in {ENDPOINT_SOURCE.relative_to(REPO_ROOT)}: {endpoint}")

    if not DOC_SOURCE.exists():
        ok = False
        _fail(f"missing narrative doc: {DOC_SOURCE.relative_to(REPO_ROOT)}")
    else:
        doc_text = DOC_SOURCE.read_text(encoding="utf-8")
        for endpoint in ENDPOINTS:
            if endpoint not in doc_text:
                ok = False
                _fail(f"endpoint not referenced in {DOC_SOURCE.relative_to(REPO_ROOT)}: {endpoint}")
        for rel_path in ARTIFACT_PATHS:
            if rel_path not in doc_text:
                ok = False
                _fail(f"artifact path not referenced in {DOC_SOURCE.relative_to(REPO_ROOT)}: {rel_path}")

    for rel_path in ARTIFACT_PATHS:
        path = REPO_ROOT / rel_path
        if not path.exists():
            ok = False
            _fail(f"referenced artifact path does not exist: {rel_path}")

    if not ok:
        return 1

    print("[drift-check] OK: governance runbook references validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
