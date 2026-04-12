# SPDX-License-Identifier: Apache-2.0
"""Innovation #20 — Constitutional Stress Testing (CST).

Generates mutations calibrated to barely pass all rules.
Finds constitutional gaps. Feeds InvariantDiscoveryEngine.

Constitutional invariants enforced by this module
──────────────────────────────────────────────────
CST-0          All stress scenarios must complete deterministically (no random.random() calls).
CST-PERSIST-0  Every StressReport must be appended to an append-only JSONL ledger; no deletion.
CST-GAP-0      A ConstitutionalGap record must be emitted for every pattern that passes all
               rules with a threshold_margin < CST_GAP_MARGIN_THRESHOLD.
CST-DIGEST-0   Every StressReport and ConstitutionalGap must carry a SHA-256 digest over its
               canonical fields; mutating a record post-hoc must change the digest.
CST-FEED-0     Gap records must be serialisable to the InvariantDiscovery feed format so the
               invariant discovery pipeline can consume them without further transformation.
CST-SCENARIO-0 The canonical scenario catalogue must contain >= 10 named patterns; extensions
               must not remove existing entries (append-only scenario list).
CST-HALT-0     If the ledger file is not writable the engine must raise ConstitutionalViolation,
               never silently swallow the error.
CST-DETERM-0   report_digest must be a pure function of (epoch_id, cases_tested, gap_digests);
               clock reads and random state must never appear in digest computation.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Sequence

import hashlib
import hmac

# Hardening scaffold — injected by fix/senior-deep-dive-hardening
COSTTE_INV_CHAIN: str = "COSTTE-INV-CHAIN"


class ConstitutionalStressTestViolation(RuntimeError):
    """Raised when a Constitutional Stress Test constitutional invariant is breached."""



# ──────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────
CST_GAP_MARGIN_THRESHOLD: float = 0.05
CST_LEDGER_DEFAULT: str = "data/constitutional_stress_reports.jsonl"
CST_DISCOVERY_FEED_DEFAULT: str = "data/cst_gap_discovery_feed.jsonl"
CST_VERSION: str = "1.0.0"


# ──────────────────────────────────────────────────────────
# Exceptions
# ──────────────────────────────────────────────────────────
class ConstitutionalViolation(RuntimeError):
    """Raised when a constitutional invariant is breached at runtime."""


# ──────────────────────────────────────────────────────────
# Data models
# ──────────────────────────────────────────────────────────
@dataclass
class StressTestCase:
    case_id: str
    target_rule: str
    description: str
    mutation_pattern: str
    expected_threshold_margin: float


@dataclass
class ConstitutionalGap:
    gap_id: str
    rules_bypassed: list
    mutation_pattern: str
    risk_assessment: str
    recommended_new_rule: str
    gap_digest: str = ""

    def __post_init__(self) -> None:
        if not self.gap_digest:
            payload = f"{self.gap_id}:{','.join(sorted(self.rules_bypassed))}:{self.mutation_pattern}"
            self.gap_digest = "sha256:" + hashlib.sha256(payload.encode()).hexdigest()[:16]

    def to_discovery_feed_row(self) -> dict:
        """Serialise to InvariantDiscovery feed format (CST-FEED-0)."""
        return {
            "source": "CST",
            "gap_id": self.gap_id,
            "bypassed_rules": self.rules_bypassed,
            "pattern": self.mutation_pattern,
            "risk": self.risk_assessment,
            "proposed_rule": self.recommended_new_rule,
            "gap_digest": self.gap_digest,
        }


@dataclass
class StressReport:
    epoch_id: str
    cases_tested: int
    gaps_found: int
    gaps: list = field(default_factory=list)
    patterns_run: list = field(default_factory=list)
    report_digest: str = ""

    def __post_init__(self) -> None:
        if not self.report_digest:
            gap_blob = ":".join(sorted(g.gap_digest for g in self.gaps))
            payload = f"{self.epoch_id}:{self.cases_tested}:{self.gaps_found}:{gap_blob}"
            self.report_digest = "sha256:" + hashlib.sha256(payload.encode()).hexdigest()[:16]


# ──────────────────────────────────────────────────────────
# Canonical scenario catalogue (CST-SCENARIO-0: >= 10 entries)
# ──────────────────────────────────────────────────────────
STRESS_PATTERNS: list = [
    StressTestCase("SC-001", "single_file_scope",
                   "Mutation touching exactly 1 file boundary",
                   "single_file_with_import_chain", 0.05),
    StressTestCase("SC-002", "entropy_budget",
                   "Mutation consuming 99% of entropy budget",
                   "near_entropy_ceiling", 0.01),
    StressTestCase("SC-003", "lineage_continuity",
                   "Mutation with minimal but valid lineage reference",
                   "minimal_lineage_evidence", 0.05),
    StressTestCase("SC-004", "ast_validity",
                   "Mutation with valid AST but questionable semantics",
                   "valid_ast_edge_case", 0.10),
    StressTestCase("SC-005", "replay_determinism",
                   "Mutation using seeded random (passes lint but borderline)",
                   "seeded_entropy_use", 0.05),
    StressTestCase("SC-006", "sandbox_isolation",
                   "Mutation importing an allowed stdlib module via an alias chain",
                   "stdlib_alias_import", 0.03),
    StressTestCase("SC-007", "fitness_score_tie",
                   "Two structurally identical mutations with same fitness score",
                   "fitness_tie_break_determinism", 0.02),
    StressTestCase("SC-008", "lineage_depth_ceiling",
                   "Mutation at max lineage depth (parent chain at constitutional cap)",
                   "lineage_at_depth_cap", 0.04),
    StressTestCase("SC-009", "exception_token_ttl",
                   "Exception token with 1-second TTL — should expire before gate check",
                   "exception_token_near_expiry", 0.01),
    StressTestCase("SC-010", "multi_rule_boundary",
                   "Mutation landing on exact threshold of 3 independent rules simultaneously",
                   "triple_rule_boundary_coincidence", 0.02),
    StressTestCase("SC-011", "governance_gate_hash_collision",
                   "Two proposals with distinct content but same GovernanceGate hash prefix",
                   "gate_hash_prefix_collision", 0.01),
    StressTestCase("SC-012", "sandbox_preflight_timeout",
                   "Mutation that makes sandbox preflight time out but not hard-fail",
                   "sandbox_preflight_near_timeout", 0.03),
]

assert len(STRESS_PATTERNS) >= 10, "CST-SCENARIO-0: catalogue must have >= 10 patterns"


# ──────────────────────────────────────────────────────────
# Engine
# ──────────────────────────────────────────────────────────
class ConstitutionalStressTester:
    """Adversarially stress-tests the constitutional framework for coverage gaps."""

    def __init__(
        self,
        report_path: Path = Path(CST_LEDGER_DEFAULT),
        discovery_feed_path: Path = Path(CST_DISCOVERY_FEED_DEFAULT),
        scenarios: list | None = None,
    ) -> None:
        self.report_path = Path(report_path)
        self.discovery_feed_path = Path(discovery_feed_path)
        self.scenarios: list = list(scenarios or STRESS_PATTERNS)

    def run(self, epoch_id: str, evaluate_fn) -> StressReport:
        """Execute all stress scenarios and return a StressReport.

        evaluate_fn(case: StressTestCase) -> (passed_all_rules: bool, rules_missed: list[str])
        Must be deterministic — CST-0.
        """
        if not epoch_id or not str(epoch_id).strip():
            raise ConstitutionalViolation("CST-0: epoch_id must be non-empty")

        gaps: list = []
        patterns_run: list = []

        for case in self.scenarios:
            patterns_run.append(case.case_id)
            try:
                passed, rules_missed = evaluate_fn(case)
            except Exception as exc:
                gaps.append(self._make_gap(
                    epoch_id, case, ["eval_error"],
                    f"evaluate_fn raised: {exc}",
                ))
                continue

            # CST-GAP-0
            if passed and not rules_missed:
                if case.expected_threshold_margin < CST_GAP_MARGIN_THRESHOLD:
                    gaps.append(self._make_gap(
                        epoch_id, case,
                        [case.target_rule],
                        f"Pattern '{case.description}' cleared all rules with margin "
                        f"{case.expected_threshold_margin:.3f} < {CST_GAP_MARGIN_THRESHOLD}",
                    ))

        report = StressReport(
            epoch_id=epoch_id,
            cases_tested=len(self.scenarios),
            gaps_found=len(gaps),
            gaps=gaps,
            patterns_run=patterns_run,
        )
        self._persist_report(report)
        if gaps:
            self._emit_discovery_feed(gaps)
        return report

    def gaps_for_epoch(self, epoch_id: str) -> list:
        """Replay persisted gap records for a given epoch (deterministic, read-only)."""
        if not self.report_path.exists():
            return []
        results: list = []
        with self.report_path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("epoch_id") == epoch_id:
                    results.extend(row.get("gaps", []))
        return results

    def catalogue(self) -> list:
        """Return canonical scenario catalogue as plain dicts (CST-SCENARIO-0)."""
        return [asdict(s) for s in self.scenarios]

    # ── private ───────────────────────────────────────────

    @staticmethod
    def _make_gap(epoch_id: str, case: StressTestCase,
                  rules_bypassed: list, risk_assessment: str) -> ConstitutionalGap:
        return ConstitutionalGap(
            gap_id=f"GAP-{epoch_id[:8]}-{case.case_id}",
            rules_bypassed=rules_bypassed,
            mutation_pattern=case.mutation_pattern,
            risk_assessment=risk_assessment,
            recommended_new_rule=(
                f"Tighten '{case.target_rule}' threshold or add pre-condition guard "
                f"for pattern '{case.mutation_pattern}'"
            ),
        )

    def _persist_report(self, report: StressReport) -> None:
        """CST-PERSIST-0 + CST-HALT-0."""
        try:
            self.report_path.parent.mkdir(parents=True, exist_ok=True)
            with self.report_path.open("a") as fh:
                fh.write(json.dumps(asdict(report)) + "\n")
        except OSError as exc:
            raise ConstitutionalViolation(
                f"CST-HALT-0: ledger not writable — {exc}"
            ) from exc

    def _emit_discovery_feed(self, gaps: list) -> None:
        """CST-FEED-0."""
        try:
            self.discovery_feed_path.parent.mkdir(parents=True, exist_ok=True)
            with self.discovery_feed_path.open("a") as fh:
                for gap in gaps:
                    fh.write(json.dumps(gap.to_discovery_feed_row()) + "\n")
        except OSError:
            pass  # feed write failure is non-fatal


__all__ = [
    "ConstitutionalStressTester",
    "ConstitutionalViolation",
    "StressReport",
    "StressTestCase",
    "ConstitutionalGap",
    "STRESS_PATTERNS",
    "CST_GAP_MARGIN_THRESHOLD",
    "CST_VERSION",
]
