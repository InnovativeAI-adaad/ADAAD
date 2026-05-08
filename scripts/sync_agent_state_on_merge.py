#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""sync_agent_state_on_merge.py — Phase 85 Track B: Canonical agent state sync.

Single-responsibility script: reads VERSION and CHANGELOG.md, writes
.adaad_agent_state.json with authoritative version/phase fields.

WHAT THIS SCRIPT UPDATES
────────────────────────
  version              ← VERSION (semver, product release identity)
  current_version      ← VERSION (semver)
  software_version     ← VERSION (semver, canonical alias)
  last_completed_version ← VERSION (semver, release closure identity)
  last_invocation      ← today ISO-8601 date
  last_sync_sha        ← git HEAD short SHA
  active_phase         ← "v{version} RELEASED · post-merge agent sync"
  last_completed_phase ← derived from most recent CHANGELOG ## header

WHAT THIS SCRIPT NEVER TOUCHES
───────────────────────────────
  schema_version       — document format constant ("1.5.0"); GSYNC-SCHEMA-0
  open_findings        — append-only audit list
  value_checkpoints_reached — append-only by design

CONSTITUTIONAL INVARIANTS
─────────────────────────
  GSYNC-0        version/current_version/software_version/last_completed_version == VERSION on every successful run.
  GSYNC-DETERM-0 identical VERSION + CHANGELOG state → identical output.
  GSYNC-SCHEMA-0 schema_version is read-only from the perspective of this script.
  GSYNC-PHASE-0  last_completed_phase derived from CHANGELOG header regex.
  GSYNC-CLOSED-0 Any read/parse failure exits non-zero — no silent fallback.

EXIT CODES
  0 — success (including "nothing to change")
  1 — AGENT_STATE_SYNC_ERROR_* with JSON detail to stdout
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / ".adaad_agent_state.json"
VERSION_PATH = ROOT / "VERSION"
CHANGELOG_PATH = ROOT / "CHANGELOG.md"

AGENT_STATE_SCHEMA_VERSION = "1.5.0"

_CHANGELOG_HEADER_RE = re.compile(
    r"^## \[(\d+\.\d+\.\d+)\]\s*[—–-]\s*[\d-]+\s*[—–-]\s*(.+)$",
    re.MULTILINE,
)

_ORCHESTRATOR_ENV_MARKER = "ADAAD_ORCHESTRATOR_RUN"


def _fatal(code: str, message: str) -> None:
    print(json.dumps({"event": code, "message": message}), flush=True)
    sys.exit(1)


def _emit(event: str, payload: dict[str, Any]) -> None:
    print(json.dumps({"event": event, **payload}), flush=True)


def _assert_orchestrator_context(dry_run: bool) -> None:
    ci = os.getenv("CI", "").strip().lower()
    marker = os.getenv(_ORCHESTRATOR_ENV_MARKER, "").strip()
    if ci in {"1", "true", "yes"} and not marker and not dry_run:
        _fatal(
            "AGENT_STATE_SYNC_ERROR_MISSING_ORCHESTRATOR_MARKER",
            "sync_agent_state_on_merge.py must be invoked by post_merge_orchestrator.yml in CI",
        )


def _read_version() -> str:
    if not VERSION_PATH.exists():
        _fatal("AGENT_STATE_SYNC_ERROR_NO_VERSION_FILE", str(VERSION_PATH))
    v = VERSION_PATH.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", v):
        _fatal("AGENT_STATE_SYNC_ERROR_BAD_VERSION", f"VERSION contains {v!r}")
    return v


def _derive_last_completed_phase(version: str) -> str:
    if not CHANGELOG_PATH.exists():
        return f"v{version} — CHANGELOG not found"
    cl = CHANGELOG_PATH.read_text(encoding="utf-8")
    for match in _CHANGELOG_HEADER_RE.finditer(cl):
        if match.group(1) == version:
            title = match.group(2).strip()
            title = re.sub(r"\s+·\s+$", "", title).strip()
            return f"Phase {title}" if not title.lower().startswith("phase") else title
    first = _CHANGELOG_HEADER_RE.search(cl)
    if first:
        return first.group(2).strip()
    return f"v{version} — phase title not parseable from CHANGELOG"


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT, text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except FileNotFoundError as exc:
        _fatal(
            "AGENT_STATE_SYNC_ERROR_GIT_SHA",
            f"git executable not found: {exc}",
        )
    except subprocess.CalledProcessError as exc:
        _fatal(
            "AGENT_STATE_SYNC_ERROR_GIT_SHA",
            f"git rev-parse failed (exit={exc.returncode})",
        )
    except OSError as exc:
        _fatal(
            "AGENT_STATE_SYNC_ERROR_GIT_SHA",
            f"os error while resolving git sha: {exc}",
        )


