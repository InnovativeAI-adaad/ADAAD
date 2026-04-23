#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run ADAAD / DEVADAAD trigger orchestration, including verified-SHA merge execution."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from adaad.orchestrator.adaad_trigger import run_trigger


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", help='Trigger command, for example: "ADAAD simulate"')
    parser.add_argument(
        "--scenario",
        default="merge_ready",
        choices=[
            "dependency_blocked",
            "evidence_missing",
            "tier1_failure",
            "merge_ready",
            "merge_verification_missing",
            "replay_diverged",
        ],
        help="Predefined scenario profile for orchestration/gate evaluation output.",
    )
    parser.add_argument("--json", action="store_true", help="Emit full JSON envelope.")
    args = parser.parse_args()

    envelope = run_trigger(args.command, repo_root=Path.cwd(), scenario=args.scenario)
    if args.json:
        print(json.dumps(envelope, indent=2, sort_keys=True, default=str))
    else:
        print(envelope["output"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
