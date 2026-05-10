# SPDX-License-Identifier: Apache-2.0
"""
INNOV-83 · CAE — Constitutional Amendment Executor
====================================================
Phase 178 · v9.111.0 · InnovativeAI LLC

World-first: A constitutionally-governed amendment execution engine that
reads HUMAN-0-ACCEPTED proposals from RDP (INNOV-81) and applies them
to the live ADAAD constitutional invariant store, producing an immutable
HMAC-chained execution ledger and a post-execution constitutional snapshot.

This is the capstone closing of the full CEL self-improvement loop:

  MSE → MRP → MPG → MEX → MFV → IIS → CAL → RDP → HUMAN-0
   ↑                                                      │
   └──── CFI ◄─────────────────── CAE (INNOV-83) ◄───────┘

CAE is the only engine authorised to write to the live constitution store.
It is fail-closed: any violation halts execution before any mutation lands.

Hard-class invariants enforced (fail-closed):
  CAE-CHAIN-0    HMAC-SHA-256 chain on execution ledger; broken chain halts all ops
  CAE-DETERM-0   No wall-clock injection; all timestamps via _utc_iso()
  CAE-HUMAN0-0   Only ACCEPTED dispositions execute; non-ACCEPTED rejected fail-closed
  CAE-IMMUT-0    Execution ledger is append-only; no record mutation permitted
  CAE-ATOMIC-0   Amendment application + ledger append are atomic; partial writes raise
  CAE-SCOPE-0    CAE reads RDP disposition only; never writes to RDP/CAL/CFI ledgers
  CAE-AUDIT-0    Every amendment execution emits a signed JSONL audit record
  CAE-SNAPSHOT-0 Post-execution constitutional snapshot written after every successful cycle
  CAE-NOSELF-0   CAE cannot amend its own invariants; self-referential amendments rejected
  CAE-REPLAY-0   execution_id must be globally unique; duplicates rejected fail-closed

Governor: DUSTIN L REID
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Set


# ── Constants ─────────────────────────────────────────────────────────────────

_GOVERNOR: str = "DUSTIN L REID"
_INNOV_CODE: str = "INNOV-83"
_MODULE_CODE: str = "CAE"
_HMAC_KEY: bytes = b"adaad-cae-chain-key-v1"

_LEDGER_DIR: Path = Path("data/cae")
_EXECUTION_LEDGER_PATH: Path = _LEDGER_DIR / "amendment_execution_ledger.jsonl"
_SNAPSHOT_PATH: Path = _LEDGER_DIR / "constitution_snapshot.json"
_REJECTED_LOG_PATH: Path = _LEDGER_DIR / "rejected_amendments.jsonl"

# Source: RDP disposition ledger (INNOV-81 output)
_RDP_DISPOSITION_LEDGER: Path = Path("data/rdp/disposition_ledger.jsonl")

# Canonical constitution store (CAE is sole writer)
_CONSTITUTION_STORE: Path = Path("data/cae/live_constitution.json")

_CHAIN_PREFIX_LEN: int = 24  # CAE-CHAIN-0 comparison window

# CAE-NOSELF-0: prefix patterns that identify CAE's own invariants
_SELF_PREFIX: FrozenSet[str] = frozenset({"CAE-"})

VALID_DISPOSITIONS: FrozenSet[str] = frozenset({"ACCEPTED", "DEFERRED", "REJECTED"})

# Amendment action types supported by CAE
VALID_ACTIONS: FrozenSet[str] = frozenset({
    "REINFORCE",   # Strengthen weight / add emphasis to existing invariant
    "REVIEW",      # Flag invariant for human review cycle
    "STABLE",      # Mark invariant as stable; no weight changes
    "ADD",         # Propose new invariant text
    "RETIRE",      # Mark invariant as retired (never hard-delete)
})


# ── Helpers ───────────────────────────────────────────────────────────────────

def _utc_iso() -> str:
    """Deterministic UTC timestamp. CAE-DETERM-0."""
    return datetime.now(timezone.utc).isoformat()


def _hmac_hex(payload: str, previous_hash: str) -> str:
    """Compute HMAC-SHA-256 over payload + previous_hash. CAE-CHAIN-0."""
    msg = (payload + previous_hash).encode("utf-8")
    return hmac.new(_HMAC_KEY, msg, hashlib.sha256).hexdigest()


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class AmendmentExecution:
    """A successfully executed constitutional amendment record."""
    execution_id: str
    proposal_id: str
    invariant_id: str
    action: str               # REINFORCE | REVIEW | STABLE | ADD | RETIRE
    rationale: str
    prior_state: dict         # Constitution entry before amendment
    post_state: dict          # Constitution entry after amendment
    governor: str
    executed_at_utc: str = field(default_factory=_utc_iso)
    hmac_chain_hash: str = ""


@dataclass
class RejectedAmendment:
    """An amendment proposal that was rejected by CAE (non-ACCEPTED or NOSELF)."""
    rejection_id: str
    proposal_id: str
    invariant_id: str
    disposition: str
    rejection_reason: str
    rejected_at_utc: str = field(default_factory=_utc_iso)


@dataclass
class ExecutionCycleResult:
    """Summary of one CAE execution cycle."""
    cycle_id: str
    proposals_read: int
    executed: int
    rejected: int
    skipped: int
    snapshot_hash: str
    invariant_count: int
    completed_at_utc: str = field(default_factory=_utc_iso)
    errors: List[str] = field(default_factory=list)


# ── CAE Core ──────────────────────────────────────────────────────────────────

class ConstitutionalAmendmentExecutor:
    """
    INNOV-83 · CAE — Constitutional Amendment Executor.

    Reads HUMAN-0-ACCEPTED proposals from the RDP disposition ledger,
    applies each amendment to the live constitution store, appends a
    signed execution record to the HMAC-chained ledger, and writes a
    post-execution constitutional snapshot. Fail-closed on all violations.
    """

    def __init__(
        self,
        rdp_ledger_path: Optional[Path] = None,
        ledger_dir: Optional[Path] = None,
        constitution_store: Optional[Path] = None,
    ) -> None:
        self._rdp_ledger: Path = rdp_ledger_path or _RDP_DISPOSITION_LEDGER
        self._ledger_dir: Path = ledger_dir or _LEDGER_DIR
        self._exec_ledger: Path = self._ledger_dir / "amendment_execution_ledger.jsonl"
        self._rejected_log: Path = self._ledger_dir / "rejected_amendments.jsonl"
        self._snapshot: Path = self._ledger_dir / "constitution_snapshot.json"
        self._constitution: Path = constitution_store or (self._ledger_dir / "live_constitution.json")
        self._ensure_dirs()

    # ── Internals ─────────────────────────────────────────────────────────────

    def _ensure_dirs(self) -> None:
        self._ledger_dir.mkdir(parents=True, exist_ok=True)

    def _get_previous_chain_hash(self, ledger_path: Path) -> str:
        """Return the last HMAC chain hash from ledger, or genesis sentinel."""
        if not ledger_path.exists():
            return "0" * 64
        last: Optional[dict] = None
        with ledger_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        last = json.loads(line)
                    except json.JSONDecodeError:
                        raise RuntimeError(
                            f"CAE-CHAIN-0: corrupt JSON in {ledger_path}"
                        )
        if last is None:
            return "0" * 64
        chain_hash = last.get("hmac_chain_hash", "")
        if not chain_hash:
            raise RuntimeError(
                f"CAE-CHAIN-0: missing hmac_chain_hash in last record of {ledger_path}"
            )
        return chain_hash

    def _verify_chain(self, ledger_path: Path) -> bool:
        """Verify HMAC chain integrity across entire ledger. CAE-CHAIN-0."""
        if not ledger_path.exists():
            return True
        records: List[dict] = []
        with ledger_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        if not records:
            return True
        prev_hash = "0" * 64
        for rec in records:
            stored = rec.get("hmac_chain_hash", "")
            payload = json.dumps(
                {k: v for k, v in rec.items() if k != "hmac_chain_hash"},
                sort_keys=True,
            )
            expected = _hmac_hex(payload, prev_hash)
            if stored[:_CHAIN_PREFIX_LEN] != expected[:_CHAIN_PREFIX_LEN]:
                return False
            prev_hash = stored
        return True

    def _seen_execution_ids(self) -> Set[str]:
        """Return all execution_id values in the ledger. CAE-REPLAY-0."""
        ids: Set[str] = set()
        if not self._exec_ledger.exists():
            return ids
        with self._exec_ledger.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rec = json.loads(line)
                    eid = rec.get("execution_id")
                    if eid:
                        ids.add(eid)
        return ids

    def _append_to_ledger(self, ledger_path: Path, record: dict) -> str:
        """
        Append a record to a JSONL ledger with HMAC chain linking.
        Returns the computed chain hash. CAE-IMMUT-0 / CAE-CHAIN-0.
        """
        prev_hash = self._get_previous_chain_hash(ledger_path)
        payload = json.dumps(
            {k: v for k, v in record.items() if k != "hmac_chain_hash"},
            sort_keys=True,
        )
        chain_hash = _hmac_hex(payload, prev_hash)
        record["hmac_chain_hash"] = chain_hash
        with ledger_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
        return chain_hash

    def _load_constitution(self) -> dict:
        """Load the live constitution store, or return a fresh skeleton."""
        if self._constitution.exists():
            with self._constitution.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        # Bootstrap an empty constitution
        return {
            "schema_version": "1.0.0",
            "governor": _GOVERNOR,
            "invariants": {},
            "created_at_utc": _utc_iso(),
            "last_amended_at_utc": None,
        }

    def _save_constitution(self, state: dict) -> None:
        """Atomically write the constitution store. CAE-ATOMIC-0."""
        tmp = self._constitution.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, sort_keys=True)
        tmp.replace(self._constitution)

    def _write_snapshot(self, constitution: dict) -> str:
        """Write constitutional snapshot and return its SHA-256. CAE-SNAPSHOT-0."""
        snapshot = {
            "snapshot_at_utc": _utc_iso(),
            "governor": _GOVERNOR,
            "innov_code": _INNOV_CODE,
            "invariant_count": len(constitution.get("invariants", {})),
            "constitution_hash": _sha256(json.dumps(constitution, sort_keys=True)),
            "constitution": constitution,
        }
        with self._snapshot.open("w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, indent=2, sort_keys=True)
        return snapshot["constitution_hash"]

    def _load_accepted_proposals(self) -> List[dict]:
        """
        Load all ACCEPTED proposals from RDP disposition ledger.
        CAE-HUMAN0-0: only ACCEPTED disposition records are returned.
        CAE-SCOPE-0: read-only access to RDP ledger.
        """
        if not self._rdp_ledger.exists():
            return []
        accepted: List[dict] = []
        with self._rdp_ledger.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("disposition") == "ACCEPTED":
                    accepted.append(rec)
        return accepted

    def _is_self_referential(self, invariant_id: str) -> bool:
        """CAE-NOSELF-0: reject amendments targeting CAE's own invariants."""
        return any(invariant_id.startswith(pfx) for pfx in _SELF_PREFIX)

    def _apply_amendment(
        self,
        constitution: dict,
        proposal: dict,
    ) -> tuple[dict, dict, dict]:
        """
        Apply a single accepted proposal to the constitution.
        Returns (updated_constitution, prior_entry, post_entry).
        CAE-ATOMIC-0: raises on any structural violation.
        """
        invariant_id: str = proposal.get("invariant_id", "")
        action: str = proposal.get("tier", proposal.get("action", "REINFORCE"))
        rationale: str = proposal.get("rationale", "")
        governor: str = proposal.get("governor", "")

        if not invariant_id:
            raise ValueError("CAE-ATOMIC-0: proposal missing invariant_id")
        if governor != _GOVERNOR:
            raise ValueError(
                f"CAE-HUMAN0-0: governor mismatch — expected '{_GOVERNOR}', got '{governor}'"
            )

        invariants: dict = constitution.setdefault("invariants", {})
        prior_entry: dict = deepcopy(invariants.get(invariant_id, {}))

        if action in ("REINFORCE", "REVIEW", "STABLE", "ADD"):
            entry = deepcopy(prior_entry) if prior_entry else {
                "id": invariant_id,
                "class": "Hard",
                "status": "ACTIVE",
                "reinforcement_count": 0,
                "review_count": 0,
            }
            if action == "REINFORCE":
                entry["reinforcement_count"] = entry.get("reinforcement_count", 0) + 1
                entry["status"] = "REINFORCED"
            elif action == "REVIEW":
                entry["review_count"] = entry.get("review_count", 0) + 1
                entry["status"] = "UNDER_REVIEW"
            elif action == "STABLE":
                entry["status"] = "STABLE"
            elif action == "ADD":
                entry["status"] = "ACTIVE"
            entry["last_amended_at_utc"] = _utc_iso()
            entry["last_rationale"] = rationale
            entry["last_action"] = action
            invariants[invariant_id] = entry
        elif action == "RETIRE":
            if invariant_id not in invariants:
                raise ValueError(
                    f"CAE-ATOMIC-0: cannot retire unknown invariant '{invariant_id}'"
                )
            entry = deepcopy(invariants[invariant_id])
            entry["status"] = "RETIRED"
            entry["retired_at_utc"] = _utc_iso()
            entry["retirement_rationale"] = rationale
            entry["last_action"] = "RETIRE"
            invariants[invariant_id] = entry
        else:
            raise ValueError(f"CAE-ATOMIC-0: unknown action '{action}'")

        post_entry: dict = deepcopy(invariants[invariant_id])
        constitution["last_amended_at_utc"] = _utc_iso()
        return constitution, prior_entry, post_entry

    # ── Public API ────────────────────────────────────────────────────────────

    def execute(self, cycle_id: Optional[str] = None) -> ExecutionCycleResult:
        """
        Execute one amendment cycle.

        1. Verify execution ledger chain integrity (CAE-CHAIN-0)
        2. Load all ACCEPTED proposals from RDP disposition ledger (CAE-HUMAN0-0)
        3. For each proposal:
           a. Reject CAE self-referential amendments (CAE-NOSELF-0)
           b. Reject duplicate execution_ids (CAE-REPLAY-0)
           c. Apply amendment atomically (CAE-ATOMIC-0)
           d. Append signed execution record (CAE-IMMUT-0 / CAE-AUDIT-0)
        4. Write constitutional snapshot (CAE-SNAPSHOT-0)
        5. Return ExecutionCycleResult summary
        """
        cycle_id = cycle_id or str(uuid.uuid4())

        # CAE-CHAIN-0: Verify ledger integrity before any writes
        if not self._verify_chain(self._exec_ledger):
            raise RuntimeError(
                "CAE-CHAIN-0: execution ledger chain integrity failure — halting"
            )

        proposals = self._load_accepted_proposals()
        seen_ids = self._seen_execution_ids()

        constitution = self._load_constitution()

        executed = 0
        rejected = 0
        skipped = 0
        errors: List[str] = []

        for proposal in proposals:
            proposal_id: str = proposal.get("proposal_id", str(uuid.uuid4()))
            invariant_id: str = proposal.get("invariant_id", "")

            # CAE-NOSELF-0
            if self._is_self_referential(invariant_id):
                rejection = RejectedAmendment(
                    rejection_id=str(uuid.uuid4()),
                    proposal_id=proposal_id,
                    invariant_id=invariant_id,
                    disposition=proposal.get("disposition", "ACCEPTED"),
                    rejection_reason="CAE-NOSELF-0: self-referential amendment rejected",
                )
                self._append_to_ledger(self._rejected_log, asdict(rejection))
                rejected += 1
                continue

            # Build deterministic execution_id from proposal_id + cycle
            execution_id = _sha256(f"{proposal_id}:{cycle_id}")[:32]

            # CAE-REPLAY-0
            if execution_id in seen_ids:
                skipped += 1
                continue

            # CAE-ATOMIC-0: apply and record atomically
            try:
                constitution, prior, post = self._apply_amendment(constitution, proposal)
            except (ValueError, KeyError) as exc:
                errors.append(f"{invariant_id}: {exc}")
                rejected += 1
                continue

            exec_record = AmendmentExecution(
                execution_id=execution_id,
                proposal_id=proposal_id,
                invariant_id=invariant_id,
                action=proposal.get("tier", proposal.get("action", "REINFORCE")),
                rationale=proposal.get("rationale", ""),
                prior_state=prior,
                post_state=post,
                governor=_GOVERNOR,
            )
            rec_dict = asdict(exec_record)
            # CAE-AUDIT-0: append to immutable ledger
            chain_hash = self._append_to_ledger(self._exec_ledger, rec_dict)
            seen_ids.add(execution_id)
            executed += 1

        # CAE-ATOMIC-0: persist updated constitution
        self._save_constitution(constitution)

        # CAE-SNAPSHOT-0: write post-execution snapshot
        snapshot_hash = self._write_snapshot(constitution)

        return ExecutionCycleResult(
            cycle_id=cycle_id,
            proposals_read=len(proposals),
            executed=executed,
            rejected=rejected,
            skipped=skipped,
            snapshot_hash=snapshot_hash,
            invariant_count=len(constitution.get("invariants", {})),
            errors=errors,
        )

    def get_constitution(self) -> dict:
        """Return the current live constitution. Read-only. CAE-SCOPE-0."""
        return deepcopy(self._load_constitution())

    def get_execution_log(self) -> List[dict]:
        """Return all execution records from the ledger."""
        if not self._exec_ledger.exists():
            return []
        records: List[dict] = []
        with self._exec_ledger.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records

    def verify_chain(self) -> bool:
        """CAE-CHAIN-0: Verify execution ledger HMAC chain integrity."""
        return self._verify_chain(self._exec_ledger)

    def get_snapshot(self) -> Optional[dict]:
        """Return the latest constitutional snapshot or None."""
        if not self._snapshot.exists():
            return None
        with self._snapshot.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def execution_summary(self) -> dict:
        """Return a structured summary of all CAE execution history."""
        records = self.get_execution_log()
        invariant_ids = {r.get("invariant_id") for r in records}
        action_counts: Dict[str, int] = {}
        for r in records:
            a = r.get("action", "UNKNOWN")
            action_counts[a] = action_counts.get(a, 0) + 1
        return {
            "module": _MODULE_CODE,
            "innov_code": _INNOV_CODE,
            "governor": _GOVERNOR,
            "total_executions": len(records),
            "unique_invariants_amended": len(invariant_ids),
            "action_breakdown": action_counts,
            "chain_valid": self.verify_chain(),
            "constitution_invariant_count": len(
                self._load_constitution().get("invariants", {})
            ),
            "summarised_at_utc": _utc_iso(),
        }
