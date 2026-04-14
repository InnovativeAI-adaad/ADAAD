#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
validate_phase_test_attestation.py — Phase 140 · WL-010 · TEST-ATTEST-0

Constitutional invariant TEST-ATTEST-0:
    Every innovation shipped in innovations_shipped MUST carry a
    tests field equal to "30/30".  Any entry with a missing, malformed,
    or non-passing attestation causes this script to exit non-zero,
    blocking the CI gate.

Usage:
    python scripts/validate_phase_test_attestation.py [--format json]
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path


def _load_agent_state(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(agent_state_path: Path) -> list[dict]:
    """Return list of violation dicts; empty means all attestations pass."""
    state = _load_agent_state(agent_state_path)
    shipped: dict = state.get("innovations_shipped") or {}
    violations: list[dict] = []

    for innov_id, meta in shipped.items():
        tests_val = meta.get("tests")
        if tests_val is None:
            violations.append({
                "innov_id": innov_id,
                "reason": "missing_tests_field",
                "tests": None,
                "invariant": "TEST-ATTEST-0",
            })
        elif str(tests_val).strip() != "30/30":
            violations.append({
                "innov_id": innov_id,
                "reason": "non_passing_attestation",
                "tests": tests_val,
                "invariant": "TEST-ATTEST-0",
            })

    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate 30-test attestation for all shipped innovations.")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument(
        "--state",
        default=".adaad_agent_state.json",
        help="Path to .adaad_agent_state.json",
    )
    args = parser.parse_args()

    state_path = Path(args.state)
    if not state_path.exists():
        print(f"ERROR: agent state file not found: {state_path}", file=sys.stderr)
        return 1

    violations = validate(state_path)

    if args.format == "json":
        result = {
            "invariant": "TEST-ATTEST-0",
            "passed": len(violations) == 0,
            "violations": violations,
            "total_shipped": len(
                (json.loads(state_path.read_text(encoding="utf-8")).get("innovations_shipped") or {})
            ),
        }
        print(json.dumps(result, indent=2))
    else:
        if violations:
            print("TEST-ATTEST-0 VIOLATIONS:")
            for v in violations:
                print(f"  [{v['innov_id']}] {v['reason']} — tests={v['tests']!r}")
        else:
            shipped_count = len(
                (json.loads(state_path.read_text(encoding="utf-8")).get("innovations_shipped") or {})
            )
            print(f"TEST-ATTEST-0 PASS — {shipped_count} innovations all carry 30/30 attestation.")

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
