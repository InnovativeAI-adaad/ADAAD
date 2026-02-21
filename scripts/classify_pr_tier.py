#!/usr/bin/env python3
"""Classify changed files into governance tiers."""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path

TIER_RANK = {"Tier-2": 2, "Tier-1": 1, "Tier-0": 0}


def load_tier_rules(tier_map_path: Path) -> list[dict[str, str]]:
    data = json.loads(tier_map_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "rules" not in data:
        raise ValueError("Tier map must be a mapping with a 'rules' key.")

    rules = data["rules"]
    if not isinstance(rules, list):
        raise ValueError("'rules' must be a list.")

    parsed_rules: list[dict[str, str]] = []
    for idx, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise ValueError(f"Rule at index {idx} must be an object.")
        glob = rule.get("glob")
        tier = rule.get("tier")
        if not isinstance(glob, str) or not isinstance(tier, str):
            raise ValueError(f"Rule at index {idx} must include string glob and tier.")
        if tier not in TIER_RANK:
            raise ValueError(f"Rule at index {idx} has unknown tier: {tier}")
        parsed_rules.append({"glob": glob, "tier": tier})
    return parsed_rules


def normalize_paths(raw_paths: list[str]) -> list[str]:
    normalized = {
        path.strip()[2:] if path.strip().startswith("./") else path.strip()
        for path in raw_paths
        if path and path.strip()
    }
    return sorted(normalized)


def collect_paths(args: argparse.Namespace) -> list[str]:
    if args.paths_file:
        contents = Path(args.paths_file).read_text(encoding="utf-8")
        paths = contents.splitlines()
    elif args.paths:
        paths = args.paths
    else:
        paths = sys.stdin.read().splitlines()

    normalized = normalize_paths(paths)
    if not normalized:
        raise ValueError("No changed file paths supplied.")
    return normalized


def classify_path(path: str, rules: list[dict[str, str]]) -> str | None:
    matches = [rule["tier"] for rule in rules if fnmatch.fnmatch(path, rule["glob"])]
    if not matches:
        return None
    return sorted(matches, key=lambda tier: TIER_RANK[tier])[0]


def write_github_output(path: str, overall_tier: str, strict_replay_required: bool) -> None:
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(f"tier={overall_tier}\n")
        handle.write(f"strict_replay_required={'true' if strict_replay_required else 'false'}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="Changed file paths.")
    parser.add_argument(
        "--paths-file",
        default="",
        help="Read changed paths from a newline-delimited file.",
    )
    parser.add_argument(
        "--tier-map",
        default="governance/tier_map.yaml",
        help="Path to tier mapping file.",
    )
    parser.add_argument(
        "--github-output",
        default="",
        help="Optional GitHub output file path.",
    )
    args = parser.parse_args()

    rules = load_tier_rules(Path(args.tier_map))
    paths = collect_paths(args)

    unmatched: list[str] = []
    classified: list[tuple[str, str]] = []
    for path in paths:
        tier = classify_path(path, rules)
        if tier is None:
            unmatched.append(path)
        else:
            classified.append((path, tier))

    print("PR Tier Classification")
    print("======================")
    for path, tier in classified:
        print(f"{path}: {tier}")

    if unmatched:
        print("\nERROR: Unmatched file paths (fail-closed):")
        for path in unmatched:
            print(f"- {path}")
        return 2

    overall_tier = sorted((tier for _, tier in classified), key=lambda t: TIER_RANK[t])[0]
    strict_replay_required = overall_tier == "Tier-0"

    print("\nSummary")
    print("-------")
    print(f"overall_tier={overall_tier}")
    print(f"strict_replay_required={'true' if strict_replay_required else 'false'}")

    if args.github_output:
        write_github_output(args.github_output, overall_tier, strict_replay_required)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
