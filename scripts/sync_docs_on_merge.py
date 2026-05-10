#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
sync_docs_on_merge.py — ADAAD Post-Merge Documentation Synchroniser
══════════════════════════════════════════════════════════════════════════════
Invariant codes: DOCSYNC-PLAN-0 · DOCSYNC-ATOM-0 · DOCSYNC-PROTECT-0
                 DOCSYNC-IDEM-0 · DOCSYNC-PILL-0

PURPOSE
───────
Applies structured documentation updates after a phase merge: governance
report version, agent state, ARCH_SNAPSHOT metadata block, install.html
version pill, and other always-sync targets.

CONSTITUTIONAL INVARIANTS
──────────────────────────
  DOCSYNC-PLAN-0    All sync operations are driven by a SyncPlan dataclass;
                    no side-channel state mutation.
  DOCSYNC-ATOM-0    File writes use os.replace for atomicity.
  DOCSYNC-PROTECT-0 Protected paths (CONSTITUTION.md etc.) are never touched.
  DOCSYNC-IDEM-0    Re-running on an already-synced state produces no changes.
  DOCSYNC-PILL-0    The HTML version pill is updated by exact regex; no DOM
                    parsing.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

# ─────────────────────────────────────────────────────────────────────────────
# DOCSYNC-PROTECT-0: Protected paths — never written by this script
# ─────────────────────────────────────────────────────────────────────────────

_PROTECTED_PATHS: frozenset[str] = frozenset(
    {
        "docs/CONSTITUTION.md",
        "governance/CONSTITUTION.md",
        "docs/governance/CONSTITUTION.md",
        "CONSTITUTION.md",
    }
)

# DOCSYNC-PILL-0: always-sync paths
_ALWAYS_SYNC: list[str] = ["docs/install.html"]

# ─────────────────────────────────────────────────────────────────────────────
# DOCSYNC-PILL-0: HTML version pill regex
# ─────────────────────────────────────────────────────────────────────────────

_HTML_VERSION_PILL_RE: re.Pattern[str] = re.compile(
    r'(<span\s+class=["\']version-pill["\']>)v\d+\.\d+\.\d+(</span>)',
    re.IGNORECASE,
)


def _is_protected(path_str: str) -> bool:
    """Return True if path_str matches a protected path. DOCSYNC-PROTECT-0."""
    return path_str in _PROTECTED_PATHS


def _replace_html_version_pill(
    content: str, version: str
) -> tuple[str, list[str]]:
    """
    Replace the version number inside <span class="version-pill">vX.Y.Z</span>.
    Returns (updated_content, list_of_change_descriptions).
    DOCSYNC-PILL-0.
    """
    changes: list[str] = []
    original = content

    def _replacer(m: re.Match[str]) -> str:
        current_ver = m.group(0)
        # Extract old version from the full match
        inner = re.search(r"v(\d+\.\d+\.\d+)", current_ver)
        old_ver = inner.group(1) if inner else "?"
        changes.append(f"install_html_version_pill {old_ver}→{version}")
        return f"{m.group(1)}v{version}{m.group(2)}"

    new_content = _HTML_VERSION_PILL_RE.sub(_replacer, content)
    if new_content == original:
        return content, []
    return new_content, changes


# ─────────────────────────────────────────────────────────────────────────────
# DOCSYNC-PLAN-0: SyncPlan dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SyncPlan:
    """Immutable record of everything needed to drive a post-merge doc sync."""

    version: str
    prev_version: str
    date_str: str
    changelog_entry: str
    new_capabilities: list[str] = field(default_factory=list)
    new_modules: list[str] = field(default_factory=list)
    shipped_phases: list[int] = field(default_factory=list)
    git_sha: str = ""
    git_branch: str = ""
    git_tag: str = ""
    merged_files: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Sync helpers
# ─────────────────────────────────────────────────────────────────────────────

_ARCH_SNAPSHOT_START = "<!-- ARCH_SNAPSHOT_METADATA:START -->"
_ARCH_SNAPSHOT_END = "<!-- ARCH_SNAPSHOT_METADATA:END -->"


