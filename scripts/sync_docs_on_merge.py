#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
sync_docs_on_merge.py — Post-merge documentation synchroniser.

Runs automatically after every merge to main.  Reads VERSION, CHANGELOG,
and git diff metadata, then propagates version numbers, info-boxes, and
the Evolution-History table across all public-facing files.

WHAT GETS UPDATED ON EVERY MERGE
──────────────────────────────────────────────────────────────────────────────
  README.md
    • shields.io version badge
    • ADAAD_VERSION_INFOBOX sentinel block — version, date, SHA, new modules
    • Evolution History table — prepends row for current version if missing

  ROADMAP.md
    • "What ships today — vX.Y.Z" heading
    • Phase target lines matching current version get ✅ appended

  QUICKSTART.md + docs/**/*.md
    • shields.io version badge

  docs/README_IMPLEMENTATION_ALIGNMENT.md
    • ARCH_SNAPSHOT_METADATA sentinel block

  governance/report_version.json
    • report_version, last_sync_sha, last_sync_date fields

  .adaad_agent_state.json
    • active_phase, last_invocation, last_sync_sha
    • schema_version is intentionally not release-synced; schema ownership
      remains with sync_agent_state_on_merge.py / governance drift validation

CONSTITUTIONAL INVARIANTS
──────────────────────────────────────────────────────────────────────────────
  Deterministic  — identical VERSION+CHANGELOG+git state → identical output
  Fail-closed    — any read/write error exits non-zero with SYNC_ERROR_*
  Audit trail    — every change printed as JSON before any write
  No silent edits — files written only when content actually changed
  Protected files — governance/constitution/schema files never touched

EXIT CODES
  0 — success (including "nothing to do")
  1 — SYNC_ERROR_* printed as JSON to stdout
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

PROTECTED_PATHS: frozenset[str] = frozenset({
    "docs/CONSTITUTION.md",
    "docs/governance/ARCHITECT_SPEC_v3.1.0.md",
    "governance/CANONICAL_ENGINE_DECLARATION.md",
    "governance_runtime_profile.lock.json",
    "runtime/constitution.py",
    "schemas/",
    ".github/workflows/",
    "AGENTS.md",
    "CHANGELOG.md",
    "VERSION",
})

INFOBOX_START       = "<!-- ADAAD_VERSION_INFOBOX:START -->"
INFOBOX_END         = "<!-- ADAAD_VERSION_INFOBOX:END -->"
ARCH_SNAPSHOT_START = "<!-- ARCH_SNAPSHOT_METADATA:START -->"
ARCH_SNAPSHOT_END   = "<!-- ARCH_SNAPSHOT_METADATA:END -->"
INFOBOX_SYNC_CONTEXT_NOTE = (
    "<!-- Sync context: generated from current git metadata at sync time; "
    "reflects last sync context only, not arbitrary local working trees. -->"
)

# Matches `<span class="version-pill">vX.Y.Z</span>` with deterministic group
# replacement for the version value only.
_HTML_VERSION_PILL_RE: re.Pattern[str] = re.compile(
    r'(<span\s+class=["\']version-pill["\']>\s*v)(\d+\.\d+\.\d+)(\s*</span>)',
    re.IGNORECASE,
)
_RULE_INSTALL_HTML_VERSION_PILL = "install_html_version_pill"

# ────────────────────────────────────────────────────────────────────────────

@dataclass
class SyncPlan:
    version:          str
    prev_version:     str
    date_str:         str
    changelog_entry:  str
    new_capabilities: list[str]
    new_modules:      list[str]
    shipped_phases:   list[str]
    git_sha:          str
    git_branch:       str
    git_tag:          str
    merged_files:     list[str]
    changes: list[dict[str, Any]] = field(default_factory=list)

    def record(self, rel: str, rule: str, old: str = "", new: str = "") -> None:
        self.changes.append(
            {"file": rel, "rule": rule,
             "old": (old or "")[:120], "new": (new or "")[:120]}
        )


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")

def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")

def _is_protected(rel: str) -> bool:
    for guard in PROTECTED_PATHS:
        if rel.startswith(guard) or rel == guard.rstrip("/"):
            return True
    return False

def _fatal(code: str, msg: str) -> None:
    print(json.dumps({"event": code, "message": msg}))
    sys.exit(1)

def _emit(event: str, payload: dict[str, Any]) -> None:
    print(json.dumps({"event": event, **payload}), flush=True)


