# SPDX-License-Identifier: Apache-2.0
"""Evolution governance and replay runtime package."""

from runtime.evolution.epoch import EpochManager, EpochState
from runtime.evolution.checkpoint_registry import CheckpointRegistry
from runtime.evolution.checkpoint_verifier import verify_checkpoint_chain
from runtime.evolution.entropy_detector import detect_entropy_metadata
from runtime.evolution.entropy_policy import EntropyPolicy, enforce_entropy_policy
from runtime.evolution.governor import EvolutionGovernor, GovernanceDecision, RecoveryTier
from runtime.evolution.impact import ImpactScorer, ImpactScore
from runtime.evolution.lineage_v2 import LineageEvent, LineageLedgerV2, EpochStartEvent, EpochEndEvent, MutationBundleEvent
from runtime.evolution.promotion_events import create_promotion_event, derive_event_id
from runtime.evolution.promotion_policy import PromotionPolicyEngine, PromotionPolicyError
from runtime.evolution.promotion_state_machine import PromotionState, can_transition, require_transition
from runtime.evolution.replay import ReplayEngine
from runtime.evolution.scoring import authority_threshold, clamp_score
from runtime.evolution.scoring_algorithm import compute_score
from runtime.evolution.scoring_ledger import ScoringLedger
from runtime.evolution.scoring_validator import validate_scoring_payload
from runtime.evolution.replay_verifier import ReplayVerifier
from runtime.evolution.runtime import EvolutionRuntime

__all__ = [
    "EpochManager",
    "EpochState",
    "enforce_entropy_policy",
    "EntropyPolicy",
    "detect_entropy_metadata",
    "verify_checkpoint_chain",
    "CheckpointRegistry",
    "EvolutionGovernor",
    "GovernanceDecision",
    "RecoveryTier",
    "ImpactScorer",
    "ImpactScore",
    "LineageEvent",
    "EpochStartEvent",
    "EpochEndEvent",
    "MutationBundleEvent",
    "LineageLedgerV2",
    "PromotionPolicyEngine",
    "PromotionPolicyError",
    "PromotionState",
    "create_promotion_event",
    "derive_event_id",
    "can_transition",
    "require_transition",
    "authority_threshold",
    "clamp_score",
    "compute_score",
    "ScoringLedger",
    "validate_scoring_payload",
    "ReplayEngine",
    "ReplayVerifier",
    "EvolutionRuntime",
]
