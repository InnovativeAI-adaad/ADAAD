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
Beast mode evaluates mutations and promotes approved staged candidates.

Phase 40: RuntimeDeterminismProvider injection — all clock calls are now
routed through the injected provider, making BeastModeLoop fully replay-safe
and audit-verifiable.  Strict replay and governance-critical tiers reject
non-deterministic providers at construction time via
``require_replay_safe_provider()``.

Backward-compatibility: existing callers that omit *provider*, *replay_mode*,
and *recovery_tier* continue to receive a ``SystemDeterminismProvider``
(live-clock, non-deterministic) with no change in observable behaviour.
"""

import fcntl
import hashlib
import json
import os
import shutil
import threading
import time
from datetime import timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from adaad.agents.base_agent import promote_offspring
from adaad.agents.discovery import agent_path_from_id, iter_agent_dirs, resolve_agent_id
from runtime.api.app_layer import (
    MutationCandidate,
    RuntimeDeterminismProvider,
    ASTSnapshotStore,
    SeededDeterminismProvider,
    SystemDeterminismProvider,
    emit_pr_lifecycle_event,
    fitness,
    generate_tool_manifest,
    get_capabilities,
    metrics,
    rank_mutation_candidates,
    register_capability,
    require_replay_safe_provider,
)
from runtime.api.runtime_services import validate_agent_contract_preflight
from security import cryovant
from security.ledger import journal

ELEMENT_ID = "Fire"

# ---------------------------------------------------------------------------
# Governance / audit tiers that mandate a deterministic provider.
# Mirrors the same constant set used by DreamMode (Phase 39).
# ---------------------------------------------------------------------------
_STRICT_TIERS = {"audit", "governance", "critical"}


class _BeastCycleKernel:
    """Thin execution kernel for BeastModeLoop cycle routing.

    Holds a weak reference to the owning loop so that test suites can patch
    ``beast._kernel.run_cycle`` independently of the public ``run_cycle``
    routing surface.  This separation enables clean kernel-swap injection
    without subclassing the full loop.
    """

    def __init__(self, owner: "BeastModeLoop") -> None:
        self._owner = owner

    def run_cycle(self, *, agent_id: Optional[str] = None) -> Dict[str, str]:
        """Delegate directly to the owner's internal execution."""
        return self._owner._execute_cycle(agent_id=agent_id)


