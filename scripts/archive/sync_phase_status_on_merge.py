#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Sync Phase 65 status to shipped after PR-PHASE65-01 merge.

This script performs file-only mutations; orchestrator workflow owns commit/push.

Fail-closed, deterministic, idempotent updater for:
- ROADMAP.md
- docs/governance/ADAAD_PR_PROCESSION_2026-03-v2.md

The script will abort without writing if:
- release evidence validation fails
- required anchors are missing
- Phase 65 dependency (Phase 64 shipped) is unmet
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROADMAP_PATH = Path("ROADMAP.md")
PROCESSION_PATH = Path("docs/governance/ADAAD_PR_PROCESSION_2026-03-v2.md")

ROADMAP_PHASE65_ROW_BEFORE = (
    "| 65 | PR-PHASE65-01 ([MUTATION-TARGET](docs/governance/ARCHITECT_SPEC_v8.0.0.md#mutation-target)) "
    "| 64 | critical | Yes — HUMAN-0 (`MUTATION-TARGET`) + AUDIT-0 + REPLAY-0 | next | pending |"
)
ROADMAP_PHASE65_ROW_AFTER = (
    "| 65 | PR-PHASE65-01 ([MUTATION-TARGET](docs/governance/ARCHITECT_SPEC_v8.0.0.md#mutation-target)) "
    "| 64 | critical | Yes — HUMAN-0 (`MUTATION-TARGET`) + AUDIT-0 + REPLAY-0 | shipped | complete |"
)
ROADMAP_NEXT_BEFORE = "**Next:** Phase 65 — Emergence (First Autonomous Capability Evolution, v9.0.0)"
ROADMAP_NEXT_AFTER = "**Next:** Post-v9.0.0 program item — Phase 66 planning + v1.0.0-GA closure" 

PROCESSION_PHASE65_ROW_BEFORE = "| 65 | v9.0.0 | Phase 64 | next |"
PROCESSION_PHASE65_ROW_AFTER = "| 65 | v9.0.0 | Phase 64 | shipped |"
PROCESSION_NEXT_BEFORE = "- Next: **Phase 65** (First Autonomous Capability Evolution, v9.0.0)."
PROCESSION_NEXT_AFTER = "- Next: **Post-Phase-65 program item** (Phase 66 planning + v1.0.0-GA closure)."
PROCESSION_ACTIVE_PHASE_BEFORE = '  active_phase: "phase64_complete"'
PROCESSION_ACTIVE_PHASE_AFTER = '  active_phase: "phase65_complete"'
PROCESSION_MILESTONE_BEFORE = '  milestone: "v8.7.0"'
PROCESSION_MILESTONE_AFTER = '  milestone: "v9.0.0"'
PROCESSION_EXPECTED_ACTIVE_BEFORE = '    expected_active_phase: "Phase 64 COMPLETE · v8.7.0"'
PROCESSION_EXPECTED_ACTIVE_AFTER = '    expected_active_phase: "Phase 65 COMPLETE · v9.0.0"'
PROCESSION_EXPECTED_NEXT_BEFORE = (
    '    expected_next_pr: "PR-PHASE65-01 (Phase 65 — First Autonomous Capability Evolution)"'
)
PROCESSION_EXPECTED_NEXT_AFTER = (
    '    expected_next_pr: "POST-PHASE65 (Phase 66 planning + v1.0.0-GA closure)"'
)

_ORCHESTRATOR_ENV_MARKER = "ADAAD_ORCHESTRATOR_RUN"


def _fatal(code: str, message: str) -> "NoReturn":
    print(json.dumps({"event": code, "message": message}), flush=True)
    raise SystemExit(1)


def _assert_orchestrator_context() -> None:
    """Fail closed in CI unless orchestrator marker is present."""
    ci = os.getenv("CI", "").strip().lower()
    marker = os.getenv(_ORCHESTRATOR_ENV_MARKER, "").strip()
    if ci in {"1", "true", "yes"} and not marker:
        _fatal(
            "PHASE_SYNC_ERROR_MISSING_ORCHESTRATOR_MARKER",
            "sync_phase_status_on_merge.py must be invoked by post_merge_orchestrator.yml in CI",
        )


class SyncError(RuntimeError):
    """Fail-closed sync error."""


@dataclass
class SyncResult:
    files_changed: int


def _replace_exact(content: str, before: str, after: str, label: str) -> str:
    if before in content:
        return content.replace(before, after, 1)
    if after in content:
        return content
    raise SyncError(f"missing required anchor for {label}")


