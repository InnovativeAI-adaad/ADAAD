# SPDX-License-Identifier: Apache-2.0
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Core invariant checks to enforce canonical tree and banned import policies.
"""

import json
import os
import re
from pathlib import Path
from typing import List, Tuple

from runtime import ROOT_DIR, metrics
from runtime.founders_law import (
    RULE_INVARIANT_ABS_PATHS,
    RULE_INVARIANT_CAPABILITIES,
    RULE_INVARIANT_IMPORTS,
    RULE_INVARIANT_METRICS,
    RULE_INVARIANT_SECURITY,
    RULE_INVARIANT_STAGING,
    RULE_INVARIANT_TREE,
    enforce_law,
)

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
BANNED_ABSOLUTE_PATTERNS = ["/workspace/", "/home/", "/sdcard/", "/storage/"]


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


def ensure_staging_dir() -> Tuple[bool, List[str]]:
    staging = ROOT_DIR / "app" / "agents" / "lineage" / "_staging"
    try:
        staging.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # pragma: no cover - defensive
        metrics.log(event_type="invariant_staging_failed", payload={"error": str(exc)}, level="ERROR", element_id=ELEMENT_ID)
        return False, [f"staging_unavailable:{exc}"]
    metrics.log(event_type="invariant_staging_ok", payload={"path": str(staging)}, level="INFO", element_id=ELEMENT_ID)
    return True, []


def verify_capabilities_file() -> Tuple[bool, List[str]]:
    capabilities_path = ROOT_DIR / "data" / "capabilities.json"
    if not capabilities_path.exists():
        return True, []
    try:
        json.loads(capabilities_path.read_text(encoding="utf-8"))
        return True, []
    except Exception as exc:  # pragma: no cover - defensive
        metrics.log(event_type="invariant_capabilities_invalid", payload={"error": str(exc)}, level="ERROR", element_id=ELEMENT_ID)
        return False, [f"capabilities_invalid:{exc}"]


def scan_absolute_paths() -> Tuple[bool, List[str]]:
    failures: List[str] = []
    for path in ROOT_DIR.rglob("*.py"):
        if "archives" in path.parts:
            continue
        if path.resolve() == Path(__file__).resolve():
            continue
        content = path.read_text(encoding="utf-8").splitlines()
        for lineno, line in enumerate(content, start=1):
            if any(pattern in line for pattern in BANNED_ABSOLUTE_PATTERNS):
                failures.append(f"{path}:{lineno}:{line.strip()}")
    if failures:
        metrics.log(event_type="invariant_abs_paths_failed", payload={"failures": failures}, level="ERROR", element_id=ELEMENT_ID)
        return False, failures
    metrics.log(event_type="invariant_abs_paths_ok", payload={}, level="INFO", element_id=ELEMENT_ID)
    return True, []


def verify_all() -> Tuple[bool, List[str]]:
    checks = [
        (RULE_INVARIANT_TREE, *verify_tree()),
        (RULE_INVARIANT_IMPORTS, *scan_banned_imports()),
        (RULE_INVARIANT_ABS_PATHS, *scan_absolute_paths()),
        (RULE_INVARIANT_METRICS, *verify_metrics_path()),
        (RULE_INVARIANT_SECURITY, *verify_security_paths()),
        (RULE_INVARIANT_STAGING, *ensure_staging_dir()),
        (RULE_INVARIANT_CAPABILITIES, *verify_capabilities_file()),
    ]
    failures: List[str] = []
    for _rule, ok, msgs in checks:
        if not ok:
            failures.extend(msgs)

    enforce_law(
        {
            "mutation_id": "invariants.verify_all",
            "trust_mode": "runtime",
            "checks": [{"rule_id": rule_id, "ok": ok, "reason": ";".join(msgs)} for rule_id, ok, msgs in checks],
        }
    )

    if failures:
        metrics.log(event_type="invariant_check_failed", payload={"failures": failures}, level="ERROR", element_id=ELEMENT_ID)
        return False, failures
    metrics.log(event_type="invariant_check_passed", payload={}, level="INFO", element_id=ELEMENT_ID)
    return True, []