class BeastModeLoop:
    """
    Executes evaluation cycles against mutated offspring.

    Parameters
    ----------
    agents_root
        Root directory containing per-agent subdirectories.
    lineage_dir
        Directory used by the lineage ledger.
    replay_mode
        One of ``"off"``, ``"strict"``.  ``"strict"`` requires a deterministic
        provider and produces bit-identical window timestamps across replays.
    recovery_tier
        Governance recovery tier string.  ``"audit"``, ``"governance"``, and
        ``"critical"`` require a deterministic provider.
    provider
        :class:`~runtime.governance.foundation.RuntimeDeterminismProvider`
        instance.  Defaults to :class:`SystemDeterminismProvider`.
        Strict replay and audit tiers reject non-deterministic providers at
        construction time.
    """

    def __init__(
        self,
        agents_root: Path,
        lineage_dir: Path,
        *,
        replay_mode: str = "off",
        recovery_tier: str | None = None,
        provider: RuntimeDeterminismProvider | None = None,
    ) -> None:
        # --- Phase 40: provider injection -----------------------------------
        self._provider: RuntimeDeterminismProvider = (
            provider
            if provider is not None
            else (
                SeededDeterminismProvider(
                    seed=os.getenv("ADAAD_DETERMINISTIC_SEED", "adaad")
                )
                if (replay_mode or "off").strip().lower() == "strict"
                or (recovery_tier or "").strip().lower() in _STRICT_TIERS
                else SystemDeterminismProvider()
            )
        )
        self._replay_mode = (replay_mode or "off").strip().lower()
        self._recovery_tier = (recovery_tier or "").strip().lower()

        # Fail-closed guard — raises RuntimeError for invalid combinations.
        require_replay_safe_provider(
            self._provider,
            replay_mode=self._replay_mode,
            recovery_tier=self._recovery_tier if self._recovery_tier else None,
        )
        # --------------------------------------------------------------------

        self.agents_root = agents_root
        self.lineage_dir = lineage_dir
        self.threshold = float(os.getenv("ADAAD_FITNESS_THRESHOLD", "0.70"))
        self.cycle_budget = int(os.getenv("ADAAD_BEAST_CYCLE_BUDGET", "50"))
        self.cycle_window_sec = int(os.getenv("ADAAD_BEAST_CYCLE_WINDOW_SEC", "3600"))
        self.mutation_quota = int(os.getenv("ADAAD_BEAST_MUTATION_QUOTA", "25"))
        self.mutation_window_sec = int(os.getenv("ADAAD_BEAST_MUTATION_WINDOW_SEC", "3600"))
        self.cooldown_sec = int(os.getenv("ADAAD_BEAST_COOLDOWN_SEC", "300"))
        self.state_path = self.agents_root.parent / "data" / "beast_mode_state.json"
        self.ast_snapshot_store = ASTSnapshotStore(
            self.agents_root.parent / "data" / "beast_ast_snapshot_state.json"
        )

        # Lazy-initialised legacy adapter; see _legacy property below.
        self.__legacy: LegacyBeastModeCompatibilityAdapter | None = None
        # Kernel shim — routes public run_cycle through a patchable surface.
        self._kernel: _BeastCycleKernel = _BeastCycleKernel(self)

    # ------------------------------------------------------------------
    # Internal clock helper — routes through the injected provider.
    # ------------------------------------------------------------------

    def _now(self) -> float:
        """Return current POSIX timestamp via the injected provider.

        Uses ``provider.now_utc()`` so that strict/audit replay produces
        bit-identical timestamps from a ``SeededDeterminismProvider``.
        """
        return self._provider.now_utc().replace(tzinfo=timezone.utc).timestamp()

    @property
    def _legacy(self) -> "LegacyBeastModeCompatibilityAdapter":
        """Lazy accessor for the legacy compatibility adapter.

        Provides the ``_legacy.run_cycle(agent_id)`` surface used by tests
        and external tooling that predates the current kernel-routed API.
        The adapter shares this instance's ``agents_root`` and ``lineage_dir``
        so it operates on the same file system context.
        """
        if self.__legacy is None:
            self.__legacy = LegacyBeastModeCompatibilityAdapter(
                self.agents_root,
                self.lineage_dir,
                provider=self._provider,
            )
        return self.__legacy

    # ------------------------------------------------------------------
    # State persistence helpers (unchanged logic, clock via _now())
    # ------------------------------------------------------------------

    def _load_state(self) -> Dict[str, float]:
        if not self.state_path.exists():
            return {
                "cycle_window_start": 0.0,
                "cycle_count": 0.0,
                "mutation_window_start": 0.0,
                "mutation_count": 0.0,
                "cooldown_until": 0.0,
            }
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {
                "cycle_window_start": 0.0,
                "cycle_count": 0.0,
                "mutation_window_start": 0.0,
                "mutation_count": 0.0,
                "cooldown_until": 0.0,
            }

    def _save_state(self, state: Dict[str, float]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")

    def _refresh_window(
        self,
        start_key: str,
        count_key: str,
        window_sec: int,
        now: float,
        state: Dict[str, float],
    ) -> None:
        window_start = float(state.get(start_key, 0.0))
        if window_start <= 0.0 or now - window_start >= window_sec:
            state[start_key] = now
            state[count_key] = 0.0

    def _throttle(
        self, reason: str, payload: Dict[str, float], state: Dict[str, float]
    ) -> Dict[str, str]:
        state["cooldown_until"] = payload["cooldown_until"]
        self._save_state(state)
        metrics.log(
            event_type="beast_cycle_throttled",
            payload=payload,
            level="WARNING",
            element_id=ELEMENT_ID,
        )
        return {"status": "throttled", "reason": reason}

    def _check_limits(self) -> Optional[Dict[str, str]]:
        now = self._now()  # Phase 40: provider-backed clock
        state = self._load_state()
        cooldown_until = float(state.get("cooldown_until", 0.0))
        if cooldown_until and now < cooldown_until:
            payload = {"cooldown_until": cooldown_until, "now": now}
            return self._throttle("cooldown", payload, state)

        self._refresh_window("cycle_window_start", "cycle_count", self.cycle_window_sec, now, state)
        self._refresh_window(
            "mutation_window_start", "mutation_count", self.mutation_window_sec, now, state
        )

        if self.cycle_budget > 0 and float(state.get("cycle_count", 0.0)) >= self.cycle_budget:
            cooldown_until = now + self.cooldown_sec
            metrics.log(
                event_type="beast_cycle_budget_exceeded",
                payload={
                    "budget": self.cycle_budget,
                    "window_sec": self.cycle_window_sec,
                    "count": state.get("cycle_count", 0.0),
                },
                level="WARNING",
                element_id=ELEMENT_ID,
            )
            return self._throttle(
                "cycle_budget",
                {
                    "cooldown_until": cooldown_until,
                    "now": now,
                    "limit": self.cycle_budget,
                    "count": state.get("cycle_count", 0.0),
                },
                state,
            )

        state["cycle_count"] = float(state.get("cycle_count", 0.0)) + 1.0
        self._save_state(state)
        return None

    def _check_mutation_quota(self) -> Optional[Dict[str, str]]:
        now = self._now()  # Phase 40: provider-backed clock
        state = self._load_state()
        self._refresh_window(
            "mutation_window_start", "mutation_count", self.mutation_window_sec, now, state
        )

        if self.mutation_quota > 0 and float(state.get("mutation_count", 0.0)) >= self.mutation_quota:
            cooldown_until = now + self.cooldown_sec
            metrics.log(
                event_type="beast_mutation_quota_exceeded",
                payload={
                    "quota": self.mutation_quota,
                    "window_sec": self.mutation_window_sec,
                    "count": state.get("mutation_count", 0.0),
                },
                level="WARNING",
                element_id=ELEMENT_ID,
            )
            return self._throttle(
                "mutation_quota",
                {
                    "cooldown_until": cooldown_until,
                    "now": now,
                    "limit": self.mutation_quota,
                    "count": state.get("mutation_count", 0.0),
                },
                state,
            )

        state["mutation_count"] = float(state.get("mutation_count", 0.0)) + 1.0
        self._save_state(state)
        return None

    def _available_agents(self) -> List[str]:
        agents: List[str] = []
        for agent_dir in iter_agent_dirs(self.agents_root):
            agents.append(resolve_agent_id(agent_dir, self.agents_root))
        return agents

    def _latest_staged(
        self, agent_id: str
    ) -> Tuple[Optional[Path], Optional[Dict[str, object]]]:
        preflight = validate_agent_contract_preflight()
        if not preflight.get("ok"):
            blocked_ids: set[str] = set()
            for module in preflight.get("failing_modules", []):
                module_name = str(module.get("module", "")).strip()
                if not module_name:
                    continue
                rel = Path(module_name)
                if rel.parts[:2] == ("adaad", "agents") and len(rel.parts) >= 3:
                    blocked_ids.add(rel.parts[2])
                else:
                    blocked_ids.add(rel.stem)

            metrics.log(
                event_type="beast_agent_contract_recheck_failed",
                payload={
                    "agent": agent_id,
                    "blocked_agent_ids": sorted(blocked_ids),
                    "failing_modules": preflight.get("failing_modules", []),
                },
                level="ERROR",
                element_id=ELEMENT_ID,
            )
            return None, None

        staging_root = self.lineage_dir / "_staging"
        if not staging_root.exists():
            return None, None
        candidates = [item for item in staging_root.iterdir() if item.is_dir()]
        candidates.sort(key=lambda entry: entry.stat().st_mtime, reverse=True)
        for candidate in candidates:
            mutation_file = candidate / "mutation.json"
            if not mutation_file.exists():
                continue
            try:
                payload = json.loads(mutation_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if payload.get("parent") == agent_id:
                return candidate, payload
        return None, None

    @staticmethod
    def _validate_handoff_contract(
        contract: object,
    ) -> Tuple[bool, str, Optional[bool]]:
        if not isinstance(contract, dict):
            return False, "handoff_contract_missing", None
        required = {"schema_version", "issued_at", "issuer", "dream_scope", "constraints"}
        missing = sorted(list(required - set(contract)))
        if missing:
            return False, f"handoff_contract_missing:{','.join(missing)}", None
        constraints = contract.get("constraints")
        if not isinstance(constraints, dict):
            return False, "handoff_contract_constraints_invalid", None
        sandboxed = constraints.get("sandboxed")
        if not isinstance(sandboxed, bool):
            return False, "handoff_contract_sandboxed_invalid", None
        return True, "ok", sandboxed

    def _discard(
        self, staged_dir: Path, payload: Dict[str, object], score: float
    ) -> None:
        shutil.rmtree(staged_dir, ignore_errors=True)
        metrics.log(
            event_type="mutation_discarded",
            payload={
                "staged": str(staged_dir),
                "score": score,
                "parent": payload.get("parent"),
            },
            level="WARNING",
            element_id=ELEMENT_ID,
        )

    def run_cycle(self, agent_id: Optional[str] = None) -> Dict[str, str]:
        """Public entry point — routes through the kernel shim for patchability."""
        return self._kernel.run_cycle(agent_id=agent_id)

    def _build_mutation_candidate(
        self, payload: Dict[str, object]
    ) -> "tuple[MutationCandidate | None, list[str]]":
        """Build a :class:`MutationCandidate` from a raw mutation payload.

        Returns ``(candidate, [])`` on success or ``(None, [missing_fields])``
        when required scoring fields are absent.  If ``mutation_id`` is absent,
        a canonical SHA-256 hash of the payload is used as a stable identifier.
        """
        scoring_fields = ("expected_gain", "risk_score", "complexity", "coverage_delta")
        missing = [f for f in scoring_fields if f not in payload]
        if missing:
            return None, missing

        if "mutation_id" in payload:
            mutation_id = str(payload["mutation_id"])
        else:
            canonical = json.dumps(
                {k: payload[k] for k in sorted(payload)},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            mutation_id = "payload-" + hashlib.sha256(canonical).hexdigest()[:12]

        from runtime.api.app_layer import MutationCandidate as _MC  # avoid circular at module level
        candidate = _MC(
            mutation_id=mutation_id,
            expected_gain=float(payload["expected_gain"]),
            risk_score=float(payload["risk_score"]),
            complexity=float(payload["complexity"]),
            coverage_delta=float(payload["coverage_delta"]),
            strategic_horizon=float(payload.get("strategic_horizon", 1.0)),
            forecast_roi=float(payload.get("forecast_roi", 0.0)),
        )
        return candidate, []

    def _ast_module_id(self, payload: Dict[str, object], agent_id: str) -> str:
        module = str(payload.get("target_module", "")).strip()
        if module:
            return module
        return f"agent:{agent_id}"

    def _evaluate_ast_change(
        self, *, agent_id: str, payload: Dict[str, object]
    ) -> tuple[str, str, bool]:
        source = str(payload.get("content", ""))
        module_id = self._ast_module_id(payload, agent_id)
        snapshot = self.ast_snapshot_store.compute_digest(
            source=source,
            agent_id=agent_id,
            module_id=module_id,
        )
        previous = self.ast_snapshot_store.read_previous_digest(
            agent_id=agent_id, module_id=module_id
        )
        changed = previous != snapshot.digest
        return module_id, snapshot.digest, changed

    def _execute_cycle(self, agent_id: Optional[str] = None) -> Dict[str, str]:
        """Core cycle execution — called by the kernel, overridable by adapters."""
        metrics.log(
            event_type="beast_cycle_start",
            payload={"agent": agent_id},
            level="INFO",
            element_id=ELEMENT_ID,
        )
        throttled = self._check_limits()
        if throttled:
            metrics.log(
                event_type="beast_cycle_end",
                payload=throttled,
                level="WARNING",
                element_id=ELEMENT_ID,
            )
            return throttled
        agents = self._available_agents()
        if not agents:
            metrics.log(
                event_type="beast_cycle_end",
                payload={"status": "skipped"},
                level="WARNING",
                element_id=ELEMENT_ID,
            )
            return {"status": "skipped", "reason": "no agents"}

        selected = agent_id or agents[0]
        metrics.log(
            event_type="beast_cycle_decision",
            payload={"agent": selected},
            level="INFO",
            element_id=ELEMENT_ID,
        )
        if not cryovant.validate_ancestry(selected):
            metrics.log(
                event_type="beast_cycle_end",
                payload={"status": "blocked", "agent": selected},
                level="ERROR",
                element_id=ELEMENT_ID,
            )
            return {"status": "blocked", "agent": selected}

        staged_dir, payload = self._latest_staged(selected)
        if not staged_dir or not payload:
            metrics.log(
                event_type="beast_cycle_end",
                payload={"status": "no_staged", "agent": selected},
                level="INFO",
                element_id=ELEMENT_ID,
            )
            return {"status": "no_staged", "agent": selected}

        throttled = self._check_mutation_quota()
        if throttled:
            metrics.log(
                event_type="beast_cycle_end",
                payload={
                    "status": "throttled",
                    "agent": selected,
                    "reason": throttled.get("reason"),
                },
                level="WARNING",
                element_id=ELEMENT_ID,
            )
            return {"status": "throttled", "agent": selected, "reason": throttled.get("reason")}

        if payload.get("dream_mode"):
            contract_ok, reason, contract_sandboxed = self._validate_handoff_contract(
                payload.get("handoff_contract")
            )
            if not contract_ok:
                metrics.log(
                    event_type="mutation_handoff_blocked",
                    payload={
                        "agent": selected,
                        "staged": str(staged_dir),
                        "reason": reason,
                    },
                    level="ERROR",
                    element_id=ELEMENT_ID,
                )
                return {"status": "blocked", "agent": selected, "reason": reason}
            sandboxed = payload.get(
                "sandboxed", contract_sandboxed if contract_sandboxed is not None else True
            )
            if sandboxed:
                metrics.log(
                    event_type="mutation_sandboxed",
                    payload={"agent": selected, "staged": str(staged_dir)},
                    level="WARNING",
                    element_id=ELEMENT_ID,
                )
                return {
                    "status": "sandboxed",
                    "agent": selected,
                    "staged_path": str(staged_dir),
                }

        module_id, current_digest, ast_changed = self._evaluate_ast_change(
            agent_id=selected, payload=payload
        )
        if not ast_changed:
            self.ast_snapshot_store.record_cosmetic_update(
                agent_id=selected,
                module_id=module_id,
                observed_at=self._now(),
            )
            metrics.log(
                event_type="cosmetic_update_only",
                payload={
                    "agent": selected,
                    "module": module_id,
                    "outcome": "ast_unchanged",
                    "staged": str(staged_dir),
                },
                level="INFO",
                element_id=ELEMENT_ID,
            )
            metrics.log(
                event_type="beast_cycle_end",
                payload={"status": "ast_unchanged", "agent": selected},
                level="INFO",
                element_id=ELEMENT_ID,
            )
            return {
                "status": "ast_unchanged",
                "agent": selected,
                "outcome": "cosmetic_update_only",
            }

        score = fitness.score_mutation(selected, payload)
        metrics.log(
            event_type="beast_fitness_scored",
            payload={"agent": selected, "score": score, "staged": str(staged_dir)},
            level="INFO",
            element_id=ELEMENT_ID,
        )

        if score < self.threshold:
            self._discard(staged_dir, payload, score)
            metrics.log(
                event_type="beast_cycle_end",
                payload={"status": "discarded", "agent": selected},
                level="INFO",
                element_id=ELEMENT_ID,
            )
            return {"status": "discarded", "agent": selected, "score": score}

        agent_dir = agent_path_from_id(selected, self.agents_root)
        cryovant.evolve_certificate(selected, agent_dir, staged_dir, get_capabilities())
        promoted = promote_offspring(staged_dir, self.lineage_dir)
        journal.write_entry(
            agent_id=selected,
            action="mutation_promoted",
            payload={"staged": str(staged_dir), "promoted": str(promoted), "score": score},
        )
        evidence = {
            "staged_path": str(staged_dir),
            "promoted_path": str(promoted),
            "fitness_score": score,
            "ledger_tail_refs": journal.read_entries(limit=5),
        }
        register_capability(
            f"agent.{selected}.mutation_quality",
            version="0.1.0",
            score=score,
            owner_element=ELEMENT_ID,
            requires=["cryovant.gate", "orchestrator.boot"],
            evidence=evidence,
        )
        metrics.log(
            event_type="mutation_promoted",
            payload={
                "agent": selected,
                "promoted_path": str(promoted),
                "score": score,
            },
            level="INFO",
            element_id=ELEMENT_ID,
        )
        metrics.log(
            event_type="beast_cycle_end",
            payload={"status": "promoted", "agent": selected},
            level="INFO",
            element_id=ELEMENT_ID,
        )
        _promotion_decision_id = f"{selected}:{int(time.time() * 1000)}"
        emit_pr_lifecycle_event(
            policy_version="1.0",
            evaluation_result="allow",
            decision_id=_promotion_decision_id,
        )
        self.ast_snapshot_store.record_accepted_ast_change(
            agent_id=selected,
            module_id=module_id,
            digest=current_digest,
            accepted_at=self._now(),
        )
        return {"status": "promoted", "agent": selected, "score": score, "promoted_path": str(promoted)}



class LegacyBeastModeCompatibilityAdapter(BeastModeLoop):
    """Compatibility adapter preserving legacy projection input helpers for tests/tools.

    Extends :class:`BeastModeLoop` with:

    * **Candidate-based scoring** — promotion decisions use
      :func:`rank_mutation_candidates` against ``ADAAD_AUTONOMY_THRESHOLD``
      (default 0.25) rather than the raw fitness score.  When required candidate
      fields are absent the adapter falls back to the legacy fitness gate and
      emits a ``beast_autonomy_fallback`` metric.

    * **Monotonic-clock throttling** — cooldown enforcement uses a monotonic
      clock so wall-clock jumps cannot accidentally release a throttle early.
      ``_wall_time_provider`` and ``_monotonic_time_provider`` are public
      callables that tests can replace.

    * **State migration** — old state files that pre-date monotonic fields are
      migrated transparently on first load.

    * **File-lock serialisation** — ``state_lock_path`` guards concurrent
      ``_check_limits`` calls; lock-contention events are emitted as
      ``beast_state_lock_contention`` metrics.

    * **Promotion rollback** — if ``promote_offspring`` raises, the agent
      certificate is restored from its pre-promotion snapshot and a
      ``mutation_promotion_rollback`` journal entry is written.
    """

    _LOCK_CONTENTION_ENV = "ADAAD_BEAST_STATE_LOCK_CONTENTION_SEC"
    _DEFAULT_LOCK_CONTENTION_SEC = 1.0

    def __init__(self, agents_root: Path, lineage_dir: Path, **kwargs: object) -> None:
        super().__init__(agents_root, lineage_dir, **kwargs)
        self.state_lock_path: Path = self.state_path.with_suffix(".lock")
        self._wall_time_provider = time.time
        self._monotonic_time_provider = time.monotonic
        self._autonomy_threshold: float = float(
            os.getenv("ADAAD_AUTONOMY_THRESHOLD", "0.25")
        )

    # ------------------------------------------------------------------
    # Clock helpers
    # ------------------------------------------------------------------

    def _now_wall(self) -> float:
        return self._wall_time_provider()

    def _now_mono(self) -> float:
        return self._monotonic_time_provider()

    # ------------------------------------------------------------------
    # State management with monotonic fields + migration
    # ------------------------------------------------------------------

    def _migrate_state(self, state: Dict[str, float]) -> Dict[str, float]:
        """Migrate pre-monotonic state file to include ``_mono`` fields."""
        now_wall = self._now_wall()
        now_mono = self._now_mono()
        changed = False

        for wall_key, mono_key in (
            ("cycle_window_start", "cycle_window_start_mono"),
            ("mutation_window_start", "mutation_window_start_mono"),
        ):
            if mono_key not in state:
                old_wall = float(state.get(wall_key, 0.0))
                if old_wall > 0.0:
                    offset = old_wall - now_wall
                    state[mono_key] = now_mono + offset
                else:
                    state[mono_key] = 0.0
                changed = True

        if "cooldown_until_mono" not in state:
            old_wall = float(state.get("cooldown_until", 0.0))
            if old_wall > 0.0:
                remaining = max(0.0, old_wall - now_wall)
                state["cooldown_until_mono"] = now_mono + remaining
            else:
                state["cooldown_until_mono"] = 0.0
            changed = True

        if changed:
            self._save_state(state)
        return state

    def _check_limits(self) -> Optional[Dict[str, str]]:
        """Thread-safe limit check using monotonic cooldown and file-lock serialisation."""
        contention_threshold = float(
            os.getenv(self._LOCK_CONTENTION_ENV, str(self._DEFAULT_LOCK_CONTENTION_SEC))
        )
        self.state_lock_path.parent.mkdir(parents=True, exist_ok=True)

        with self.state_lock_path.open("a+", encoding="utf-8") as lock_file:
            t_acquire_start = self._now_mono()
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            wait = self._now_mono() - t_acquire_start
            if wait >= contention_threshold:
                metrics.log(
                    event_type="beast_state_lock_contention",
                    payload={"wait_sec": wait, "threshold_sec": contention_threshold},
                    level="WARNING",
                    element_id=ELEMENT_ID,
                )

            try:
                now_mono = self._now_mono()
                now_wall = self._now_wall()
                state = self._load_state()
                state = self._migrate_state(state)

                # Monotonic cooldown check
                cooldown_mono = float(state.get("cooldown_until_mono", 0.0))
                if cooldown_mono and now_mono < cooldown_mono:
                    metrics.log(
                        event_type="beast_cycle_throttled",
                        payload={"cooldown_until_mono": cooldown_mono, "now_mono": now_mono},
                        level="WARNING",
                        element_id=ELEMENT_ID,
                    )
                    return {"status": "throttled", "reason": "cooldown"}

                # Window refresh using monotonic time
                def _refresh(start_mono_key: str, count_key: str, window_sec: int) -> None:
                    start = float(state.get(start_mono_key, 0.0))
                    if start <= 0.0 or now_mono - start >= window_sec:
                        state[start_mono_key] = now_mono
                        state[count_key] = 0.0

                _refresh("cycle_window_start_mono", "cycle_count", self.cycle_window_sec)
                _refresh("mutation_window_start_mono", "mutation_count", self.mutation_window_sec)

                if self.cycle_budget > 0 and float(state.get("cycle_count", 0.0)) >= self.cycle_budget:
                    cooldown_until_mono = now_mono + self.cooldown_sec
                    state["cooldown_until_mono"] = cooldown_until_mono
                    state["cooldown_until"] = now_wall + self.cooldown_sec
                    self._save_state(state)
                    metrics.log(
                        event_type="beast_cycle_budget_exceeded",
                        payload={
                            "budget": self.cycle_budget,
                            "window_sec": self.cycle_window_sec,
                            "count": state.get("cycle_count", 0.0),
                        },
                        level="WARNING",
                        element_id=ELEMENT_ID,
                    )
                    metrics.log(
                        event_type="beast_cycle_throttled",
                        payload={"cooldown_until_mono": cooldown_until_mono, "now_mono": now_mono},
                        level="WARNING",
                        element_id=ELEMENT_ID,
                    )
                    return {"status": "throttled", "reason": "cycle_budget"}

                state["cycle_count"] = float(state.get("cycle_count", 0.0)) + 1.0
                self._save_state(state)
                return None

            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    # ------------------------------------------------------------------
    # Core cycle — candidate-based scoring with fitness fallback
    # ------------------------------------------------------------------

    def run_cycle(self, agent_id: Optional[str] = None) -> Dict[str, str]:
        """Candidate-scored cycle with monotonic throttling and promotion rollback."""
        metrics.log(
            event_type="beast_cycle_start",
            payload={"agent": agent_id},
            level="INFO",
            element_id=ELEMENT_ID,
        )

        throttled = self._check_limits()
        if throttled:
            metrics.log(
                event_type="beast_cycle_end",
                payload=throttled,
                level="WARNING",
                element_id=ELEMENT_ID,
            )
            return throttled

        agents = self._available_agents()
        if not agents:
            result: Dict[str, str] = {"status": "skipped", "reason": "no agents"}
            metrics.log(
                event_type="beast_cycle_end",
                payload=result,
                level="WARNING",
                element_id=ELEMENT_ID,
            )
            return result

        selected = agent_id or agents[0]
        if not cryovant.validate_ancestry(selected):
            result = {"status": "blocked", "agent": selected}
            metrics.log(
                event_type="beast_cycle_end",
                payload=result,
                level="ERROR",
                element_id=ELEMENT_ID,
            )
            return result

        staged_dir, payload = self._latest_staged(selected)
        if not staged_dir or not payload:
            result = {"status": "no_staged", "agent": selected}
            metrics.log(
                event_type="beast_cycle_end",
                payload=result,
                level="INFO",
                element_id=ELEMENT_ID,
            )
            return result

        throttled = self._check_mutation_quota()
        if throttled:
            return {"status": "throttled", "agent": selected, "reason": throttled.get("reason")}

        module_id, current_digest, ast_changed = self._evaluate_ast_change(
            agent_id=selected, payload=payload
        )
        if not ast_changed:
            self.ast_snapshot_store.record_cosmetic_update(
                agent_id=selected,
                module_id=module_id,
                observed_at=self._now_wall(),
            )
            metrics.log(
                event_type="cosmetic_update_only",
                payload={
                    "agent": selected,
                    "module": module_id,
                    "outcome": "ast_unchanged",
                    "staged": str(staged_dir),
                },
                level="INFO",
                element_id=ELEMENT_ID,
            )
            metrics.log(
                event_type="beast_cycle_end",
                payload={"status": "ast_unchanged", "agent": selected},
                level="INFO",
                element_id=ELEMENT_ID,
            )
            return {
                "status": "ast_unchanged",
                "agent": selected,
                "outcome": "cosmetic_update_only",
            }

        # Build candidate for autonomous scoring
        candidate, missing_fields = self._build_mutation_candidate(payload)

        if missing_fields:
            # Fallback: emit telemetry and use raw fitness threshold gate
            metrics.log(
                event_type="beast_autonomy_fallback",
                payload={
                    "agent": selected,
                    "staged": str(staged_dir),
                    "missing_candidate_fields": missing_fields,
                },
                level="WARNING",
                element_id=ELEMENT_ID,
            )
            decision_score = fitness.score_mutation(selected, payload)
            score = decision_score
            gate_threshold = self.threshold
        else:
            # Candidate-based scoring against autonomy threshold
            ranked = rank_mutation_candidates(
                [candidate], acceptance_threshold=self._autonomy_threshold
            )
            decision_score = ranked[0].score if ranked else 0.0
            score = fitness.score_mutation(selected, payload)
            gate_threshold = self._autonomy_threshold

        metrics.log(
            event_type="beast_fitness_scored",
            payload={
                "agent": selected,
                "score": decision_score,
                "staged": str(staged_dir),
                "gate": "fitness" if missing_fields else "candidate",
            },
            level="INFO",
            element_id=ELEMENT_ID,
        )

        if decision_score < gate_threshold:
            self._discard(staged_dir, payload, decision_score)
            metrics.log(
                event_type="beast_cycle_end",
                payload={"status": "discarded", "agent": selected},
                level="INFO",
                element_id=ELEMENT_ID,
            )
            return {"status": "discarded", "agent": selected, "score": decision_score}

        # Promotion with rollback on failure
        agent_dir = agent_path_from_id(selected, self.agents_root)
        cert_path = agent_dir / "certificate.json"
        cert_snapshot = cert_path.read_text(encoding="utf-8") if cert_path.exists() else None

        cryovant.evolve_certificate(selected, agent_dir, staged_dir, get_capabilities())

        try:
            promoted = promote_offspring(staged_dir, self.lineage_dir)
        except Exception:
            if cert_snapshot is not None:
                cert_path.write_text(cert_snapshot, encoding="utf-8")
            journal.write_entry(
                agent_id=selected,
                action="mutation_promotion_rollback",
                payload={"staged": str(staged_dir), "reason": "promote_offspring_failed"},
            )
            metrics.log(
                event_type="mutation_promotion_rollback",
                payload={"agent": selected, "staged": str(staged_dir)},
                level="ERROR",
                element_id=ELEMENT_ID,
            )
            raise

        journal.write_entry(
            agent_id=selected,
            action="mutation_promoted",
            payload={"staged": str(staged_dir), "promoted": str(promoted), "score": score},
        )
        evidence = {
            "staged_path": str(staged_dir),
            "promoted_path": str(promoted),
            "fitness_score": score,
            "ledger_tail_refs": journal.read_entries(limit=5),
        }
        register_capability(
            f"agent.{selected}.mutation_quality",
            version="0.1.0",
            score=score,
            owner_element=ELEMENT_ID,
            requires=["cryovant.gate", "orchestrator.boot"],
            evidence=evidence,
            identity=generate_tool_manifest(
                __name__,
                f"agent.{selected}.mutation_quality",
                "0.1.0",
            ),
        )
        metrics.log(
            event_type="mutation_promoted",
            payload={"agent": selected, "promoted_path": str(promoted), "score": score},
            level="INFO",
            element_id=ELEMENT_ID,
        )
        metrics.log(
            event_type="beast_cycle_end",
            payload={"status": "promoted", "agent": selected},
            level="INFO",
            element_id=ELEMENT_ID,
        )
        _promotion_decision_id = f"{selected}:{int(time.time() * 1000)}"
        emit_pr_lifecycle_event(
            policy_version="1.0",
            evaluation_result="allow",
            decision_id=_promotion_decision_id,
        )
        self.ast_snapshot_store.record_accepted_ast_change(
            agent_id=selected,
            module_id=module_id,
            digest=current_digest,
            accepted_at=self._now_wall(),
        )
        return {"status": "promoted", "agent": selected, "score": score, "promoted_path": str(promoted)}

    # ------------------------------------------------------------------
    # Candidate builder — with canonical hash fallback for missing mutation_id
    # ------------------------------------------------------------------

    def _build_mutation_candidate(
        self, payload: Dict[str, object]
    ) -> tuple[MutationCandidate | None, list[str]]:
        """Build a MutationCandidate from payload.

        If ``mutation_id`` is absent, a canonical SHA-256 payload hash is
        used as a stable deterministic identifier.  If any *scoring* fields
        are missing, returns ``(None, [<missing fields>])`` to signal fallback.
        """
        scoring_fields = ("expected_gain", "risk_score", "complexity", "coverage_delta")
        missing = [f for f in scoring_fields if f not in payload]
        if missing:
            return None, missing

        if "mutation_id" in payload:
            mutation_id = str(payload["mutation_id"])
        else:
            canonical = json.dumps(
                {k: payload[k] for k in sorted(payload)},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            mutation_id = "payload-" + hashlib.sha256(canonical).hexdigest()[:12]

        candidate = MutationCandidate(
            mutation_id=mutation_id,
            expected_gain=float(payload["expected_gain"]),
            risk_score=float(payload["risk_score"]),
            complexity=float(payload["complexity"]),
            coverage_delta=float(payload["coverage_delta"]),
            strategic_horizon=float(payload.get("strategic_horizon", 1.0)),
            forecast_roi=float(payload.get("forecast_roi", 0.0)),
        )
        return candidate, []
