# SPDX-License-Identifier: Apache-2.0
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Deterministic orchestrator entrypoint.
"""

import json
import importlib
import logging
import os
import re
from pathlib import Path
import time
import sys
from typing import Any, Dict, Optional

from app import APP_ROOT
from app.boot import (
    apply_governance_ci_mode_defaults,
    governance_ci_mode_enabled,
    read_adaad_version,
    replay_env_flags,
)
from app.architect_agent import ArchitectAgent
from app.beast_mode_loop import BeastModeLoop
from app.dream_mode import DreamMode
from app.mutation_executor import MutationExecutor
from adaad.orchestrator.boot_config import (
    FacadeRuntimeState,
    build_init_state,
    dry_run_env_enabled,
    resolve_replay_mode,
    select_epoch,
)
from adaad.orchestrator.cli_handlers import (
    build_main_parser,
    handle_export_replay_proof,
    handle_replay_namespace,
    handle_runbook_composer,
    handle_status_report,
)
from adaad.orchestrator.runtime_factory import build_orchestrator
from adaad.orchestrator.replay_preflight import execute_replay_preflight
from runtime.api import MutationEngine, MutationRequest, agent_path_from_id, iter_agent_dirs, resolve_agent_id
from runtime.api.app_layer import OperatingMode, classify_current_changes, get_operating_mode, get_required_gate_tiers
from runtime.api.mutation_runtime import verify_all
from runtime.api.runtime_services import (
    AutoRecoveryHook,
    AndroidMonitor,
    CONSTITUTION_VERSION,
    CheckpointVerificationError,
    CheckpointVerifier,
    EvolutionRuntime,
    LineageIntegrityError,
    RecoveryPolicy,
    RecoveryTierLevel,
    ReplayMode,
    RULE_ARCHITECT_SCAN,
    RULE_CONSTITUTION_VERSION,
    RULE_KEY_ROTATION,
    RULE_LEDGER_INTEGRITY,
    RULE_MUTATION_ENGINE,
    RULE_PLATFORM_RESOURCES,
    RULE_WARM_POOL,
    SnapshotManager,
    StorageManager,
    TierManager,
    WarmPool,
    default_provider,
    determine_tier,
    dump,
    enforce_law,
    evaluate_boot_invariants,
    evaluate_mutation,
    generate_tool_manifest,
    get_forced_tier,
    metrics,
    normalize_replay_mode,
    now_iso,
    register,
    register_capability,
    score_mutation_enhanced,
    validate_agent_contract_preflight,
)
from adaad.orchestrator.bootstrap import bootstrap_tool_registry
from adaad.orchestrator.dispatcher import dispatch
from security import cryovant
from security.whaledic_secrets import enforce_whaledic_secret_policy
from security.ledger import journal
from security.ledger.journal import JournalIntegrityError


ORCHESTRATOR_LOGGER = "adaad.orchestrator"

# Underscore-prefixed aliases for test-import compatibility
_apply_governance_ci_mode_defaults = apply_governance_ci_mode_defaults
_governance_ci_mode_enabled = governance_ci_mode_enabled
_read_adaad_version = read_adaad_version


def _get_orchestrator_logger() -> logging.Logger:
    logger = logging.getLogger(ORCHESTRATOR_LOGGER)
    if logger.handlers:
        return logger
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


def _build_aponi_dashboard() -> Any:
    try:
        # lint:fix forbidden_dynamic_execution — lazy dashboard loading — governance-reviewed
        dashboard_cls = getattr(
            importlib.import_module("ui.aponi_dashboard"),  # lint:fix forbidden_dynamic_execution
            "AponiDashboard",
        )
    except Exception as exc:
        detail = f"lazy_init_failed:ui.aponi_dashboard.AponiDashboard:{type(exc).__name__}:{exc}"
        metrics.log(
            event_type="lazy_init_failure",
            payload={"component": "app.main", "target": "ui.aponi_dashboard.AponiDashboard", "error": str(exc)},
            level="ERROR",
        )
        raise RuntimeError(detail) from exc
    metrics.log(
        event_type="lazy_init_success",
        payload={"component": "app.main", "target": "ui.aponi_dashboard.AponiDashboard"},
        level="INFO",
    )
    return dashboard_cls()


class Orchestrator:
    """
    Coordinates boot order and health checks.
    """

    def __init__(
        self,
        *,
        dry_run: bool = False,
        replay_mode: str | bool | ReplayMode = ReplayMode.OFF,
        replay_epoch: str = "",
        exit_after_boot: bool = False,
        verbose: bool = False,
        fast_mode: bool = False,
    ) -> None:
        self.state: Dict[str, Any] = {
            "status": "initializing",
            "mutation_enabled": False,
            "adaad_version": read_adaad_version(APP_ROOT.parent),
            "constitution_version": CONSTITUTION_VERSION,
            "fast_mode": fast_mode,
        }
        self.logger = _get_orchestrator_logger()
        self.agents_root = APP_ROOT / "agents"
        self.lineage_dir = self.agents_root / "lineage"
        self.warm_pool = WarmPool(size=2)
        self.architect = ArchitectAgent(self.agents_root)
        self.dream: Optional[DreamMode] = None
        self.beast: Optional[BeastModeLoop] = None
        self.dashboard: Optional[Any] = None
        self.evolution_runtime = EvolutionRuntime()
        self.snapshot_manager = SnapshotManager(APP_ROOT.parent / ".ledger_snapshots")
        self.recovery_hook = AutoRecoveryHook(self.snapshot_manager)
        self.tier_manager = TierManager()
        self.resource_monitor = AndroidMonitor(APP_ROOT.parent)
        self.storage_manager = StorageManager(APP_ROOT.parent)
        self.executor = MutationExecutor(self.agents_root, evolution_runtime=self.evolution_runtime)
        self.mutation_engine = MutationEngine(metrics.METRICS_PATH)
        self.dry_run = dry_run
        self.verbose = verbose
        self.fast_mode = fast_mode
        self.replay_mode = normalize_replay_mode(replay_mode)
        self.replay_epoch = replay_epoch.strip()
        self.exit_after_boot = exit_after_boot
        self.evolution_runtime.set_replay_mode(self.replay_mode)

        # Phase 107 Streamlining
        from runtime.governance.fast_path_policy import OperatingMode, get_operating_mode  # adaad: import-boundary-ok:phase107-fast-path-compat
        from runtime.governance.change_classifier import classify_current_changes_decision  # adaad: import-boundary-ok:phase107-fast-path-compat
        self.operating_mode = get_operating_mode()
        if self.fast_mode:
            self.operating_mode = OperatingMode.DEV_FAST
        self.change_decision = classify_current_changes_decision()
        self.change_type = self.change_decision.change_type

    def _v(self, message: str) -> None:
        if not self.verbose:
            return
        home = os.getenv("HOME", "")
        safe_message = message.replace(home, "~") if home else message
        self.logger.info(f"[ADAAD] {safe_message}")

    def _fail(self, reason: str, *, payload: Optional[Dict[str, Any]] = None) -> None:
        reason_code = reason.split(":", 1)[0] if reason else "unknown_failure"
        event_payload: Dict[str, Any] = {"reason": reason, "reason_code": reason_code}
        if payload:
            event_payload["failure_event"] = payload
        metrics.log(event_type="orchestrator_error", payload=event_payload, level="ERROR")
        self.state["status"] = "error"
        self.state["reason"] = reason
        self.state["reason_code"] = reason_code
        failure_chain: list[Dict[str, str]] = []
        journal_status = "not_attempted"
        dump_status = "not_attempted"
        fallback_stderr_status = "not_needed"
        try:
            journal_status = "attempted"
            journal.ensure_ledger()
            journal.write_entry(
                agent_id="system",
                action="orchestrator_failed",
                payload={
                    "reason": reason,
                    "reason_code": reason_code,
                    "event_type": "orchestrator_failure_envelope.v1",
                },
            )
            journal_status = "ok"
        except Exception as exc:
            journal_status = "failed"
            failure_chain.append(
                {
                    "step": "journal_write",
                    "reason_code": "orchestrator_failure_journal_write_failed",
                    "error": f"{type(exc).__name__}:{exc}",
                }
            )
        try:
            dump_status = "attempted"
            dump()
            dump_status = "ok"
        except Exception as exc:
            dump_status = "failed"
            failure_chain.append(
                {
                    "step": "dump",
                    "reason_code": "orchestrator_failure_dump_failed",
                    "error": f"{type(exc).__name__}:{exc}",
                }
            )
            try:
                metrics.log(
                    event_type="orchestrator_dump_failed",
                    payload={"error": str(exc), "reason_code": "orchestrator_failure_dump_failed"},
                    level="ERROR",
                )
            except Exception:
                fallback_stderr_status = "write_attempted"
                try:
                    sys.stderr.write(f"orchestrator_dump_failed:{exc}\n")
                    fallback_stderr_status = "ok"
                except Exception as stderr_exc:
                    fallback_stderr_status = "failed"
                    failure_chain.append(
                        {
                            "step": "stderr_fallback",
                            "reason_code": "orchestrator_failure_stderr_fallback_failed",
                            "error": f"{type(stderr_exc).__name__}:{stderr_exc}",
                        }
                    )
        envelope = {
            "event_type": "orchestrator_failure_envelope.v1",
            "primary_reason": reason,
            "primary_reason_code": reason_code,
            "journal_write_status": journal_status,
            "dump_status": dump_status,
            "fallback_stderr_status": fallback_stderr_status,
            "failure_chain": failure_chain,
        }
        metrics.log(event_type="orchestrator_failure_envelope", payload=envelope, level="ERROR")
        self.state["failure_envelope"] = envelope
        sys.exit(1)

    @staticmethod
    def _extract_blocked_agent_ids(preflight: Dict[str, Any]) -> list[str]:
        blocked: set[str] = set()
        for module in preflight.get("failing_modules", []):
            module_name = str(module.get("module", "")).strip()
            if not module_name:
                continue
            rel = Path(module_name)
            if rel.parts[:2] == ("adaad", "agents") and len(rel.parts) >= 3:
                blocked.add(Path(rel.parts[2]).stem)
            else:
                blocked.add(rel.stem)
        return sorted(blocked)

    def _validate_agent_contract_gate(self) -> None:
        preflight = validate_agent_contract_preflight()
        if preflight.get("ok"):
            self.state["agent_contract_preflight"] = {
                "ok": True,
                "checked_modules": preflight.get("checked_modules", 0),
                "blocked_agent_ids": [],
            }
            return

        blocked_agent_ids = self._extract_blocked_agent_ids(preflight)
        fail_reason = "agent_contract_preflight_failed"
        self.state["agent_contract_preflight"] = {
            "ok": False,
            "reason": fail_reason,
            "checked_modules": preflight.get("checked_modules", 0),
            "blocked_agent_ids": blocked_agent_ids,
            "failing_modules": preflight.get("failing_modules", []),
        }
        self.state["fail_closed"] = True
        self.evolution_runtime.governor.fail_closed = True
        self._fail(fail_reason, payload=self.state["agent_contract_preflight"])

    def boot(self) -> None:
        self._v(f"Replay mode normalized: {self.replay_mode.value}")
        if self.dry_run and self.replay_mode == ReplayMode.STRICT:
            self._v("Warning: dry-run + strict replay may not reflect production execution semantics.")
        
        # Phase 107: Fast Path Orientation
        required_tiers = get_required_gate_tiers(self.operating_mode, self.change_type)
        self._v(f"Operating mode: {self.operating_mode.value} | Change type: {self.change_type.value}")
        self._v(f"Required gate tiers: {sorted(required_tiers)}")

        self._v("Starting governance spine initialization")
        metrics.log(event_type="orchestrator_start", payload={}, level="INFO")
        # C-01: assert ADAAD_ENV is explicitly set before any governance surface.
        try:
            cryovant.assert_env_mode_set()
        except RuntimeError as exc:
            self._fail(str(exc), payload={"boot_stage": "env_mode_assertion"})
        # H-02: assert governance signing key present before any governance surface is reached.
        try:
            cryovant.assert_governance_signing_key_boot()
        except RuntimeError as exc:
            self._fail(str(exc), payload={"boot_stage": "governance_signing_key_assertion"})
        try:
            self.state["whaledic_secret_policy"] = enforce_whaledic_secret_policy().__dict__
        except RuntimeError as exc:
            self._fail(str(exc), payload={"boot_stage": "whaledic_secret_policy_assertion"})
        
        # Tier 0 Invariants
        boot_invariants = evaluate_boot_invariants(replay_mode=self.replay_mode.value, agents_root=self.agents_root)
        if not boot_invariants.ok:
            self._fail(boot_invariants.reason, payload=boot_invariants.payload)
        self._v("Boot invariant preflight passed")
        self.state["boot_invariants"] = boot_invariants.payload
        
        # Tier 1 Gates (Selective)
        if 1 in required_tiers:
            self._validate_agent_contract_gate()
            self._v("Agent contract preflight passed")
        else:
            self._v("Skipping Tier 1 agent contract gate (Fast Path)")

        bootstrap_tool_registry()
        self._register_elements()
        self.warm_pool.start()

        # Tier 2 Checkpoint/Replay (Selective)
        if 2 in required_tiers:
            self._verify_checkpoint_chain()
            self._v("Checkpoint chain verification passed")
        else:
            self._v("Skipping Tier 2 checkpoint verification (Fast Path)")

        epoch_state = self.evolution_runtime.boot()
        self.state["epoch"] = epoch_state
        self._v("Replay baseline initialized")
        
        # Health-First Mode (Selective)
        if 1 in required_tiers:
            self.dream = DreamMode(
                self.agents_root,
                self.lineage_dir,
                replay_mode=self.replay_mode.value,
                recovery_tier=self.evolution_runtime.governor.recovery_tier.value,
            )
            self.beast = BeastModeLoop(self.agents_root, self.lineage_dir)
            self._health_check_architect()
            self._health_check_dream()
            self._health_check_beast()
        
        if 2 in required_tiers:
            self._run_replay_preflight()
            self._v(f"Replay decision: {self.state.get('replay_decision')}")
            self._v(f"Fail-closed state: {self.evolution_runtime.fail_closed}")
            self._v(f"Replay aggregate score: {self.state.get('replay_score')}")
        
        if self.state.get("mutation_enabled"):
            if self.evolution_runtime.fail_closed:
                self.state["replay_divergence"] = True
                journal.write_entry(agent_id="system", action="mutation_blocked_fail_closed", payload={"epoch_id": self.evolution_runtime.current_epoch_id, "ts": now_iso()})
            elif self._governance_gate():
                if self.exit_after_boot:
                    self.state["mutation_cycle_skipped"] = "exit_after_boot"
                else:
                    self._run_mutation_cycle()
        self._v(f"Mutation cycle status: {'enabled' if self.state.get('mutation_enabled') else 'disabled'}")
        self._register_capabilities()
        self._v("Capability registration complete")
        self.state["status"] = "ready"
        self._v("Boot sequence complete (status=ready)")
        metrics.log(event_type="orchestrator_ready", payload=self.state, level="INFO")
        journal.write_entry(agent_id="system", action="orchestrator_ready", payload=self.state)
        dump()
        if self.exit_after_boot:
            self.logger.info("ADAAD_BOOT_OK")
            sys.exit(0)
        self._init_ui()
        self._v("Aponi dashboard started")

    def _run_replay_preflight(self, *, verify_only: bool = False) -> Dict[str, Any]:
        """Delegate to the module-level run_replay_preflight for testability."""
        return run_replay_preflight(self, dump, verify_only=verify_only)

    def _run_replay_preflight_impl(self, dump_func: Any, *, verify_only: bool = False) -> Dict[str, Any]:
        """Core replay preflight implementation (called via module-level delegation)."""
        return execute_replay_preflight(
            self,
            dump_func,
            verify_only=verify_only,
            replay_env_flags=replay_env_flags,
        )

    def verify_replay_only(self) -> None:
        self._v("Running replay verification-only mode")
        self.state["verify_only"] = True
        metrics.log(event_type="orchestrator_start", payload={"verify_only": True}, level="INFO")
        boot_invariants = evaluate_boot_invariants(replay_mode=self.replay_mode.value, agents_root=self.agents_root)
        if not boot_invariants.ok:
            self._fail(boot_invariants.reason, payload=boot_invariants.payload)
        self._register_elements()
        self.warm_pool.start()
        self._verify_checkpoint_chain()
        epoch_state = self.evolution_runtime.boot()
        self.state["epoch"] = epoch_state
        self._run_replay_preflight(verify_only=True)

    def _register_elements(self) -> None:
        register("Earth", "runtime.metrics")
        register("Earth", "runtime.element_registry")
        register("Earth", "runtime.warm_pool")
        register("Water", "security.cryovant")
        register("Water", "security.ledger.journal")
        register("Wood", "app.architect_agent")
        register("Fire", "app.dream_mode")
        register("Fire", "app.beast_mode_loop")
        register("Metal", "ui.aponi_dashboard")

    def _init_runtime(self) -> None:
        self.warm_pool.start()

    def _verify_checkpoint_chain(self) -> None:
        try:
            verification = CheckpointVerifier.verify_all_checkpoints(self.evolution_runtime.ledger.ledger_path)
        except CheckpointVerificationError as exc:
            journal.write_entry(
                agent_id="system",
                action="checkpoint_chain_violated",
                payload={"reason": str(exc), "ts": now_iso()},
            )
            self._fail(f"checkpoint_chain_violated:{exc}")
            return
        journal.write_entry(
            agent_id="system",
            action="checkpoint_chain_verified",
            payload={**verification, "ts": now_iso()},
        )

    def _verify_checkpoint_chain_stage(self) -> None:
        try:
            CheckpointVerifier.verify_chain(self.evolution_runtime.ledger, provider=self.evolution_runtime.governor.provider)
        except CheckpointVerificationError as exc:
            self._fail(f"checkpoint_chain_violated:{exc}")

    def _init_cryovant(self) -> None:
        return

    def _health_check_architect(self) -> None:
        scan = self.architect.scan()
        if not scan.get("valid"):
            self._fail("architect_scan_failed")

    def _health_check_dream(self) -> None:
        assert self.dream is not None
        tasks = self.dream.discover_tasks()
        if not tasks:
            metrics.log(event_type="dream_safe_boot", payload={"reason": "no tasks"}, level="WARN")
            self.state["mutation_enabled"] = False
            self.state["safe_boot"] = True
            return
        metrics.log(event_type="dream_health_ok", payload={"tasks": tasks}, level="INFO")
        self.state["mutation_enabled"] = True
        self.state["safe_boot"] = False

    def _health_check_beast(self) -> None:
        assert self.beast is not None
        staging_root = self.lineage_dir / "_staging"
        if not staging_root.exists():
            try:
                staging_root.mkdir(parents=True, exist_ok=True)
            except OSError:
                self._fail("beast_staging_unavailable")
        invalid_agents = []
        for agent_dir in iter_agent_dirs(self.agents_root):
            agent_id = resolve_agent_id(agent_dir, self.agents_root)
            if not cryovant.validate_ancestry(agent_id):
                invalid_agents.append(agent_id)
        if invalid_agents:
            self._fail(f"beast_ancestry_invalid:{','.join(invalid_agents)}")
        metrics.log(
            event_type="beast_health_ok",
            payload={"staging_root": str(staging_root), "validated_agents": len(invalid_agents) == 0},
            level="INFO",
        )

    def _governance_gate(self) -> bool:
        checks = [
            ("constitution_version", RULE_CONSTITUTION_VERSION, *self._check_constitution_version()),
            ("key_rotation", RULE_KEY_ROTATION, *self._check_key_rotation_status()),
            ("ledger_integrity", RULE_LEDGER_INTEGRITY, *self._check_ledger_integrity()),
            ("mutation_engine", RULE_MUTATION_ENGINE, *self._check_mutation_engine_health()),
            ("warm_pool", RULE_WARM_POOL, *self._check_warm_pool_ready()),
            ("architect_invariants", RULE_ARCHITECT_SCAN, *self._check_architect_invariants()),
            ("platform_resources", RULE_PLATFORM_RESOURCES, *self._check_platform_resources()),
        ]
        decision = enforce_law(
            {
                "mutation_id": f"governance-gate-{self.evolution_runtime.current_epoch_id or 'boot'}",
                "trust_mode": os.getenv("ADAAD_TRUST_MODE", "dev").strip().lower(),
                "checks": [{"rule_id": rule_id, "ok": ok, "reason": reason} for _, rule_id, ok, reason in checks],
            }
        )

        failures = [{"check": check_name, "reason": reason} for check_name, _, ok, reason in checks if not ok]
        if not decision.passed:
            tier = self.tier_manager.evaluate_escalation(
                governance_violations=len(failures),
                ledger_errors=sum(1 for f in failures if f.get("check") == "ledger_integrity"),
                mutation_failures=sum(1 for f in failures if f.get("check") == "mutation_engine"),
                metric_anomalies=0,
            )
            policy = RecoveryPolicy.for_tier(tier)
            self.tier_manager.apply(tier, "governance_gate_failed")
            metrics.log(
                event_type="governance_gate_failed",
                payload={"failures": failures, "recovery_tier": tier.value, "recovery_policy": policy.__dict__},
                level="ERROR",
            )
            self.state["mutation_enabled"] = False
            self.state["governance_gate_failed"] = failures
            self.state["recovery_tier"] = tier.value
            if policy.fail_close and tier in {RecoveryTierLevel.GOVERNANCE, RecoveryTierLevel.CRITICAL}:
                self._fail(f"recovery_tier_{tier.value}")
            return False

        metrics.log(event_type="governance_gate_passed", payload={}, level="INFO")
        return True

    def _check_constitution_version(self) -> tuple[bool, str]:
        if not CONSTITUTION_VERSION:
            return False, "missing_constitution_version"
        expected = os.getenv("ADAAD_CONSTITUTION_VERSION", "").strip()
        if not expected:
            expected = self._load_constitution_doc_version() or CONSTITUTION_VERSION
        if expected != CONSTITUTION_VERSION:
            return False, f"constitution_version_mismatch:{CONSTITUTION_VERSION}!={expected}"
        return True, "ok"

    def _check_platform_resources(self) -> tuple[bool, str]:
        snapshot = self.resource_monitor.snapshot()
        prune_result = self.storage_manager.check_and_prune()
        metrics.log(
            event_type="platform_resource_snapshot",
            payload={
                "battery_percent": snapshot.battery_percent,
                "memory_mb": round(snapshot.memory_mb, 2),
                "storage_mb": round(snapshot.storage_mb, 2),
                "cpu_percent": round(snapshot.cpu_percent, 2),
                "prune": prune_result,
            },
            level="INFO",
        )
        if snapshot.is_constrained():
            return False, "resource_constrained"
        return True, "ok"

    def _load_constitution_doc_version(self) -> str:
        doc_path = APP_ROOT.parent / "docs" / "CONSTITUTION.md"
        if not doc_path.exists():
            return ""
        try:
            content = doc_path.read_text(encoding="utf-8")
        except Exception:
            return ""
        match = re.search(r"Framework v([0-9]+\.[0-9]+\.[0-9]+)", content)
        if match:
            return match.group(1)
        match = re.search(r"Version\s*[:]\s*([0-9]+\.[0-9]+\.[0-9]+)", content)
        if match:
            return match.group(1)
        return ""

    def _check_key_rotation_status(self) -> tuple[bool, str]:
        keys_dir = cryovant.KEYS_DIR
        if not keys_dir.exists():
            return False, "keys_dir_missing"
        key_files = [path for path in keys_dir.iterdir() if path.is_file() and path.name != ".gitkeep"]
        if not key_files:
            if cryovant.dev_signature_allowed("cryovant-dev-probe"):
                return True, "dev_signature_mode"
            return False, "no_signing_keys"
        max_age_raw = os.getenv("ADAAD_KEY_ROTATION_MAX_AGE_DAYS", "90")
        try:
            max_age_days = int(max_age_raw)
        except ValueError:
            return False, "invalid_key_rotation_max_age_days"
        newest_mtime = max(path.stat().st_mtime for path in key_files)
        age_days = (default_provider().now_utc().timestamp() - newest_mtime) / 86400
        if age_days > max_age_days:
            return False, f"keys_stale:{age_days:.1f}d>{max_age_days}d"
        return True, "ok"

    def _check_ledger_integrity(self) -> tuple[bool, str]:
        self.snapshot_manager.create_snapshot(journal.JOURNAL_PATH)
        self.snapshot_manager.create_snapshot(self.evolution_runtime.ledger.ledger_path)
        try:
            journal.verify_journal_integrity(recovery_hook=self.recovery_hook)
        except JournalIntegrityError as exc:
            return False, str(exc)
        except Exception as exc:
            return False, f"journal_unreadable:{exc}"

        try:
            self.evolution_runtime.ledger.verify_integrity(recovery_hook=self.recovery_hook)
        except LineageIntegrityError as exc:
            return False, str(exc)
        except Exception as exc:
            return False, f"lineage_unreadable:{exc}"
        return True, "ok"

    def _check_mutation_engine_health(self) -> tuple[bool, str]:
        try:
            self.mutation_engine._load_history()
        except Exception as exc:  # pragma: no cover - defensive
            return False, f"mutation_engine_history_error:{exc}"
        metrics_path = metrics.METRICS_PATH
        if metrics_path.exists() and not os.access(metrics_path, os.R_OK | os.W_OK):
            return False, "metrics_unwritable"
        return True, "ok"

    def _check_warm_pool_ready(self) -> tuple[bool, str]:
        if not self.warm_pool._started:
            return False, "warm_pool_not_started"
        if not self.warm_pool._ready_event.is_set():
            return False, "warm_pool_not_ready"
        return True, "ok"

    def _check_architect_invariants(self) -> tuple[bool, str]:
        scan = self.architect.scan()
        if not scan.get("valid"):
            return False, "architect_scan_failed"
        return True, "ok"

    def _run_mutation_cycle(self) -> None:
        """Delegate to module-level run_mutation_cycle for testability."""
        run_mutation_cycle(self)

    def _run_mutation_cycle_impl(self) -> None:
        """
        Execute one mutation cycle (CEL or legacy).
        """
        from runtime.api import is_cel_enabled
        if is_cel_enabled():
            from runtime.api import EvolutionLoop, CodebaseContext
            self._v("Triggering 16-step Constitutional Evolution Loop (CEL)")

            
            # Phase 107: CEL routing bridged to Orchestrator
            loop = EvolutionLoop(api_key=os.getenv("ADAAD_ANTHROPIC_API_KEY", "test"))
            ctx = CodebaseContext(
                file_summaries={}, # Discovery handled inside CEL if empty
                recent_failures=[],
                current_epoch_id=self.evolution_runtime.current_epoch_id,
            )
            
            cel_result = loop.run_epoch(ctx)
            
            self._v(f"CEL sequence complete (epoch_id={cel_result.epoch_id})")
            journal.write_entry(
                agent_id="system",
                action="cel_epoch_complete",
                payload={
                    "epoch_id": self.evolution_runtime.current_epoch_id,
                    "mutations_attempted": cel_result.total_candidates,
                    "mutations_succeeded": len(cel_result.top_mutation_ids),
                    "accepted_count": cel_result.accepted_count,
                }
            )
            return

        if self.evolution_runtime.fail_closed:
            metrics.log(event_type="mutation_cycle_blocked", payload={"reason": "replay_fail_closed", "epoch_id": self.evolution_runtime.current_epoch_id}, level="ERROR")
            return
        hook_before = self.evolution_runtime.before_mutation_cycle()
        active_epoch_id = hook_before.get("epoch_id")
        epoch_meta = {"epoch_id": active_epoch_id, "epoch_start_ts": self.evolution_runtime.epoch_start_ts, "epoch_mutation_count": self.evolution_runtime.epoch_mutation_count}
        proposals = self.architect.propose_mutations()
        for proposal in proposals:
            proposal.epoch_id = active_epoch_id
        if not proposals:
            metrics.log(event_type="mutation_cycle_skipped", payload={"reason": "no proposals", "epoch_id": active_epoch_id}, level="INFO")
            return
        self.mutation_engine.refresh_state_from_metrics()
        selected, scores = self.mutation_engine.select(proposals)
        metrics.log(event_type="mutation_strategy_scores", payload={"scores": scores, **epoch_meta}, level="INFO")
        if not selected:
            metrics.log(event_type="mutation_cycle_skipped", payload={"reason": "no selection", "epoch_id": active_epoch_id}, level="INFO")
            return
        forced_tier = get_forced_tier()
        tier = forced_tier or determine_tier(selected.agent_id)
        if forced_tier is not None:
            metrics.log(
                event_type="mutation_tier_override",
                payload={"agent_id": selected.agent_id, "tier": tier.name},
                level="INFO",
            )
        platform_snapshot = self.resource_monitor.snapshot()
        eval_wall_start = time.monotonic()
        eval_cpu_start = time.process_time()
        envelope_state = {
            "epoch_id": active_epoch_id,
            "epoch_entropy_bits": int(getattr(self.evolution_runtime, "epoch_cumulative_entropy_bits", 0) or 0),
            "observed_entropy_bits": 0,
            "platform_telemetry": {
                "battery_percent": round(platform_snapshot.battery_percent, 4),
                "memory_mb": round(platform_snapshot.memory_mb, 4),
                "storage_mb": round(platform_snapshot.storage_mb, 4),
                "cpu_percent": round(platform_snapshot.cpu_percent, 4),
            },
            # Pre-evaluation snapshot for headroom checks: resource_bounds validates
            # platform capacity here, while post-evaluation timing is logged separately.
            "resource_measurements": {
                "wall_seconds": 0.0,
                "cpu_seconds": 0.0,
                "peak_rss_mb": round(platform_snapshot.memory_mb, 4),
            },
        }
        constitutional_verdict = evaluate_mutation(selected, tier, envelope_state=envelope_state)
        eval_wall_elapsed = max(0.0, time.monotonic() - eval_wall_start)
        eval_cpu_elapsed = max(0.0, time.process_time() - eval_cpu_start)
        metrics.log(
            event_type="constitutional_evaluation_resource_measurements",
            payload={
                "epoch_id": active_epoch_id,
                "agent_id": selected.agent_id,
                "wall_seconds": round(eval_wall_elapsed, 6),
                "cpu_seconds": round(eval_cpu_elapsed, 6),
                "peak_rss_mb": round(platform_snapshot.memory_mb, 4),
            },
            level="INFO",
        )
        if not constitutional_verdict.get("passed"):
            entropy_budget_verdict = next(
                (
                    item
                    for item in constitutional_verdict.get("verdicts", [])
                    if isinstance(item, dict) and item.get("rule") == "entropy_budget_limit"
                ),
                {},
            )
            entropy_details = entropy_budget_verdict.get("details") if isinstance(entropy_budget_verdict, dict) else {}
            entropy_details = entropy_details if isinstance(entropy_details, dict) else {}
            if isinstance(entropy_details.get("details"), dict):
                entropy_details = dict(entropy_details["details"])
            if "entropy_budget_limit" in constitutional_verdict.get("blocking_failures", []):
                metrics.log(
                    event_type="mutation_rejected_entropy",
                    payload={
                        "agent_id": selected.agent_id,
                        "epoch_id": active_epoch_id,
                        "rule": "entropy_budget_limit",
                        "reason": entropy_details.get("reason") or entropy_budget_verdict.get("reason", "entropy_budget_limit"),
                        "max_mutation_entropy_bits": entropy_details.get("max_mutation_entropy_bits"),
                        "epoch_entropy_bits": entropy_details.get("epoch_entropy_bits"),
                        "constitutional_verdict": constitutional_verdict,
                        "evidence": {
                            "rule": "entropy_budget_limit",
                            "details": entropy_details,
                            "blocking_failures": constitutional_verdict.get("blocking_failures", []),
                        },
                    },
                    level="ERROR",
                )
            metrics.log(
                event_type="mutation_rejected_constitutional",
                payload={**constitutional_verdict, "epoch_id": active_epoch_id, "decision": "rejected", "evidence": constitutional_verdict},
                level="ERROR",
            )
            journal.write_entry(
                agent_id=selected.agent_id,
                action="mutation_rejected_constitutional",
                payload={**constitutional_verdict, "epoch_id": active_epoch_id, "decision": "rejected", "evidence": constitutional_verdict},
            )
            if self.dry_run:
                bias = self.mutation_engine.bias_details(selected)
                metrics.log(
                    event_type="mutation_dry_run",
                    payload={
                        "agent_id": selected.agent_id,
                        "strategy_id": selected.intent or "default",
                        "tier": tier.name,
                        "constitution_version": constitutional_verdict.get("constitution_version"),
                        "constitutional_verdict": constitutional_verdict,
                        "bias": bias,
                        "fitness_score": None,
                        "status": "rejected",
                    },
                    level="WARN",
                )
                journal.write_entry(
                    agent_id=selected.agent_id,
                    action="mutation_dry_run",
                    payload={
                        "epoch_id": active_epoch_id,
                        "strategy_id": selected.intent or "default",
                        "tier": tier.name,
                        "constitutional_verdict": constitutional_verdict,
                        "bias": bias,
                        "fitness_score": None,
                        "status": "rejected",
                        "ts": now_iso(),
                    },
                )
            return
        metrics.log(
            event_type="mutation_approved_constitutional",
            payload={
                "agent_id": selected.agent_id,
                **epoch_meta,
                "tier": tier.name,
                "constitution_version": constitutional_verdict.get("constitution_version"),
                "warnings": constitutional_verdict.get("warnings", []),
            },
            level="INFO",
        )
        if self.dry_run:
            fitness_score = self._simulate_fitness_score(selected)
            bias = self.mutation_engine.bias_details(selected)
            metrics.log(
                event_type="mutation_dry_run",
                payload={
                    "agent_id": selected.agent_id,
                    "epoch_id": active_epoch_id,
                    "strategy_id": selected.intent or "default",
                    "tier": tier.name,
                    "constitution_version": constitutional_verdict.get("constitution_version"),
                    "constitutional_verdict": constitutional_verdict,
                    "bias": bias,
                    "fitness_score": fitness_score,
                    "status": "approved",
                },
                level="INFO",
            )
            journal.write_entry(
                agent_id=selected.agent_id,
                action="mutation_dry_run",
                payload={
                    "epoch_id": active_epoch_id,
                    "strategy_id": selected.intent or "default",
                    "tier": tier.name,
                    "constitutional_verdict": constitutional_verdict,
                    "bias": bias,
                    "fitness_score": fitness_score,
                    "status": "approved",
                    "ts": now_iso(),
                },
            )
            return

        result = self.executor.execute(selected)
        journal.write_entry(
            agent_id=selected.agent_id,
            action="mutation_cycle",
            payload={
                "result": result,
                "constitutional_verdict": constitutional_verdict,
                "epoch_id": active_epoch_id,
                "epoch_start_ts": self.evolution_runtime.epoch_start_ts,
                "epoch_mutation_count": self.evolution_runtime.epoch_mutation_count,
                "replay": result.get("evolution", {}).get("replay", {}),
                "ts": now_iso(),
            },
        )

    def _register_capabilities(self) -> None:
        registrations = [
            ("orchestrator.boot", "0.65.0", "Earth"),
            ("cryovant.gate", "0.65.0", "Water"),
            ("architect.scan", "0.65.0", "Wood"),
            ("dream.cycle", "0.65.0", "Fire"),
            ("beast.evaluate", "0.65.0", "Fire"),
            ("ui.dashboard", "0.65.0", "Metal"),
        ]
        for capability_name, capability_version, owner in registrations:
            identity = generate_tool_manifest(__name__, capability_name, capability_version)
            register_capability(capability_name, capability_version, 1.0, owner, identity=identity)

    def _init_ui(self) -> None:
        if self.exit_after_boot or self.state.get("verify_only"):
            return
        if self.dashboard is None:
            self.dashboard = _build_aponi_dashboard()
        self.dashboard.start(self.state)

    def _simulate_fitness_score(self, request: MutationRequest) -> float:
        agent_dir = agent_path_from_id(request.agent_id, self.agents_root)
        dna_path = agent_dir / "dna.json"
        dna = {}
        if dna_path.exists():
            dna = json.loads(dna_path.read_text(encoding="utf-8"))
        simulated = json.loads(json.dumps(dna))
        if request.targets:
            for target in request.targets:
                if target.path == "dna.json":
                    dispatch("mutation.apply_ops", simulated, target.ops)
        else:
            dispatch("mutation.apply_ops", simulated, request.ops)
        payload = {
            "parent": dna.get("lineage") or "dry_run",
            "intent": request.intent,
            "content": simulated,
        }
        return score_mutation_enhanced(request.agent_id, payload)


# ---------------------------------------------------------------------------
# Module-level delegation functions
# ---------------------------------------------------------------------------
# These thin wrappers expose Orchestrator._run_replay_preflight and
# Orchestrator._run_mutation_cycle as patchable module-level names so that
# characterization tests and external callers can monkeypatch them without
# needing to reach into instance methods.

def run_replay_preflight(
    orchestrator: "Orchestrator",
    dump_func: Any,
    *,
    verify_only: bool = False,
) -> Dict[str, Any]:
    """Module-level delegation target for Orchestrator._run_replay_preflight.

    Exposed as a patchable name so characterization tests and external callers
    can monkeypatch behaviour without subclassing Orchestrator.
    """
    return orchestrator._run_replay_preflight_impl(dump_func, verify_only=verify_only)


def run_mutation_cycle(orchestrator: "Orchestrator") -> None:
    """Module-level delegation target for Orchestrator._run_mutation_cycle."""
    orchestrator._run_mutation_cycle_impl()


def _read_adaad_version() -> str:
    """Backward-compatible shim for tests and callers expecting legacy helper names."""
    return read_adaad_version(APP_ROOT.parent)


def _governance_ci_mode_enabled() -> bool:
    """Backward-compatible shim for tests and callers expecting legacy helper names."""
    return governance_ci_mode_enabled()


def _apply_governance_ci_mode_defaults() -> None:
    """Backward-compatible shim for tests and callers expecting legacy helper names."""
    apply_governance_ci_mode_defaults()


def main() -> None:
    parser = build_main_parser()
    args = parser.parse_args()

    if handle_replay_namespace(parser=parser, args=args):
        return

    dry_run_env = dry_run_env_enabled(os.environ)
    try:
        replay_mode = resolve_replay_mode(args.replay)
    except ValueError as exc:
        parser.error(str(exc))

    if governance_ci_mode_enabled():
        apply_governance_ci_mode_defaults()

    selected_epoch = select_epoch(args.epoch, args.replay_epoch)
    if args.epoch and args.replay_epoch and args.epoch.strip() != args.replay_epoch.strip():
        logging.warning("Both --epoch (%s) and --replay-epoch (%s) were provided; using --epoch.", args.epoch, args.replay_epoch)

    facade_state = FacadeRuntimeState(dry_run_env=dry_run_env, selected_epoch=selected_epoch)

    if handle_export_replay_proof(
        parser=parser,
        export_replay_proof=args.export_replay_proof,
        selected_epoch=facade_state.selected_epoch,
    ):
        return

    if handle_status_report(
        adaad_status=args.adaad_status,
        trigger_mode=args.trigger_mode,
        status_format=args.status_format,
    ):
        return
    if handle_runbook_composer(
        adaad_runbook=args.adaad_runbook,
        trigger_mode=args.trigger_mode,
        runbook_verbosity=args.runbook_verbosity,
        runbook_output_dir=args.runbook_output_dir,
    ):
        return

    from adaad.orchestrator.cli_handlers import handle_explain_gates
    if handle_explain_gates(explain_gates=args.explain_gates):
        return

    init_state = build_init_state(
        args=args,
        dry_run_env=facade_state.dry_run_env,
        replay_mode=replay_mode,
        selected_epoch=facade_state.selected_epoch,
    )
    orchestrator = build_orchestrator(init_state)
    if init_state.verify_replay:
        orchestrator.verify_replay_only()
        return
    orchestrator.boot()


if __name__ == "__main__":
    main()
