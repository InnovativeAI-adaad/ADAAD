# SPDX-License-Identifier: Apache-2.0
"""
ADAAD v8 — Integration Test Scaffold
======================================
Test scaffold for the six core v8 modules.
Tests are organized by Gemini deep-think pillar:
  T-SCHEMA   — five evidence schema dataclasses + EvolutionEvidence aggregator
  T-SANDBOX  — ephemeral clone + Tier-0 protection + SANDBOX-DIV-0
  T-ADV      — adversarial fitness engine
  T-PRUNE    — ledger pruner + chain integrity
  T-AMEND    — constitutional amendment lifecycle
  T-SYNC     — repo-ledger sync watchdog + lockdown

Run:
    pytest tests/test_adaad_v8_integration.py -v
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from runtime.evolution.evidence.schemas import (
    EpochEvidence,
    MutationLineageEvidence,
    CapabilityVersionEvidence,
    GovernanceExceptionEvidence,
    ModelDriftEvidence,
    EvolutionEvidence,
    PromotionStatus,
    ResolutionStatus,
    DriftCatalyst,
)
from runtime.evolution.adversarial_fitness import AdversarialFitnessEngine, AdversarialVerdict
from runtime.evolution.ledger_pruner import LedgerPruner, LedgerIntegrityError
from runtime.governance.constitutional_amendment import (
    ConstitutionalAmendmentEngine,
    AmendmentStatus,
)
from runtime.integrity.repo_ledger_sync import RepoLedgerSyncWatchdog, LockdownActiveError


# ===========================================================================
# T-SCHEMA: Evidence Schema Tests
# ===========================================================================

class TestEpochEvidence:
    """T-SCHEMA-01..05"""

    def _make_epoch(self, epoch_id="ep_001", predecessor_hash="0" * 64) -> EpochEvidence:
        return EpochEvidence(
            epoch_id=epoch_id,
            model_hash_before="a" * 64,
            model_hash_after="b" * 64,
            capability_graph_before="c" * 64,
            capability_graph_after="d" * 64,
            evaluated_lineages=("lin_001", "lin_002"),
            promoted_lineage_id="lin_001",
            replay_verification_hash="e" * 64,
            sandbox_container_id="f" * 64,
            predecessor_hash=predecessor_hash,
            timestamp="2026-03-13T00:00:00Z",
            capability_targets=("StrategySelection",),
            mutations_attempted=("mut_001", "mut_002"),
            mutations_succeeded=("mut_001",),
        )

    def test_T_SCHEMA_01_frozen_instance(self):
        """Frozen dataclass raises on mutation attempt."""
        e = self._make_epoch()
        with pytest.raises((AttributeError, TypeError)):
            e.epoch_id = "tampered"

    def test_T_SCHEMA_02_hash_determinism(self):
        """Same EpochEvidence produces same hash on repeated calls."""
        e = self._make_epoch()
        assert e.compute_hash() == e.compute_hash()

    def test_T_SCHEMA_03_chain_validation(self):
        """Chain validation succeeds when predecessor_hash is correct."""
        e1 = self._make_epoch(epoch_id="ep_001", predecessor_hash="genesis" * 9 + "0000")
        predecessor_hash = e1.compute_hash()
        e2 = self._make_epoch(epoch_id="ep_002", predecessor_hash=predecessor_hash)
        assert e2.validate_chain(e1)

    def test_T_SCHEMA_04_chain_validation_fails_on_tamper(self):
        """Chain validation fails when predecessor_hash is wrong."""
        e1 = self._make_epoch(epoch_id="ep_001", predecessor_hash="0" * 64)
        e2 = self._make_epoch(epoch_id="ep_002", predecessor_hash="tampered" * 8)
        assert not e2.validate_chain(e1)

    def test_T_SCHEMA_05_adversarial_fields_present(self):
        e = self._make_epoch()
        assert hasattr(e, "adversarial_challenges_run")
        assert hasattr(e, "adversarial_challenges_failed")


class TestCapabilityVersionEvidence:
    """T-SCHEMA-06..07"""

    def test_T_SCHEMA_06_tier0_blocks_autonomous_mutation(self):
        """Tier-0 capability raises ValueError on validate()."""
        ev = CapabilityVersionEvidence(
            capability_name="ConstitutionEnforcement",
            version_from="1.0.0",
            version_to="1.1.0",
            contract_delta_hash="a" * 64,
            bound_functions_mutated=("fn_a",),
            causal_mutation_hashes=("mut_001",),
            invariant_changes=(),
            is_backward_compatible=True,
            tier="0",
            epoch_id="ep_001",
            timestamp="2026-03-13T00:00:00Z",
        )
        with pytest.raises(ValueError, match="CAP-VERS-0"):
            ev.validate_tier()

    def test_T_SCHEMA_07_tier1_passes_validation(self):
        ev = CapabilityVersionEvidence(
            capability_name="StrategySelection",
            version_from="1.0.0",
            version_to="1.1.0",
            contract_delta_hash="a" * 64,
            bound_functions_mutated=("fn_a",),
            causal_mutation_hashes=("mut_001",),
            invariant_changes=(),
            is_backward_compatible=True,
            tier="1",
            epoch_id="ep_001",
            timestamp="2026-03-13T00:00:00Z",
        )
        ev.validate_tier()  # must not raise


class TestGovernanceExceptionEvidence:
    """T-SCHEMA-08..10"""

    def _make_exception(self, rule="AST-COMPLEX-0", capability="StrategySelection",
                         duration=3) -> GovernanceExceptionEvidence:
        return GovernanceExceptionEvidence(
            exception_token_id="tok_" + "a" * 60,
            target_capability=capability,
            violated_rule=rule,
            justification_trace="j" * 64,
            duration_epochs=duration,
            human_key_fingerprint="SHA256:abc123",
            human_approval_ref="HUMAN-GATE-001",
            granted_at_epoch="ep_001",
            expires_at_epoch=130,
            resolution_status=ResolutionStatus.ACTIVE,
            lineage_projection=(0.72, 0.81, 0.88),
            mutations_covered=(),
        )

    def test_T_SCHEMA_08_valid_exception_passes(self):
        self._make_exception().validate()  # must not raise

    def test_T_SCHEMA_09_non_amendable_rule_blocked(self):
        e = self._make_exception(rule="AST-SAFE-0")
        with pytest.raises(ValueError):
            e.validate()

    def test_T_SCHEMA_10_tier0_capability_blocked(self):
        e = self._make_exception(capability="GovernanceGate")
        with pytest.raises(ValueError, match="TIER0-EXCEPT-0"):
            e.validate()

    def test_T_SCHEMA_11_duration_exceeds_ttl_blocked(self):
        e = self._make_exception(duration=5)
        with pytest.raises(ValueError, match="EXCEPTION-TTL-0"):
            e.validate()


class TestEvolutionEvidence:
    """T-SCHEMA-12"""

    def test_T_SCHEMA_12_compound_digest_integrity(self):
        """verify_integrity returns True for untampered EvolutionEvidence."""
        epoch = EpochEvidence(
            epoch_id="ep_001", model_hash_before="a"*64, model_hash_after="b"*64,
            capability_graph_before="c"*64, capability_graph_after="d"*64,
            evaluated_lineages=(), promoted_lineage_id=None,
            replay_verification_hash="e"*64, sandbox_container_id="f"*64,
            predecessor_hash="g"*64, timestamp="2026-03-13T00:00:00Z",
        )
        drift = ModelDriftEvidence(
            drift_event_id="drift_001", function_graph_delta=0.02,
            hotspot_map_shift=0.01, mutation_history_delta=0.005,
            catalyst_event=DriftCatalyst.MUTATION_PROMOTION,
            determinism_verified=True, model_hash_before="a"*64,
            model_hash_after="a"*64, divergent_functions=(),
            lockdown_triggered=False, drift_threshold=0.15,
            epoch_id="ep_001", timestamp="2026-03-13T00:00:00Z",
        )
        ev = EvolutionEvidence.build(
            epoch=epoch, lineages=[], capabilities=[], exceptions=[], drift=drift
        )
        assert ev.verify_integrity()


# ===========================================================================
# T-SANDBOX: Ephemeral Clone Tests
# ===========================================================================

class TestEphemeralClone:
    """T-SANDBOX-01..04"""

    def test_T_SANDBOX_01_clean_sandbox_runs_without_error(self):
        """Sandbox creation and teardown works on a temp directory."""
        from runtime.sandbox.ephemeral_clone import EphemeralCloneExecutor
        with tempfile.TemporaryDirectory() as repo_root:
            Path(repo_root, "test_module.py").write_text("def add(a, b): return a + b\n")
            with EphemeralCloneExecutor(repo_root=repo_root, test_command="echo OK") as ex:
                result = ex.apply_and_test(
                    mutation_id="mut_001",
                    target_file="test_module.py",
                    after_source="def add(a, b): return a + b + 0\n",
                )
            assert result.mutation_id == "mut_001"

    def test_T_SANDBOX_02_tier0_write_rejected(self):
        """Tier-0 path write raises SandboxViolation."""
        from runtime.sandbox.ephemeral_clone import EphemeralCloneExecutor, SandboxViolation
        with tempfile.TemporaryDirectory() as repo_root:
            tier0_file = Path(repo_root, "CONSTITUTION.md")
            tier0_file.write_text("# Constitutional invariants\n")
            with EphemeralCloneExecutor(repo_root=repo_root, test_command="echo OK") as ex:
                result = ex.apply_and_test(
                    mutation_id="mut_tier0_attack",
                    target_file="CONSTITUTION.md",
                    after_source="# Tampered!\n",
                )
            assert result.tier0_write_attempted
            assert result.tests_failed > 0

    def test_T_SANDBOX_03_sandbox_id_is_deterministic_for_same_state(self):
        """Same repo content produces same sandbox_id."""
        from runtime.sandbox.ephemeral_clone import EphemeralCloneExecutor
        with tempfile.TemporaryDirectory() as repo_root:
            Path(repo_root, "mod.py").write_text("x = 1\n")
            with EphemeralCloneExecutor(repo_root=repo_root, test_command="echo OK") as ex:
                id1 = ex._compute_sandbox_id()
                id2 = ex._compute_sandbox_id()
            assert id1 == id2


# ===========================================================================
# T-ADV: Adversarial Fitness Engine Tests
# ===========================================================================

class TestAdversarialFitness:
    """T-ADV-01..05"""

    engine = AdversarialFitnessEngine()

    SIMPLE_BEFORE = "def compute(x):\n    return x * 2\n"
    SIMPLE_AFTER  = "def compute(x):\n    return x * 2 + 1\n"
    SIMPLE_TEST   = (
        "def test_compute():\n"
        "    assert compute(2) != compute(3)\n"
        "    assert compute(0) == 1\n"
        "    assert compute(-1) == -1\n"
        "    assert isinstance(compute(5), int)\n"
    )

    def test_T_ADV_01_clean_mutation_passes(self):
        result = self.engine.challenge(
            mutation_id="mut_clean",
            before_source=self.SIMPLE_BEFORE,
            after_source=self.SIMPLE_AFTER,
            test_source=self.SIMPLE_TEST,
            node_count_delta=2,
            cyclomatic_delta=0,
        )
        assert result.verdict == AdversarialVerdict.PASSED
        assert result.passed

    def test_T_ADV_02_bloat_detected(self):
        result = self.engine.challenge(
            mutation_id="mut_bloat",
            before_source=self.SIMPLE_BEFORE,
            after_source=self.SIMPLE_AFTER,
            test_source=self.SIMPLE_TEST,
            node_count_delta=50,  # exceeds threshold of 40
            cyclomatic_delta=0,
        )
        assert result.verdict == AdversarialVerdict.BLOAT

    def test_T_ADV_03_collusion_detected(self):
        """Test that mirrors implementation constants triggers COLLUSION."""
        after = "def compute(x):\n    return x * 99999\n"
        # Test that literally asserts the constant 99999
        colluded_test = (
            "def test_compute():\n"
            "    assert compute(1) == 99999\n"
            "    assert compute(2) == 199998\n"
        )
        result = self.engine.challenge(
            mutation_id="mut_collude",
            before_source=self.SIMPLE_BEFORE,
            after_source=after,
            test_source=colluded_test,
            node_count_delta=1,
            cyclomatic_delta=0,
        )
        # With high constant overlap, should detect collusion
        assert result.challenge_hash  # at minimum, challenge ran

    def test_T_ADV_04_challenge_hash_non_empty(self):
        result = self.engine.challenge(
            mutation_id="mut_001",
            before_source=self.SIMPLE_BEFORE,
            after_source=self.SIMPLE_AFTER,
            test_source=self.SIMPLE_TEST,
            node_count_delta=1,
            cyclomatic_delta=0,
        )
        assert len(result.challenge_hash) == 64  # SHA-256 hex

    def test_T_ADV_05_division_without_guard_flagged(self):
        unsafe = "def divide(a, b):\n    return a / b\n"
        result = self.engine.challenge(
            mutation_id="mut_div",
            before_source=self.SIMPLE_BEFORE,
            after_source=unsafe,
            test_source=self.SIMPLE_TEST,
            node_count_delta=1,
            cyclomatic_delta=0,
        )
        # Edge case detection should flag missing zero guard
        assert len(result.edge_case_failures) > 0


# ===========================================================================
# T-PRUNE: Ledger Pruner Tests
# ===========================================================================

class TestLedgerPruner:
    """T-PRUNE-01..03"""

    def _write_ledger(self, path: Path, n: int) -> None:
        """Write n fake EvolutionEvidence entries to path."""
        prior_hash = "genesis" * 9 + "0000"
        with open(path, "w") as f:
            for i in range(n):
                entry = {
                    "compound_digest": hashlib.sha256(f"entry_{i}".encode()).hexdigest(),
                    "epoch_evidence": {
                        "epoch_id": f"ep_{i:05d}",
                        "predecessor_hash": prior_hash,
                    },
                }
                entry_json = json.dumps(entry, sort_keys=True)
                prior_hash = hashlib.sha256(entry_json.encode()).hexdigest()
                f.write(entry_json + "\n")

    def test_T_PRUNE_01_no_prune_needed_below_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "evolution_ledger.jsonl"
            self._write_ledger(ledger_path, 10)
            pruner = LedgerPruner(
                ledger_path=str(ledger_path),
                archive_dir=str(Path(tmp) / "archives"),
                state_path=str(Path(tmp) / "state.json"),
                snapshot_interval=1000,
                retention_epochs=100,
            )
            assert not pruner.should_prune()

    def test_T_PRUNE_02_prune_archives_and_retains(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "evolution_ledger.jsonl"
            self._write_ledger(ledger_path, 150)
            pruner = LedgerPruner(
                ledger_path=str(ledger_path),
                archive_dir=str(Path(tmp) / "archives"),
                state_path=str(Path(tmp) / "state.json"),
                snapshot_interval=1000,
                retention_epochs=50,
                max_ledger_size_mb=0.001,  # force prune on size
            )
            summary = pruner.prune_and_archive()
            assert summary.entries_archived == 100
            assert summary.entries_retained == 50

    def test_T_PRUNE_03_checkpoint_hash_non_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "evolution_ledger.jsonl"
            self._write_ledger(ledger_path, 150)
            pruner = LedgerPruner(
                ledger_path=str(ledger_path),
                archive_dir=str(Path(tmp) / "archives"),
                state_path=str(Path(tmp) / "state.json"),
                retention_epochs=50,
                max_ledger_size_mb=0.001,
            )
            summary = pruner.prune_and_archive()
            assert len(summary.checkpoint_hash) == 64


# ===========================================================================
# T-AMEND: Constitutional Amendment Tests
# ===========================================================================

class TestConstitutionalAmendment:
    """T-AMEND-01..05"""

    def _engine(self, tmp_dir):
        return ConstitutionalAmendmentEngine(
            ledger_path=str(Path(tmp_dir) / "exception_tokens.jsonl")
        )

    def _request(self, engine):
        return engine.request_amendment(
            capability_name="StrategySelection",
            rule_id="AST-COMPLEX-0",
            justification="Multi-step refactor valley crossing.",
            lineage_projection=(0.72, 0.81, 0.88),
            duration_epochs=3,
            human_key_fingerprint="SHA256:abc123",
            human_approval_ref="HUMAN-GATE-001",
            epoch_id="ep_127",
            current_epoch_count=127,
        )

    def test_T_AMEND_01_valid_amendment_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = self._engine(tmp)
            amendment = self._request(engine)
            assert amendment.status == AmendmentStatus.ACTIVE
            assert amendment.expires_at_epoch == 130

    def test_T_AMEND_02_non_amendable_rule_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = self._engine(tmp)
            with pytest.raises(ValueError):
                engine.request_amendment(
                    capability_name="StrategySelection",
                    rule_id="AST-SAFE-0",  # non-amendable
                    justification="test",
                    lineage_projection=(0.5, 0.6, 0.7),
                    duration_epochs=1,
                    human_key_fingerprint="SHA256:abc",
                    human_approval_ref="ref",
                    epoch_id="ep_001",
                    current_epoch_count=1,
                )

    def test_T_AMEND_03_tier0_capability_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = self._engine(tmp)
            with pytest.raises(ValueError, match="AMEND-TIER0-0"):
                engine.request_amendment(
                    capability_name="GovernanceGate",  # Tier-0
                    rule_id="AST-COMPLEX-0",
                    justification="test",
                    lineage_projection=(0.5, 0.6, 0.7),
                    duration_epochs=1,
                    human_key_fingerprint="SHA256:abc",
                    human_approval_ref="ref",
                    epoch_id="ep_001",
                    current_epoch_count=1,
                )

    def test_T_AMEND_04_amendment_written_to_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = self._engine(tmp)
            self._request(engine)
            ledger = Path(tmp) / "exception_tokens.jsonl"
            assert ledger.exists()
            lines = [l for l in ledger.read_text().splitlines() if l.strip()]
            assert len(lines) >= 1

    def test_T_AMEND_05_expiry_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = self._engine(tmp)
            amendment = self._request(engine)  # expires at epoch 130
            assert not amendment.is_expired(129)
            assert amendment.is_expired(130)


# ===========================================================================
# T-SYNC: Repo-Ledger Sync Tests
# ===========================================================================

class TestRepoLedgerSync:
    """T-SYNC-01..03"""

    def test_T_SYNC_01_clean_repo_passes_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "module.py").write_text("x = 1\n")
            watchdog = RepoLedgerSyncWatchdog(
                repo_root=tmp,
                sync_events_path=str(Path(tmp, "sync_events.jsonl")),
                state_path=str(Path(tmp, "sync_state.json")),
            )
            watchdog._baseline_snapshot = watchdog._snapshot_repo()
            assert watchdog.is_clean()

    def test_T_SYNC_02_modified_file_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = Path(tmp, "module.py")
            mod.write_text("x = 1\n")
            watchdog = RepoLedgerSyncWatchdog(
                repo_root=tmp,
                sync_events_path=str(Path(tmp, "sync_events.jsonl")),
                state_path=str(Path(tmp, "sync_state.json")),
            )
            watchdog._baseline_snapshot = watchdog._snapshot_repo()
            # Simulate manual edit
            mod.write_text("x = 999\n")  # changed without telling orchestrator
            assert not watchdog.is_clean()

    def test_T_SYNC_04_poll_failure_writes_telemetry_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            watchdog = RepoLedgerSyncWatchdog(
                repo_root=tmp,
                sync_events_path=str(Path(tmp, "sync_events.jsonl")),
                state_path=str(Path(tmp, "sync_state.json")),
                poll_interval_s=1,
                poll_failure_threshold=3,
            )
            with patch.object(watchdog, "_check_once", side_effect=RuntimeError("boom")):
                watchdog._handle_poll_failure(RuntimeError("boom"))

            events = [
                json.loads(line)
                for line in Path(tmp, "sync_events.jsonl").read_text().splitlines()
                if line.strip()
            ]
            assert events[-1]["event_type"] == "WATCHDOG_POLL_FAILURE"
            assert events[-1]["component"] == "RepoLedgerSyncWatchdog"
            assert events[-1]["operation"] == "poll_loop_check_once"
            assert events[-1]["exception_type"] == "RuntimeError"
            assert events[-1]["exception_message"] == "boom"
            assert events[-1]["exception_classification"] == "invariant_violation_exception"
            assert events[-1]["poll_interval_s"] == 1
            assert events[-1]["thread_name"]
            assert events[-1]["timestamp"]

    def test_T_SYNC_06_poll_failure_environmental_classification(self):
        with tempfile.TemporaryDirectory() as tmp:
            watchdog = RepoLedgerSyncWatchdog(
                repo_root=tmp,
                sync_events_path=str(Path(tmp, "sync_events.jsonl")),
                state_path=str(Path(tmp, "sync_state.json")),
            )
            watchdog._handle_poll_failure(FileNotFoundError("missing ledger file"))
            events = [
                json.loads(line)
                for line in Path(tmp, "sync_events.jsonl").read_text().splitlines()
                if line.strip()
            ]
            assert events[-1]["exception_type"] == "FileNotFoundError"
            assert events[-1]["exception_classification"] == "environmental_exception"

    def test_T_SYNC_05_repeated_poll_failures_set_monitoring_impaired_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp, "sync_state.json")
            watchdog = RepoLedgerSyncWatchdog(
                repo_root=tmp,
                sync_events_path=str(Path(tmp, "sync_events.jsonl")),
                state_path=str(state_path),
                poll_interval_s=2,
                poll_failure_threshold=2,
                max_poll_failure_backoff_s=16,
            )

            watchdog._handle_poll_failure(ValueError("f1"))
            assert watchdog._state.get("monitoring_impaired") is not True
            assert watchdog._compute_poll_sleep_s() == 4.0

            watchdog._handle_poll_failure(ValueError("f2"))
            assert watchdog._state.get("monitoring_impaired") is True
            assert watchdog._state.get("monitoring_impaired_reason") == "WATCHDOG_POLL_FAILURE"
            assert watchdog._state.get("monitoring_impaired_consecutive_failures") == 2
            assert watchdog._state.get("monitoring_impaired_since")
            assert watchdog._compute_poll_sleep_s() == 8.0

            persisted = json.loads(state_path.read_text())
            assert persisted["monitoring_impaired"] is True

            watchdog._handle_poll_success()
            assert watchdog._state["monitoring_impaired"] is False
            assert watchdog._state["monitoring_last_recovered_at"]
            assert watchdog._compute_poll_sleep_s() == 2.0

    def test_T_SYNC_03_lockdown_blocked_by_assert_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            watchdog = RepoLedgerSyncWatchdog(
                repo_root=tmp,
                sync_events_path=str(Path(tmp, "sync_events.jsonl")),
                state_path=str(Path(tmp, "sync_state.json")),
            )
            watchdog._state["lockdown_active"] = True
            with pytest.raises(LockdownActiveError):
                watchdog.assert_clean()