def _update_arch_snapshot(content: str, plan: SyncPlan) -> tuple[str, list[str]]:
    """
    Replace the ARCH_SNAPSHOT_METADATA block with version/sha/branch/tag info.
    Returns (updated_content, list_of_change_descriptions).
    """
    if _ARCH_SNAPSHOT_START not in content or _ARCH_SNAPSHOT_END not in content:
        return content, []

    new_block = (
        f"{_ARCH_SNAPSHOT_START}\n"
        f"| Version | `{plan.version}` |\n"
        f"| Tag | `{plan.git_tag}` |\n"
        f"| Branch | `{plan.git_branch}` |\n"
        f"| Short SHA | `{plan.git_sha}` |\n"
        f"| Date | `{plan.date_str}` |\n"
        f"{_ARCH_SNAPSHOT_END}"
    )

    start_idx = content.index(_ARCH_SNAPSHOT_START)
    end_idx = content.index(_ARCH_SNAPSHOT_END) + len(_ARCH_SNAPSHOT_END)
    old_block = content[start_idx:end_idx]

    if old_block == new_block:
        return content, []

    updated = content[:start_idx] + new_block + content[end_idx:]
    return updated, [f"ARCH_SNAPSHOT→v{plan.version}/{plan.git_sha}"]


def _update_governance_report_version(plan: SyncPlan) -> list[str]:
    """
    Update governance/report_version.json to the plan version.
    Returns list of change descriptions.
    DOCSYNC-ATOM-0.
    """
    report_path = ROOT / "governance" / "report_version.json"
    if not report_path.exists():
        return []

    report: dict[str, Any] = json.loads(report_path.read_text(encoding="utf-8"))
    changed = False
    changes: list[str] = []

    if report.get("report_version") != plan.version:
        report["report_version"] = plan.version
        changed = True
        changes.append(f"report_version→{plan.version}")

    if report.get("version") != plan.version:
        report["version"] = plan.version
        changed = True
        changes.append(f"governance_report.version→{plan.version}")

    if report.get("last_sync_sha") != plan.git_sha and plan.git_sha:
        report["last_sync_sha"] = plan.git_sha
        changed = True
        changes.append(f"last_sync_sha→{plan.git_sha}")

    if changed:
        new_text = json.dumps(report, indent=2) + "\n"
        tmp = report_path.with_suffix(".tmp")
        tmp.write_text(new_text, encoding="utf-8")
        os.replace(tmp, report_path)

    return changes


def _update_agent_state(plan: SyncPlan) -> list[str]:
    """
    Sync .adaad_agent_state.json version fields to plan.version.
    Preserves schema_version and all non-version fields.
    Returns list of change descriptions.
    DOCSYNC-ATOM-0.
    """
    state_path = ROOT / ".adaad_agent_state.json"
    if not state_path.exists():
        return []

    state: dict[str, Any] = json.loads(state_path.read_text(encoding="utf-8"))
    version_fields = ("version", "current_version", "software_version", "last_completed_version")
    changes: list[str] = []

    for vf in version_fields:
        old_val = state.get(vf)
        if old_val != plan.version:
            state[vf] = plan.version
            changes.append(f"agent_state.{vf}→{plan.version}")

    if not changes:
        return []

    new_text = json.dumps(state, indent=2) + "\n"
    tmp = state_path.with_suffix(".tmp")
    tmp.write_text(new_text, encoding="utf-8")
    os.replace(tmp, state_path)
    return changes


def _sync_always_targets(plan: SyncPlan) -> list[str]:
    """Sync _ALWAYS_SYNC targets (e.g. docs/install.html version pill)."""
    all_changes: list[str] = []
    for rel_path in _ALWAYS_SYNC:
        if _is_protected(rel_path):
            continue
        target = ROOT / rel_path
        if not target.exists():
            continue
        content = target.read_text(encoding="utf-8")
        new_content, changes = _replace_html_version_pill(content, plan.version)
        if changes:
            tmp = target.with_suffix(target.suffix + ".tmp")
            tmp.write_text(new_content, encoding="utf-8")
            os.replace(tmp, target)
            all_changes.extend(changes)
    return all_changes


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def sync_all(plan: SyncPlan) -> list[str]:
    """Execute all sync operations for a given plan. Returns all change descriptions."""
    all_changes: list[str] = []
    all_changes.extend(_update_governance_report_version(plan))
    all_changes.extend(_update_agent_state(plan))
    all_changes.extend(_sync_always_targets(plan))
    return all_changes


def main() -> int:  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(description="ADAAD post-merge doc sync")
    parser.add_argument("--version", required=True)
    parser.add_argument("--prev-version", default="")
    parser.add_argument("--date", default="")
    parser.add_argument("--sha", default="")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--tag", default="(none)")
    args = parser.parse_args()

    plan = SyncPlan(
        version=args.version,
        prev_version=args.prev_version,
        date_str=args.date,
        changelog_entry="",
        git_sha=args.sha,
        git_branch=args.branch,
        git_tag=args.tag,
    )
    changes = sync_all(plan)
    for c in changes:
        print(f"  [synced] {c}")
    print(f"[sync_docs_on_merge] complete — {len(changes)} changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
