from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# He65 Nexus Setup
# Structure-only. Idempotent. No imports from app/runtime/security.
# Allowed side effects: mkdir, touch .keep, write missing docs, write missing __init__.py, best-effort chmod keys dir.

ROOT = Path(__file__).resolve().parents[1]
SENTINEL = "HE65_ROOT"

CANONICAL_ROOTS: Tuple[str, ...] = (
    "app",
    "runtime",
    "security",
    "tests",
    "docs",
    "data",
    "reports",
    "releases",
    "experiments",
    "scripts",
    "ui",
    "tools",
    "archives",
)

CANONICAL_DIRS: Tuple[str, ...] = (
    *CANONICAL_ROOTS,
    "docs/protocols/v1",
    "runtime/interfaces",
    "runtime/tools",
    "security/ledger",
    "security/keys",
    "app/agents",
    "app/agents/incubator",
    "app/agents/candidates",
    "app/agents/active",
    "app/agents/quarantine",
    "app/agents/lineage",
    "app/agents/agent_template",
    "data/work/00_inbox",
    "data/work/01_active",
    "data/work/02_review",
    "data/work/03_done",
    "data/logs",
)

PACKAGE_ROOTS: Tuple[str, ...] = ("app", "runtime", "security", "ui", "reports")

PROTOCOL_FILES: Dict[str, str] = {
    "docs/protocols/v1/logging_standard.md": """# Protocol v1.0: Structured Logging Standard

## Mandate
1. No direct use of `print()` in `runtime/` or `app/`.
2. All logs must be structured JSON lines (JSONL).
3. Rotation occurs at 5MB.
4. Callers must redact secrets before logging.

## Canonical Schema
```json
{
  "ts": "ISO-8601 Timestamp",
  "lvl": "INFO|ERROR|DEBUG|AUDIT",
  "cmp": "Component Name",
  "msg": "Human readable message",
  "ctx": { "any": "extra fields" }
}
```""",
    "docs/protocols/v1/cryovant_ledger.md": """# Protocol v1.0: Cryovant Ledger Contract

Purpose

Append-only JSONL ledger for certification, lineage, and gatekeeping outcomes. Ledger entries are the single source of truth for promotions.

Location (fixed)

security/ledger/events.jsonl

Schema (one JSON object per line)

{
  "ts": "ISO-8601 timestamp in UTC",
  "action": "certify|ledger_probe|promotion|doctor_probe|other",
  "actor": "cryovant|gatekeeper|doctor|system|<caller>",
  "outcome": "ok|error|accepted|rejected",
  "agent_id": "string identifier of the agent (if applicable)",
  "lineage_hash": "deterministic hash of agent lineage or metadata",
  "signature_id": "signature or record id, may be stubbed but must be present",
  "detail": { "optional": "additional context" }
}

Rules

File must be append-only; no rewrites or truncation.

Writes must pass through Cryovant helpers.

Boot fails if the ledger directory is not writable.

No other component should emit to this file directly.
""",
}

LEDGER_FILE_REL = "security/ledger/events.jsonl"


def _die(msg: str, code: int = 2) -> None:
    sys.stderr.write(msg.rstrip() + "\n")
    raise SystemExit(code)


def assert_repo_root() -> None:
    sentinel_path = ROOT / SENTINEL
    if not sentinel_path.exists():
        _die(f"ERROR: Missing {SENTINEL} at repo root: {ROOT}")


def ensure_sentinel(dry_run: bool) -> bool:
    path = ROOT / SENTINEL
    if path.exists():
        return False
    if not dry_run:
        path.write_text("", encoding="utf-8")
    return True


def mkdirp(rel: str, dry_run: bool) -> bool:
    path = ROOT / rel
    if path.exists():
        return False
    if not dry_run:
        path.mkdir(parents=True, exist_ok=True)
    return True


def touch_keep(rel_dir: str, dry_run: bool) -> bool:
    keep = ROOT / rel_dir / ".keep"
    if keep.exists():
        return False
    if not dry_run:
        keep.parent.mkdir(parents=True, exist_ok=True)
        keep.touch()
    return True


def ensure_packages(dry_run: bool) -> int:
    created = 0
    for rel in PACKAGE_ROOTS:
        init = ROOT / rel / "__init__.py"
        if init.exists():
            continue
        created += 1
        if not dry_run:
            init.parent.mkdir(parents=True, exist_ok=True)
            init.write_text("", encoding="utf-8")
    return created


def ensure_protocols(dry_run: bool) -> int:
    created = 0
    for rel, content in PROTOCOL_FILES.items():
        path = ROOT / rel
        if path.exists():
            continue
        created += 1
        if not dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content.strip() + "\n", encoding="utf-8")
    return created


def best_effort_chmod_keys() -> None:
    keys_dir = ROOT / "security/keys"
    try:
        keys_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(keys_dir, stat.S_IRWXU)
    except Exception:
        # Best-effort only; do not fail setup on permission issues.
        pass


def check_mode() -> None:
    errors: List[str] = []
    if not (ROOT / SENTINEL).exists():
        errors.append(f"Missing sentinel: {SENTINEL}")

    for rel in CANONICAL_DIRS:
        if not (ROOT / rel).exists():
            errors.append(f"Missing dir: {rel}")

    for rel in PACKAGE_ROOTS:
        if not (ROOT / rel / "__init__.py").exists():
            errors.append(f"Missing package init: {rel}/__init__.py")

    for rel in PROTOCOL_FILES.keys():
        if not (ROOT / rel).exists():
            errors.append(f"Missing protocol doc: {rel}")

    if (ROOT / LEDGER_FILE_REL).exists():
        errors.append(f"Ledger file must not be created by setup: {LEDGER_FILE_REL}")

    if errors:
        _die("CHECK FAILED:\n" + "\n".join(f"- {e}" for e in errors), code=1)

    print("CHECK OK")


def setup_mode() -> None:
    created_dirs = 0
    created_keeps = 0

    ensure_sentinel(dry_run=False)

    for rel in CANONICAL_DIRS:
        if mkdirp(rel, dry_run=False):
            created_dirs += 1
        if touch_keep(rel, dry_run=False):
            created_keeps += 1

    created_inits = ensure_packages(dry_run=False)
    created_docs = ensure_protocols(dry_run=False)

    best_effort_chmod_keys()

    print("He65 nexus setup complete.")
    print(
        f"dirs_created={created_dirs} keeps_created={created_keeps} "
        f"inits_created={created_inits} docs_created={created_docs}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="nexus_setup.py")
    parser.add_argument("--check", action="store_true", help="Validate base without mutating.")
    args = parser.parse_args()

    if args.check:
        assert_repo_root()
        check_mode()
        return

    setup_mode()


if __name__ == "__main__":
    main()