def _validate_release_evidence(root: Path) -> None:
    cmd = [
        sys.executable,
        "scripts/validate_release_evidence.py",
        "--require-complete",
    ]
    proc = subprocess.run(cmd, cwd=root, check=False)
    if proc.returncode != 0:
        raise SyncError("release evidence validation failed; refusing to mutate docs")


def _check_dependencies(roadmap: str, procession: str) -> None:
    if "| 64 |" not in roadmap or "| 65 |" not in roadmap:
        raise SyncError("missing Phase 64/65 rows in ROADMAP tracker")
    phase64_ok = "| 64 |" in roadmap and "| 64 | PR-PHASE64-01" in roadmap and "| shipped | complete |" in roadmap
    if not phase64_ok:
        raise SyncError("Phase 64 dependency not satisfied in ROADMAP tracker")

    if "| 64 | v8.7.0 | Phase 63 | shipped |" not in procession:
        raise SyncError("Phase 64 dependency not satisfied in procession table")
    if "| 65 | v9.0.0 | Phase 64 | next |" not in procession and "| 65 | v9.0.0 | Phase 64 | shipped |" not in procession:
        raise SyncError("Phase 65 row missing or malformed in procession table")


def _update_roadmap(content: str) -> str:
    updated = _replace_exact(content, ROADMAP_PHASE65_ROW_BEFORE, ROADMAP_PHASE65_ROW_AFTER, "ROADMAP phase-65 tracker row")
    updated = _replace_exact(updated, ROADMAP_NEXT_BEFORE, ROADMAP_NEXT_AFTER, "ROADMAP next pointer")
    return updated


def _update_procession(content: str) -> str:
    updated = _replace_exact(content, PROCESSION_PHASE65_ROW_BEFORE, PROCESSION_PHASE65_ROW_AFTER, "procession phase-65 status row")
    updated = _replace_exact(updated, PROCESSION_NEXT_BEFORE, PROCESSION_NEXT_AFTER, "procession next pointer")
    updated = _replace_exact(updated, PROCESSION_ACTIVE_PHASE_BEFORE, PROCESSION_ACTIVE_PHASE_AFTER, "procession active_phase")
    updated = _replace_exact(updated, PROCESSION_MILESTONE_BEFORE, PROCESSION_MILESTONE_AFTER, "procession milestone")
    updated = _replace_exact(updated, PROCESSION_EXPECTED_ACTIVE_BEFORE, PROCESSION_EXPECTED_ACTIVE_AFTER, "procession expected_active_phase")
    updated = _replace_exact(updated, PROCESSION_EXPECTED_NEXT_BEFORE, PROCESSION_EXPECTED_NEXT_AFTER, "procession expected_next_pr")
    return updated


def sync_phase65_status(root: Path = ROOT, require_evidence: bool = True, write: bool = True) -> SyncResult:
    roadmap_file = root / ROADMAP_PATH
    procession_file = root / PROCESSION_PATH

    roadmap_before = roadmap_file.read_text(encoding="utf-8")
    procession_before = procession_file.read_text(encoding="utf-8")

    _check_dependencies(roadmap_before, procession_before)
    if require_evidence:
        _validate_release_evidence(root)

    roadmap_after = _update_roadmap(roadmap_before)
    procession_after = _update_procession(procession_before)

    files_changed = 0
    if roadmap_after != roadmap_before:
        if write:
            roadmap_file.write_text(roadmap_after, encoding="utf-8")
        files_changed += 1
    if procession_after != procession_before:
        if write:
            procession_file.write_text(procession_after, encoding="utf-8")
        files_changed += 1

    return SyncResult(files_changed=files_changed)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync Phase 65 status on merge")
    parser.add_argument("--root", type=Path, default=ROOT, help="Repo root path")
    parser.add_argument("--dry-run", action="store_true", help="Validate and calculate changes without writing")
    args = parser.parse_args()

    try:
        _assert_orchestrator_context()
        result = sync_phase65_status(root=args.root, require_evidence=True, write=not args.dry_run)
        if args.dry_run:
            # idempotency: second dry-run against already-updated files should still report current state
            print(f"phase65_sync_ok files_changed={result.files_changed}")
        else:
            print(f"phase65_sync_ok files_changed={result.files_changed}")
        return 0
    except SyncError as exc:
        print(f"phase65_sync_error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
