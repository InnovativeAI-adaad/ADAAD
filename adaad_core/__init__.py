# SPDX-License-Identifier: Apache-2.0
"""
adaad_core — Constitutional Governance Kernel
=============================================
Stable API surface for the ADAAD constitutional governance engine.
Independently importable without Aponi UI, SPIE, or federation modules.

Public exports (semver-governed from v9.57.0 / Phase 124):
    GovernanceGate                — deterministic gate evaluation
    ConstitutionalRollbackEngine  — amendment versioning and rollback
    InvariantDiscoveryEngine      — self-discovering constitutional rules
    MirrorTestEngine              — constitutional self-calibration
    EpochMemoryStore              — ledger-backed epoch memory
    verify_ledger                 — JSONL ledger chain verification

Invariants: CORE-EXPORT-0, CORE-IMPORT-0
"""
from __future__ import annotations

__version__ = "10.9.0"
__author__ = "Innovative AI LLC"
__license__ = "Apache-2.0"

# CORE-IMPORT-0: All exports must be importable without triggering
# Aponi UI, SPIE, or federation module initialisation.
from runtime.governance.gate import GovernanceGate
from runtime.innovations30.constitutional_rollback import ConstitutionalRollbackEngine
from runtime.innovations30.invariant_discovery import InvariantDiscoveryEngine
from runtime.innovations30.mirror_test import MirrorTestEngine
from runtime.autonomy.epoch_memory_store import EpochMemoryStore
from runtime.innovations30.deterministic_audit_sandbox import DeterministicAuditSandbox as _DAS

# CORE-EXPORT-0: verify_ledger is a first-class public function,
# not a method reference, to keep the API surface stable across
# internal refactors of DeterministicAuditSandbox.
def verify_ledger(ledger_path) -> dict:
    """Verify every chain link in a JSONL ledger.

    Args:
        ledger_path: Path to a JSONL ledger file.

    Returns:
        dict with keys: ok (bool), records_checked (int), error (str|None).

    Raises:
        DASVerifyError on first broken link (fail-closed).
    """
    from pathlib import Path
    return _DAS.verify_ledger(Path(ledger_path))


__all__ = [
    "GovernanceGate",
    "ConstitutionalRollbackEngine",
    "InvariantDiscoveryEngine",
    "MirrorTestEngine",
    "EpochMemoryStore",
    "verify_ledger",
]
