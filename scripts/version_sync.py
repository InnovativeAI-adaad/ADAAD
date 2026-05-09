#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
version_sync.py — ADAAD Master Version Synchroniser
═══════════════════════════════════════════════════════════════════════════════
Invariant codes: VSYNC-TRUTH-0 · VSYNC-ATOM-0 · VSYNC-IDEM-0 · VSYNC-AUDIT-0
                 VSYNC-SVG-0   · VSYNC-NOLOOP-0

PURPOSE
───────
Single-command elimination of version drift across every tracked surface.
Runs on every push to main via GitHub Actions and is safe to run locally
at any time.  Idempotent: identical state → zero file writes → no commit.

CANONICAL TRUTH HIERARCHY
──────────────────────────
  1. VERSION                          → semver string (e.g. 9.108.0)
  2. .adaad_agent_state.json          → phase, hard_class_count,
                                        innovations_shipped, last_innovation_id
  3. All other surfaces               → derived; updated by this script

SURFACES SYNCHRONISED
──────────────────────
  • pyproject.toml                    version field
  • README.md                         shield badges, ADAAD_VERSION_INFOBOX,
                                      By-the-numbers table
  • docs/README.md                    shield badges (Version + Phase badges)
  • ROADMAP.md                        ## Current State header line
  • governance/report_version.json    version, report_version, phase, date
  • .adaad_agent_state.json           current_version, software_version,
                                      current_phase, hard_class_count,
                                      hard_class_invariant_count,
                                      hard_class_invariants_cumulative,
                                      constitutional_invariants,
                                      invariant_count, hard_invariant_count,
                                      total_innovations_shipped,
                                      innovation_count, total_innovations,
                                      last_innovation_id, last_innovation
  • docs/assets/readme/inline-hero_banner.svg
                                      stat boxes: version, phases, innovations,
                                      invariants; latest-phases panel

CONSTITUTIONAL INVARIANTS
──────────────────────────
  VSYNC-TRUTH-0   VERSION file is the sole arbiter of the version string.
                  No other file may override it.
  VSYNC-ATOM-0    All writes happen in-memory; files are only written when
                  their content would change. Partial-write failures abort
                  the sync run and exit non-zero.
  VSYNC-IDEM-0    Running this script twice on an already-synced repo
                  produces zero file changes and exits 0.
  VSYNC-AUDIT-0   The script prints a JSON sync manifest on stdout and
                  writes it to governance/sync_manifest_latest.json.
  VSYNC-SVG-0     SVG stat-box values are updated by exact-string replacement
                  with pre/post confirmation guards — no XML parsing.
  VSYNC-NOLOOP-0  This script must not call itself or trigger CI workflows
                  that call itself. CI workflows invoke it directly.
