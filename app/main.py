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

import argparse
import json
import os
import re
import sys
import time
from typing import Any, Dict, Optional

from app import APP_ROOT
from app.architect_agent import ArchitectAgent
from app.agents.mutation_engine import MutationEngine
from app.agents.mutation_request import MutationRequest
from app.beast_mode_loop import BeastModeLoop
from app.dream_mode import DreamMode
from app.mutation_executor import MutationExecutor
from runtime.evolution import EvolutionRuntime
from runtime.evolution.replay_mode import ReplayMode, normalize_replay_mode
from runtime.evolution.lineage_v2 import LineageIntegrityError
from runtime.recovery.ledger_guardian import AutoRecoveryHook, SnapshotManager
from runtime.recovery.tier_manager import RecoveryPolicy, RecoveryTierLevel, TierManager
from runtime.platform.android_monitor import AndroidMonitor
from runtime.platform.storage_manager import StorageManager
from runtime import metrics
from runtime.capability_graph import register_capability
from runtime.element_registry import dump, register
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
from runtime.invariants import verify_all
from app.agents.discovery import agent_path_from_id, iter_agent_dirs, resolve_agent_id
from runtime.constitution import CONSTITUTION_VERSION, determine_tier, evaluate_mutation, get_forced_tier
from runtime.fitness_v2 import score_mutation_enhanced
from runtime.timeutils import now_iso
from runtime.warm_pool import WarmPool
from runtime.tools.mutation_guard import _apply_ops
from security import cryovant
from security.gatekeeper_protocol import run_gatekeeper
from security.ledger import journal
from security.ledger.journal import JournalIntegrityError
from ui.aponi_dashboard import AponiDashboard


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
        verbose: bool = False,
    ) -> None:
        self.state: Dict[str, Any] = {"status": "initializing", "mutation_enabled": False}
        self.agents_root = APP_ROOT / "agents"
        self.lineage_dir = self.agents_root / "lineage"
        self.warm_pool = WarmPool(size=2)
        self.architect = ArchitectAgent(self.agents_root)
        self.dream: Optional[DreamMode] = None
        self.beast: Optional[BeastModeLoop] = None
        self.dashboard = AponiDashboard()
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
        self.replay_mode = normalize_replay_mode(replay_mode)
        self.replay_epoch = replay_epoch.strip()
        self.evolution_runtime.set_replay_mode(self.replay_mode)

    def _v(self, message: str) -> None:
        if not self.verbose:
            return
        home = os.getenv("HOME", "")
        safe_message = message.replace(home, "~") if home else message
        print(f"[ADAAD] {safe_message}")

    def _fail(self, reason: str) -> None:
        metrics.log(event_type="orchestrator_error", payload={"reason": reason}, level="ERROR")
        self.state["status"] = "error"
        self.state["reason"] = reason
        try:
            journal.ensure_ledger()
            journal.write_entry(agent_id="system", action="orchestrator_failed", payload={"reason": reason})
        except Exception:
            pass
        try:
            dump()
        except Exception as exc:
            try:
                metrics.log(
                    event_type="orchestrator_dump_failed",
                    payload={"error": str(exc)},
                    level="ERROR",
                )
            except Exception:
                sys.stderr.write(f"orchestrator_dump_failed:{exc}\n")
        sys.exit(1)

    def boot(self) -> None:
        self._v(f"Replay mode normalized: {self.replay_mode.value}")
        if self.dry_run and self.replay_mode == ReplayMode.STRICT:
            self._v("Warning: dry-run + strict replay may not reflect production execution semantics.")
        self._v("Starting governance spine initialization")
        metrics.log(event_type="orchestrator_start", payload={}, level="INFO")
        gate = run_gatekeeper()
        if not gate.get("ok"):
            self._fail(f"gatekeeper_failed:{','.join(gate.get('missing', []))}")
        self._v("Gatekeeper preflight passed")
        self._register_elements()
        self._init_runtime()
        self._v("Runtime invariants passed")
        self._init_cryovant()
        self._v("Cryovant validation passed")
        epoch_state = self.evolution_runtime.boot()
        self.state["epoch"] = epoch_state
        self._v("Replay baseline initialized")
        self.dream = DreamMode(
            self.agents_root,
            self.lineage_dir,
            replay_mode=self.replay_mode.value,
            recovery_tier=self.evolution_runtime.governor.recovery_tier.value,
        )
        self.beast = BeastModeLoop(self.agents_root, self.lineage_dir)
        # Health-First Mode: run architect/dream/beast checks and safe-boot gating
        # before any mutation cycle to enforce boot invariants.
        self._health_check_architect()
        self._health_check_dream()
        self._health_check_beast()
        self._run_replay_preflight()
        self._v(f"Replay decision: {self.state.get('replay_decision')}")
        self._v(f"Fail-closed state: {self.evolution_runtime.fail_closed}")
        self._v(f"Replay aggregate score: {self.state.get('replay_score')}")
        if self.state.get("mutation_enabled"):
            if self.evolution_runtime.fail_closed:
                self.state["replay_divergence"] = True
                journal.write_entry(agent_id="system", action="mutation_blocked_fail_closed", payload={"epoch_id": self.evolution_runtime.current_epoch_id, "ts": now_iso()})
            elif self._governance_gate():
                self._run_mutation_cycle()
        self._v(f"Mutation cycle status: {'enabled' if self.state.get('mutation_enabled') else 'disabled'}")
        self._register_capabilities()
        self._v("Capability registration complete")
        self._init_ui()
        self._v("Aponi dashboard started")
        self.state["status"] = "ready"
        self._v("Boot sequence complete (status=ready)")
        metrics.log(event_type="orchestrator_ready", payload=self.state, level="INFO")
        journal.write_entry(agent_id="system", action="orchestrator_ready", payload=self.state)
        dump()

    def _run_replay_preflight(self, *, verify_only: bool = False) -> Dict[str, Any]:
        mode = self.replay_mode
        preflight = self.evolution_runtime.replay_preflight(mode, epoch_id=self.replay_epoch or None)
        has_divergence = bool(preflight.get("has_divergence"))
        self.state["replay_mode"] = mode.value
        self.state["replay_target"] = preflight.get("verify_target")
        self.state["replay_decision"] = preflight.get("decision")
        self.state["replay_results"] = preflight.get("results", [])
        self.state["replay_divergence"] = has_divergence
        self.state["status"] = "replay_warning" if has_divergence else "replay_verified"
        replay_score = self._aggregate_replay_score(preflight.get("results", []))
        self.state["replay_score"] = replay_score
        outcome = {
            "mode": mode.value,
            "verify_only": verify_only,
            "ok": not has_divergence,
            "decision": preflight.get("decision"),
            "target": preflight.get("verify_target"),
            "divergence": has_divergence,
            "results": preflight.get("results", []),
            "replay_score": replay_score,
            "ts": now_iso(),
        }
        journal.write_entry(agent_id="system", action="replay_verified", payload=outcome)
        try:
            manifest_path = self.write_replay_manifest(outcome)
            self._v(f"Replay manifest written: {manifest_path}")
        except Exception as exc:
            metrics.log(
                event_type="replay_manifest_write_failed",
                payload={"error": str(exc), "mode": outcome["mode"], "target": outcome.get("target")},
                level="WARN",
            )
        if has_divergence and mode.fail_closed:
            self._fail("replay_divergence")
        self._v("Replay Summary:")
        self._v(f"  Mode: {mode.value}")
        self._v(f"  Target: {preflight.get('verify_target')}")
        self._v(f"  Divergence: {has_divergence}")
        self._v(f"  Score: {replay_score}")
        if verify_only:
            dump()
            return {"verify_only": True, **outcome}
        return {"verify_only": False, **outcome}

    @staticmethod
    def _aggregate_replay_score(results: list[Dict[str, Any]]) -> float:
        if not results:
            return 1.0
        scores = [float(result.get("replay_score", 0.0)) for result in results]
        return round(sum(scores) / len(scores), 4)


    def write_replay_manifest(self, outcome: Dict[str, Any]) -> os.PathLike[str]:
        manifests_dir = APP_ROOT.parent / "security" / "replay_manifests"
        manifests_dir.mkdir(parents=True, exist_ok=True)

        def _sanitize_component(value: Any) -> str:
            normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "unknown")).strip("-._")
            return normalized or "unknown"

        mode_component = _sanitize_component(outcome.get("mode"))
        target_component = _sanitize_component(outcome.get("target"))
        timestamp_component = _sanitize_component(outcome.get("ts"))
        manifest_path = manifests_dir / f"{mode_component}__{target_component}__{timestamp_component}.json"
        manifest_path.write_text(json.dumps(outcome, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return manifest_path

    def verify_replay_only(self) -> None:
        self._v("Running replay verification-only mode")
        metrics.log(event_type="orchestrator_start", payload={"verify_only": True}, level="INFO")
        gate = run_gatekeeper()
        if not gate.get("ok"):
            self._fail(f"gatekeeper_failed:{','.join(gate.get('missing', []))}")
        self._register_elements()
        self._init_runtime()
        self._init_cryovant()
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
        ok, failures = verify_all()
        if not ok:
            self._fail(f"invariants_failed:{','.join(failures)}")

    def _init_cryovant(self) -> None:
        if not cryovant.validate_environment():
            self._fail("cryovant_environment")
        certified, errors = cryovant.certify_agents(self.agents_root)
        if not certified:
            self._fail(f"cryovant_certification:{','.join(errors)}")

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
        match = re.search(r"Framework v([0-9]+\\.[0-9]+\\.[0-9]+)", content)
        if match:
            return match.group(1)
        match = re.search(r"Version\\s*[:]\\s*([0-9]+\\.[0-9]+\\.[0-9]+)", content)
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
        max_age_days = int(os.getenv("ADAAD_KEY_ROTATION_MAX_AGE_DAYS", "90"))
        newest_mtime = max(path.stat().st_mtime for path in key_files)
        age_days = (time.time() - newest_mtime) / 86400
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
        """
        Execute one architect → mutation engine → executor cycle.
        """
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
        constitutional_verdict = evaluate_mutation(selected, tier)
        if not constitutional_verdict.get("passed"):
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
        register_capability("orchestrator.boot", "0.65.0", 1.0, "Earth")
        register_capability("cryovant.gate", "0.65.0", 1.0, "Water")
        register_capability("architect.scan", "0.65.0", 1.0, "Wood")
        register_capability("dream.cycle", "0.65.0", 1.0, "Fire")
        register_capability("beast.evaluate", "0.65.0", 1.0, "Fire")
        register_capability("ui.dashboard", "0.65.0", 1.0, "Metal")

    def _init_ui(self) -> None:
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
                    _apply_ops(simulated, target.ops)
        else:
            _apply_ops(simulated, request.ops)
        payload = {
            "parent": dna.get("lineage") or "dry_run",
            "intent": request.intent,
            "content": simulated,
        }
        return score_mutation_enhanced(request.agent_id, payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="ADAAD orchestrator")
    parser.add_argument("--verbose", action="store_true", help="Print boot stage diagnostics to stdout.")
    parser.add_argument("--dry-run", action="store_true", help="Evaluate mutations without applying them.")
    parser.add_argument(
        "--replay",
        default="off",
        help=(
            "Replay mode: off (skip replay), audit (verify and continue), strict (verify and fail-close). "
            "Legacy aliases: full->audit, true->audit, false->off."
        ),
    )
    parser.add_argument("--replay-epoch", default="", help="Replay a specific epoch id as the verification target.")
    parser.add_argument("--verify-replay", action="store_true", help="Run replay verification and exit after reporting result.")
    args = parser.parse_args()

    dry_run_env = os.getenv("ADAAD_DRY_RUN", "").lower() in {"1", "true", "yes", "on"}
    try:
        replay_mode = normalize_replay_mode(args.replay)
    except ValueError as exc:
        parser.error(str(exc))

    orchestrator = Orchestrator(
        dry_run=args.dry_run or dry_run_env,
        replay_mode=replay_mode,
        replay_epoch=args.replay_epoch,
        verbose=args.verbose,
    )
    if args.verify_replay:
        orchestrator.verify_replay_only()
        return
    orchestrator.boot()


if __name__ == "__main__":
    main()
