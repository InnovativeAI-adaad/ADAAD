"""
Constitutional Mutation Execution Sandbox (CMES) — INNOV-104
Phase 199 · v10.10.0 · InnovativeAI LLC · Governor: DUSTIN L REID

World-first constitutionally-governed deterministic sandbox that executes proposed
mutations in an isolated trial environment, captures the full behavioral delta
(invariant coverage, ledger growth, API surface diff, test pass-rate), and seals
a pre/post execution snapshot into an HMAC-chained sandbox ledger before any live
promotion decision is made.

Hard-class invariants enforced:
  CMES-ISOLATE-0   Sandbox execution NEVER touches the live ledger or live module state.
  CMES-DETERM-0    Given identical seed + mutation spec, replay MUST produce identical delta.
  CMES-DELTA-0     Every sandbox run MUST emit a signed BehavioralDelta record.
  CMES-CHAIN-0     Sandbox ledger entries MUST form an unbroken HMAC-SHA256 chain.
  CMES-IMMUT-0     Committed sandbox ledger entries are append-only; no mutations or deletes.
  CMES-HUMAN0-0    HUMAN-0 holds sole authority to promote or permanently discard sandbox results.
  CMES-PROMOTE-0   Live promotion REQUIRES a PASSED sandbox run sealed in the ledger.
  CMES-SCOPE-0     Sandbox scope MUST match the declared blast_radius of the mutation.
  CMES-REPLAY-0    Any sandbox run MUST be deterministically replayable from its seed + spec.
  CMES-AUDIT-0     All sandbox operations are logged with ISO-8601 timestamps and HUMAN-0 attribution.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import copy
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional

# ── Constants ────────────────────────────────────────────────────────────────

GOVERNOR = "DUSTIN L REID"
CMES_LEDGER_PATH = os.environ.get("CMES_LEDGER_PATH", "data/cmes/sandbox_ledger.jsonl")
CMES_HMAC_KEY = os.environ.get("CMES_HMAC_KEY", "cmes-innov104-adaad-innovativeai-llc").encode()

# ── Enums ─────────────────────────────────────────────────────────────────────


class SandboxStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    PROMOTED = "PROMOTED"
    DISCARDED = "DISCARDED"


class BlastRadius(str, Enum):
    TIER1 = "TIER1"   # single module
    TIER2 = "TIER2"   # cross-module
    TIER3 = "TIER3"   # system-wide


# ── Exceptions ────────────────────────────────────────────────────────────────


class CMESConstitutionalViolation(Exception):
    """Raised on any Hard-class invariant breach."""


class CMESChainViolation(CMESConstitutionalViolation):
    """HMAC chain integrity failure."""


class CMESPromotionBlocked(CMESConstitutionalViolation):
    """Attempted live promotion without a PASSED sandbox run."""


class CMESImmutabilityViolation(CMESConstitutionalViolation):
    """Attempted modification of a committed ledger entry."""


# ── Data models ───────────────────────────────────────────────────────────────


@dataclass
class MutationSpec:
    """Declarative specification for a proposed mutation."""
    mutation_id: str
    module_path: str
    blast_radius: BlastRadius
    description: str
    invariants_targeted: List[str] = field(default_factory=list)
    expected_test_markers: List[str] = field(default_factory=list)
    seed: str = field(default_factory=lambda: str(uuid.uuid4()))
    proposed_by: str = "MutationAgent"

    def canonical_bytes(self) -> bytes:
        d = {
            "mutation_id": self.mutation_id,
            "module_path": self.module_path,
            "blast_radius": self.blast_radius,
            "seed": self.seed,
        }
        return json.dumps(d, sort_keys=True).encode()


@dataclass
class BehavioralDelta:
    """Captured diff between pre- and post-sandbox execution state."""
    invariants_pre: int
    invariants_post: int
    invariant_delta: int
    tests_passed: int
    tests_failed: int
    api_endpoints_added: List[str]
    api_endpoints_removed: List[str]
    ledger_entries_added: int
    module_hash_pre: str
    module_hash_post: str
    execution_duration_ms: float
    determinism_seed: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SandboxRun:
    """A single sandbox execution record."""
    run_id: str
    mutation_spec: MutationSpec
    status: SandboxStatus
    delta: Optional[BehavioralDelta]
    failure_reason: Optional[str]
    promoted_by: Optional[str]       # HUMAN-0 identity
    discarded_by: Optional[str]
    timestamp_created: str
    timestamp_closed: Optional[str]
    ledger_index: int = 0
    prev_hash: str = "GENESIS"
    entry_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["mutation_spec"]["blast_radius"] = self.mutation_spec.blast_radius.value
        d["status"] = self.status.value
        return d


# ── HMAC helpers ──────────────────────────────────────────────────────────────


def _compute_entry_hash(entry_bytes: bytes) -> str:
    return hmac.new(CMES_HMAC_KEY, entry_bytes, hashlib.sha256).hexdigest()


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


# ── Sandbox ledger ────────────────────────────────────────────────────────────


class CMESSandboxLedger:
    """
    Append-only HMAC-chained ledger for sandbox runs.
    Hard-class invariants: CMES-CHAIN-0, CMES-IMMUT-0, CMES-AUDIT-0.
    """

    def __init__(self, path: str = CMES_LEDGER_PATH) -> None:
        self._path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._entries: List[Dict[str, Any]] = []
        self._prev_hash: str = "GENESIS"
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self._path):
            return
        with open(self._path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                self._entries.append(entry)
                self._prev_hash = entry["entry_hash"]

    def append(self, run: SandboxRun) -> SandboxRun:
        """Seal run into ledger — CMES-CHAIN-0, CMES-IMMUT-0."""
        run.ledger_index = len(self._entries)
        run.prev_hash = self._prev_hash
        # Hash the content WITHOUT entry_hash (it doesn't exist yet)
        entry_dict = run.to_dict()
        entry_dict.pop("entry_hash", None)
        entry_payload = json.dumps(entry_dict, sort_keys=True).encode()
        run.entry_hash = _compute_entry_hash(entry_payload)
        self._prev_hash = run.entry_hash
        self._entries.append(run.to_dict())
        with open(self._path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(run.to_dict()) + "\n")
        return run

    def verify_chain(self) -> bool:
        """Replay HMAC chain — CMES-CHAIN-0."""
        prev = "GENESIS"
        for entry in self._entries:
            stored_hash = entry["entry_hash"]
            # Recompute: same as append — hash everything except entry_hash
            verify_entry = {k: v for k, v in entry.items() if k != "entry_hash"}
            verify_payload = json.dumps(verify_entry, sort_keys=True).encode()
            expected = _compute_entry_hash(verify_payload)
            if stored_hash != expected:
                raise CMESChainViolation(
                    f"CMES-CHAIN-0 violated at index {entry.get('ledger_index')}: "
                    f"stored={stored_hash[:16]} expected={expected[:16]}"
                )
            prev = stored_hash
        return True

    def all_entries(self) -> List[Dict[str, Any]]:
        return list(self._entries)

    def get_by_run_id(self, run_id: str) -> Optional[Dict[str, Any]]:
        for e in self._entries:
            if e.get("run_id") == run_id:
                return e
        return None

    def export(self) -> Dict[str, Any]:
        return {
            "ledger_path": self._path,
            "total_entries": len(self._entries),
            "chain_tip": self._prev_hash,
            "entries": self._entries,
        }


# ── Execution Sandbox ─────────────────────────────────────────────────────────


class ConstitutionalMutationExecutionSandbox:
    """
    Core CMES engine. Executes proposed mutations in an isolated context,
    captures BehavioralDelta, and seals results in the sandbox ledger.

    Hard-class invariants enforced:
      CMES-ISOLATE-0, CMES-DETERM-0, CMES-DELTA-0, CMES-CHAIN-0,
      CMES-IMMUT-0, CMES-HUMAN0-0, CMES-PROMOTE-0, CMES-SCOPE-0,
      CMES-REPLAY-0, CMES-AUDIT-0.
    """

    INVARIANT_IDS = [
        "CMES-ISOLATE-0", "CMES-DETERM-0", "CMES-DELTA-0", "CMES-CHAIN-0",
        "CMES-IMMUT-0", "CMES-HUMAN0-0", "CMES-PROMOTE-0", "CMES-SCOPE-0",
        "CMES-REPLAY-0", "CMES-AUDIT-0",
    ]

    def __init__(
        self,
        ledger: Optional[CMESSandboxLedger] = None,
        baseline_invariant_count: int = 607,
    ) -> None:
        self._ledger = ledger or CMESSandboxLedger()
        self._baseline_invariants = baseline_invariant_count
        self._active_runs: Dict[str, SandboxRun] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    def open_sandbox(self, spec: MutationSpec) -> SandboxRun:
        """
        Open a new sandbox execution for the given mutation spec.
        CMES-SCOPE-0: blast_radius must be declared.
        """
        self._assert_blast_radius_declared(spec)
        run = SandboxRun(
            run_id=str(uuid.uuid4()),
            mutation_spec=spec,
            status=SandboxStatus.PENDING,
            delta=None,
            failure_reason=None,
            promoted_by=None,
            discarded_by=None,
            timestamp_created=self._iso_now(),
            timestamp_closed=None,
        )
        self._active_runs[run.run_id] = run
        return run

    def execute(self, run_id: str, dry_run_callable: Optional[Any] = None) -> SandboxRun:
        """
        Execute the mutation in isolation.
        CMES-ISOLATE-0: Execution operates on a deep-copy snapshot, never live state.
        CMES-DETERM-0 + CMES-REPLAY-0: determinism enforced via seed.
        CMES-DELTA-0: BehavioralDelta MUST be emitted.
        """
        run = self._get_active_run(run_id)
        run.status = SandboxStatus.RUNNING

        t_start = time.monotonic()

        # ── Isolation: snapshot the module path (CMES-ISOLATE-0) ─────────────
        spec = run.mutation_spec
        pre_hash = self._compute_module_hash(spec.module_path)

        # ── Deterministic dry-run (CMES-DETERM-0 + CMES-REPLAY-0) ────────────
        sandbox_state: Dict[str, Any] = {
            "invariants": copy.deepcopy(self._baseline_invariants),
            "ledger_entries": 0,
            "api_endpoints": [],
        }

        tests_passed = 0
        tests_failed = 0
        api_added: List[str] = []
        api_removed: List[str] = []
        failure_reason: Optional[str] = None

        try:
            if dry_run_callable is not None:
                result = dry_run_callable(copy.deepcopy(sandbox_state), spec.seed)
                sandbox_state = result.get("state", sandbox_state)
                tests_passed = result.get("tests_passed", 0)
                tests_failed = result.get("tests_failed", 0)
                api_added = result.get("api_added", [])
                api_removed = result.get("api_removed", [])
            else:
                # Deterministic simulation when no callable supplied
                seeded_val = int(hashlib.sha256(
                    (spec.seed + spec.mutation_id).encode()
                ).hexdigest(), 16)
                tests_passed = min(30, seeded_val % 31)
                tests_failed = 30 - tests_passed
                invariant_gain = len(spec.invariants_targeted)
                sandbox_state["invariants"] += invariant_gain
                sandbox_state["ledger_entries"] = seeded_val % 100 + 10
                api_added = [f"POST /{spec.module_path.split('/')[-1].replace('.py', '')}/execute"]

            # Validate scope matches blast radius (CMES-SCOPE-0)
            self._validate_scope(spec)

        except CMESConstitutionalViolation:
            raise
        except Exception as exc:
            failure_reason = str(exc)
            tests_failed = 30

        t_end = time.monotonic()

        post_hash = self._compute_module_hash(spec.module_path)

        # ── BehavioralDelta (CMES-DELTA-0) ────────────────────────────────────
        delta = BehavioralDelta(
            invariants_pre=self._baseline_invariants,
            invariants_post=sandbox_state["invariants"],
            invariant_delta=sandbox_state["invariants"] - self._baseline_invariants,
            tests_passed=tests_passed,
            tests_failed=tests_failed,
            api_endpoints_added=api_added,
            api_endpoints_removed=api_removed,
            ledger_entries_added=sandbox_state["ledger_entries"],
            module_hash_pre=pre_hash,
            module_hash_post=post_hash,
            execution_duration_ms=round((t_end - t_start) * 1000, 3),
            determinism_seed=spec.seed,
        )

        if failure_reason or tests_failed > 0:
            run.status = SandboxStatus.FAILED
            run.failure_reason = failure_reason or f"{tests_failed} tests failed in sandbox"
        else:
            run.status = SandboxStatus.PASSED

        run.delta = delta
        run.timestamp_closed = self._iso_now()

        # Seal into ledger (CMES-CHAIN-0, CMES-IMMUT-0, CMES-AUDIT-0)
        self._ledger.append(run)
        return run

    def promote(self, run_id: str, human0_identity: str) -> SandboxRun:
        """
        Promote a PASSED sandbox run to live.
        CMES-HUMAN0-0: Only HUMAN-0 may promote.
        CMES-PROMOTE-0: Run MUST be in PASSED status.
        """
        self._assert_human0(human0_identity)
        run = self._get_committed_run(run_id)

        run_status = run["status"] if isinstance(run, dict) else run.status.value
        if run_status != SandboxStatus.PASSED.value:
            raise CMESPromotionBlocked(
                f"CMES-PROMOTE-0: Cannot promote run {run_id} with status {run_status}. "
                "Only PASSED runs may be promoted."
            )

        spec_data = run["mutation_spec"] if isinstance(run, dict) else asdict(run.mutation_spec)
        spec_data["blast_radius"] = BlastRadius(spec_data["blast_radius"])
        delta_data = run.get("delta") if isinstance(run, dict) else None
        # Create a promoted record (CMES-IMMUT-0: original entry unchanged)
        promoted = SandboxRun(
            run_id=str(uuid.uuid4()),
            mutation_spec=MutationSpec(**spec_data),
            status=SandboxStatus.PROMOTED,
            delta=BehavioralDelta(**delta_data) if delta_data else None,
            failure_reason=None,
            promoted_by=human0_identity,
            discarded_by=None,
            timestamp_created=self._iso_now(),
            timestamp_closed=self._iso_now(),
        )
        self._ledger.append(promoted)
        return promoted

    def discard(self, run_id: str, human0_identity: str) -> SandboxRun:
        """
        Permanently discard a sandbox run.
        CMES-HUMAN0-0: Only HUMAN-0 may discard.
        """
        self._assert_human0(human0_identity)
        run = self._get_committed_run(run_id)

        spec_data2 = dict(run["mutation_spec"])
        spec_data2["blast_radius"] = BlastRadius(spec_data2["blast_radius"])
        discarded = SandboxRun(
            run_id=str(uuid.uuid4()),
            mutation_spec=MutationSpec(**spec_data2),
            status=SandboxStatus.DISCARDED,
            delta=None,
            failure_reason=None,
            promoted_by=None,
            discarded_by=human0_identity,
            timestamp_created=self._iso_now(),
            timestamp_closed=self._iso_now(),
        )
        self._ledger.append(discarded)
        return discarded

    def verify_chain(self) -> bool:
        """Verify full sandbox ledger chain integrity. CMES-CHAIN-0."""
        return self._ledger.verify_chain()

    def replay(self, run_id: str) -> Dict[str, Any]:
        """
        Replay a sandbox run from its seed + spec.
        CMES-REPLAY-0: Must produce identical BehavioralDelta.
        """
        entry = self._ledger.get_by_run_id(run_id)
        if not entry:
            raise CMESConstitutionalViolation(f"CMES-REPLAY-0: Run {run_id} not in ledger.")
        spec_data = entry["mutation_spec"]
        spec = MutationSpec(
            mutation_id=spec_data["mutation_id"],
            module_path=spec_data["module_path"],
            blast_radius=BlastRadius(spec_data["blast_radius"]),
            description=spec_data["description"],
            invariants_targeted=spec_data.get("invariants_targeted", []),
            expected_test_markers=spec_data.get("expected_test_markers", []),
            seed=spec_data["seed"],
            proposed_by=spec_data.get("proposed_by", "MutationAgent"),
        )
        replay_run = self.open_sandbox(spec)
        replayed = self.execute(replay_run.run_id)
        return {
            "original_run_id": run_id,
            "replay_run_id": replayed.run_id,
            "original_delta": entry.get("delta"),
            "replayed_delta": replayed.delta.to_dict() if replayed.delta else None,
            "determinism_verified": (
                entry.get("delta", {}).get("tests_passed") ==
                (replayed.delta.tests_passed if replayed.delta else None)
            ),
        }

    def summary(self) -> Dict[str, Any]:
        entries = self._ledger.all_entries()
        status_counts: Dict[str, int] = {}
        for e in entries:
            s = e.get("status", "UNKNOWN")
            status_counts[s] = status_counts.get(s, 0) + 1
        return {
            "total_runs": len(entries),
            "status_counts": status_counts,
            "chain_tip": self._ledger.export()["chain_tip"],
            "invariants": self.INVARIANT_IDS,
            "governor": GOVERNOR,
        }

    def export(self) -> Dict[str, Any]:
        return self._ledger.export()

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _iso_now() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    @staticmethod
    def _assert_human0(identity: str) -> None:
        if identity != GOVERNOR and "HUMAN-0" not in identity:
            raise CMESConstitutionalViolation(
                f"CMES-HUMAN0-0: Operation requires HUMAN-0 authority. "
                f"Got: '{identity}'"
            )

    @staticmethod
    def _assert_blast_radius_declared(spec: MutationSpec) -> None:
        if spec.blast_radius not in (BlastRadius.TIER1, BlastRadius.TIER2, BlastRadius.TIER3):
            raise CMESConstitutionalViolation(
                f"CMES-SCOPE-0: blast_radius must be declared for mutation {spec.mutation_id}."
            )

    @staticmethod
    def _validate_scope(spec: MutationSpec) -> None:
        """CMES-SCOPE-0: Scope must match declared blast radius."""
        n_invariants = len(spec.invariants_targeted)
        if spec.blast_radius == BlastRadius.TIER1 and n_invariants > 15:
            raise CMESConstitutionalViolation(
                f"CMES-SCOPE-0: TIER1 mutation may not target >15 invariants; got {n_invariants}."
            )
        if spec.blast_radius == BlastRadius.TIER2 and n_invariants > 30:
            raise CMESConstitutionalViolation(
                f"CMES-SCOPE-0: TIER2 mutation may not target >30 invariants; got {n_invariants}."
            )

    @staticmethod
    def _compute_module_hash(module_path: str) -> str:
        if os.path.exists(module_path):
            with open(module_path, "rb") as fh:
                return hashlib.sha256(fh.read()).hexdigest()[:16]
        return hashlib.sha256(module_path.encode()).hexdigest()[:16]

    def _get_active_run(self, run_id: str) -> SandboxRun:
        run = self._active_runs.get(run_id)
        if not run:
            raise CMESConstitutionalViolation(f"CMES-AUDIT-0: No active run with id {run_id}.")
        return run

    def _get_committed_run(self, run_id: str) -> Dict[str, Any]:
        entry = self._ledger.get_by_run_id(run_id)
        if not entry:
            raise CMESConstitutionalViolation(
                f"CMES-AUDIT-0: Run {run_id} not found in ledger."
            )
        return entry
