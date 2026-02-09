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
import hashlib
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
from runtime import metrics
from runtime.capability_graph import register_capability
from runtime.element_registry import dump, register
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
from ui.aponi_dashboard import AponiDashboard


class Orchestrator:
    """
    Coordinates boot order and health checks.
    """

    def __init__(self, *, dry_run: bool = False) -> None:
        self.state: Dict[str, Any] = {"status": "initializing", "mutation_enabled": False}
        self.agents_root = APP_ROOT / "agents"
        self.lineage_dir = self.agents_root / "lineage"
        self.warm_pool = WarmPool(size=2)
        self.architect = ArchitectAgent(self.agents_root)
        self.dream: Optional[DreamMode] = None
        self.beast: Optional[BeastModeLoop] = None
        self.dashboard = AponiDashboard()
        self.executor = MutationExecutor(self.agents_root)
        self.mutation_engine = MutationEngine(metrics.METRICS_PATH)
        self.dry_run = dry_run

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
        metrics.log(event_type="orchestrator_start", payload={}, level="INFO")
        gate = run_gatekeeper()
        if not gate.get("ok"):
            self._fail(f"gatekeeper_failed:{','.join(gate.get('missing', []))}")
        self._register_elements()
        self._init_runtime()
        self._init_cryovant()
        self.dream = DreamMode(self.agents_root, self.lineage_dir)
        self.beast = BeastModeLoop(self.agents_root, self.lineage_dir)
        # Health-First Mode: run architect/dream/beast checks and safe-boot gating
        # before any mutation cycle to enforce boot invariants.
        self._health_check_architect()
        self._health_check_dream()
        self._health_check_beast()
        if self.state.get("mutation_enabled"):
            if self._governance_gate():
                self._run_mutation_cycle()
        self._register_capabilities()
        self._init_ui()
        self.state["status"] = "ready"
        metrics.log(event_type="orchestrator_ready", payload=self.state, level="INFO")
        journal.write_entry(agent_id="system", action="orchestrator_ready", payload=self.state)
        dump()

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
        failures: list[dict[str, str]] = []

        constitution_ok, constitution_reason = self._check_constitution_version()
        if not constitution_ok:
            failures.append({"check": "constitution_version", "reason": constitution_reason})

        key_ok, key_reason = self._check_key_rotation_status()
        if not key_ok:
            failures.append({"check": "key_rotation", "reason": key_reason})

        ledger_ok, ledger_reason = self._check_ledger_integrity()
        if not ledger_ok:
            failures.append({"check": "ledger_integrity", "reason": ledger_reason})

        mutation_ok, mutation_reason = self._check_mutation_engine_health()
        if not mutation_ok:
            failures.append({"check": "mutation_engine", "reason": mutation_reason})

        warm_ok, warm_reason = self._check_warm_pool_ready()
        if not warm_ok:
            failures.append({"check": "warm_pool", "reason": warm_reason})

        architect_ok, architect_reason = self._check_architect_invariants()
        if not architect_ok:
            failures.append({"check": "architect_invariants", "reason": architect_reason})

        if failures:
            metrics.log(
                event_type="governance_gate_failed",
                payload={"failures": failures},
                level="ERROR",
            )
            self.state["mutation_enabled"] = False
            self.state["governance_gate_failed"] = failures
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
        try:
            journal.ensure_journal()
            journal_path = journal.JOURNAL_PATH
            if not journal_path.exists():
                return False, "journal_missing"
            lines = journal_path.read_text(encoding="utf-8").splitlines()
        except Exception as exc:
            return False, f"journal_unreadable:{exc}"
        prev_hash = "0" * 64
        for index, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                return False, f"journal_invalid_json:line{index}:{exc}"
            entry_prev = str(entry.get("prev_hash") or "")
            entry_hash = str(entry.get("hash") or "")
            if entry_prev != prev_hash:
                return False, f"journal_prev_hash_mismatch:line{index}"
            payload = {key: value for key, value in entry.items() if key != "hash"}
            material = (prev_hash + json.dumps(payload, ensure_ascii=False, sort_keys=True)).encode("utf-8")
            computed = hashlib.sha256(material).hexdigest()
            if computed != entry_hash:
                return False, f"journal_hash_mismatch:line{index}"
            prev_hash = entry_hash
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
        proposals = self.architect.propose_mutations()
        if not proposals:
            metrics.log(event_type="mutation_cycle_skipped", payload={"reason": "no proposals"}, level="INFO")
            return
        self.mutation_engine.refresh_state_from_metrics()
        selected, scores = self.mutation_engine.select(proposals)
        metrics.log(event_type="mutation_strategy_scores", payload={"scores": scores}, level="INFO")
        if not selected:
            metrics.log(event_type="mutation_cycle_skipped", payload={"reason": "no selection"}, level="INFO")
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
                payload=constitutional_verdict,
                level="ERROR",
            )
            journal.write_entry(
                agent_id=selected.agent_id,
                action="mutation_rejected_constitutional",
                payload=constitutional_verdict,
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
    parser.add_argument("--dry-run", action="store_true", help="Evaluate mutations without applying them.")
    args = parser.parse_args()

    dry_run_env = os.getenv("ADAAD_DRY_RUN", "").lower() in {"1", "true", "yes", "on"}
    orchestrator = Orchestrator(dry_run=args.dry_run or dry_run_env)
    orchestrator.boot()


if __name__ == "__main__":
    main()
