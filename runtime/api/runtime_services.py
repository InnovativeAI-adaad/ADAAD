# SPDX-License-Identifier: Apache-2.0
"""Runtime facade exposing orchestrator-safe runtime services.

Canonical governance health logic lives in ``runtime.governance.health_service``.
Duplication is forbidden: this module must keep a thin delegation wrapper only.
"""

from typing import Any, Iterable

from security.ledger import journal
from runtime.governance.review_pressure import (
    HIGH_REPUTATION_THRESHOLD,
    compute_tier_reviewer_count,
)
from runtime.governance.reviewer_reputation import (
    SCORING_ALGORITHM_VERSION,
    compute_epoch_reputation_batch,
)

from runtime import metrics
from runtime.boot import BootPreflightService
from runtime.boot.preflight import evaluate_boot_invariants
from runtime.capability_graph import register_capability
from runtime.constitution import (
    CONSTITUTION_VERSION,
    determine_tier,
    deterministic_envelope_scope,
    get_forced_tier,
)
from runtime.element_registry import dump, register
from runtime.evolution import EvolutionRuntime
from runtime.evolution.checkpoint_verifier import CheckpointVerificationError, CheckpointVerifier
from runtime.evolution.lineage_v2 import LineageIntegrityError
from runtime.evolution.replay_attestation import ReplayProofBuilder
from runtime.evolution.replay_divergence import build_signed_replay_manifest
from runtime.evolution.replay_divergence_artifacts import build_replay_divergence_artifacts
from runtime.evolution.replay_manifest import REPLAY_MANIFESTS_DIR, build_replay_manifest_v1, write_replay_manifest_v1
from runtime.evolution.replay_mode import ReplayMode, normalize_replay_mode
from runtime.evolution.replay_state_machine import ReplayStateMachine
from runtime.evolution.replay_service import ReplayVerificationService
from runtime.fitness_v2 import score_mutation_enhanced
from runtime.founders_law import (
    RULE_ARCHITECT_SCAN,
    RULE_CONSTITUTION_VERSION,
    RULE_KEY_ROTATION,
    RULE_LEDGER_INTEGRITY,
    RULE_MUTATION_ENGINE,
    RULE_PLATFORM_RESOURCES,
    RULE_WARM_POOL,
    enforce_law,
)
from runtime.governance.foundation import default_provider
from runtime.governance.foundation import canonical_json
from runtime.governance.decision_pipeline import evaluate_mutation_decision as evaluate_mutation
from runtime.preflight import validate_agent_contract_preflight, validate_constitution_version_config
from runtime.manifest.generator import generate_tool_manifest
from runtime.mcp.server import create_app as create_mcp_app
from runtime.platform.android_monitor import AndroidMonitor
from runtime.platform.storage_manager import StorageManager
from runtime.recovery.ledger_guardian import AutoRecoveryHook, SnapshotManager
from runtime.recovery.tier_manager import RecoveryPolicy, RecoveryTierLevel, TierManager
from runtime.timeutils import now_iso
from runtime.warm_pool import WarmPool