def _compute_sync_digest(version: str, phase_title: str, git_sha: str) -> str:
    payload = json.dumps(
        {"version": version, "phase_title": phase_title, "git_sha": git_sha},
        sort_keys=True, separators=(",", ":"),
    )
    return "gsync-" + hashlib.sha256(payload.encode()).hexdigest()[:16]


def sync_agent_state(*, dry_run: bool = False) -> list[dict[str, Any]]:
    version = _read_version()
    phase_title = _derive_last_completed_phase(version)
    git_sha = _git_sha()
    today = date.today().isoformat()
    sync_digest = _compute_sync_digest(version, phase_title, git_sha)
    active_phase_str = f"v{version} RELEASED · post-merge agent sync"

    if not STATE_PATH.exists():
        _fatal("AGENT_STATE_SYNC_ERROR_NO_STATE_FILE", str(STATE_PATH))

    try:
        state: dict[str, Any] = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        _fatal("AGENT_STATE_SYNC_ERROR_READ", str(exc))

    if not isinstance(state, dict):
        _fatal("AGENT_STATE_SYNC_ERROR_SCHEMA", "root must be a JSON object")

    schema_ver = state.get("schema_version")
    if schema_ver != AGENT_STATE_SCHEMA_VERSION:
        _emit("AGENT_STATE_SYNC_WARN_SCHEMA_VERSION", {
            "expected": AGENT_STATE_SCHEMA_VERSION,
            "found": schema_ver,
            "action": "schema_version_not_modified_by_this_script",
        })

    changes: list[dict[str, Any]] = []

    def _set(key: str, value: str, invariant: str) -> None:
        old = str(state.get(key, ""))
        if old != value:
            changes.append({
                "file": ".adaad_agent_state.json",
                "key": key,
                "invariant": invariant,
                "old": old[:120],
                "new": value,
            })
            if not dry_run:
                state[key] = value

    # GSYNC-SCHEMA-0: correct legacy semver written to schema_version
    _current_schema = state.get("schema_version")
    if _current_schema is not None and re.fullmatch(r"\d+\.\d+\.\d+", str(_current_schema)):
        if not dry_run:
            state["schema_version"] = AGENT_STATE_SCHEMA_VERSION
        changes.append({
            "file": ".adaad_agent_state.json",
            "key": "schema_version",
            "invariant": "GSYNC-SCHEMA-0-correction",
            "old": str(_current_schema),
            "new": AGENT_STATE_SCHEMA_VERSION,
        })

    # Rationale: VERSION is the canonical product release identity; these
    # aliases are synchronized together while schema_version remains a document
    # format invariant, not a release-version field.
    _set("version", version, "GSYNC-0")
    _set("current_version", version, "GSYNC-0")
    _set("software_version", version, "GSYNC-0")
    _set("last_completed_version", version, "GSYNC-0")
    _set("last_completed_phase", phase_title, "GSYNC-PHASE-0")
    _set("active_phase", active_phase_str, "GSYNC-DETERM-0")
    _set("last_invocation", today, "GSYNC-DETERM-0")
    _set("last_sync_sha", git_sha, "GSYNC-DETERM-0")
    _set("last_agent_state_sync_digest", sync_digest, "GSYNC-DETERM-0")

    if changes and not dry_run:
        STATE_PATH.write_text(
            json.dumps(state, indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
        )

    _emit("sync_complete", {
        "version": version,
        "phase_title": phase_title,
        "fields_changed": len(changes),
        "dry_run": dry_run,
        "sync_digest": sync_digest,
        "git_sha": git_sha,
    })
    for change in changes:
        _emit("field_updated", change)

    return changes


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Sync .adaad_agent_state.json version/phase fields post-merge."
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--format", choices=["json", "text"], default="json")
    args = ap.parse_args()
    _assert_orchestrator_context(dry_run=args.dry_run)
    sync_agent_state(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
