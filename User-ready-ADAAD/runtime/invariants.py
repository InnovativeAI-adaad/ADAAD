"""
Core invariant checks to enforce canonical tree and banned import policies.
"""

import re
import os
from pathlib import Path
from typing import List, Tuple

from runtime import ROOT_DIR, metrics

ELEMENT_ID = "Earth"

REQUIRED_DIRS = [
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
]

BANNED_ROOTS = {"core", "engines", "adad_core", "ADAAD22"}


def verify_tree() -> Tuple[bool, List[str]]:
    missing = [name for name in REQUIRED_DIRS if not (ROOT_DIR / name).exists()]
    if missing:
        metrics.log(event_type="invariant_missing_dirs", payload={"missing": missing}, level="ERROR", element_id=ELEMENT_ID)
        return False, missing
    metrics.log(event_type="invariant_tree_ok", payload={"dirs": REQUIRED_DIRS}, level="INFO", element_id=ELEMENT_ID)
    return True, []


def scan_banned_imports() -> Tuple[bool, List[str]]:
    failures: List[str] = []
    for path in ROOT_DIR.rglob("*.py"):
        if "archives" in path.parts:
            continue
        content = path.read_text(encoding="utf-8").splitlines()
        for lineno, line in enumerate(content, start=1):
            if line.startswith(("from ", "import ")):
                match = re.match(r"^(from|import) ([\\w\\.\\/]+)", line)
                if not match:
                    continue
                root = match.group(2).split(".")[0]
                if root in BANNED_ROOTS or root.startswith("/"):
                    failures.append(f"{path}:{lineno}:{line.strip()}")
    if failures:
        metrics.log(
            event_type="invariant_banned_imports",
            payload={"failures": failures},
            level="ERROR",
            element_id=ELEMENT_ID,
        )
        return False, failures
    metrics.log(event_type="invariant_imports_ok", payload={}, level="INFO", element_id=ELEMENT_ID)
    return True, []


def verify_metrics_path() -> Tuple[bool, List[str]]:
    from runtime import metrics as metrics_module  # local import to avoid circular

    try:
        metrics_module.log(event_type="invariant_metrics_probe", payload={}, level="INFO", element_id=ELEMENT_ID)
        return True, []
    except Exception as exc:  # pragma: no cover - defensive
        failure = f"metrics_probe_failed:{exc}"
        metrics.log(event_type="invariant_metrics_failed", payload={"error": str(exc)}, level="ERROR", element_id=ELEMENT_ID)
        return False, [failure]


def verify_security_paths() -> Tuple[bool, List[str]]:
    ledger_dir = ROOT_DIR / "security" / "ledger"
    keys_dir = ROOT_DIR / "security" / "keys"
    failures: List[str] = []
    if not ledger_dir.exists():
        failures.append("ledger_missing")
    if ledger_dir.exists() and not os.access(ledger_dir, os.W_OK):
        failures.append("ledger_not_writable")
    if not keys_dir.exists():
        failures.append("keys_missing")
    if failures:
        metrics.log(event_type="invariant_security_failed", payload={"failures": failures}, level="ERROR", element_id=ELEMENT_ID)
        return False, failures
    metrics.log(event_type="invariant_security_ok", payload={}, level="INFO", element_id=ELEMENT_ID)
    return True, []


def verify_all() -> Tuple[bool, List[str]]:
    checks = [verify_tree(), scan_banned_imports(), verify_metrics_path(), verify_security_paths()]
    failures: List[str] = []
    for ok, msgs in checks:
        if not ok:
            failures.extend(msgs)
    if failures:
        metrics.log(event_type="invariant_check_failed", payload={"failures": failures}, level="ERROR", element_id=ELEMENT_ID)
        return False, failures
    metrics.log(event_type="invariant_check_passed", payload={}, level="INFO", element_id=ELEMENT_ID)
    return True, []