def reviewer_calibration_service(*, epoch_id: str, reviewer_ids: Iterable[str] | None = None) -> dict[str, Any]:
    """Aggregate reviewer calibration telemetry for the requested epoch.

    Read-only: this function only reads from ledger-backed journal events.

    Performance contract:
    - Uses an epoch-filtered ledger read instead of broad tail scans.
    - Preserves deterministic ordering by consuming ledger append order.
    - Keeps response shape stable for endpoint/schema compatibility.
    """
    normalized_reviewer_ids = sorted({rid.strip() for rid in (reviewer_ids or []) if rid and rid.strip()})

    if normalized_reviewer_ids:
        events = journal.read_entries_for_epoch(
            epoch_id=epoch_id,
            reviewer_ids=normalized_reviewer_ids,
            limit=5_000,
        )
    else:
        events = journal.read_entries_for_epoch(epoch_id=epoch_id, limit=5_000)
        inferred: set[str] = set()
        for entry in events:
            payload = entry.get("payload") if isinstance(entry, dict) else {}
            if isinstance(payload, dict):
                reviewer_id = str(payload.get("reviewer_id") or "").strip()
                if reviewer_id:
                    inferred.add(reviewer_id)
        normalized_reviewer_ids = sorted(inferred)

    reputation_scores = compute_epoch_reputation_batch(
        normalized_reviewer_ids,
        events,
        epoch_id=epoch_id,
        scoring_algorithm_version=SCORING_ALGORITHM_VERSION,
    )

    composite_scores = [record["composite_score"] for record in reputation_scores.values()]
    avg_reputation = round(sum(composite_scores) / len(composite_scores), 6) if composite_scores else 0.0

    cohort_summary = {
        "high": sum(1 for score in composite_scores if score >= HIGH_REPUTATION_THRESHOLD),
        "standard": sum(1 for score in composite_scores if 0.60 <= score < HIGH_REPUTATION_THRESHOLD),
        "low": sum(1 for score in composite_scores if score < 0.60),
    }

    calibration = compute_tier_reviewer_count("standard", avg_reputation)
    if calibration["adjustment"] < 0:
        tier_pressure = "extended"
    elif calibration["adjustment"] > 0:
        tier_pressure = "elevated"
    else:
        tier_pressure = "nominal"

    return {
        "cohort_summary": cohort_summary,
        "avg_reputation": avg_reputation,
        "tier_pressure": tier_pressure,
        "constitutional_floor": "enforced",
        "epoch_id": epoch_id,
        "constitution_version": CONSTITUTION_VERSION,
        "scoring_algorithm_version": SCORING_ALGORITHM_VERSION,
    }

__all__ = [
    "AutoRecoveryHook",
    "AndroidMonitor",
    "BootPreflightService",
    "CONSTITUTION_VERSION",
    "CheckpointVerificationError",
    "CheckpointVerifier",
    "EvolutionRuntime",
    "LineageIntegrityError",
    "RULE_ARCHITECT_SCAN",
    "RULE_CONSTITUTION_VERSION",
    "RULE_KEY_ROTATION",
    "RULE_LEDGER_INTEGRITY",
    "RULE_MUTATION_ENGINE",
    "RULE_PLATFORM_RESOURCES",
    "RULE_WARM_POOL",
    "RecoveryPolicy",
    "RecoveryTierLevel",
    "ReplayMode",
    "REPLAY_MANIFESTS_DIR",
    "ReplayProofBuilder",
    "ReplayVerificationService",
    "SnapshotManager",
    "StorageManager",
    "TierManager",
    "WarmPool",
    "build_signed_replay_manifest",
    "build_replay_divergence_artifacts",
    "create_mcp_app",
    "default_provider",
    "determine_tier",
    "deterministic_envelope_scope",
    "dump",
    "enforce_law",
    "evaluate_mutation",
    "evaluate_boot_invariants",
    "generate_tool_manifest",
    "get_telemetry_sink",
    "get_forced_tier",
    "metrics",
    "normalize_replay_mode",
    "now_iso",
    "build_replay_divergence_artifacts",
    "build_replay_manifest_v1",
    "canonical_json",
    "register",
    "register_capability",
    "reviewer_calibration_service",
    "ReplayStateMachine",
    "score_mutation_enhanced",
    "write_replay_manifest_v1",
    "validate_constitution_version_config",
]


def governance_health_service(*, epoch_id: str) -> dict[str, Any]:
    """Delegation wrapper for backwards-compatible imports.

    Canonical implementation lives in ``runtime.governance.health_service``.
    """
    from runtime.governance.health_service import governance_health_service as _canonical_governance_health_service

    return _canonical_governance_health_service(epoch_id=epoch_id)


def get_telemetry_sink():
    """Facade accessor for app telemetry sink required by runtime analytics."""
    from app.api.telemetry import get_telemetry_sink as _get_telemetry_sink

    return _get_telemetry_sink()
