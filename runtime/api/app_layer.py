# SPDX-License-Identifier: Apache-2.0
"""Facade for runtime services consumed by app-layer modules."""

from runtime import ROOT_DIR, fitness, metrics
from runtime.autonomy.mutation_scaffold import MutationCandidate, rank_mutation_candidates
from runtime.capability_graph import get_capabilities, register_capability
from runtime.evolution.entropy_discipline import EntropyBudget, derive_seed, deterministic_context, deterministic_token, deterministic_token_with_budget
from runtime.evolution.fitness import FitnessEvaluator
from runtime.mutation.ast_substrate.ast_snapshot import ASTSnapshotStore
from runtime.evolution.promotion_manifest import PromotionManifestWriter, emit_pr_lifecycle_event
from runtime.audit_auth import load_audit_tokens, require_audit_read_scope
from runtime.governance.mutation_ledger import MutationLedger
from runtime.governance.branch_manager import BranchManager
from runtime.governance.foundation import RuntimeDeterminismProvider, SeededDeterminismProvider, SystemDeterminismProvider, default_provider, require_replay_safe_provider, safe_get
from runtime.governance.gate_certifier import GateCertifier
from runtime.governance.gate import DeterministicAxisEvaluator, GovernanceGate
from runtime.director import GovernanceDeniedError, RuntimeDirector
from runtime.integrations.aponi_sync import push_to_dashboard
from runtime.intelligence.llm_provider import LLMProviderClient, load_provider_config
from runtime.manifest.generator import generate_tool_manifest
from runtime.metrics_analysis import summarize_preflight_rejections, top_preflight_rejections
from runtime.timeutils import now_iso
from runtime.tools.mutation_fs import file_hash

__all__ = [
    "BranchManager",
    "EntropyBudget",
    "EvolutionKernel",
    "FitnessEvaluator",
    "DeterministicAxisEvaluator",
    "GateCertifier",
    "GovernanceDeniedError",
    "GovernanceGate",
    "RuntimeDirector",
    "LLMProviderClient",
    "load_audit_tokens",
    "require_audit_read_scope",
    "MutationCandidate",
    "MutationLedger",
    "PromotionManifestWriter",
    "ROOT_DIR",
    "RuntimeDeterminismProvider",
    "SeededDeterminismProvider",
    "SystemDeterminismProvider",
    "ASTSnapshotStore",
    "default_provider",
    "deterministic_context",
    "deterministic_token",
    "deterministic_token_with_budget",
    "derive_seed",
    "emit_pr_lifecycle_event",
    "file_hash",
    "fitness",
    "generate_tool_manifest",
    "get_capabilities",
    "load_provider_config",
    "metrics",
    "now_iso",
    "push_to_dashboard",
    "rank_mutation_candidates",
    "record_external_governance_event",
    "register_capability",
    "require_replay_safe_provider",
    "safe_get",
    "summarize_preflight_rejections",
    "top_preflight_rejections",
]


def record_external_governance_event(*args, **kwargs):
    from runtime.governance.external_event_bridge import record

    return record(*args, **kwargs)



def __getattr__(name: str):
    if name == "EvolutionKernel":
        from runtime.evolution.evolution_kernel import EvolutionKernel

        return EvolutionKernel
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
