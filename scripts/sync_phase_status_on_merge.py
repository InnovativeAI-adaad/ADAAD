#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
sync_phase_status_on_merge.py — ADAAD Phase Status Synchroniser
══════════════════════════════════════════════════════════════════════════════
Invariant codes: PHSYNC-ATOM-0 · PHSYNC-ANCHOR-0 · PHSYNC-IDEM-0

PURPOSE
───────
Updates ROADMAP.md and the PR Procession document after a phase is shipped.
Specifically handles the phase 65 (v9.0.0 Emergence) transition, marking
status columns from "next | pending" to "shipped | complete" and updating
the YAML contract block.

CONSTITUTIONAL INVARIANTS
──────────────────────────
  PHSYNC-ATOM-0    File writes use os.replace for atomicity.
  PHSYNC-ANCHOR-0  Required anchors must be present; missing anchors
                   raise SyncError (fail-closed).
  PHSYNC-IDEM-0    Re-running on already-synced files produces files_changed=0.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# Errors
# ─────────────────────────────────────────────────────────────────────────────

class SyncError(RuntimeError):
    """Raised when a sync pre-condition is not met. PHSYNC-ANCHOR-0."""


# ─────────────────────────────────────────────────────────────────────────────
# Result
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SyncResult:
    files_changed: int
    changes: list[str]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _atomic_write(path: Path, content: str) -> None:
    """PHSYNC-ATOM-0: write via temp + os.replace."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def _validate_release_evidence(root: Path) -> None:
    """
    Validate that release evidence artifacts exist.
    Monkeypatched in tests to be a no-op.
    """
    evidence_path = root / "artifacts" / "governance" / "phase65"
    if not evidence_path.exists():
        raise SyncError(f"missing release evidence directory: {evidence_path.as_posix()}")


# ─────────────────────────────────────────────────────────────────────────────
# ROADMAP.md patch
# ─────────────────────────────────────────────────────────────────────────────

_ROADMAP_NEXT_ANCHOR = "**Next:**"
_ROADMAP_SHIPPED_MARKER = "Post-v9.0.0 program item"


def _patch_roadmap(content: str) -> tuple[str, list[str]]:
    """
    Patch the ROADMAP:
    - Replace '| next | pending |' row for phase 65 with '| shipped | complete |'
    - Ensure '**Next:**' line is updated to point past phase 65
    Returns (updated_content, list_of_changes).
    PHSYNC-ANCHOR-0: raises SyncError if anchor is absent.
    """
    if _ROADMAP_NEXT_ANCHOR not in content:
        raise SyncError(f"missing required anchor '{_ROADMAP_NEXT_ANCHOR}' in ROADMAP.md")

    changes: list[str] = []
    original = content

    # Replace 'next | pending' in the phase-65 table row
    new_content = re.sub(
        r"(\|\s*65\s*\|[^\|]+\|[^\|]+\|[^\|]+\|[^\|]+\|)\s*next\s*\|\s*pending\s*\|",
        lambda m: m.group(1) + " shipped | complete |",
        content,
    )
    if new_content != content:
        changes.append("ROADMAP.phase65.status: next→shipped, pending→complete")
        content = new_content

    # If _ROADMAP_SHIPPED_MARKER not already present, inject a line after the table
    if _ROADMAP_SHIPPED_MARKER not in content:
        # Inject after the phase 65 shipped row
        insert_after = re.search(
            r"(\|\s*65\s*\|.*?shipped.*?\n)",
            content,
            re.DOTALL,
        )
        if insert_after:
            pos = insert_after.end()
            content = (
                content[:pos]
                + f"\n**{_ROADMAP_SHIPPED_MARKER}** — v9.0.0 Emergence complete.\n"
                + content[pos:]
            )
            changes.append(f"ROADMAP: injected '{_ROADMAP_SHIPPED_MARKER}'")

    return content, changes


# ─────────────────────────────────────────────────────────────────────────────
# Procession document patch
# ─────────────────────────────────────────────────────────────────────────────

def _patch_procession(content: str) -> tuple[str, list[str]]:
    """
    Patch the PR Procession doc:
    - Update '| 65 | v9.0.0 | Phase 64 | next |' → '| 65 | v9.0.0 | Phase 64 | shipped |'
    - Update YAML contract block: active_phase, milestone
    Returns (updated_content, list_of_changes).
    """
    changes: list[str] = []
    original = content

    # Update table row: phase 65 status
    new_content = re.sub(
        r"(\|\s*65\s*\|\s*v9\.0\.0\s*\|\s*Phase\s*64\s*\|)\s*next\s*\|",
        r"\g<1> shipped |",
        content,
    )
    if new_content != content:
        changes.append("PROCESSION.phase65.status: next→shipped")
        content = new_content

    # Update YAML block: active_phase
    new_content = re.sub(
        r'(active_phase:\s*)"phase64_complete"',
        r'\g<1>"phase65_complete"',
        content,
    )
    if new_content != content:
        changes.append("PROCESSION.active_phase: phase64_complete→phase65_complete")
        content = new_content

    # Update YAML block: milestone
    new_content = re.sub(
        r'(milestone:\s*)"v8\.7\.0"',
        r'\g<1>"v9.0.0"',
        content,
    )
    if new_content != content:
        changes.append("PROCESSION.milestone: v8.7.0→v9.0.0")
        content = new_content

    return content, changes


# ─────────────────────────────────────────────────────────────────────────────
# Main sync entry point
# ─────────────────────────────────────────────────────────────────────────────

_PROCESSION_REL = "docs/governance/ADAAD_PR_PROCESSION_2026-03-v2.md"


def sync_phase65_status(
    root: Path = Path("."),
    require_evidence: bool = True,
) -> SyncResult:
    """
    Sync phase 65 shipped status into ROADMAP.md and the PR Procession doc.
    PHSYNC-ANCHOR-0: raises SyncError on missing anchors.
    PHSYNC-IDEM-0: returns files_changed=0 if already synced.
    """
    if require_evidence:
        _validate_release_evidence(root)

    files_changed = 0
    all_changes: list[str] = []

    # ── ROADMAP.md ──
    roadmap_path = root / "ROADMAP.md"
    if roadmap_path.exists():
        roadmap_content = roadmap_path.read_text(encoding="utf-8")
        updated, changes = _patch_roadmap(roadmap_content)
        if changes:
            _atomic_write(roadmap_path, updated)
            files_changed += 1
            all_changes.extend(changes)

    # ── Procession doc ──
    procession_path = root / _PROCESSION_REL
    if procession_path.exists():
        proc_content = procession_path.read_text(encoding="utf-8")
        updated, changes = _patch_procession(proc_content)
        if changes:
            _atomic_write(procession_path, updated)
            files_changed += 1
            all_changes.extend(changes)

    return SyncResult(files_changed=files_changed, changes=all_changes)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:  # pragma: no cover
    result = sync_phase65_status(require_evidence=True)
    for c in result.changes:
        print(f"  [synced] {c}")
    print(f"[sync_phase_status_on_merge] files_changed={result.files_changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
