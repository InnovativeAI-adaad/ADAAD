# SPDX-License-Identifier: Apache-2.0
"""
check_invariant_count.py — CI gate enforcing invariant count consistency.

Reads the canonical count from artifacts/governance/invariant_registry.json
and verifies that all document surfaces reference the correct number.
Fails with a non-zero exit code if any surface is stale.

Audit finding C-2: Internal claim inconsistencies.
"""
import json
import re
import sys
from pathlib import Path

REGISTRY = Path("artifacts/governance/invariant_registry.json")

SURFACES: list[tuple[str, str]] = [
    # (filepath, human label)
    ("README.md", "README badge"),
    ("ROADMAP.md", "ROADMAP current state"),
    ("TRUST_CENTER.md", "Trust Center header"),
    ("CONTRIBUTING.md", "Contributing checkpoint"),
    ("docs/CONSTITUTION.md", "Constitution active phase"),
]


def load_registry() -> dict:
    if not REGISTRY.exists():
        print(f"[FAIL] Registry not found: {REGISTRY}", file=sys.stderr)
        sys.exit(1)
    return json.loads(REGISTRY.read_text())


def check_surface(path: str, label: str, expected: int) -> list[str]:
    """Return list of failure messages for this surface."""
    p = Path(path)
    if not p.exists():
        return [f"[SKIP] {label} ({path}) — file not found"]
    text = p.read_text()
    # Find all integer values that follow "invariant" context within ±100 chars
    pattern = re.compile(r"(\d{3,})\s*Hard.class", re.IGNORECASE)
    matches = pattern.findall(text)
    failures = []
    for m in matches:
        found = int(m)
        if found != expected:
            failures.append(
                f"[FAIL] {label} ({path}): found {found}, expected {expected}"
            )
    return failures


def main() -> int:
    registry = load_registry()
    expected = registry["cumulative_hard_class_invariants"]
    phase = registry["phase"]
    version = registry["version"]

    print(f"Invariant registry: v{version} · Phase {phase} · {expected} Hard-class invariants")
    print("-" * 60)

    all_failures: list[str] = []
    for path, label in SURFACES:
        failures = check_surface(path, label, expected)
        if failures:
            all_failures.extend(failures)
            for f in failures:
                print(f)
        else:
            p = Path(path)
            if p.exists():
                print(f"[OK]   {label} ({path})")
            else:
                print(f"[SKIP] {label} ({path}) — not found")

    print("-" * 60)
    if all_failures:
        print(f"FAILED: {len(all_failures)} stale invariant count(s) detected.")
        print("Update the stale surface(s) to match the registry before merging.")
        return 1

    print(f"PASSED: All surfaces reference {expected} Hard-class invariants.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
