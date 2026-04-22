# SPDX-License-Identifier: Apache-2.0
"""
AgentBanditSelector — reward-profile-informed multi-armed bandit for
ADAAD agent persona selection (Phase 11-A, PR-11-A-01).

Purpose:
    Replaces the heuristic win-rate agent recommendation in FitnessLandscape
    with a principled bandit that draws on LearningProfileRegistry reward data.

    Two strategies are supported:
    - UCB1 (default):  score_i = mean_reward_i + C * sqrt(ln(N) / n_i)
    - Thompson:        sample from Beta(α, β) where α = reward_mass, β = loss_mass

    The bandit is ADVISORY ONLY. GovernanceGate approval authority is never
    affected. Agent selection preference is one input to EvolutionLoop; it
    does not approve, sign, or execute mutations.

    Key improvement over BanditSelector (existing):
    - Operates on float reward signals (0.0–1.0) from EpochRewardSignal.avg_reward,
      not binary win/loss — captures partial-quality signals.
    - Per-arm reward mass: successes = cumulative reward, failures = 1 - reward,
      giving Thompson a continuous Beta prior.
    - LearningProfileRegistry bootstrap: seeds arms from historical decision
      reward_score records when arm state file is absent.

Architecture:
    AgentBanditSelector is a stateful module:
    - Arm state is persisted to data/agent_bandit_state.json on every update.
    - Consecutive-recommendation tracking enables constitution validation.
    - exception-isolated: failures in update() or recommend() never propagate
      to EvolutionLoop (callers must enforce this with try/except).

Constitutional invariants:
    - Arm stats must be non-negative (reward_mass ≥ 0, pull_count ≥ 0).
    - No single agent may be recommended for more than MAX_CONSECUTIVE_BANDIT_EPOCHS
      consecutive epochs without at least one competing agent being recommended.
      (enforced by ConstitutionValidator in PR-11-A-03 — arm state exposes
      consecutive_recommendations for audit)

Determinism:
    - UCB1 mode is fully deterministic given identical arm state.
    - Thompson mode contract:
        - If constructor rng is NOT supplied, recommend() derives a per-call RNG
          from epoch_id, producing reproducible output for identical epoch_id +
          identical arm state.
        - If constructor rng IS supplied, recommend() uses that injected RNG
          directly (caller-controlled deterministic stream).

Android/Pydroid3 compatibility:
    - Pure Python stdlib only.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AGENTS: tuple[str, ...] = ("architect", "dream", "beast")

UCB1_EXPLORATION_C: float = math.sqrt(2)        # Standard UCB1 exploration constant
MIN_PULLS_FOR_ACTIVATION: int = 5               # Minimum pulls before bandit overrides landscape
MAX_CONSECUTIVE_BANDIT_EPOCHS: int = 10         # Constitutional cap — PR-11-A-03 rule
BANDIT_CONFIDENCE_FLOOR: float = 0.60           # Minimum confidence to override landscape
REWARD_FLOOR: float = 0.0                       # Reward clamp lower bound
REWARD_CEILING: float = 1.0                     # Reward clamp upper bound

DEFAULT_STATE_PATH: Path = Path("data/agent_bandit_state.json")

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ArmRewardState:
    """Float-reward arm state for one agent persona."""
    agent: str
    pull_count: int = 0
    reward_mass: float = 0.0        # Cumulative clamped reward (sum of signals 0-1)
    loss_mass: float = 0.0          # Cumulative loss mass (pull_count - reward_mass)
    consecutive_recommendations: int = 0

    @property
    def mean_reward(self) -> float:
        if self.pull_count == 0:
            return 0.0
        return self.reward_mass / self.pull_count

    def ucb1_score(self, total_pulls: int, c: float = UCB1_EXPLORATION_C) -> float:
        """UCB1: mean_reward + C * sqrt(ln(total_pulls) / pull_count).
        Unpulled arms return +inf to guarantee initial exploration.
        """
        if self.pull_count == 0:
            return float("inf")
        if total_pulls <= 0:
            return self.mean_reward
        return self.mean_reward + c * math.sqrt(math.log(max(1, total_pulls)) / self.pull_count)

    def thompson_sample(self, rng: random.Random) -> float:
        """Sample from Beta(reward_mass + 1, loss_mass + 1).
        Continuous generalisation: reward_mass as pseudo successes.
        """
        alpha = max(0.01, self.reward_mass + 1.0)
        beta  = max(0.01, self.loss_mass  + 1.0)
        return rng.betavariate(alpha, beta)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent":                      self.agent,
            "pull_count":                 self.pull_count,
            "reward_mass":                round(self.reward_mass, 6),
            "loss_mass":                  round(self.loss_mass,   6),
            "mean_reward":                round(self.mean_reward, 6),
            "consecutive_recommendations": self.consecutive_recommendations,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ArmRewardState":
        obj = cls(agent=str(d.get("agent", "")))
        obj.pull_count = int(d.get("pull_count", 0))
        obj.reward_mass = float(d.get("reward_mass", 0.0))
        obj.loss_mass   = float(d.get("loss_mass", 0.0))
        obj.consecutive_recommendations = int(d.get("consecutive_recommendations", 0))
        return obj


@dataclass(frozen=True)
class BanditAgentRecommendation:
    """Output of AgentBanditSelector.recommend().

    Consumed by EvolutionLoop Phase 0d → FitnessLandscape.recommended_agent().
    """
    agent: str               # Recommended persona: "architect" | "dream" | "beast"
    confidence: float        # UCB1 score or Thompson sample (normalised 0-1)
    strategy: str            # "ucb1" | "thompson"
    exploration_bonus: float # Extra explore_ratio boost from arm uncertainty
    is_active: bool          # False when below MIN_PULLS_FOR_ACTIVATION
    total_pulls: int

    def as_dict(self) -> Dict[str, Any]:
        return {
            "agent":             self.agent,
            "confidence":        round(self.confidence, 6),
            "strategy":          self.strategy,
            "exploration_bonus": round(self.exploration_bonus, 4),
            "is_active":         self.is_active,
            "total_pulls":       self.total_pulls,
        }


# ---------------------------------------------------------------------------
# AgentBanditSelector
# ---------------------------------------------------------------------------


class AgentBanditSelector:
    """Reward-profile-informed multi-armed bandit for ADAAD agent selection.

    Usage::

        selector = AgentBanditSelector()
        rec = selector.recommend(epoch_id="epoch-042")
        if rec.is_active and rec.confidence >= BANDIT_CONFIDENCE_FLOOR:
            preferred_agent = rec.agent

        # After epoch completes — update with reward signal:
        selector.update(agent=rec.agent, reward=0.73, epoch_id="epoch-042")

    Bootstrap from LearningProfileRegistry::

        selector = AgentBanditSelector.from_registry(registry, state_path=path)
    """

    def __init__(
        self,
        *,
        strategy: str = "ucb1",
        exploration_c: float = UCB1_EXPLORATION_C,
        agents: Sequence[str] = AGENTS,
        state_path: Path = DEFAULT_STATE_PATH,
        rng: Optional[random.Random] = None,
    ) -> None:
        if strategy not in ("ucb1", "thompson"):
            raise ValueError(f"Unknown strategy {strategy!r}. Use 'ucb1' or 'thompson'.")
        self._strategy     = strategy
        self._c            = exploration_c
        self._state_path   = Path(state_path)
        self._rng          = rng
        self._arms: Dict[str, ArmRewardState] = {
            a: ArmRewardState(agent=a) for a in agents
        }
        self._load_state()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def total_pulls(self) -> int:
        return sum(arm.pull_count for arm in self._arms.values())

    @property
    def is_active(self) -> bool:
        """True once MIN_PULLS_FOR_ACTIVATION total pulls are recorded."""
        return self.total_pulls >= MIN_PULLS_FOR_ACTIVATION

    def recommend(self, *, epoch_id: str) -> BanditAgentRecommendation:
        """Return the recommended agent persona for the next epoch.

        Thompson RNG behavior:
            - If selector was created with rng=..., that RNG is used.
            - Otherwise RNG is derived from epoch_id:
                seed = int(hashlib.sha256(epoch_id.encode()).hexdigest(), 16) % (2**31)
                epoch_rng = random.Random(seed)

        Returns BanditAgentRecommendation with is_active=False when below
        MIN_PULLS_FOR_ACTIVATION — callers should fall back to landscape heuristic.
        """
        n = self.total_pulls

        if self._strategy == "ucb1":
            scored = {
                agent: arm.ucb1_score(n, self._c)
                for agent, arm in self._arms.items()
            }
            # Tie-break: alphabetical (deterministic)
            best_agent = min(
                scored,
                key=lambda a: (-scored[a], a),
            )
            raw_confidence = scored[best_agent]
            # Normalise: clamp inf to 1.0 for downstream consumers
            confidence = 1.0 if math.isinf(raw_confidence) else min(1.0, max(0.0, raw_confidence))

        else:  # thompson
            # Contract: caller-injected RNG takes precedence. Fallback derives
            # per-call RNG from epoch_id for deterministic replayability.
            epoch_rng = self._rng
            if epoch_rng is None:
                seed = int(hashlib.sha256(epoch_id.encode()).hexdigest(), 16) % (2 ** 31)
                epoch_rng = random.Random(seed)
            samples = {
                agent: arm.thompson_sample(epoch_rng)
                for agent, arm in self._arms.items()
            }
            best_agent = min(samples, key=lambda a: (-samples[a], a))
            confidence = samples[best_agent]

        # Exploration bonus: inverse of arm certainty — more bonus for low-pull arms
        arm = self._arms[best_agent]
        exploration_bonus = max(0.0, 0.1 * (1.0 - min(1.0, arm.pull_count / 20.0)))

        return BanditAgentRecommendation(
            agent=best_agent,
            confidence=round(confidence, 6),
            strategy=self._strategy,
            exploration_bonus=round(exploration_bonus, 4),
            is_active=self.is_active,
            total_pulls=n,
        )

    def update(self, *, agent: str, reward: float, epoch_id: str) -> None:
        """Record a float reward signal for the given agent arm.

        Args:
            agent:    The agent persona that was used this epoch.
            reward:   Float reward signal in [0.0, 1.0] (e.g. EpochRewardSignal.avg_reward).
            epoch_id: Epoch identifier for audit trail (not persisted, for callers only).
        """
        if agent not in self._arms:
            self._arms[agent] = ArmRewardState(agent=agent)

        clamped = max(REWARD_FLOOR, min(REWARD_CEILING, float(reward)))
        arm = self._arms[agent]
        arm.pull_count   += 1
        arm.reward_mass  += clamped
        arm.loss_mass    += (1.0 - clamped)

        # Track consecutive recommendations
        for a, other_arm in self._arms.items():
            if a == agent:
                other_arm.consecutive_recommendations += 1
            else:
                other_arm.consecutive_recommendations = 0

        self._save_state()

    def reset_arm(self, *, agent: str) -> None:
        """Reset a single arm's statistics. Used for constitutional enforcement
        when MAX_CONSECUTIVE_BANDIT_EPOCHS is exceeded.
        """
        if agent in self._arms:
            self._arms[agent] = ArmRewardState(agent=agent)
            self._save_state()

    def arm_stats(self) -> Dict[str, Dict[str, Any]]:
        """Return serialisable arm statistics for audit and dashboard consumers."""
        return {agent: arm.to_dict() for agent, arm in self._arms.items()}

    def summary(self) -> Dict[str, Any]:
        """Full state snapshot for logging and health endpoints."""
        return {
            "strategy":          self._strategy,
            "exploration_c":     round(self._c, 6),
            "total_pulls":       self.total_pulls,
            "is_active":         self.is_active,
            "min_pulls":         MIN_PULLS_FOR_ACTIVATION,
            "max_consecutive":   MAX_CONSECUTIVE_BANDIT_EPOCHS,
            "confidence_floor":  BANDIT_CONFIDENCE_FLOOR,
            "arms":              self.arm_stats(),
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def to_state(self) -> Dict[str, Any]:
        return {
            "schema_version": "1",
            "strategy":       self._strategy,
            "exploration_c":  self._c,
            "arms": {
                agent: arm.to_dict()
                for agent, arm in self._arms.items()
            },
        }

    def _load_state(self) -> None:
        if not self._state_path.exists():
            return
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return
            for agent, arm_dict in raw.get("arms", {}).items():
                if agent in self._arms:
                    self._arms[agent] = ArmRewardState.from_dict({**arm_dict, "agent": agent})
            # Restore strategy and exploration_c if present
            if "strategy" in raw:
                self._strategy = str(raw["strategy"])
            if "exploration_c" in raw:
                self._c = float(raw["exploration_c"])
        except Exception:  # noqa: BLE001 — corrupt state → fresh start
            pass

    def _save_state(self) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(
                json.dumps(self.to_state(), indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except Exception:  # noqa: BLE001 — save failure must never block epoch
            pass

    # ------------------------------------------------------------------
    # Bootstrap helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_registry(
        cls,
        registry: Any,  # LearningProfileRegistry — typed loosely to avoid circular import
        *,
        state_path: Path = DEFAULT_STATE_PATH,
        strategy: str = "ucb1",
    ) -> "AgentBanditSelector":
        """Bootstrap arm reward_mass from LearningProfileRegistry decision records.

        Maps decision.reward_score values to agent arms via agent-to-mutation-type
        heuristic (structural→architect, performance/coverage→beast, other→dream).
        If no decisions exist, returns a fresh selector with empty arms.
        """
        selector = cls(strategy=strategy, state_path=state_path)
        try:
            decisions = registry._state.get("decisions", [])  # noqa: SLF001
            _agent_type_map = {
                "structural":  "architect",
                "performance": "beast",
                "coverage":    "beast",
            }
            for dec in decisions:
                reward = float(dec.get("reward_score", 0.0))
                # Decisions don't carry mutation_type directly — use agent map via
                # the mutation_id prefix convention: "architect-*", "dream-*", "beast-*"
                mutation_id = str(dec.get("mutation_id", ""))
                agent = "dream"  # default
                for persona in AGENTS:
                    if mutation_id.startswith(persona):
                        agent = persona
                        break
                if agent in selector._arms:
                    clamped = max(REWARD_FLOOR, min(REWARD_CEILING, reward))
                    selector._arms[agent].pull_count  += 1
                    selector._arms[agent].reward_mass += clamped
                    selector._arms[agent].loss_mass   += (1.0 - clamped)
        except Exception:  # noqa: BLE001
            pass
        return selector


__all__ = [
    "AGENTS",
    "BANDIT_CONFIDENCE_FLOOR",
    "MAX_CONSECUTIVE_BANDIT_EPOCHS",
    "MIN_PULLS_FOR_ACTIVATION",
    "UCB1_EXPLORATION_C",
    "DEFAULT_STATE_PATH",
    "ArmRewardState",
    "BanditAgentRecommendation",
    "AgentBanditSelector",
]
