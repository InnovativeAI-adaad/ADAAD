# SPDX-License-Identifier: Apache-2.0
"""
Tests for AgentBanditSelector — Phase 11-A PR-11-A-01.

Test IDs: T11-A-01 through T11-A-12
"""
from __future__ import annotations

import json
import math
import random
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
pytestmark = pytest.mark.autonomous_critical

from runtime.autonomy.agent_bandit_selector import (
    AGENTS,
    BANDIT_CONFIDENCE_FLOOR,
    MAX_CONSECUTIVE_BANDIT_EPOCHS,
    MIN_PULLS_FOR_ACTIVATION,
    UCB1_EXPLORATION_C,
    AgentBanditSelector,
    ArmRewardState,
    BanditAgentRecommendation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_selector(strategy: str = "ucb1", tmp_path: Path = None) -> AgentBanditSelector:
    if tmp_path:
        path = tmp_path / "bandit_state.json"
    else:
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as handle:
            path = Path(handle.name)
    return AgentBanditSelector(strategy=strategy, state_path=path)


def _feed_rewards(selector: AgentBanditSelector, agent: str, rewards: list[float]) -> None:
    for i, r in enumerate(rewards):
        selector.update(agent=agent, reward=r, epoch_id=f"e{i:03d}")


# ---------------------------------------------------------------------------
# T11-A-01: ArmRewardState UCB1 score math
# ---------------------------------------------------------------------------

def test_t11_a_01_ucb1_score_math():
    """T11-A-01: UCB1 score = mean_reward + C * sqrt(ln(N) / pulls) for non-zero arms."""
    arm = ArmRewardState(agent="architect")
    arm.pull_count  = 4
    arm.reward_mass = 2.8   # mean = 0.7
    arm.loss_mass   = 1.2

    total_pulls = 20
    expected = 0.7 + UCB1_EXPLORATION_C * math.sqrt(math.log(20) / 4)
    assert arm.ucb1_score(total_pulls) == pytest.approx(expected, rel=1e-6)


def test_t11_a_01b_ucb1_unpulled_arm_returns_inf():
    """T11-A-01b: Unpulled arm (pull_count=0) returns +inf to guarantee exploration."""
    arm = ArmRewardState(agent="dream")
    assert arm.ucb1_score(total_pulls=100) == float("inf")


# ---------------------------------------------------------------------------
# T11-A-02: Thompson sampling distribution
# ---------------------------------------------------------------------------

def test_t11_a_02_thompson_sample_range():
    """T11-A-02: thompson_sample() always returns value in [0, 1]."""
    arm = ArmRewardState(agent="beast")
    arm.pull_count  = 10
    arm.reward_mass = 7.0
    arm.loss_mass   = 3.0
    rng = random.Random(42)
    for _ in range(200):
        s = arm.thompson_sample(rng)
        assert 0.0 <= s <= 1.0


def test_t11_a_02b_thompson_high_reward_arm_preferred():
    """T11-A-02b: High-reward arm yields higher Thompson samples on average."""
    rng = random.Random(999)
    good_arm = ArmRewardState(agent="architect")
    good_arm.pull_count  = 20
    good_arm.reward_mass = 18.0
    good_arm.loss_mass   = 2.0

    bad_arm = ArmRewardState(agent="dream")
    bad_arm.pull_count  = 20
    bad_arm.reward_mass = 2.0
    bad_arm.loss_mass   = 18.0

    good_samples = [good_arm.thompson_sample(rng) for _ in range(500)]
    bad_samples  = [bad_arm.thompson_sample(rng)  for _ in range(500)]
    assert sum(good_samples) / 500 > sum(bad_samples) / 500


# ---------------------------------------------------------------------------
# T11-A-03: Arm initialization
# ---------------------------------------------------------------------------

def test_t11_a_03_fresh_selector_has_all_agents(tmp_path: Path):
    """T11-A-03: Fresh selector initialises arms for all three personas."""
    sel = _fresh_selector(tmp_path=tmp_path)
    assert set(sel._arms.keys()) == {"architect", "dream", "beast"}


def test_t11_a_03b_fresh_arms_zero_state(tmp_path: Path):
    """T11-A-03b: Fresh arms have pull_count=0, reward_mass=0, loss_mass=0."""
    sel = _fresh_selector(tmp_path=tmp_path)
    for arm in sel._arms.values():
        assert arm.pull_count  == 0
        assert arm.reward_mass == 0.0
        assert arm.loss_mass   == 0.0


# ---------------------------------------------------------------------------
# T11-A-04: update() — reward accumulation
# ---------------------------------------------------------------------------

def test_t11_a_04_update_accumulates_reward(tmp_path: Path):
    """T11-A-04: update() increments pull_count, reward_mass, and loss_mass correctly."""
    sel = _fresh_selector(tmp_path=tmp_path)
    sel.update(agent="architect", reward=0.8, epoch_id="e001")
    arm = sel._arms["architect"]
    assert arm.pull_count   == 1
    assert arm.reward_mass  == pytest.approx(0.8)
    assert arm.loss_mass    == pytest.approx(0.2)


def test_t11_a_04b_reward_clamped_to_unit_interval(tmp_path: Path):
    """T11-A-04b: Rewards are clamped to [0, 1] — over/under values safe."""
    sel = _fresh_selector(tmp_path=tmp_path)
    sel.update(agent="dream", reward=1.5, epoch_id="e001")
    sel.update(agent="dream", reward=-0.3, epoch_id="e002")
    arm = sel._arms["dream"]
    assert arm.reward_mass == pytest.approx(1.0)   # 1.0 + 0.0
    assert arm.loss_mass   == pytest.approx(1.0)   # 0.0 + 1.0


# ---------------------------------------------------------------------------
# T11-A-05: reset_arm()
# ---------------------------------------------------------------------------

def test_t11_a_05_reset_arm_clears_state(tmp_path: Path):
    """T11-A-05: reset_arm() clears pull_count, reward_mass, loss_mass to zero."""
    sel = _fresh_selector(tmp_path=tmp_path)
    _feed_rewards(sel, "beast", [0.7, 0.6, 0.8])
    sel.reset_arm(agent="beast")
    arm = sel._arms["beast"]
    assert arm.pull_count  == 0
    assert arm.reward_mass == 0.0
    assert arm.loss_mass   == 0.0


# ---------------------------------------------------------------------------
# T11-A-06: Cold-start / is_active
# ---------------------------------------------------------------------------

def test_t11_a_06_cold_start_is_not_active(tmp_path: Path):
    """T11-A-06: Fresh selector (0 pulls) is_active=False."""
    sel = _fresh_selector(tmp_path=tmp_path)
    assert sel.is_active is False


def test_t11_a_06b_becomes_active_after_min_pulls(tmp_path: Path):
    """T11-A-06b: is_active=True once total_pulls >= MIN_PULLS_FOR_ACTIVATION."""
    sel = _fresh_selector(tmp_path=tmp_path)
    for i in range(MIN_PULLS_FOR_ACTIVATION):
        sel.update(agent="architect", reward=0.5, epoch_id=f"e{i:03d}")
    assert sel.is_active is True


def test_t11_a_06c_recommend_returns_is_active_false_when_cold(tmp_path: Path):
    """T11-A-06c: recommend() returns is_active=False below activation threshold."""
    sel = _fresh_selector(tmp_path=tmp_path)
    rec = sel.recommend(epoch_id="e001")
    assert rec.is_active is False


# ---------------------------------------------------------------------------
# T11-A-07: UCB1 selects highest-reward arm when warm
# ---------------------------------------------------------------------------

def test_t11_a_07_ucb1_selects_dominant_arm(tmp_path: Path):
    """T11-A-07: UCB1 recommends the arm with dominant reward after sufficient pulls."""
    sel = _fresh_selector(strategy="ucb1", tmp_path=tmp_path)
    # Force enough pulls to pass activation; make architect clearly best
    _feed_rewards(sel, "architect", [0.9, 0.95, 0.85])
    _feed_rewards(sel, "dream",     [0.2, 0.25, 0.15])
    _feed_rewards(sel, "beast",     [0.3, 0.35, 0.25])
    # After equal pulls, exploration bonus is equal — UCB1 score determined by mean_reward
    rec = sel.recommend(epoch_id="epoch-test")
    assert rec.agent == "architect"
    assert rec.strategy == "ucb1"
    assert rec.is_active is True


# ---------------------------------------------------------------------------
# T11-A-08: Thompson Sampling selects high-reward arm on average
# ---------------------------------------------------------------------------

def test_t11_a_08_thompson_sampling_selects_high_reward_arm(tmp_path: Path):
    """T11-A-08: Thompson sampling predominantly selects the highest-reward arm."""
    sel = _fresh_selector(strategy="thompson", tmp_path=tmp_path)
    _feed_rewards(sel, "architect", [0.95] * 10)
    _feed_rewards(sel, "dream",     [0.10] * 10)
    _feed_rewards(sel, "beast",     [0.10] * 10)

    counts: dict[str, int] = {"architect": 0, "dream": 0, "beast": 0}
    for i in range(200):
        rec = sel.recommend(epoch_id=f"probe-{i:04d}")
        counts[rec.agent] += 1

    # Architect should win overwhelmingly (≥ 150/200)
    assert counts["architect"] >= 150, f"Thompson did not prefer architect: {counts}"


def test_t11_a_08b_thompson_same_epoch_reproducible_without_injected_rng(tmp_path: Path):
    """T11-A-08b: Without rng injection, identical epoch_id yields identical recommendations."""
    sel = _fresh_selector(strategy="thompson", tmp_path=tmp_path)
    _feed_rewards(sel, "architect", [0.80, 0.85, 0.90, 0.88])
    _feed_rewards(sel, "dream",     [0.30, 0.35, 0.25, 0.20])
    _feed_rewards(sel, "beast",     [0.40, 0.45, 0.35, 0.30])

    rec1 = sel.recommend(epoch_id="epoch-stable-001")
    rec2 = sel.recommend(epoch_id="epoch-stable-001")

    assert rec1.agent == rec2.agent
    assert rec1.confidence == rec2.confidence


def test_t11_a_08c_thompson_tie_break_is_alphabetical(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """T11-A-08c: Thompson tie-break is deterministic alphabetical when samples are equal."""
    sel = _fresh_selector(strategy="thompson", tmp_path=tmp_path)
    _feed_rewards(sel, "architect", [0.5])
    _feed_rewards(sel, "dream", [0.5])
    _feed_rewards(sel, "beast", [0.5])

    monkeypatch.setattr(ArmRewardState, "thompson_sample", lambda self, rng: 0.5)
    rec = sel.recommend(epoch_id="epoch-tie")

    assert rec.agent == "architect"


# ---------------------------------------------------------------------------
# T11-A-09: BanditAgentRecommendation fields
# ---------------------------------------------------------------------------

def test_t11_a_09_recommendation_fields_populated():
    """T11-A-09: BanditAgentRecommendation has agent, confidence, strategy, exploration_bonus."""
    sel = _fresh_selector()
    rec = sel.recommend(epoch_id="e001")
    assert isinstance(rec, BanditAgentRecommendation)
    assert rec.agent in AGENTS
    assert isinstance(rec.confidence, float)
    assert rec.strategy in ("ucb1", "thompson")
    assert isinstance(rec.exploration_bonus, float)
    assert rec.exploration_bonus >= 0.0


# ---------------------------------------------------------------------------
# T11-A-10: State persistence round-trip
# ---------------------------------------------------------------------------

def test_t11_a_10_state_json_round_trip(tmp_path):
    """T11-A-10: Arm state persists to JSON and loads correctly on new instance."""
    path = tmp_path / "bandit_state.json"
    sel = AgentBanditSelector(state_path=path)
    _feed_rewards(sel, "architect", [0.8, 0.7, 0.9])
    _feed_rewards(sel, "dream",     [0.4])

    # Load fresh instance from same path
    sel2 = AgentBanditSelector(state_path=path)
    assert sel2._arms["architect"].pull_count  == 3
    assert sel2._arms["architect"].reward_mass == pytest.approx(2.4)
    assert sel2._arms["dream"].pull_count      == 1
    assert sel2._arms["dream"].reward_mass     == pytest.approx(0.4)


def test_t11_a_10b_corrupt_state_file_yields_fresh_arms(tmp_path):
    """T11-A-10b: Corrupt JSON state file falls back to fresh empty arms."""
    path = tmp_path / "bandit_state.json"
    path.write_text("NOT_VALID_JSON{{{", encoding="utf-8")
    sel = AgentBanditSelector(state_path=path)
    for arm in sel._arms.values():
        assert arm.pull_count == 0


# ---------------------------------------------------------------------------
# T11-A-11: LearningProfileRegistry bootstrap
# ---------------------------------------------------------------------------

def test_t11_a_11_from_registry_seeds_arms_from_decisions(tmp_path):
    """T11-A-11: from_registry() seeds arm reward_mass from decision records."""
    mock_registry = MagicMock()
    mock_registry._state = {
        "decisions": [
            {"mutation_id": "architect-refactor-001", "reward_score": 0.85, "accepted": True},
            {"mutation_id": "architect-refactor-002", "reward_score": 0.90, "accepted": True},
            {"mutation_id": "beast-opt-001",          "reward_score": 0.40, "accepted": False},
        ]
    }
    path = tmp_path / "bandit_bootstrap.json"
    sel = AgentBanditSelector.from_registry(mock_registry, state_path=path)

    assert sel._arms["architect"].pull_count  == 2
    assert sel._arms["architect"].reward_mass == pytest.approx(1.75)
    assert sel._arms["beast"].pull_count      == 1
    assert sel._arms["beast"].reward_mass     == pytest.approx(0.40)
    assert sel._arms["dream"].pull_count      == 0


def test_t11_a_11b_from_registry_empty_decisions_returns_fresh(tmp_path):
    """T11-A-11b: from_registry() with no decisions returns fresh zero-state selector."""
    mock_registry = MagicMock()
    mock_registry._state = {"decisions": []}
    sel = AgentBanditSelector.from_registry(mock_registry, state_path=tmp_path / "b.json")
    assert sel.total_pulls == 0


# ---------------------------------------------------------------------------
# T11-A-12: Boundary conditions and consecutive tracking
# ---------------------------------------------------------------------------

def test_t11_a_12_consecutive_recommendations_tracked():
    """T11-A-12: consecutive_recommendations increments for selected agent, resets for others."""
    sel = _fresh_selector()
    sel.update(agent="architect", reward=0.8, epoch_id="e001")
    sel.update(agent="architect", reward=0.7, epoch_id="e002")
    assert sel._arms["architect"].consecutive_recommendations == 2
    assert sel._arms["dream"].consecutive_recommendations     == 0

    sel.update(agent="dream", reward=0.5, epoch_id="e003")
    assert sel._arms["dream"].consecutive_recommendations     == 1
    assert sel._arms["architect"].consecutive_recommendations == 0


def test_t11_a_12b_max_consecutive_constant_defined():
    """T11-A-12b: MAX_CONSECUTIVE_BANDIT_EPOCHS constant is ≥ 3 (constitutional cap)."""
    assert MAX_CONSECUTIVE_BANDIT_EPOCHS >= 3


def test_t11_a_12c_arm_stats_returns_all_agents():
    """T11-A-12c: arm_stats() returns a dict keyed by all three agent personas."""
    sel = _fresh_selector()
    stats = sel.arm_stats()
    assert set(stats.keys()) == {"architect", "dream", "beast"}
    for v in stats.values():
        assert "pull_count"   in v
        assert "reward_mass"  in v
        assert "mean_reward"  in v