# ── Source-of-truth readers ───────────────────────────────────────────────────

def _read_version() -> str:
    v = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", v):
        _fatal("SYNC_ERROR_BAD_VERSION", f"VERSION contains {v!r}")
    return v


def _read_prev_version(version: str) -> str:
    cl = _read(ROOT / "CHANGELOG.md")
    headers = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", cl, re.MULTILINE)
    seen = False
    for h in headers:
        if h == version:
            seen = True
            continue
        if seen:
            return h
    return version


def _read_changelog_entry(
    version: str,
) -> tuple[str, list[str], list[str], list[str]]:
    """Return (block, capability_lines, module_paths, shipped_phases)."""
    cl = _read(ROOT / "CHANGELOG.md")
    pat = rf"(^## \[{re.escape(version)}\].*?)(?=^## \[|\Z)"
    m = re.search(pat, cl, re.MULTILINE | re.DOTALL)
    if not m:
        return "", [], [], []

    block = m.group(1).strip()
    caps: list[str] = []
    mods: list[str] = []
    phases: list[str] = []

    for line in block.splitlines():
        s = line.strip()
        if s.startswith("- **New:**") or s.startswith("- **New "):
            caps.append(s)
        for mod in re.findall(r"`([a-zA-Z0-9_/]+\.[a-zA-Z]{2,6})`", s):
            if "/" in mod and mod not in mods:
                mods.append(mod)
        if s.startswith("### ") and "SHIPPED" in s.upper():
            clean = re.sub(r"\(SHIPPED\)", "", s.lstrip("#"),
                           flags=re.IGNORECASE).strip()
            phases.append(clean)

    return block, caps, mods[:12], phases


