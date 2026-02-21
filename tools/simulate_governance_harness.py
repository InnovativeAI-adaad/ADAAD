# SPDX-License-Identifier: Apache-2.0
"""Deterministic governance simulation harness for constitutional rule evaluation."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from app.agents.mutation_request import MutationRequest
from runtime import constitution


@dataclass(frozen=True)
class SimulationSummary:
    total_requests: int
    passed: int
    blocked: int
    warnings: int
    unique_envelope_digests: int


def _request(index: int) -> MutationRequest:
    return MutationRequest(
        agent_id="test_subject",
        generation_ts="2026-01-01T00:00:00Z",
        intent=f"simulate-{index}",
        ops=[{"op": "replace", "path": "/value", "value": index}],
        signature="cryovant-dev-test",
        nonce=f"nonce-{index:05d}",
        epoch_id=f"sim-epoch-{index // 100}",
    )


def run_simulation(*, count: int, tier: constitution.Tier) -> SimulationSummary:
    passed = 0
    blocked = 0
    warnings = 0
    digests: set[str] = set()

    for idx in range(count):
        verdict = constitution.evaluate_mutation(_request(idx), tier)
        if verdict.get("passed"):
            passed += 1
        else:
            blocked += 1
        warnings += len(verdict.get("warnings", []))
        digests.add(str(verdict.get("governance_envelope", {}).get("digest", "")))

    return SimulationSummary(
        total_requests=count,
        passed=passed,
        blocked=blocked,
        warnings=warnings,
        unique_envelope_digests=len(digests),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic governance simulation harness.")
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--tier", choices=[tier.name for tier in constitution.Tier], default="SANDBOX")
    parser.add_argument("--output", default="", help="Optional JSON output file path.")
    args = parser.parse_args(argv)

    summary = run_simulation(count=max(1, args.count), tier=constitution.Tier[args.tier])
    payload = asdict(summary)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