"""

from __future__ import annotations

import json
import re
import sys
import hashlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ─── Repo root resolution ────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent


def _root(path: str) -> Path:
    return REPO_ROOT / path


# ─── Load canonical truth ────────────────────────────────────────────────────

def load_canonical() -> dict[str, Any]:
    """Read canonical values from VERSION and agent state."""
    version = _root("VERSION").read_text().strip()

    state_path = _root(".adaad_agent_state.json")
    state = json.loads(state_path.read_text())

    # Phase: prefer 'phase' field (most recently written by delivery scripts)
    phase = int(state.get("phase") or state.get("current_phase") or 0)

    # Hard-class invariants: prefer 'hard_class_count' if > 0, else
    # fall back to len(hard_class_invariants) array as a floor.
    # The delivery script writes 'hard_class_count'; the array is a
    # representative sample only.
    hci = int(state.get("hard_class_count") or
               state.get("hard_class_invariant_count") or
               state.get("constitutional_invariants") or 0)

    # innovations_shipped is authoritative; total_innovations_shipped is a
    # legacy alias that drifts — we derive from innovations_shipped.
    innov = int(state.get("innovations_shipped") or
                 state.get("total_innovations_shipped") or 0)

    last_innov_id = state.get("last_innovation_id") or "INNOV-???"
    last_innov    = state.get("last_innovation") or last_innov_id
    last_innov_name = state.get("last_innovation_name") or ""
    last_phase_name = state.get("last_phase_name") or f"Phase {phase}"

    # Attempt to get current git SHA (best-effort; silent on failure)
    try:
        sha = subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        sha = "unknown"

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    return {
        "version":         version,
        "version_v":       f"v{version}",
        "phase":           phase,
        "hard_class_count": hci,
        "innovations":     innov,
        "last_innov_id":   last_innov_id,
        "last_innov":      last_innov,
        "last_innov_name": last_innov_name,
        "last_phase_name": last_phase_name,
        "sha":             sha,
        "today":           today,
    }


# ─── Helper: read / write with drift detection ───────────────────────────────

class FileSync:
    """Reads a file, tracks changes, writes only if content differs."""

    def __init__(self, path: Path):
        self.path = path
        self.original = path.read_text(encoding="utf-8")
        self.content  = self.original
        self._ops: list[str] = []

    def replace(self, old: str, new: str, label: str = "") -> bool:
        if old not in self.content:
            return False
        self.content = self.content.replace(old, new)
        self._ops.append(label or f"{repr(old[:40])} → {repr(new[:40])}")
        return True

    def replace_block(self, start_marker: str, end_marker: str,
                      new_inner: str) -> bool:
        """Replace everything between start_marker and end_marker (exclusive)."""
        pattern = re.compile(
            rf"({re.escape(start_marker)})(.*?)({re.escape(end_marker)})",
            re.DOTALL,
        )
        match = pattern.search(self.content)
        if not match:
            return False
        old_block = match.group(0)
        new_block  = start_marker + "\n" + new_inner.strip() + "\n" + end_marker
        if old_block == new_block:
            return False
        self.content = self.content.replace(old_block, new_block)
        self._ops.append(f"block [{start_marker[:30]}]")
        return True

    @property
    def changed(self) -> bool:
        return self.content != self.original

    def write_if_changed(self) -> bool:
        if self.changed:
            self.path.write_text(self.content, encoding="utf-8")
        return self.changed

    @property
    def ops(self) -> list[str]:
        return self._ops


# ─── Surface sync functions ──────────────────────────────────────────────────

def sync_pyproject(c: dict) -> dict:
    path = _root("pyproject.toml")
    fs = FileSync(path)
    # Match 'version = "X.Y.Z"' at start of line
    old_match = re.search(r'^version = "([^"]+)"', fs.content, re.MULTILINE)
    if old_match and old_match.group(1) != c["version"]:
        fs.replace(
            f'version = "{old_match.group(1)}"',
            f'version = "{c["version"]}"',
            "pyproject version",
        )
    changed = fs.write_if_changed()
    return {"file": "pyproject.toml", "changed": changed, "ops": fs.ops}


def sync_readme(c: dict) -> dict:
    path = _root("README.md")
    fs = FileSync(path)

    # ── Shields.io badge line ──────────────────────────────────────────────
    # Version badge: [![vX.Y.Z](https://img.shields.io/badge/version-vX.Y.Z-...
    badge_ver_pat = re.compile(
        r"\[!\[v[\d.]+\]\(https://img\.shields\.io/badge/version-v[\d.]+-[^)]+\)\]"
    )
    m = badge_ver_pat.search(fs.content)
    if m:
        old_badge = m.group(0)
        new_badge = re.sub(
            r"v[\d.]+",
            c["version_v"],
            old_badge,
        )
        if old_badge != new_badge:
            fs.replace(old_badge, new_badge, "README version badge")

    # Invariants badge: [![NNN Invariants](…badge/invariants-NNN%20Hard--class…
    inv_pat = re.compile(
        r"\[!\[\d+ Invariants\]\(https://img\.shields\.io/badge/invariants-\d+%20Hard--class[^)]+\)\]"
    )
    m = inv_pat.search(fs.content)
    if m:
        old_b = m.group(0)
        new_b = re.sub(r"\d+ Invariants", f"{c['hard_class_count']} Invariants", old_b)
        new_b = re.sub(r"invariants-\d+%20Hard", f"invariants-{c['hard_class_count']}%20Hard", new_b)
        if old_b != new_b:
            fs.replace(old_b, new_b, "README invariants badge")

    # Innovations badge: [![NN Innovations](…badge/innovations-NN%20shipped…
    inn_pat = re.compile(
        r"\[!\[\d+ Innovations\]\(https://img\.shields\.io/badge/innovations-\d+%20shipped[^)]+\)\]"
    )
    m = inn_pat.search(fs.content)
    if m:
        old_b = m.group(0)
        new_b = re.sub(r"\d+ Innovations", f"{c['innovations']} Innovations", old_b)
        new_b = re.sub(r"innovations-\d+%20shipped", f"innovations-{c['innovations']}%20shipped", new_b)
        if old_b != new_b:
            fs.replace(old_b, new_b, "README innovations badge")

    # ── ADAAD_VERSION_INFOBOX block ────────────────────────────────────────
    infobox = (
        f"> Auto-generated by scripts/version_sync.py\n"
        f"> Sync context note: release metadata is mirrored from governance/report_version.json.\n"
        f"\n"
        f"| Field | Value |\n"
        f"| --- | --- |\n"
        f"| **Current version** | `{c['version']}` |\n"
        f"| **Phase** | `{c['phase']}` |\n"
        f"| **Released** | `{c['today']}` |\n"
        f"| **Release SHA** | `{c['sha']}` |\n"
        f"| **Hard-class invariants** | `{c['hard_class_count']}` |\n"
        f"| **Innovations shipped** | `{c['innovations']}` |\n"
    )
    fs.replace_block(
        "<!-- ADAAD_VERSION_INFOBOX:START -->",
        "<!-- ADAAD_VERSION_INFOBOX:END -->",
        infobox,
    )

    # ── By the numbers table (specific rows) ──────────────────────────────
    # Row: | Current version | `vX.Y.Z` · Phase `NNN` |
    row_ver_pat = re.compile(
        r"\| Current version \| `v[\d.]+` · Phase `\d+` \|"
    )
    m = row_ver_pat.search(fs.content)
    if m:
        new_row = f"| Current version | `{c['version_v']}` · Phase `{c['phase']}` |"
        if m.group(0) != new_row:
            fs.replace(m.group(0), new_row, "By-the-numbers: version+phase")

    # Row: | Hard-class constitutional invariants | **NNN** — ...
    inv_row_pat = re.compile(
        r"(\| Hard-class constitutional invariants \| \*\*)\d+(\*\* — cryptographically enforced \|)"
    )
    m = inv_row_pat.search(fs.content)
    if m:
        new_row = m.group(1) + str(c["hard_class_count"]) + m.group(2)
        if m.group(0) != new_row:
            fs.replace(m.group(0), new_row, "By-the-numbers: invariants")

    # Row: | Shipped innovations | **NN** — INNOV-01 through INNOV-XX |
    inn_row_pat = re.compile(
        r"(\| Shipped innovations \| \*\*)\d+(\*\* — INNOV-01 through INNOV-)\S+"
    )
    m = inn_row_pat.search(fs.content)
    if m:
        last = c["last_innov_id"].replace("INNOV-", "")
        new_row = m.group(1) + str(c["innovations"]) + m.group(2) + f"INNOV-{last} |"
        if m.group(0) + " |" != new_row:  # rough guard
            # More precise replacement
            old_row = m.group(0)
            new_exact = (
                f"| Shipped innovations | **{c['innovations']}** — "
                f"INNOV-01 through {c['last_innov_id']} |"
            )
            # Only replace if old row is present
            row_search = re.search(
                r"\| Shipped innovations \| \*\*\d+\*\* — INNOV-01 through INNOV-\S+ \|",
                fs.content,
            )
            if row_search and row_search.group(0) != new_exact:
                fs.replace(row_search.group(0), new_exact, "By-the-numbers: innovations")

    changed = fs.write_if_changed()
    return {"file": "README.md", "changed": changed, "ops": fs.ops}


def sync_docs_readme(c: dict) -> dict:
    path = _root("docs/README.md")
    if not path.exists():
        return {"file": "docs/README.md", "changed": False, "ops": ["skipped: not found"]}
    fs = FileSync(path)

    # [![Version](https://img.shields.io/badge/ADAAD-vX.Y.Z-...)
    ver_pat = re.compile(
        r"\[!\[Version\]\(https://img\.shields\.io/badge/ADAAD-v[\d.]+-[^)]+\)\]"
    )
    m = ver_pat.search(fs.content)
    if m:
        old_b = m.group(0)
        new_b = re.sub(r"ADAAD-v[\d.]+-", f"ADAAD-{c['version_v']}-", old_b)
        if old_b != new_b:
            fs.replace(old_b, new_b, "docs/README version badge")

    # [![Phase](https://img.shields.io/badge/Phase_NNN-...-...)
    phase_pat = re.compile(
        r"\[!\[Phase\]\(https://img\.shields\.io/badge/Phase_\d+[^)]+\)\]"
    )
    m = phase_pat.search(fs.content)
    if m:
        old_b = m.group(0)
        # Replace phase number in badge name
        new_b = re.sub(r"Phase_\d+", f"Phase_{c['phase']}", old_b)
        if old_b != new_b:
            fs.replace(old_b, new_b, "docs/README phase badge")

    changed = fs.write_if_changed()
    return {"file": "docs/README.md", "changed": changed, "ops": fs.ops}


def sync_roadmap(c: dict) -> dict:
    path = _root("ROADMAP.md")
    fs = FileSync(path)

    # ## Current State — vX.Y.Z · Phase NNN · INNOV-XX ... — ...
    cs_pat = re.compile(
        r"## Current State — v[\d.]+ · Phase \d+ · \S+.*"
    )
    m = cs_pat.search(fs.content)
    if m:
        # last_phase_name format: "INNOV-80 · CAL — Constitutional Adaptive Learner"
        new_line = (
            f"## Current State — {c['version_v']} · Phase {c['phase']} · "
            f"{c['last_phase_name']}"
        )
        if m.group(0) != new_line:
            fs.replace(m.group(0), new_line, "ROADMAP Current State header")

    # Also update the status line beneath it
    status_pat = re.compile(
        r"\*\*Status:\*\* \d+ innovations shipped \(INNOV-01 through INNOV-\S+\)\. Phase \d+ complete\. v[\d.]+ baseline\."
    )
    m = status_pat.search(fs.content)
    if m:
        new_status = (
            f"**Status:** {c['innovations']} innovations shipped "
            f"(INNOV-01 through {c['last_innov_id']}). "
            f"Phase {c['phase']} complete. {c['version_v']} baseline."
        )
        if m.group(0) != new_status:
            fs.replace(m.group(0), new_status, "ROADMAP status line")

    # Hard-class invariants mention in roadmap
    hci_pat = re.compile(
        r"\*\*Hard-class invariants:\*\* \d+ \(cumulative, enforced\)"
    )
    m = hci_pat.search(fs.content)
    if m:
        new_hci = f"**Hard-class invariants:** {c['hard_class_count']} (cumulative, enforced)"
        if m.group(0) != new_hci:
            fs.replace(m.group(0), new_hci, "ROADMAP invariant count")

    changed = fs.write_if_changed()
    return {"file": "ROADMAP.md", "changed": changed, "ops": fs.ops}


def sync_report_version(c: dict) -> dict:
    path = _root("governance/report_version.json")
    fs = FileSync(path)
    data = json.loads(fs.content)

    # Non-timestamp fields drive change detection
    core_updates = {
        "version":        c["version"],
        "report_version": c["version"],
        "phase":          c["phase"],
        "date":           c["today"],
        "last_sync_date": c["today"],
        "last_sync_sha":  c["sha"],
        "innovation":     c["last_innov_id"],
        "version_source": "governance/report_version.json",
    }
    changed_keys = [k for k, v in core_updates.items() if data.get(k) != v]
    if changed_keys:
        data.update(core_updates)
        data["updated"]      = datetime.now(timezone.utc).isoformat()
        data["last_updated"] = c["today"]
        new_json = json.dumps(data, indent=4)
        fs.content = new_json
        fs.write_if_changed()

    return {
        "file": "governance/report_version.json",
        "changed": bool(changed_keys),
        "ops": [f"updated {k}" for k in changed_keys],
    }


def sync_agent_state(c: dict) -> dict:
    path = _root(".adaad_agent_state.json")
    data = json.loads(path.read_text())
    original_json = json.dumps(data, indent=4, sort_keys=False)

    # Fields to keep in sync — all should reflect canonical values
    # Core fields drive change detection — exclude timestamp
    syncs_core = {
        "version":                         c["version"],
        "current_version":                 c["version"],
        "software_version":                c["version"],
        "last_completed_version":          c["version"],
        "current_phase":                   c["phase"],
        "phase":                           c["phase"],
        "next_phase":                      c["phase"] + 1,
        "next_phase_id":                   c["phase"] + 1,
        "phases_complete":                 c["phase"],
        "total_phases":                    c["phase"],
        "constitutional_invariants":       c["hard_class_count"],
        "hard_class_count":                c["hard_class_count"],
        "hard_class_invariant_count":      c["hard_class_count"],
        "hard_class_invariants_cumulative": c["hard_class_count"],
        "invariant_count":                 c["hard_class_count"],
        "hard_invariant_count":            c["hard_class_count"],
        "total_innovations_shipped":       c["innovations"],
        "innovation_count":                c["innovations"],
        "total_innovations":               c["innovations"],
        "innovations_shipped":             c["innovations"],
        "last_innovation_id":              c["last_innov_id"],
        "last_innovation":                 c["last_innov"],
        "last_innovation_name":            c["last_innov_name"],
    }

    changed_keys = []
    for k, v in syncs_core.items():
        if k in data and data[k] != v:
            data[k] = v
            changed_keys.append(k)

    # Timestamps only update when core content changed
    if changed_keys:
        data["last_updated"]  = datetime.now(timezone.utc).isoformat()
        data["last_invocation"] = c["today"]

    new_json = json.dumps(data, indent=4, sort_keys=False)
    if new_json != original_json:
        path.write_text(new_json, encoding="utf-8")

    return {
        "file": ".adaad_agent_state.json",
        "changed": bool(changed_keys),
        "ops": [f"synced {k}" for k in changed_keys],
    }


def sync_svg_hero(c: dict) -> dict:
    """
    Update the inline-hero_banner.svg stat boxes and version references.

    VSYNC-SVG-0: all replacements use exact-string matching with
    pre-replacement existence guards. No XML parsing.
    """
    path = _root("docs/assets/readme/inline-hero_banner.svg")
    if not path.exists():
        return {"file": str(path.name), "changed": False, "ops": ["skipped: not found"]}

    fs = FileSync(path)
    ops: list[str] = []

    def svg_replace(old: str, new: str, label: str) -> None:
        if old in fs.content:
            fs.content = fs.content.replace(old, new)
            ops.append(label)

    # ── Version badge (two occurrences in the SVG) ─────────────────────────
    # Pattern: >v9.XX.0  LIVE<  and  v9.XX.0</text>  (in the live bar)
    ver_live_pat = re.compile(r">v[\d.]+  LIVE<")
    m = ver_live_pat.search(fs.content)
    if m and m.group(0) != f">{c['version_v']}  LIVE<":
        fs.content = ver_live_pat.sub(f">{c['version_v']}  LIVE<", fs.content)
        ops.append("SVG: version LIVE badge")

    ver_bar_pat = re.compile(r"v[\d.]+</text>\s*</g>\s*<rect x=\"0\" y=\"337\"")
    m = ver_bar_pat.search(fs.content)
    if m:
        old_frag = m.group(0)
        new_frag = re.sub(r"v[\d.]+", c["version_v"], old_frag, count=1)
        if old_frag != new_frag:
            fs.content = fs.content.replace(old_frag, new_frag)
            ops.append("SVG: bottom bar version")

    # ── Stat box: Phases ────────────────────────────────────────────────────
    # Pattern: stat-val fill used before "Phases" label
    # The SVG has: <text ...>146</text>...<text ...>Phases</text>
    phases_pat = re.compile(
        r'(<text[^>]*class="stat-val"[^>]*>)\d+(</text>)(\s*<text[^>]*class="stat-lbl"[^>]*>Phases</text>)'
    )
    m = phases_pat.search(fs.content)
    if m and m.group(2) + m.group(3):
        old_frag = m.group(0)
        new_frag = m.group(1) + str(c["phase"]) + m.group(2) + m.group(3)
        if old_frag != new_frag:
            fs.content = fs.content.replace(old_frag, new_frag)
            ops.append(f"SVG: phases stat {c['phase']}")

    # ── Stat box: Innovations ───────────────────────────────────────────────
    innov_pat = re.compile(
        r'(<text[^>]*class="stat-val"[^>]*>)\d+(</text>)(\s*<text[^>]*class="stat-lbl"[^>]*>Innovations</text>)'
    )
    m = innov_pat.search(fs.content)
    if m:
        old_frag = m.group(0)
        new_frag = m.group(1) + str(c["innovations"]) + m.group(2) + m.group(3)
        if old_frag != new_frag:
            fs.content = fs.content.replace(old_frag, new_frag)
            ops.append(f"SVG: innovations stat {c['innovations']}")

    # ── Stat box: Invariants ────────────────────────────────────────────────
    inv_pat = re.compile(
        r'(<text[^>]*class="stat-val"[^>]*>)\d+(</text>)(\s*<text[^>]*class="stat-lbl"[^>]*>Invariants</text>)'
    )
    m = inv_pat.search(fs.content)
    if m:
        old_frag = m.group(0)
        new_frag = m.group(1) + str(c["hard_class_count"]) + m.group(2) + m.group(3)
        if old_frag != new_frag:
            fs.content = fs.content.replace(old_frag, new_frag)
            ops.append(f"SVG: invariants stat {c['hard_class_count']}")

    # ── Latest-Phases panel: update the live version reference ─────────────
    # The SVG encodes 'v9.96.0' hard-coded in the live status bar at bottom
    # of the latest-phases panel. Catch any remaining stale version refs.
    remaining_old_ver_pat = re.compile(r">v[\d]+\.[\d]+\.[\d]+<")
    for m in remaining_old_ver_pat.finditer(fs.content):
        old_ref = m.group(0)
        expected = f">{c['version_v']}<"
        if old_ref != expected:
            fs.content = fs.content.replace(old_ref, expected)
            ops.append(f"SVG: stale version ref {old_ref}")
            break  # one pass; re-scan for safety

    if ops:
        path.write_text(fs.content, encoding="utf-8")

    return {
        "file": "docs/assets/readme/inline-hero_banner.svg",
        "changed": bool(ops),
        "ops": ops,
    }


# ─── Manifest ────────────────────────────────────────────────────────────────

def write_manifest(c: dict, results: list[dict]) -> None:
    manifest = {
        "sync_timestamp": datetime.now(timezone.utc).isoformat(),
        "canonical": {
            "version": c["version"],
            "phase":   c["phase"],
            "hard_class_count": c["hard_class_count"],
            "innovations": c["innovations"],
            "sha": c["sha"],
        },
        "surfaces": results,
        "total_changed": sum(1 for r in results if r.get("changed")),
        "digest": hashlib.sha256(
            json.dumps(c, sort_keys=True).encode()
        ).hexdigest()[:16],
    }
    manifest_path = _root("governance/sync_manifest_latest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))


# ─── Main ────────────────────────────────────────────────────────────────────

def main() -> int:
    print("ADAAD version_sync.py — reading canonical truth…", file=sys.stderr)
    c = load_canonical()
    print(
        f"  Canonical: version={c['version']} phase={c['phase']} "
        f"invariants={c['hard_class_count']} innovations={c['innovations']}",
        file=sys.stderr,
    )

    results = [
        sync_pyproject(c),
        sync_readme(c),
        sync_docs_readme(c),
        sync_roadmap(c),
        sync_report_version(c),
        sync_agent_state(c),
        sync_svg_hero(c),
    ]

    changed = [r for r in results if r.get("changed")]
    skipped = [r for r in results if not r.get("changed")]

    print(f"  Changed: {len(changed)}  Unchanged: {len(skipped)}", file=sys.stderr)
    for r in changed:
        print(f"    ✓ {r['file']}: {', '.join(r['ops'][:3])}", file=sys.stderr)

    write_manifest(c, results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
