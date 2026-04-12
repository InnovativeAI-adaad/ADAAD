# SPDX-License-Identifier: Apache-2.0
"""Integration layer — wires all 30 innovations into a single pipeline.

Usage:
    from runtime.innovations30.integration import InnovationsPipeline
    pipeline = InnovationsPipeline()
    result = pipeline.evaluate_mutation(mutation_id, intent, diff, changed_files, ...)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import hashlib
import hmac

# Hardening scaffold — injected by fix/senior-deep-dive-hardening
IN_INV_CHAIN: str = "IN-INV-CHAIN"
IN_LEDGER_DEFAULT: str = "data/integration_events.jsonl"


class IntegrationViolation(RuntimeError):
    """Raised when a Integration constitutional invariant is breached."""



@dataclass
class InnovationEvalResult:
    mutation_id: str
    # Constitutional
    invariant_discoveries: list[str] = field(default_factory=list)
    constitutional_tensions: list[str] = field(default_factory=list)
    rule_promotion_recommendations: list[dict] = field(default_factory=list)
    rule_calibration_summary: dict[str, Any] = field(default_factory=dict)
    intent_realization_score: float = 1.0
    temporal_governance_ruleset: dict[str, str] = field(default_factory=dict)
    entropy_drift_ratio: float = 0.0
    entropy_requires_double_signoff: bool = False
    # Fitness
    temporal_regret_registered: bool = False
    temporal_regret_avg_25: float = 0.0
    temporal_regret_high_count: int = 0
    counterfactual_adjusted_score: float = 0.0
    market_adjusted_score: float = 0.0
    market_health_score: float = 1.0
    hardware_adapted_score: float = 0.0
    hardware_profile: str = ""
    hardware_weights: dict[str, float] = field(default_factory=dict)
    epistemic_decay_summary: dict[str, Any] = field(default_factory=dict)
    red_team_verdict: str = "PASS"
    aesthetic_score: float = 0.5
    # Safety
    self_aware_passed: bool = True
    regulatory_passed: bool = True
    semver_honored: bool = True
    blast_radius_tier: str = "low"
    mirror_test_due: bool = False
    mirror_last_score: float | None = None
    mirror_requires_calibration: bool = False
    stress_cases_tested: int = 0
    stress_gaps_found: int = 0
    # Governance
    jury_verdict: str | None = None
    jury_dissent_count: int = 0
    staking_balance: float = 0.0
    staking_win_rate: float = 1.0
    emergent_role: str | None = None
    postmortem_recurring_gaps: dict[str, int] = field(default_factory=dict)
    archaeology_timeline_digest: str | None = None
    archaeology_event_count: int = 0
    dream_candidate_ids: list[str] = field(default_factory=list)
    genealogy_productive_lineages: list[str] = field(default_factory=list)
    genealogy_dead_end_epochs: list[str] = field(default_factory=list)
    genealogy_direction: dict[str, float] = field(default_factory=dict)
    curiosity_active: bool = False
    curiosity_inverted_fitness: float | None = None
    # Aggregated
    overall_innovations_score: float = 1.0
    blocking_violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    component_signal_map: dict[str, list[str]] = field(default_factory=dict)


class InnovationsPipeline:
    """Runs all applicable innovations for a given mutation proposal."""

    def __init__(self, data_dir: Path = Path("data"),
                 hardware_profile=None,
                 dry_run: bool = False):
        self.data_dir = Path(data_dir)
        self.dry_run = dry_run

        # Lazy-init all 30 components
        self._components: dict[str, Any] = {}
        self._hardware_profile = hardware_profile
        self._initialized = False

    def _init(self) -> None:
        if self._initialized:
            return
        d = self.data_dir

        from runtime.innovations30.invariant_discovery import InvariantDiscoveryEngine
        from runtime.innovations30.constitutional_tension import ConstitutionalTensionResolver
        from runtime.innovations30.graduated_invariants import GraduatedInvariantPromoter
        from runtime.innovations30.intent_preservation import IntentPreservationVerifier
        from runtime.innovations30.temporal_regret import TemporalRegretScorer
        from runtime.innovations30.counterfactual_fitness import CounterfactualFitnessSimulator
        from runtime.innovations30.epistemic_decay import EpistemicDecayEngine
        from runtime.innovations30.red_team_agent import RedTeamAgent
        from runtime.innovations30.aesthetic_fitness import AestheticFitnessScorer
        from runtime.innovations30.morphogenetic_memory import MorphogeneticMemory
        from runtime.innovations30.dream_state import DreamStateEngine
        from runtime.innovations30.mutation_genealogy import MutationGenealogyAnalyzer
        from runtime.innovations30.constitutional_jury import ConstitutionalJury, is_high_stakes
        from runtime.innovations30.reputation_staking import ReputationStakingLedger
        from runtime.innovations30.emergent_roles import EmergentRoleSpecializer
        from runtime.innovations30.agent_postmortem import AgentPostMortemSystem
        from runtime.innovations30.temporal_governance import TemporalGovernanceEngine
        from runtime.innovations30.governance_archaeology import GovernanceArchaeologist
        from runtime.innovations30.constitutional_stress_test import ConstitutionalStressTester
        from runtime.innovations30.governance_bankruptcy import GovernanceBankruptcyProtocol
        from runtime.innovations30.market_fitness import MarketConditionedFitness
        from runtime.innovations30.regulatory_compliance import RegulatoryComplianceEngine
        from runtime.innovations30.semantic_version_enforcer import SemanticVersionEnforcer
        from runtime.innovations30.hardware_adaptive_fitness import HardwareAdaptiveFitness
        from runtime.innovations30.constitutional_entropy_budget import ConstitutionalEntropyBudget
        from runtime.innovations30.blast_radius_model import BlastRadiusModeler
        from runtime.innovations30.self_awareness_invariant import SelfAwarenessInvariant
        from runtime.innovations30.curiosity_engine import CuriosityEngine
        from runtime.innovations30.mirror_test import MirrorTestEngine

        self._components = {
            "invariant_discovery":   InvariantDiscoveryEngine(d/"discovered_rules.jsonl"),
            "tension_resolver":      ConstitutionalTensionResolver(d/"tensions.jsonl"),
            "graduated_invariants":  GraduatedInvariantPromoter(d/"rule_calibrations.json"),
            "intent_verifier":       IntentPreservationVerifier(d/"intent_realization.jsonl"),
            "regret_scorer":         TemporalRegretScorer(d/"temporal_regret.jsonl"),
            "counterfactual":        CounterfactualFitnessSimulator(),
            "epistemic_decay":       EpistemicDecayEngine(d/"epistemic_decay_state.json"),
            "red_team":              RedTeamAgent(d/"red_team_verdicts.jsonl"),
            "aesthetic":             AestheticFitnessScorer(),
            "morpho_memory":         MorphogeneticMemory(d/"identity_ledger.jsonl"),
            "dream_state":           DreamStateEngine(d/"dream_candidates.jsonl"),
            "genealogy":             MutationGenealogyAnalyzer(d/"genealogy_vectors.jsonl"),
            "jury":                  ConstitutionalJury(d/"jury_decisions.jsonl"),
            "is_high_stakes":        is_high_stakes,
            "staking":               ReputationStakingLedger(d/"reputation_stakes.jsonl",
                                                               d/"agent_wallets.json"),
            "emergent_roles":        EmergentRoleSpecializer(d/"emergent_roles.json"),
            "postmortem":            AgentPostMortemSystem(d/"agent_postmortems.jsonl"),
            "temporal_gov":          TemporalGovernanceEngine(),
            "archaeologist":         GovernanceArchaeologist(),
            "stress_tester":         ConstitutionalStressTester(d/"stress_reports.jsonl"),
            "bankruptcy":            GovernanceBankruptcyProtocol(d/"bankruptcy_state.jsonl"),
            "market_fitness":        MarketConditionedFitness(d/"market_signals.jsonl"),
            "regulatory":            RegulatoryComplianceEngine(ledger_path=d/"compliance_violations.jsonl"),
            "semver":                SemanticVersionEnforcer(),
            "hw_fitness":            HardwareAdaptiveFitness(self._hardware_profile),
            "entropy_budget":        ConstitutionalEntropyBudget(state_path=d/"constitutional_entropy.json"),
            "blast_radius":          BlastRadiusModeler(),
            "self_aware":            SelfAwarenessInvariant(),
            "curiosity":             CuriosityEngine(d/"curiosity_state.json"),
            "mirror_test":           MirrorTestEngine(d/"mirror_test_state.jsonl"),
        }

        # ── [INNOV-COMPLETE-0] Boot completeness gate ─────────────────────
        # All component slots must be populated before marking _initialized.
        # Fail-closed: partial pipeline cannot accept mutations.
        expected_components = len(self.component_names())
        actual_components   = len(self._components)
        if actual_components < expected_components:
            missing_keys = set(self.component_names()) - set(self._components)
            raise RuntimeError(
                f"[INNOV-COMPLETE-0] InnovationsPipeline boot FAILED: "
                f"{actual_components}/{expected_components} components initialised. "
                f"Missing keys: {sorted(missing_keys)}. "
                f"System cannot accept mutations with incomplete innovation set."
            )

        self._initialized = True

    def evaluate_mutation(
        self,
        mutation_id: str,
        agent_id: str,
        intent: str,
        diff_text: str,
        changed_files: list[str],
        before_source: str = "",
        after_source: str = "",
        epoch_id: str = "",
        epoch_seq: int = 0,
        declared_semver: str = "patch",
        base_fitness: float = 0.70,
        recent_fitness_deltas: list[float] | None = None,
        health_score: float = 0.75,
        blocking_rules: list[str] | None = None,
        overridden_rules: list[str] | None = None,
    ) -> InnovationEvalResult:
        self._init()
        c = self._components
        result = InnovationEvalResult(mutation_id=mutation_id)
        result.component_signal_map = {name: ["direct"] for name in self.component_names()}

        # ── 28: Self-Awareness Invariant (blocking) ────────────────────────
        sa = c["self_aware"].evaluate(mutation_id, diff_text, changed_files)
        result.self_aware_passed = sa.passed
        if not sa.passed:
            result.blocking_violations.extend(sa.violations)
            result.component_signal_map["self_aware"].append("blocking")

        # ── 23: Regulatory Compliance (blocking) ──────────────────────────
        reg = c["regulatory"].evaluate(mutation_id, diff_text, intent)
        result.regulatory_passed = reg.passed
        if not reg.passed:
            for v in reg.violations:
                if v.rule_id.endswith("blocking"):
                    result.blocking_violations.append(v.violation_description)
                    result.component_signal_map["regulatory"].append("blocking")
                else:
                    result.warnings.append(v.violation_description)
                    result.component_signal_map["regulatory"].append("warning")

        # ── 21: Governance Bankruptcy (blocking) ──────────────────────────
        allowed, reason = c["bankruptcy"].is_mutation_allowed(intent)
        if not allowed:
            result.blocking_violations.append(reason)
            result.component_signal_map["bankruptcy"].append("blocking")

        # ── 8: Red Team (warning) ─────────────────────────────────────────
        red = c["red_team"].challenge(mutation_id, before_source,
                                        after_source, changed_files)
        result.red_team_verdict = red.verdict
        if red.verdict == "FAIL":
            result.warnings.extend(red.vulnerabilities[:2])
            result.component_signal_map["red_team"].append("warning")

        # ── 4: Intent Preservation ────────────────────────────────────────
        if diff_text:
            intent_r = c["intent_verifier"].verify(
                mutation_id, agent_id, intent, diff_text, epoch_id)
            result.intent_realization_score = intent_r.realization_score

        # ── 18: Temporal Governance (structured) ──────────────────────────
        result.temporal_governance_ruleset = c["temporal_gov"].get_adjusted_ruleset(health_score)

        # ── 24: Semantic Version Enforcer (warning) ───────────────────────
        semver_v = c["semver"].verify(mutation_id, declared_semver, diff_text)
        result.semver_honored = semver_v.contract_honored
        if not semver_v.contract_honored:
            result.warnings.extend(semver_v.violations)
            result.component_signal_map["semver"].append("warning")

        # ── 27: Blast Radius ─────────────────────────────────────────────
        blast = c["blast_radius"].model(mutation_id, changed_files)
        result.blast_radius_tier = blast.risk_tier
        if blast.risk_tier == "critical":
            result.warnings.append(f"CRITICAL blast radius: {blast.reversal_cost_estimate}")
            result.component_signal_map["blast_radius"].append("warning")

        # ── 9: Aesthetic Fitness ──────────────────────────────────────────
        if before_source and after_source:
            aes = c["aesthetic"].score(mutation_id, before_source, after_source)
            result.aesthetic_score = aes.overall_aesthetic

        # ── 6: Counterfactual Fitness ─────────────────────────────────────
        cf = c["counterfactual"].evaluate(
            mutation_id, base_fitness, base_fitness,
            recent_fitness_deltas or [])
        result.counterfactual_adjusted_score = cf.adjusted_proposal_score

        # ── 22: Market-conditioned Fitness ────────────────────────────────
        result.market_adjusted_score = c["market_fitness"].adjust_fitness(
            result.counterfactual_adjusted_score, mutation_id)
        result.market_health_score = c["market_fitness"].market_health_score()

        # ── 25: Hardware-adaptive Fitness ─────────────────────────────────
        result.hardware_weights = c["hw_fitness"].adapted_weights()
        result.hardware_profile = c["hw_fitness"].profile_description()
        result.hardware_adapted_score = c["hw_fitness"].score_with_profile({
            "correctness_score": 1.0 if result.self_aware_passed else 0.0,
            "efficiency_score": result.aesthetic_score,
            "policy_compliance_score": 1.0 if result.regulatory_passed else 0.0,
            "goal_alignment_score": result.intent_realization_score,
            "simulated_market_score": result.market_adjusted_score,
        })

        # ── 26: Constitutional Entropy Budget ─────────────────────────────
        entropy = c["entropy_budget"].check_drift(
            current_rule_names=sorted(result.temporal_governance_ruleset.keys()),
            current_epoch_seq=epoch_seq,
        )
        result.entropy_drift_ratio = entropy.drift_ratio
        result.entropy_requires_double_signoff = entropy.requires_double_signoff
        if entropy.requires_double_signoff:
            result.warnings.append("Constitutional drift requires double HUMAN-0 signoff.")

        # ── 29: Curiosity Engine ──────────────────────────────────────────
        result.curiosity_active = c["curiosity"].in_curiosity
        if result.curiosity_active:
            result.curiosity_inverted_fitness = c["curiosity"].invert_fitness(base_fitness)

        # ── 2: Constitutional Tensions ────────────────────────────────────
        if blocking_rules and overridden_rules:
            tensions = c["tension_resolver"].record_verdict(
                mutation_id, epoch_id, blocking_rules, overridden_rules)
            result.constitutional_tensions = [t.digest for t in tensions]

        # ── 1: Invariant Discovery (structured) ───────────────────────────
        pending_rules = c["invariant_discovery"].pending_rules()
        result.invariant_discoveries = [r.digest for r in pending_rules]

        # ── 3: Graduated Invariants (structured) ──────────────────────────
        result.rule_promotion_recommendations = c["graduated_invariants"].recommend_changes()
        result.rule_calibration_summary = c["graduated_invariants"].calibration_summary()

        # ── 5: Temporal Regret (structured) ───────────────────────────────
        if epoch_id:
            c["regret_scorer"].register_acceptance(
                mutation_id=mutation_id,
                epoch_seq=epoch_seq,
                predicted_fitness=result.market_adjusted_score,
            )
            result.temporal_regret_registered = True
        result.temporal_regret_avg_25 = c["regret_scorer"].avg_regret(offset=25)
        result.temporal_regret_high_count = len(c["regret_scorer"].high_regret_mutations(offset=25))
        if result.temporal_regret_high_count > 0:
            result.warnings.append("Temporal regret hotspots detected.")

        # ── 7: Epistemic Decay (structured) ───────────────────────────────
        result.epistemic_decay_summary = c["epistemic_decay"].summary()
        if result.epistemic_decay_summary.get("needing_recalibration"):
            result.warnings.append("Epistemic decay indicates recalibration is needed.")

        # ── 11: Dream State (deterministic no-op path) ────────────────────
        dream_candidates = c["dream_state"].dream([], epoch_id or mutation_id)
        result.dream_candidate_ids = [cand.candidate_id for cand in dream_candidates]

        # ── 12: Genealogy (structured) ────────────────────────────────────
        result.genealogy_productive_lineages = c["genealogy"].productive_lineages()
        result.genealogy_dead_end_epochs = c["genealogy"].dead_end_epochs()
        result.genealogy_direction = c["genealogy"].evolutionary_direction(epoch_id)

        # ── 14: Constitutional Jury (structured) ──────────────────────────
        result.jury_dissent_count = len(c["jury"].dissent_records(limit=20))
        if c["is_high_stakes"](changed_files):
            result.jury_verdict = "review_required"
            result.warnings.append("High-stakes mutation requires jury deliberation.")

        # ── 15: Reputation Staking (structured, read-only) ────────────────
        result.staking_balance = c["staking"].balance(agent_id)
        result.staking_win_rate = c["staking"].agent_win_rate(agent_id)

        # ── 16: Emergent Roles (structured, read-only) ────────────────────
        role = c["emergent_roles"].get_role(agent_id)
        result.emergent_role = role.discovered_role if role else None

        # ── 17: Agent Postmortem (structured, read-only) ──────────────────
        result.postmortem_recurring_gaps = c["postmortem"].agent_recurring_gaps(agent_id, last_n=20)

        # ── 19: Governance Archaeology (structured) ───────────────────────
        timeline = c["archaeologist"].excavate(mutation_id)
        result.archaeology_timeline_digest = timeline.timeline_digest
        result.archaeology_event_count = len(timeline.events)

        # ── 20: Constitutional Stress Test (deterministic low-impact) ─────
        stress = c["stress_tester"].run(
            epoch_id=epoch_id or f"adhoc-{mutation_id[:8]}",
            evaluate_fn=lambda _case: (False, ["manual-review-only"]),
        )
        result.stress_cases_tested = stress.cases_tested
        result.stress_gaps_found = stress.gaps_found

        # ── 30: Mirror Test (read-only scheduling signals) ────────────────
        result.mirror_test_due = c["mirror_test"].should_run(epoch_seq)
        result.mirror_last_score = c["mirror_test"].last_score()
        if result.mirror_last_score is not None and result.mirror_last_score < 0.60:
            result.mirror_requires_calibration = True
            result.warnings.append("Mirror test score below calibration threshold.")

        # ── 10: Morphogenetic Memory ──────────────────────────────────────
        consistency = c["morpho_memory"].check_mutation_consistency(
            mutation_id, intent, diff_text)
        if not consistency.consistent:
            result.warnings.extend(consistency.violated_statements[:2])
            result.component_signal_map["morpho_memory"].append("warning")

        # ── Aggregate overall score ───────────────────────────────────────
        scores = [
            cf.adjusted_proposal_score,
            result.intent_realization_score,
            result.aesthetic_score,
            result.market_adjusted_score,
            result.hardware_adapted_score,
            1.0 if result.self_aware_passed else 0.0,
            1.0 if result.regulatory_passed else 0.5,
        ]
        result.overall_innovations_score = round(
            sum(scores) / len(scores), 4)

        return result

    def get_component(self, name: str) -> Any:
        self._init()
        return self._components.get(name)

    def component_names(self) -> list[str]:
        return [
            "invariant_discovery", "tension_resolver", "graduated_invariants",
            "intent_verifier", "regret_scorer", "counterfactual", "epistemic_decay",
            "red_team", "aesthetic", "morpho_memory", "dream_state", "genealogy",
            "jury", "staking", "emergent_roles", "postmortem", "temporal_gov",
            "archaeologist", "stress_tester", "bankruptcy", "market_fitness",
            "regulatory", "semver", "hw_fitness", "entropy_budget", "blast_radius",
            "self_aware", "curiosity", "mirror_test",
        ]


__all__ = ["InnovationsPipeline", "InnovationEvalResult"]
