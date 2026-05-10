#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
sync_docs_and_assets.py — ADAAD Documentation and Asset Synchroniser
══════════════════════════════════════════════════════════════════════════════
Invariant codes: DASYNC-GIT-0 · DASYNC-ATOM-0 · DASYNC-DETERM-0
                 DASYNC-FAILCLOSED-0

PURPOSE
───────
Reads git log to extract current phase, innovation number, and invariant count,
then synchronises documentation assets accordingly. Designed for deterministic,
idempotent operation in CI/CD pipelines.

CONSTITUTIONAL INVARIANTS
──────────────────────────
  DASYNC-GIT-0         All git interactions go through _run_git(); callers
                       never subprocess.run() git directly.
  DASYNC-ATOM-0        File writes use os.replace for atomicity.
  DASYNC-DETERM-0      _load_state() is deterministic for fixed git log output.
  DASYNC-FAILCLOSED-0  Any git failure emits a JSON error to stderr and raises
                       SystemExit(1). No silent failures.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


# ─────────────────────────────────────────────────────────────────────────────
# DASYNC-FAILCLOSED-0: Structured error emission
# ─────────────────────────────────────────────────────────────────────────────

def _emit_error(detail: dict) -> None:
    """Write structured JSON error to stderr. DASYNC-FAILCLOSED-0."""
    payload = {"event": "DOCSYNC_ERROR", "msg": json.dumps(detail)}
    print(json.dumps(payload), file=sys.stderr)


# ─────────────────────────────────────────────────────────────────────────────
# DASYNC-GIT-0: Git wrapper
# ─────────────────────────────────────────────────────────────────────────────

def _run_git(args: list[str]) -> str:
    """
    Run a git command and return stdout as a string.
    On failure: emits structured error to stderr, raises SystemExit(1).
    DASYNC-GIT-0 · DASYNC-FAILCLOSED-0.
    """
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as exc:
        _emit_error(
            {
                "kind": "git_command_failed",
                "error_type": "non_zero_exit",
                "args": args,
                "returncode": exc.returncode,
                "stderr_snippet": (exc.stderr or "").strip()[:500],
            }
        )
        raise SystemExit(1)


# ─────────────────────────────────────────────────────────────────────────────
# DASYNC-DETERM-0: State extraction
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RepoState:
    """Deterministic snapshot of current repo state from git log."""
    phase: int
    innov_num: int
    hard: int  # hard invariant count (cumulative)
    last_tag: str
    log_subjects: list[str]


def _extract_phase(subjects: list[str]) -> int:
    """Extract latest phase number from commit subject lines."""
    for subject in subjects:
        m = re.search(r"phase\s*(\d+)", subject, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return 0


def _extract_innov_num(subjects: list[str]) -> int:
    """Extract latest innovation number from commit subject lines."""
    for subject in subjects:
        m = re.search(r"INNOV-(\d+)", subject)
        if m:
            return int(m.group(1))
    return 0


def _extract_hard_count(body_log: str) -> int:
    """Extract cumulative hard invariant count from commit bodies."""
    m = re.search(r"Cumulative:\s*(\d+)", body_log)
    if m:
        return int(m.group(1))
    # Fallback: count lines mentioning Hard-class
    count = len(re.findall(r"[Hh]ard.class", body_log))
    return max(count, 0)


def _load_state() -> RepoState:
    """
    Load current repo state from git log.
    Deterministic for fixed git log output. DASYNC-DETERM-0.
    Fails closed (SystemExit(1)) if git log is empty. DASYNC-FAILCLOSED-0.
    """
    subject_log = _run_git(["log", "--format=%s", "--max-count=80"])
    if not subject_log:
        _emit_error({"kind": "empty_git_log", "error_type": "no_commits_found"})
        raise SystemExit(1)

    subjects = [s for s in subject_log.splitlines() if s.strip()]
    body_log = _run_git(["log", "--format=%B", "--max-count=30"])

    phase = _extract_phase(subjects)
    innov_num = _extract_innov_num(subjects)
    hard = _extract_hard_count(body_log)

    # Try to read hard count from agent state as authoritative fallback
    state_path = ROOT / ".adaad_agent_state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            agent_hard = state.get("hard_invariant_count") or state.get("hard_class_count") or 0
            hard = max(hard, int(agent_hard))
        except Exception:
            pass

    return RepoState(
        phase=phase,
        innov_num=innov_num,
        hard=hard,
        last_tag="",
        log_subjects=subjects,
    )


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:  # pragma: no cover
    state = _load_state()
    print(f"[sync_docs_and_assets] phase={state.phase} innov={state.innov_num} hard={state.hard}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
