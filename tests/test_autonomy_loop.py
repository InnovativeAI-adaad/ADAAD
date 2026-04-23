# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

from adaad.core.autonomy_loop import AutonomyLoop


def _seed_repo(root: Path) -> None:
    (root / "docs/governance").mkdir(parents=True)
    (root / "docs/comms").mkdir(parents=True)
    (root / "security/adaad_runbooks").mkdir(parents=True)

    (root / "docs/governance/ADAAD_PR_PROCESSION_2026-03-v2.md").write_text(
        'state_alignment:\n  expected_next_pr: "Phase 148 — INNOV-54"\n\n| Phase | Version | Depends on | Status |\n|---|---|---|---|\n| 147 | v9.8 | Phase 146 | shipped |\n| 148 | v9.9 | Phase 147 | next |\n',
        encoding="utf-8",
    )
    (root / "docs/comms/claims_evidence_matrix.md").write_text(
        "| Claim ID | Claim | Evidence | Scope | Status |\n|---|---|---|---|---|\n| `x` | x | x | x | Complete |\n",
        encoding="utf-8",
    )
    (root / ".adaad_agent_state.json").write_text(
        json.dumps({"blocked_reason": None, "last_gate_results": {"tier_0": "pass", "tier_1": "pass", "tier_2": "pass", "tier_3": "pass", "tier_m": "pass"}}),
        encoding="utf-8",
    )


def test_autonomy_loop_cycle_telemetry(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    loop = AutonomyLoop(repo_root=tmp_path)

    telemetry = loop.run_cycle()

    assert telemetry.task_count >= 3
    assert "generate_goals" in telemetry.stage_timings_ms
    assert "dispatch_agents" in telemetry.stage_timings_ms
    assert telemetry.success_rate == 1.0
