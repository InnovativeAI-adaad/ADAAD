# SPDX-License-Identifier: Apache-2.0
#!/usr/bin/env python3
"""Validate canonical phase↔innovation mapping consistency.

Fail-closed checks:
1) No INNOV-* ID may be mapped to more than one phase.
2) No phase may be mapped to more than one INNOV-* ID.
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

MAPPING_PATH = Path("docs/governance/PHASE_INNOVATION_MAPPING_CANONICAL.md")
ROW_RE = re.compile(r"^\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*$")
INNOV_RE = re.compile(r"\bINNOV-(\d+)\b")


def main() -> int:
    if not MAPPING_PATH.exists():
        print(f"[phase-innov-map] missing mapping file: {MAPPING_PATH}")
        return 1

    phase_to_innov: dict[int, str] = {}
    innov_to_phases: dict[str, list[int]] = defaultdict(list)

    for raw_line in MAPPING_PATH.read_text(encoding="utf-8").splitlines():
        match = ROW_RE.match(raw_line.strip())
        if not match:
            continue

        phase = int(match.group(1))
        innovation_cell = match.group(2)

        innov_match = INNOV_RE.search(innovation_cell)
        if not innov_match:
            continue

        innov_id = f"INNOV-{int(innov_match.group(1)):02d}"
        if phase in phase_to_innov and phase_to_innov[phase] != innov_id:
            print(
                f"[phase-innov-map] phase {phase} has multiple innovations: "
                f"{phase_to_innov[phase]} and {innov_id}"
            )
            return 1

        phase_to_innov[phase] = innov_id
        innov_to_phases[innov_id].append(phase)

    duplicate_innov = {k: sorted(v) for k, v in innov_to_phases.items() if len(set(v)) > 1}
    if duplicate_innov:
        for innov_id, phases in sorted(duplicate_innov.items()):
            print(f"[phase-innov-map] duplicate innovation mapping: {innov_id} -> phases {phases}")
        return 1

    print(
        "[phase-innov-map] OK "
        f"({len(phase_to_innov)} innovation-linked phases validated from {MAPPING_PATH})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