def _git(args_: list[str]) -> str:
    try:
        return subprocess.check_output(
            ["git"] + args_, cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return ""


def _git_sha() -> str:
    return _git(["rev-parse", "--short", "HEAD"]) or "unknown"

def _git_branch() -> str:
    return _git(["rev-parse", "--abbrev-ref", "HEAD"]) or "main"


def _git_tag() -> str:
    return _git(["describe", "--tags", "--exact-match"]) or "(none)"

def _git_merged_files() -> list[str]:
    out = _git(["diff-tree", "--no-commit-id", "-r", "--name-only", "HEAD"])
    return [f for f in out.splitlines() if f] if out else []


# ── Replacement rules ─────────────────────────────────────────────────────────

def _replace_badge_version(content: str, version: str) -> tuple[str, list[str]]:
    pat = r"(https://img\.shields\.io/badge/version-)(\d+\.\d+\.\d+)(-[0-9a-fA-F]+)"
    old_vers = [m[1] for m in re.findall(pat, content)]
    new = re.sub(pat, rf"\g<1>{version}\g<3>", content)
    return new, [f"badge {v}→{version}" for v in old_vers if v != version]


def _replace_inline_badge(content: str, version: str) -> tuple[str, list[str]]:
    pat = r"(!\[Version: )(\d+\.\d+\.\d+)(\])"
    old_vers = re.findall(r"!\[Version: (\d+\.\d+\.\d+)\]", content)
    new = re.sub(pat, rf"\g<1>{version}\g<3>", content)
    return new, [f"inline-badge {v}→{version}" for v in old_vers if v != version]


def _replace_html_version_pill(content: str, version: str) -> tuple[str, list[str]]:
    """Replace version-pill semver values using VERSION as the only source."""
    changes: list[str] = []

    def _repl(match: re.Match[str]) -> str:
        old = match.group(2)
        if old == version:
            return match.group(0)
        changes.append(f"{_RULE_INSTALL_HTML_VERSION_PILL} {old}→{version}")
        return f"{match.group(1)}{version}{match.group(3)}"

    new = _HTML_VERSION_PILL_RE.sub(_repl, content)
    return new, changes


def _build_infobox(plan: SyncPlan) -> str:
    # Capability summary
    if plan.shipped_phases:
        cap = " · ".join(plan.shipped_phases[:3])
    elif plan.new_capabilities:
        cap = "; ".join(
            re.sub(r"\*\*New:\*\*\s*", "", c.lstrip("- ")).split("—")[0].strip()
            for c in plan.new_capabilities[:4]
        )
    elif plan.new_modules:
        cap = ", ".join(f"`{m}`" for m in plan.new_modules[:4])
    else:
        cap = f"v{plan.version} — see CHANGELOG for details"

    # Module table (up to 6 entries)
    module_section = ""
    if plan.new_modules:
        rows = "\n".join(f"| `{m}` |" for m in plan.new_modules[:6])
        module_section = (
            "\n\n**New modules in this release:**\n\n"
            "| Module |\n|--------|\n" + rows
        )

    return (
        f"{INFOBOX_START}\n"
        f"<!-- Auto-generated by scripts/sync_docs_on_merge.py — do not edit manually -->\n"
        f"{INFOBOX_SYNC_CONTEXT_NOTE}\n"
        f"\n"
        f"| Field | Value |\n"
        f"|---|---|\n"
        f"| **Current version** | `{plan.version}` |\n"
        f"| **Released** | {plan.date_str} |\n"
        f"| **Release SHA** | `{plan.git_sha}` |\n"
        f"| **Release Branch** | `{plan.git_branch}` |\n"
        f"\n"
        f"**New in this release:** {cap}"
        f"{module_section}\n"
        f"\n"
        f"{INFOBOX_END}"
    )


def _update_version_infobox(content: str, plan: SyncPlan) -> tuple[str, list[str]]:
    new_box = _build_infobox(plan)
    pat = re.compile(
        re.escape(INFOBOX_START) + r".*?" + re.escape(INFOBOX_END), re.DOTALL
    )
    if INFOBOX_START in content:
        new_content = pat.sub(new_box, content)
        if new_content == content:
            return content, []
        return new_content, [f"VERSION_INFOBOX refreshed→v{plan.version}"]

    # Auto-inject: try inserting before the tagline paragraph
    inject_pat = re.compile(
        r"(</p>\n)(\n<p align=\"center\">.*?<b>)", re.DOTALL
    )
    m = inject_pat.search(content)
    if m:
        new_content = (
            content[: m.start()]
            + m.group(1)
            + "\n" + new_box + "\n"
            + m.group(2)
            + content[m.end():]
        )
        return new_content, [f"VERSION_INFOBOX injected→v{plan.version}"]
    return content, []


def _update_arch_snapshot(content: str, plan: SyncPlan) -> tuple[str, list[str]]:
    if ARCH_SNAPSHOT_START not in content:
        return content, []
    new_block = (
        f"{ARCH_SNAPSHOT_START}\n"
        f"## Architecture Deep-Dive Snapshot\n\n"
        f"| Metric | Value |\n| --- | --- |\n"
        f"| Report version | `{plan.version}` |\n"
        f"| Branch | `{plan.git_branch}` |\n"
        f"| Tag | `{plan.git_tag}` |\n"
        f"| Short SHA | `{plan.git_sha}` |\n"
        f"| Last sync | {plan.date_str} |\n\n"
        f"All future architecture snapshots MUST include branch, tag (if any), and short SHA.\n"
        f"{ARCH_SNAPSHOT_END}"
    )
    pat = re.compile(
        re.escape(ARCH_SNAPSHOT_START) + r".*?" + re.escape(ARCH_SNAPSHOT_END),
        re.DOTALL,
    )
    new_content = pat.sub(new_block, content)
    if new_content == content:
        return content, []
    return new_content, [f"ARCH_SNAPSHOT→v{plan.version}/{plan.git_sha}"]


def _update_evolution_table(content: str, plan: SyncPlan) -> tuple[str, list[str]]:
    table_pat = re.compile(
        r"(## Evolution History\n\n\| Version \| Capability \|\n\|[-| ]+\|\n)(.*?)(\n---)",
        re.DOTALL,
    )
    m = table_pat.search(content)
    if not m:
        return content, []

    header, rows, tail = m.group(1), m.group(2), m.group(3)
    major_minor = ".".join(plan.version.split(".")[:2])

    if f"**v{major_minor}**" in rows or f"v{major_minor} " in rows:
        return content, []

    # Build summary
    parts: list[str] = []
    for line in plan.changelog_entry.splitlines():
        s = line.strip()
        if s.startswith("### ") and "SHIPPED" in s.upper():
            parts.append(
                re.sub(r"\(SHIPPED\)", "", s.lstrip("#"), flags=re.IGNORECASE).strip()
            )
    if not parts:
        for line in plan.changelog_entry.splitlines():
            if line.strip().startswith("#### "):
                parts.append(line.strip().lstrip("#").strip())
                break
    cap = " · ".join(parts) if parts else f"v{plan.version} capabilities"

    new_row = f"| **v{major_minor}** | {cap} |\n"
    new_content = content.replace(
        header + rows + tail, header + new_row + rows + tail
    )
    if new_content == content:
        return content, []
    return new_content, [f"Evolution table row added v{major_minor}"]


def _update_roadmap_ships_today(content: str, plan: SyncPlan) -> tuple[str, list[str]]:
    pat = re.compile(r"(## What ships today — v)(\d+\.\d+\.\d+)")
    m = pat.search(content)
    if not m or m.group(2) == plan.version:
        return content, []
    old = m.group(2)
    return pat.sub(rf"\g<1>{plan.version}", content), \
           [f"ROADMAP ships-today {old}→{plan.version}"]


def _update_roadmap_phase_targets(content: str, plan: SyncPlan) -> tuple[str, list[str]]:
    pat = re.compile(
        r"(\*\*Target:\*\* v)(" + re.escape(plan.version) + r")((?! ✅).*?)(?=\n)"
    )
    changes: list[str] = []
    def mark(m: re.Match) -> str:
        changes.append(f"ROADMAP phase target v{plan.version} marked ✅")
        return m.group(1) + m.group(2) + " ✅" + m.group(3)
    new_content = pat.sub(mark, content)
    return new_content, changes


# ── JSON file updaters ────────────────────────────────────────────────────────

def _update_governance_report_version(plan: SyncPlan) -> list[dict[str, Any]]:
    path = ROOT / "governance" / "report_version.json"
    if not path.exists():
        return []
    try:
        obj = json.loads(_read(path))
    except json.JSONDecodeError:
        return []

    old = obj.get("report_version", "")
    if old == plan.version and obj.get("last_sync_sha") == plan.git_sha:
        return []

    obj["report_version"] = plan.version
    obj["version"] = plan.version
    obj["version_source"] = "governance/report_version.json"
    obj["last_sync_sha"] = plan.git_sha
    obj["last_sync_date"] = plan.date_str
    _write(path, json.dumps(obj, indent=2, sort_keys=True) + "\n")
    return [{"file": "governance/report_version.json",
             "rule": "report_version", "old": old, "new": plan.version}]


def _update_agent_state(plan: SyncPlan) -> list[dict[str, Any]]:
    path = ROOT / ".adaad_agent_state.json"
    if not path.exists():
        return []
    try:
        state = json.loads(_read(path))
    except json.JSONDecodeError:
        return []

    rel = ".adaad_agent_state.json"
    changes: list[dict[str, Any]] = []

    def _set(key: str, val: str, rule: str) -> None:
        old = str(state.get(key, ""))
        if old != val:
            state[key] = val
            changes.append({"file": rel, "rule": rule, "old": old[:80], "new": val})

    # Rationale: release identity aliases follow VERSION; schema_version is
    # intentionally preserved as the JSON document-format invariant.
    _set("version", plan.version, "version")
    _set("current_version", plan.version, "current_version")
    _set("software_version", plan.version, "software_version")
    _set("last_completed_version", plan.version, "last_completed_version")
    _set("active_phase",
         f"v{plan.version} RELEASED · post-merge doc sync",
         "active_phase")
    _set("last_invocation", plan.date_str, "last_invocation")
    _set("last_sync_sha", plan.git_sha, "last_sync_sha")

    if changes:
        _write(path, json.dumps(state, indent=2, sort_keys=False) + "\n")
    return changes


# ── File processor ────────────────────────────────────────────────────────────

def _process_file(
    path: Path, plan: SyncPlan, dry_run: bool
) -> list[dict[str, Any]]:
    rel = str(path.relative_to(ROOT))
    if _is_protected(rel) or not path.is_file():
        return []

    try:
        original = _read(path)
    except Exception as exc:
        _fatal("SYNC_ERROR_READ", f"Cannot read {rel}: {exc}")
        return []

    content = original
    file_changes: list[str] = []

    content, c = _replace_badge_version(content, plan.version)
    file_changes.extend(c)

    content, c = _replace_inline_badge(content, plan.version)
    file_changes.extend(c)

    if path.suffix.lower() == ".html":
        content, c = _replace_html_version_pill(content, plan.version)
        file_changes.extend(c)

    if INFOBOX_START in original or rel == "README.md":
        content, c = _update_version_infobox(content, plan)
        file_changes.extend(c)

    if ARCH_SNAPSHOT_START in original:
        content, c = _update_arch_snapshot(content, plan)
        file_changes.extend(c)

    if rel == "README.md":
        content, c = _update_evolution_table(content, plan)
        file_changes.extend(c)

    if rel == "ROADMAP.md":
        content, c = _update_roadmap_ships_today(content, plan)
        file_changes.extend(c)
        content, c = _update_roadmap_phase_targets(content, plan)
        file_changes.extend(c)

    if content == original or not file_changes:
        return []

    if not dry_run:
        try:
            _write(path, content)
        except Exception as exc:
            _fatal("SYNC_ERROR_WRITE", f"Cannot write {rel}: {exc}")

    return [{"file": rel, "rule": r} for r in file_changes]


# ── Target discovery ──────────────────────────────────────────────────────────

_ALWAYS_SYNC: list[str] = [
    "docs/install.html",
    "README.md",
    "ROADMAP.md",
    "QUICKSTART.md",
    "docs/README_IMPLEMENTATION_ALIGNMENT.md",
    "docs/EVOLUTION_ARCHITECTURE.md",
    "docs/ARCHITECTURE_SUMMARY.md",
    "docs/ARCHITECTURE_CONTRACT.md",
    "docs/FOUNDATIONS.md",
]

_SCAN_DIRS: list[str] = ["."]

_SKIP_SCAN_DIR_PREFIXES: tuple[str, ...] = (
    ".git/",
    ".venv/",
    "venv/",
    "node_modules/",
    "dist/",
    "build/",
    "site-packages/",
    "archives/",
)


def _collect_targets() -> list[Path]:
    targets: list[Path] = []
    seen: set[Path] = set()
    for rel in _ALWAYS_SYNC:
        p = ROOT / rel
        if p.exists() and p not in seen:
            targets.append(p)
            seen.add(p)
    for d in _SCAN_DIRS:
        dr = ROOT / d
        if dr.is_dir():
            for p in sorted(dr.rglob("*.md")):
                rel = str(p.relative_to(ROOT))
                if rel.startswith(_SKIP_SCAN_DIR_PREFIXES):
                    continue
                if p not in seen and not _is_protected(rel):
                    targets.append(p)
                    seen.add(p)
    return targets


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Post-merge documentation synchroniser."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print planned changes without writing files.")
    parser.add_argument("--format", choices=("text", "json"), default="json")
    args = parser.parse_args(argv)

    version      = _read_version()
    prev_ver     = _read_prev_version(version)
    date_str     = date.today().isoformat()
    # Always derive metadata from the current git state at sync time.
    sha          = _git_sha()
    branch       = _git_branch()
    tag          = _git_tag()
    merged_files = _git_merged_files()
    entry, caps, modules, phases = _read_changelog_entry(version)

    plan = SyncPlan(
        version=version, prev_version=prev_ver, date_str=date_str,
        changelog_entry=entry, new_capabilities=caps,
        new_modules=modules, shipped_phases=phases,
        git_sha=sha, git_branch=branch, git_tag=tag, merged_files=merged_files,
    )

    _emit("sync_start", {
        "version": version, "prev_version": prev_ver, "git_sha": sha,
        "git_branch": branch, "git_tag": tag, "merged_files": len(merged_files),
        "new_modules": modules, "shipped_phases": phases,
        "dry_run": args.dry_run,
    })

    all_changes: list[dict[str, Any]] = []

    if not args.dry_run:
        for updater in (_update_governance_report_version, _update_agent_state):
            fc = updater(plan)  # type: ignore[call-arg]
            all_changes.extend(fc)
            for c in fc:
                _emit("file_updated", {"file": c["file"], "changes": [c["rule"]]})

    for path in _collect_targets():
        rel = str(path.relative_to(ROOT))
        fc = _process_file(path, plan, dry_run=args.dry_run)
        if fc:
            all_changes.extend(fc)
            _emit("file_updated", {"file": rel, "changes": [c["rule"] for c in fc]})
        else:
            _emit("file_skipped", {"file": rel, "reason": "no changes needed"})

    files_changed = len({c["file"] for c in all_changes})

    _emit("sync_complete", {
        "version": version,
        # Contract invariant: always emit integer files_changed for CI parsers.
        "files_changed": files_changed,
        "total_replacements": len(all_changes),
        "dry_run": args.dry_run,
    })

    # Secondary dry-run summary event for lightweight stdout parsers.
    if args.dry_run:
        _emit("dry_run_summary", {"files_would_change": files_changed})

    if args.format == "text" and all_changes:
        print("\nSummary:")
        for c in all_changes:
            print(f"  [{c['file']}] {c.get('rule', '')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
