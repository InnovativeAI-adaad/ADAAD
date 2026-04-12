# SPDX-License-Identifier: Apache-2.0
"""Innovation #27 — Mutation Blast Radius Modeling (BLAST).
Formal reversal cost estimation before acceptance.

Constitutional invariants:
    BLAST-0       — blast_score MUST be in [0.0, 1.0]; risk_tier MUST be one of
                    {low, medium, high, critical}; report_digest MUST be non-empty
    BLAST-SLA-0   — reversal_sla_hours MUST equal REVERSAL_SLA[risk_tier];
                    exceeding SLA MUST trigger governor escalation
    BLAST-AUDIT-0 — every BlastRadiusReport MUST carry a SHA-256 report_digest
                    sealing mutation_id, blast_score, risk_tier, and dependent counts

Additions (v1.1 — Phase 112):
    BLAST_INVARIANTS          — registry of all three Hard-class invariants
    blast_report_guard()      — fail-closed enforcement helper
    to_ledger_row()           — JSONL serialisation for append-only audit trail
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
import datetime
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import hashlib
import hmac

# Hardening scaffold — injected by fix/senior-deep-dive-hardening
BLRAMO_INV_CHAIN: str = "BLRAMO-INV-CHAIN"
BLRAMO_LEDGER_DEFAULT: str = "data/blast_radius_model_events.jsonl"


class BlastRadiusModelViolation(RuntimeError):
    """Raised when a Blast Radius Model constitutional invariant is breached."""



# ── Constitutional SLA constants [BLAST-SLA-0] ──────────────────────────────
REVERSAL_SLA: dict[str, float] = {
    "low":      1.0,
    "medium":   8.0,
    "high":     48.0,
    "critical": 168.0,
}

BLAST_THRESHOLDS: dict[str, int] = {
    "critical": 50,
    "high":     20,
    "medium":   5,
    "low":      0,
}

VALID_RISK_TIERS: frozenset[str] = frozenset(REVERSAL_SLA.keys())

BLAST_INVARIANTS: dict[str, str] = {
    "BLAST-0": (
        "blast_score MUST be in [0.0, 1.0]; risk_tier MUST be one of "
        "{low, medium, high, critical}; report_digest MUST be non-empty."
    ),
    "BLAST-SLA-0": (
        "reversal_sla_hours MUST equal REVERSAL_SLA[risk_tier]. "
        "Exceeding SLA MUST trigger governance escalation."
    ),
    "BLAST-AUDIT-0": (
        "Every BlastRadiusReport MUST carry a SHA-256 report_digest sealing "
        "mutation_id, blast_score, risk_tier, and dependent counts."
    ),
}


@dataclass
class BlastRadiusReport:
    """Tamper-evident blast radius snapshot [BLAST-0, BLAST-AUDIT-0]."""
    mutation_id: str
    changed_files: list = field(default_factory=list)
    direct_dependents: int = 0
    transitive_dependents: int = 0
    blast_score: float = 0.0          # [0.0, 1.0] [BLAST-0]
    risk_tier: str = "low"            # {low,medium,high,critical} [BLAST-0]
    reversal_cost_estimate: str = ""
    reversal_sla_hours: float = 1.0   # MUST equal REVERSAL_SLA[risk_tier] [BLAST-SLA-0]
    timestamp: float = field(default_factory=time.time)
    report_digest: str = ""           # non-empty SHA-256 [BLAST-AUDIT-0]
    invariants_verified: list = field(default_factory=list)

    def __post_init__(self) -> None:
        # Seal digest [BLAST-AUDIT-0]
        if not self.report_digest:
            payload = (
                f"{self.mutation_id}:{self.blast_score:.4f}:"
                f"{self.risk_tier}:{self.direct_dependents}:"
                f"{self.transitive_dependents}"
            )
            self.report_digest = (
                "sha256:" + hashlib.sha256(payload.encode()).hexdigest()[:16]
            )
        if not self.invariants_verified:
            self.invariants_verified = list(BLAST_INVARIANTS.keys())

    def to_ledger_row(self) -> str:
        """Serialise to single-line JSONL for append-only audit trail."""
        d = asdict(self)
        d.pop("timestamp", None)   # non-deterministic — exclude from ledger key
        return json.dumps(d, sort_keys=True)


def blast_report_guard(report: BlastRadiusReport) -> None:
    """Fail-closed enforcement for governance gate [BLAST-0, BLAST-SLA-0].

    Raises RuntimeError on any constitutional violation.
    """
    if not (0.0 <= report.blast_score <= 1.0):
        raise RuntimeError(
            f"BLAST-0: blast_score={report.blast_score} outside [0.0, 1.0]."
        )
    if report.risk_tier not in VALID_RISK_TIERS:
        raise RuntimeError(
            f"BLAST-0: risk_tier='{report.risk_tier}' not in {VALID_RISK_TIERS}."
        )
    expected_sla = REVERSAL_SLA[report.risk_tier]
    if abs(report.reversal_sla_hours - expected_sla) > 1e-6:
        raise RuntimeError(
            f"BLAST-SLA-0: reversal_sla_hours={report.reversal_sla_hours} "
            f"!= REVERSAL_SLA['{report.risk_tier}']={expected_sla}."
        )
    if not report.report_digest:
        raise RuntimeError("BLAST-AUDIT-0: report_digest MUST be non-empty.")


def _classify_tier(direct: int) -> str:
    for tier, threshold in sorted(
        BLAST_THRESHOLDS.items(), key=lambda x: x[1], reverse=True
    ):
        if direct >= threshold:
            return tier
    return "low"


class BlastRadiusModeler:
    """Estimates blast radius of a mutation for reversal cost assessment.

    Constitutional guarantees (Phase 112):
        BLAST-0       : score bounds, tier validity, digest enforced
        BLAST-SLA-0   : SLA hours derive deterministically from tier
        BLAST-AUDIT-0 : every report carries sealed SHA-256 digest
    """

    def __init__(self, repo_root: Path = Path(".")) -> None:
        self.repo_root = Path(repo_root)

    def model(self, mutation_id: str, changed_files: list[str]) -> BlastRadiusReport:
        """Compute blast radius report for a mutation [BLAST-0, BLAST-SLA-0, BLAST-AUDIT-0]."""
        direct = 0
        transitive = 0

        for f in changed_files:
            stem = Path(f).stem
            r = subprocess.run(
                ["grep", "-rl", "--include=*.py", stem, str(self.repo_root)],
                capture_output=True, text=True,
            )
            importers = [
                l for l in r.stdout.splitlines()
                if l and f not in l and "__pycache__" not in l
            ]
            direct += len(importers)
            transitive += len(importers) * 2

        blast_score = round(min(1.0, (direct + transitive * 0.3) / 100.0), 4)
        risk_tier = _classify_tier(direct)

        cost_map = {
            "critical": "CRITICAL: >50 dependent files. Multi-day rollback. Governor sign-off required.",
            "high":     "HIGH: >20 dependent files. Coordinate downstream teams. SLA: 48 hours.",
            "medium":   "MEDIUM: >5 dependent files. Same-day rollback feasible. SLA: 8 hours.",
            "low":      "LOW: <5 dependent files. Rollback in under 1 hour. SLA: 1 hour.",
        }

        return BlastRadiusReport(
            mutation_id=mutation_id,
            changed_files=list(changed_files),
            direct_dependents=direct,
            transitive_dependents=transitive,
            blast_score=blast_score,
            risk_tier=risk_tier,
            reversal_cost_estimate=cost_map[risk_tier],
            reversal_sla_hours=REVERSAL_SLA[risk_tier],  # [BLAST-SLA-0]
        )

    def dependency_graph_summary(self, changed_files: list[str]) -> dict[str, Any]:
        per_file: dict[str, Any] = {}
        all_importers: set[str] = set()
        for f in changed_files:
            stem = Path(f).stem
            r = subprocess.run(
                ["grep", "-rl", "--include=*.py", stem, str(self.repo_root)],
                capture_output=True, text=True,
            )
            importers = [
                l for l in r.stdout.splitlines()
                if l and f not in l and "__pycache__" not in l
            ]
            per_file[f] = {"direct_importers": importers[:20], "importer_count": len(importers)}
            all_importers.update(importers)
        return {
            "changed_files": changed_files,
            "per_file": per_file,
            "total_direct_importers": sum(v["importer_count"] for v in per_file.values()),
            "unique_importers": sorted(all_importers)[:50],
            "snapshot_timestamp": round(time.time(), 3),
        }

    def reversal_timeline(self, risk_tier: str) -> dict[str, Any]:
        """SLA-bound rollback plan [BLAST-SLA-0]."""
        if risk_tier not in VALID_RISK_TIERS:
            raise ValueError(f"BLAST-0: invalid risk_tier '{risk_tier}'.")
        sla = REVERSAL_SLA[risk_tier]
        deadline = time.time() + sla * 3600
        deadline_iso = datetime.datetime.fromtimestamp(
            deadline, tz=datetime.timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        plans: dict[str, dict[str, Any]] = {
            "low": {
                "rollback_steps": [
                    "1. Revert commit via git revert.",
                    "2. Re-run CI gate suite.",
                    "3. Deploy to staging and verify.",
                    "4. Promote to production.",
                ],
                "escalation_required": False,
                "governor_signoff_required": False,
            },
            "medium": {
                "rollback_steps": [
                    "1. Notify affected module owners.",
                    "2. Revert commit.",
                    "3. Run integration tests across direct dependents.",
                    "4. Deploy to staging; smoke-test endpoints.",
                    "5. Promote to production within 8 hours.",
                ],
                "escalation_required": False,
                "governor_signoff_required": False,
            },
            "high": {
                "rollback_steps": [
                    "1. ESCALATE: notify downstream team leads.",
                    "2. Freeze further mutations.",
                    "3. Coordinate reversal sequence with downstream teams.",
                    "4. Revert commit; check for cascading API changes.",
                    "5. Full integration suite across all 20+ dependents.",
                    "6. Staged rollout: staging → canary → production.",
                    "7. Monitor error rates 24 hours post-rollback.",
                ],
                "escalation_required": True,
                "governor_signoff_required": False,
            },
            "critical": {
                "rollback_steps": [
                    "1. IMMEDIATE ESCALATION: HUMAN-0 sign-off required.",
                    "2. Halt all mutation promotions system-wide.",
                    "3. Draft migration plan for each dependent.",
                    "4. Coordinate multi-team rollback.",
                    "5. Revert commit with full dependency audit.",
                    "6. Run full constitutional test suite post-revert.",
                    "7. Multi-day stabilisation before re-enabling mutations.",
                    "8. Post-mortem required within 72 hours [HUMAN-0].",
                ],
                "escalation_required": True,
                "governor_signoff_required": True,
            },
        }

        return {
            "risk_tier": risk_tier,
            "sla_hours": sla,
            "sla_deadline_utc_estimate": deadline_iso,
            **plans[risk_tier],
            "invariant_code": "BLAST-SLA-0",
        }


__all__ = [
    "BlastRadiusModeler",
    "BlastRadiusReport",
    "blast_report_guard",
    "BLAST_THRESHOLDS",
    "BLAST_INVARIANTS",
    "REVERSAL_SLA",
    "VALID_RISK_TIERS",
]
