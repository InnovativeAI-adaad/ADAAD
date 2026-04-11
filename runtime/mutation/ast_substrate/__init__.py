# SPDX-License-Identifier: Apache-2.0
"""
runtime.mutation.ast_substrate — AST Mutation Substrate (Phase 60)
===================================================================
The Motor layer of ADAAD v8.  Provides the primitive pipeline for
governed code mutation:

  ASTDiffPatch          The DNA: hash-verifiable mutation primitive.
  StaticSafetyScanner   Gates patches with 4 constitutional rules.
  PatchApplicator       LibCST-based application with SANDBOX-DIV-0 guard.
  SandboxTournament     Ephemeral candidate competition; always sandbox-only.

Invariants
----------
SANDBOX-DIV-0  before/after AST hashes must match after apply; auto-rollback.
PATCH-SIZE-0   max 40 delta AST nodes, max 2 files.
TIER0-SELF-0   Tier-0 bound modules blocked by CapabilityTargetDiscovery upstream.
MUTATION_SANDBOX_ONLY=true enforced during stabilisation (all Phase 60 work).
"""

from runtime.mutation.ast_substrate.ast_diff_patch import (  # noqa: F401
    ASTDiffPatch,
    MutationKind,
    RiskClass,
    PatchSizeViolation,
    PatchHashError,
    MAX_AST_NODES,
    MAX_FILES,
)
from runtime.mutation.ast_substrate.static_scanner import (  # noqa: F401
    StaticSafetyScanner,
    ScanResult,
    RuleViolation,
    ImportBoundaryRule,
    NonDeterminismRule,
    ComplexityCeilingRule,
    PatchSizeRule,
    COMPLEXITY_DELTA_MAX,
)
from runtime.mutation.ast_substrate.patch_applicator import (  # noqa: F401
    PatchApplicator,
    ApplyResult,
)
from runtime.mutation.ast_substrate.sandbox_tournament import (  # noqa: F401
    SandboxTournament,
    TournamentResult,
    CandidateScore,
)
from runtime.mutation.ast_substrate.ast_snapshot import (  # noqa: F401
    SnapshotResult,
    compute_snapshot,
    compute_digest,
    read_previous_digest,
    write_snapshot_state,
    target_key,
)

__all__ = [
    "ASTDiffPatch", "MutationKind", "RiskClass",
    "PatchSizeViolation", "PatchHashError", "MAX_AST_NODES", "MAX_FILES",
    "StaticSafetyScanner", "ScanResult", "RuleViolation",
    "ImportBoundaryRule", "NonDeterminismRule",
    "ComplexityCeilingRule", "PatchSizeRule", "COMPLEXITY_DELTA_MAX",
    "PatchApplicator", "ApplyResult",
    "SandboxTournament", "TournamentResult", "CandidateScore",
    "SnapshotResult", "compute_snapshot", "compute_digest",
    "read_previous_digest", "write_snapshot_state", "target_key",
]
