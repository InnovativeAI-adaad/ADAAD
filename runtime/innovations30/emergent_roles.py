# SPDX-License-Identifier: Apache-2.0
"""Innovation #16 — Emergent Role Specialization (ERS).

Roles emerge from observed behavioral patterns, not static assignments.
Agents that consistently exhibit a dominant strategy and target type above
SPECIALIZATION_THRESHOLD are classified into named role archetypes.

Constitutional invariants enforced by this module
──────────────────────────────────────────────────
  ERS-0         EmergentRoleSpecializer.discover_roles() is the sole role-assignment
                authority. Roles MUST NOT be manually assigned; they emerge from
                recorded behavioral evidence only.
  ERS-WINDOW-0  A role MUST NOT be discovered for an agent with fewer than
                SPECIALIZATION_WINDOW (50) recorded epochs. Premature classification
                is blocked at the discover_roles() gate.
  ERS-THRESHOLD-0 A role MUST NOT be discovered unless specialization_score >=
                SPECIALIZATION_THRESHOLD (0.65). Agents below threshold remain
                unspecialized; no archetype is emitted.
  ERS-DETERM-0  Role classification is deterministic: identical behavior profiles
                produce identical EmergentRole objects. No datetime.now(), random,
                or uuid4 in any classification path.
  ERS-PERSIST-0 _save() MUST use Path.open("w") with sort_keys=True. _load() is
                fail-open: corrupt or missing state file never raises.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import logging

import hashlib
import hmac

# Hardening scaffold — injected by fix/senior-deep-dive-hardening
EMRO_INV_CHAIN: str = "EMRO-INV-CHAIN"
EMRO_LEDGER_DEFAULT: str = "data/emergent_roles_events.jsonl"


class EmergentRolesViolation(RuntimeError):
    """Raised when a Emergent Roles constitutional invariant is breached."""



logger = logging.getLogger(__name__)

# ── Invariant constants ───────────────────────────────────────────────────────
SPECIALIZATION_WINDOW: int = 50          # ERS-WINDOW-0
SPECIALIZATION_THRESHOLD: float = 0.65  # ERS-THRESHOLD-0

ROLE_ARCHETYPES: dict[str, dict[str, Any]] = {
    "structural_architect":    {"strategy": "structural_refactor",        "risk": (0.0, 0.4)},
    "test_coverage_guardian":  {"strategy": "test_coverage_expansion",    "risk": (0.0, 0.5)},
    "performance_optimizer":   {"strategy": "performance_optimization",   "risk": (0.3, 0.7)},
    "safety_hardener":         {"strategy": "safety_hardening",           "risk": (0.0, 0.3)},
    "adaptive_explorer":       {"strategy": "adaptive_self_mutate",       "risk": (0.4, 1.0)},
}

_ERS_STATE_DEFAULT: str = "data/emergent_roles.json"


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class AgentBehaviorProfile:
    """Running behavioral record for one agent.

    ERS-DETERM-0: all aggregation (counts, list appends) is deterministic.
    Properties are pure functions of accumulated data — no entropy.
    """
    agent_id: str
    target_type_counts: dict[str, int] = field(default_factory=dict)
    strategy_counts: dict[str, int] = field(default_factory=dict)
    risk_scores: list[float] = field(default_factory=list)
    fitness_deltas: list[float] = field(default_factory=list)
    epochs_active: int = 0

    def record_action(
        self,
        target_type: str,
        strategy: str,
        risk_score: float,
        fitness_delta: float,
    ) -> None:
        """Append one observation. ERS-DETERM-0: pure accumulation, no entropy."""
        self.target_type_counts[target_type] = (
            self.target_type_counts.get(target_type, 0) + 1
        )
        self.strategy_counts[strategy] = (
            self.strategy_counts.get(strategy, 0) + 1
        )
        self.risk_scores.append(round(risk_score, 6))
        self.fitness_deltas.append(round(fitness_delta, 6))
        self.epochs_active += 1

    # ── Derived properties ────────────────────────────────────────────────────

    @property
    def dominant_target(self) -> str:
        """ERS-DETERM-0: deterministic max by count; ties broken alphabetically."""
        if not self.target_type_counts:
            return "unknown"
        return max(sorted(self.target_type_counts), key=self.target_type_counts.__getitem__)

    @property
    def dominant_strategy(self) -> str:
        """ERS-DETERM-0: deterministic max by count; ties broken alphabetically."""
        if not self.strategy_counts:
            return "unknown"
        return max(sorted(self.strategy_counts), key=self.strategy_counts.__getitem__)

    @property
    def avg_risk(self) -> float:
        """Mean risk score across all recorded epochs."""
        return round(sum(self.risk_scores) / len(self.risk_scores), 6) if self.risk_scores else 0.5

    @property
    def avg_fitness_delta(self) -> float:
        """Mean fitness delta across all recorded epochs."""
        return round(sum(self.fitness_deltas) / len(self.fitness_deltas), 6) if self.fitness_deltas else 0.0

    @property
    def specialization_score(self) -> float:
        """ERS-THRESHOLD-0: fraction of epochs dominated by the single top target type.

        Range [0.0, 1.0]. Score of 1.0 means agent exclusively targets one type.
        """
        if not self.target_type_counts:
            return 0.0
        total = sum(self.target_type_counts.values())
        max_count = max(self.target_type_counts.values())
        return round(max_count / total, 6) if total > 0 else 0.0


@dataclass
class EmergentRole:
    """Discovered role for one agent.

    ERS-DETERM-0: all fields derived purely from AgentBehaviorProfile properties.
    ERS-0: only discover_roles() may create EmergentRole instances.
    """
    agent_id: str
    discovered_role: str          # e.g. "structural_architect", "adaptive_explorer"
    dominant_target_type: str
    dominant_strategy: str
    risk_preference: float        # 0=conservative, 1=aggressive
    consistency_score: float      # == specialization_score at discovery time
    epochs_observed: int


# ── Main specializer ──────────────────────────────────────────────────────────

class EmergentRoleSpecializer:
    """Discovers agent roles from behavioral evidence.

    ERS-0         discover_roles() sole assignment authority.
    ERS-WINDOW-0  Agents with < SPECIALIZATION_WINDOW epochs are skipped.
    ERS-THRESHOLD-0 Agents with specialization_score < SPECIALIZATION_THRESHOLD skipped.
    ERS-DETERM-0  Classification is deterministic from profile state.
    ERS-PERSIST-0 _save() uses Path.open("w"); _load() is fail-open.
    """

    def __init__(self, state_path: Path = Path(_ERS_STATE_DEFAULT)):
        self.state_path = Path(state_path)
        self._profiles: dict[str, AgentBehaviorProfile] = {}
        self._discovered_roles: dict[str, EmergentRole] = {}
        self._load()

    # ── Observation recording ─────────────────────────────────────────────────

    def record_behavior(
        self,
        agent_id: str,
        target_type: str,
        strategy: str,
        risk_score: float,
        fitness_delta: float,
    ) -> None:
        """Append one behavioral observation for an agent.

        ERS-DETERM-0: no entropy; pure accumulation.
        """
        if agent_id not in self._profiles:
            self._profiles[agent_id] = AgentBehaviorProfile(agent_id=agent_id)
        self._profiles[agent_id].record_action(target_type, strategy, risk_score, fitness_delta)

    # ── Role discovery ────────────────────────────────────────────────────────

    def discover_roles(self) -> dict[str, EmergentRole]:
        """ERS-0: classify qualifying agents into role archetypes.

        ERS-WINDOW-0:    skips agents with < SPECIALIZATION_WINDOW epochs.
        ERS-THRESHOLD-0: skips agents with specialization_score < SPECIALIZATION_THRESHOLD.
        ERS-DETERM-0:    classification is deterministic from profile properties.

        Returns dict of agent_id → EmergentRole for newly/re-classified agents.
        """
        newly_discovered: dict[str, EmergentRole] = {}

        for agent_id, profile in sorted(self._profiles.items()):  # sorted → deterministic
            # ERS-WINDOW-0: minimum observation window
            if profile.epochs_active < SPECIALIZATION_WINDOW:
                continue
            # ERS-THRESHOLD-0: minimum specialization
            if profile.specialization_score < SPECIALIZATION_THRESHOLD:
                continue

            role = self._classify_role(profile)
            newly_discovered[agent_id] = role
            self._discovered_roles[agent_id] = role

        self._save()
        return newly_discovered

    def get_role(self, agent_id: str) -> EmergentRole | None:
        """Return the currently discovered role for an agent, or None."""
        return self._discovered_roles.get(agent_id)

    def profile(self, agent_id: str) -> AgentBehaviorProfile | None:
        """Return raw behavioral profile for an agent, or None."""
        return self._profiles.get(agent_id)

    def unspecialized_agents(self) -> list[str]:
        """Return agent_ids tracked but not yet meeting specialization criteria."""
        return sorted(
            aid for aid, p in self._profiles.items()
            if aid not in self._discovered_roles
            and (p.epochs_active < SPECIALIZATION_WINDOW
                 or p.specialization_score < SPECIALIZATION_THRESHOLD)
        )

    # ── Classification (ERS-DETERM-0) ────────────────────────────────────────

    def _classify_role(self, profile: AgentBehaviorProfile) -> EmergentRole:
        """ERS-DETERM-0: pure deterministic classification. No entropy."""
        dom_strategy = profile.dominant_strategy
        avg_risk = profile.avg_risk

        role_name = "undifferentiated"
        # Iterate in sorted order for determinism
        for archetype in sorted(ROLE_ARCHETYPES):
            criteria = ROLE_ARCHETYPES[archetype]
            risk_min, risk_max = criteria["risk"]
            if (criteria["strategy"] in dom_strategy
                    and risk_min <= avg_risk <= risk_max):
                role_name = archetype
                break

        if role_name == "undifferentiated":
            role_name = f"emergent_{dom_strategy[:15]}"

        return EmergentRole(
            agent_id=profile.agent_id,
            discovered_role=role_name,
            dominant_target_type=profile.dominant_target,
            dominant_strategy=dom_strategy,
            risk_preference=avg_risk,
            consistency_score=profile.specialization_score,
            epochs_observed=profile.epochs_active,
        )

    # ── Persistence (ERS-PERSIST-0) ───────────────────────────────────────────

    def _load(self) -> None:
        """ERS-PERSIST-0 (fail-open): corrupt or missing state returns empty dicts."""
        if not self.state_path.exists():
            return
        try:
            data = json.loads(self.state_path.read_text())
            for k, v in data.get("profiles", {}).items():
                try:
                    self._profiles[k] = AgentBehaviorProfile(**v)
                except Exception as exc:
                    # Fail-open for corrupt profile entries: skip invalid records.
                    logger.debug("Skipping corrupt profile entry %r in %s: %s", k, self.state_path, exc)
            for k, v in data.get("discovered_roles", {}).items():
                try:
                    self._discovered_roles[k] = EmergentRole(**v)
                except Exception as exc:
                    # Fail-open for corrupt role entries: skip invalid records.
                    logger.debug("Skipping corrupt discovered_role entry %r in %s: %s", k, self.state_path, exc)
        except Exception as exc:
            # Fail-open for unreadable/corrupt state file: ignore and start fresh.
            logger.debug("Failed to load ERS state from %s; ignoring corrupt state: %s", self.state_path, exc)

    def _save(self) -> None:
        """ERS-PERSIST-0: write state with sort_keys=True via Path.open("w")."""
        import dataclasses
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "profiles": {
                k: dataclasses.asdict(v)
                for k, v in sorted(self._profiles.items())
            },
            "discovered_roles": {
                k: dataclasses.asdict(v)
                for k, v in sorted(self._discovered_roles.items())
            },
        }
        with self.state_path.open("w") as fh:
            fh.write(json.dumps(payload, indent=2, sort_keys=True))


__all__ = [
    "EmergentRoleSpecializer",
    "EmergentRole",
    "AgentBehaviorProfile",
    "ROLE_ARCHETYPES",
    "SPECIALIZATION_WINDOW",
    "SPECIALIZATION_THRESHOLD",
]
