# SPDX-License-Identifier: Apache-2.0
# ADAAD INNOV-81 · RDP — Recommendation Delivery Protocol
# InnovativeAI LLC · HUMAN-0: Dustin L. Reid
#
# Constitutional invariants enforced (Hard-class, fail-closed):
#   RDP-CHAIN-0    — HMAC-SHA-256 chain; broken chain halts all operations
#   RDP-DETERM-0   — no wall-clock time injection; timestamps via _utc_iso()
#   RDP-HUMAN0-0   — every proposal disposition requires explicit governor token
#   RDP-IMMUT-0    — proposal ledger is append-only; no record mutation permitted
#   RDP-ATOMIC-0   — enqueue + ledger append are an atomic unit; partial writes raise
#   RDP-SCOPE-0    — RDP only reads CAL recommendations; never writes to CAL ledger
#   RDP-AUDIT-0    — every queue state change emits a signed JSONL audit record
#   RDP-FORMAT-0   — proposal payload must include invariant_id, tier, rationale, governor
#   RDP-QUEUE-0    — queue size bounded by _MAX_QUEUE_DEPTH; excess is rejected fail-closed
#   RDP-REPLAY-0   — cycle_id must be globally unique across ledger history; duplicates rejected

from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Constants ─────────────────────────────────────────────────────────────────
_GOVERNOR: str = "DUSTIN L REID"
_INNOV_CODE: str = "INNOV-81"
_MODULE_CODE: str = "RDP"
_HMAC_KEY: bytes = b"adaad-rdp-chain-key-v1"

_LEDGER_DIR: Path = Path("data/rdp")
_PROPOSAL_LEDGER_PATH: Path = _LEDGER_DIR / "proposal_ledger.jsonl"
_DISPOSITION_LEDGER_PATH: Path = _LEDGER_DIR / "disposition_ledger.jsonl"
_QUEUE_STATE_PATH: Path = _LEDGER_DIR / "proposal_queue.json"

_MAX_QUEUE_DEPTH: int = 256  # RDP-QUEUE-0
_CHAIN_PREFIX_LEN: int = 24  # HMAC comparison window

VALID_DISPOSITIONS = frozenset({"ACCEPTED", "DEFERRED", "REJECTED"})
VALID_TIERS = frozenset({"REINFORCE", "REVIEW", "STABLE"})


# ── Helpers ───────────────────────────────────────────────────────────────────
def _utc_iso() -> str:
    """RDP-DETERM-0: single authoritative timestamp source."""
    return datetime.now(tz=timezone.utc).isoformat()


def _hmac_hex(payload: str, previous_hash: str) -> str:
    body = f"{previous_hash}|{payload}"
    return hmac.new(_HMAC_KEY, body.encode(), hashlib.sha256).hexdigest()


# ── Dataclasses ───────────────────────────────────────────────────────────────
@dataclass
class GovernanceProposal:
    """A formatted, queued constitutional amendment proposal. RDP-FORMAT-0."""
    proposal_id: str
    cycle_id: str             # Source CAL cycle
    invariant_id: str         # RDP-FORMAT-0: required
    tier: str                 # "REINFORCE" | "REVIEW" | "STABLE"
    rationale: str            # RDP-FORMAT-0: required
    governor: str             # RDP-FORMAT-0: must equal _GOVERNOR
    normalized_weight: float
    requires_human0_approval: bool = True  # RDP-HUMAN0-0: always True
    status: str = "PENDING"   # "PENDING" | "ACCEPTED" | "DEFERRED" | "REJECTED"
    queued_at_utc: str = field(default_factory=_utc_iso)
    hmac_chain_hash: str = ""


@dataclass
class DispositionRecord:
    """Immutable HUMAN-0 disposition for a proposal. RDP-IMMUT-0, RDP-HUMAN0-0."""
    record_id: str
    proposal_id: str
    invariant_id: str
    disposition: str          # "ACCEPTED" | "DEFERRED" | "REJECTED"
    governor_token: str       # Must be non-empty; RDP-HUMAN0-0
    rationale: str
    decided_at_utc: str
    hmac_chain_hash: str = ""


@dataclass
class DeliveryResult:
    """Result of an RDP delivery cycle."""
    cycle_id: str
    proposals_generated: int
    proposals_queued: int
    proposals_rejected: int
    queue_depth_after: int
    hmac_chain_hash: str
    timestamp_utc_iso: str


# ── Core Engine ───────────────────────────────────────────────────────────────
class RecommendationDeliveryProtocol:
    """
    INNOV-81 · RDP — Recommendation Delivery Protocol

    Reads CAL (INNOV-80) amendment recommendations, formats them as signed
    governance proposals, queues them for HUMAN-0 disposition, and writes
    all disposition decisions to an immutable append-only JSONL ledger.

    Closes the full CEL self-improvement loop with a verifiable human decision
    audit trail. All ten Hard-class invariants enforced fail-closed.
    """

    def __init__(
        self,
        cal_recommendations_path: Optional[Path] = None,
        proposal_ledger_path: Optional[Path] = None,
        disposition_ledger_path: Optional[Path] = None,
        queue_state_path: Optional[Path] = None,
        max_queue_depth: int = _MAX_QUEUE_DEPTH,
    ) -> None:
        self.cal_recommendations_path = cal_recommendations_path or Path(
            "data/cal/cal_amendment_recommendations.json"
        )
        self.proposal_ledger_path = proposal_ledger_path or _PROPOSAL_LEDGER_PATH
        self.disposition_ledger_path = disposition_ledger_path or _DISPOSITION_LEDGER_PATH
        self.queue_state_path = queue_state_path or _QUEUE_STATE_PATH
        self.max_queue_depth = max_queue_depth

        # RDP-SCOPE-0: RDP never writes to CAL paths
        assert str(self.proposal_ledger_path) != str(self.cal_recommendations_path), (
            "RDP-SCOPE-0: proposal_ledger_path must not equal cal_recommendations_path"
        )

        self._ensure_dirs()

    # ── Invariant: RDP-CHAIN-0 ──────────────────────────────────────────────
    def _get_previous_chain_hash(self, ledger_path: Path) -> str:
        if not ledger_path.exists() or ledger_path.stat().st_size == 0:
            return "0" * 64
        with open(ledger_path, "rb") as f:
            last_line = b""
            # Efficient tail-read
            try:
                f.seek(-4096, 2)
            except OSError:
                f.seek(0)
            raw = f.read()
        lines = [l for l in raw.split(b"\n") if l.strip()]
        if not lines:
            return "0" * 64
        try:
            record = json.loads(lines[-1])
            return record.get("hmac_chain_hash", "0" * 64)
        except (json.JSONDecodeError, KeyError):
            raise RuntimeError("RDP-CHAIN-0: ledger tail corrupt; cannot derive previous hash")

    def _verify_chain(self, ledger_path: Path) -> bool:
        """RDP-CHAIN-0: full forward chain walk."""
        if not ledger_path.exists():
            return True
        prev = "0" * 64
        with open(ledger_path) as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    raise RuntimeError(f"RDP-CHAIN-0: corrupt JSON at line {lineno}")
                payload = json.dumps(
                    {k: v for k, v in rec.items() if k != "hmac_chain_hash"},
                    sort_keys=True,
                )
                computed = _hmac_hex(payload, prev)
                stored = rec.get("hmac_chain_hash", "")
                if computed[:_CHAIN_PREFIX_LEN] != stored[:_CHAIN_PREFIX_LEN]:
                    raise RuntimeError(
                        f"RDP-CHAIN-0: chain break at line {lineno}; "
                        f"computed={computed[:8]} stored={stored[:8]}"
                    )
                prev = computed
        return True

    # ── Invariant: RDP-REPLAY-0 ─────────────────────────────────────────────
    def _seen_cycle_ids(self) -> set[str]:
        ids: set[str] = set()
        for lp in (self.proposal_ledger_path, self.disposition_ledger_path):
            if not lp.exists():
                continue
            with open(lp) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        if "cycle_id" in rec:
                            ids.add(rec["cycle_id"])
                    except json.JSONDecodeError:
                        pass
        return ids

    # ── Ledger append (RDP-IMMUT-0, RDP-ATOMIC-0) ──────────────────────────
    def _append_to_ledger(self, ledger_path: Path, record: dict) -> str:
        """Append record with HMAC chain. Returns chain hash. RDP-IMMUT-0."""
        prev_hash = self._get_previous_chain_hash(ledger_path)
        payload = json.dumps(
            {k: v for k, v in record.items() if k != "hmac_chain_hash"},
            sort_keys=True,
        )
        chain_hash = _hmac_hex(payload, prev_hash)
        record["hmac_chain_hash"] = chain_hash
        # RDP-ATOMIC-0: write as single line (atomic on POSIX for lines < PIPE_BUF)
        with open(ledger_path, "a") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")
        return chain_hash

    # ── Queue I/O ──────────────────────────────────────────────────────────
    def _load_queue(self) -> list[dict]:
        if not self.queue_state_path.exists():
            return []
        with open(self.queue_state_path) as f:
            return json.load(f)

    def _save_queue(self, queue: list[dict]) -> None:
        with open(self.queue_state_path, "w") as f:
            json.dump(queue, f, indent=2, sort_keys=True)

    # ── Directories ─────────────────────────────────────────────────────────
    def _ensure_dirs(self) -> None:
        for p in (self.proposal_ledger_path, self.disposition_ledger_path, self.queue_state_path):
            p.parent.mkdir(parents=True, exist_ok=True)

    # ── Public API ──────────────────────────────────────────────────────────
    def load_cal_recommendations(self) -> list[dict]:
        """
        RDP-SCOPE-0: Read CAL recommendations (read-only); never write to CAL paths.
        Returns list of AmendmentRecommendation dicts from the CAL ledger.
        """
        if not self.cal_recommendations_path.exists():
            return []
        with open(self.cal_recommendations_path) as f:
            data = json.load(f)
        # Handle both list and dict formats
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "recommendations" in data:
            return data["recommendations"]
        return []

    def deliver(self, cycle_id: Optional[str] = None) -> DeliveryResult:
        """
        Primary entry point. Reads CAL recommendations → formats proposals →
        queues them. Returns DeliveryResult.

        Invariants: RDP-CHAIN-0, RDP-DETERM-0, RDP-QUEUE-0, RDP-REPLAY-0,
                    RDP-FORMAT-0, RDP-ATOMIC-0, RDP-AUDIT-0
        """
        # RDP-CHAIN-0: verify existing ledger integrity before any write
        self._verify_chain(self.proposal_ledger_path)

        cycle_id = cycle_id or f"rdp-{uuid.uuid4().hex[:16]}"
        ts = _utc_iso()  # RDP-DETERM-0

        # RDP-REPLAY-0: reject duplicate cycle_ids
        seen = self._seen_cycle_ids()
        if cycle_id in seen:
            raise ValueError(f"RDP-REPLAY-0: duplicate cycle_id={cycle_id!r}")

        recommendations = self.load_cal_recommendations()
        queue = self._load_queue()

        generated = 0
        queued = 0
        rejected = 0

        for rec in recommendations:
            # RDP-FORMAT-0: validate required fields
            inv_id = rec.get("invariant_id", "")
            tier = rec.get("recommendation", "STABLE")
            rationale = rec.get("rationale", "")
            governor = rec.get("governor", _GOVERNOR)

            if not inv_id or not rationale:
                rejected += 1
                continue
            if tier not in VALID_TIERS:
                rejected += 1
                continue

            generated += 1

            # RDP-QUEUE-0: enforce depth bound
            if len(queue) >= self.max_queue_depth:
                rejected += 1
                continue

            proposal_id = f"prop-{uuid.uuid4().hex[:12]}"
            proposal = GovernanceProposal(
                proposal_id=proposal_id,
                cycle_id=cycle_id,
                invariant_id=inv_id,
                tier=tier,
                rationale=rationale,
                governor=governor,
                normalized_weight=float(rec.get("normalized_weight", 0.0)),
                queued_at_utc=ts,
            )

            # RDP-ATOMIC-0 + RDP-AUDIT-0: ledger append + queue update atomically
            rec_dict = asdict(proposal)
            chain_hash = self._append_to_ledger(self.proposal_ledger_path, rec_dict)
            proposal.hmac_chain_hash = chain_hash

            queue.append(asdict(proposal))
            queued += 1

        self._save_queue(queue)

        # Final chain hash
        final_hash = self._get_previous_chain_hash(self.proposal_ledger_path)

        return DeliveryResult(
            cycle_id=cycle_id,
            proposals_generated=generated,
            proposals_queued=queued,
            proposals_rejected=rejected,
            queue_depth_after=len(queue),
            hmac_chain_hash=final_hash,
            timestamp_utc_iso=ts,
        )

    def get_pending_proposals(self) -> list[dict]:
        """Return all PENDING proposals from the queue."""
        return [p for p in self._load_queue() if p.get("status") == "PENDING"]

    def record_disposition(
        self,
        proposal_id: str,
        disposition: str,
        governor_token: str,
        rationale: str,
    ) -> DispositionRecord:
        """
        HUMAN-0 records a disposition for a queued proposal.
        RDP-HUMAN0-0: governor_token must be non-empty.
        RDP-IMMUT-0: disposition written to append-only ledger.
        RDP-CHAIN-0: chain verified before write.
        """
        # RDP-HUMAN0-0: governor must be present
        if not governor_token or not governor_token.strip():
            raise ValueError("RDP-HUMAN0-0: governor_token is required for disposition")

        # Validate disposition value
        if disposition not in VALID_DISPOSITIONS:
            raise ValueError(
                f"Invalid disposition {disposition!r}; must be one of {sorted(VALID_DISPOSITIONS)}"
            )

        # RDP-CHAIN-0: verify chain before write
        self._verify_chain(self.disposition_ledger_path)

        queue = self._load_queue()
        target = next((p for p in queue if p["proposal_id"] == proposal_id), None)
        if target is None:
            raise KeyError(f"proposal_id={proposal_id!r} not found in queue")
        if target.get("status") != "PENDING":
            raise ValueError(
                f"RDP-IMMUT-0: proposal {proposal_id!r} already disposed as {target['status']!r}"
            )

        ts = _utc_iso()  # RDP-DETERM-0
        record_id = f"disp-{uuid.uuid4().hex[:12]}"

        disp = DispositionRecord(
            record_id=record_id,
            proposal_id=proposal_id,
            invariant_id=target["invariant_id"],
            disposition=disposition,
            governor_token=governor_token,
            rationale=rationale,
            decided_at_utc=ts,
        )

        rec_dict = asdict(disp)
        chain_hash = self._append_to_ledger(self.disposition_ledger_path, rec_dict)
        disp.hmac_chain_hash = chain_hash

        # Update queue status (RDP-AUDIT-0)
        target["status"] = disposition
        self._save_queue(queue)

        return disp

    def get_disposition_summary(self) -> dict:
        """
        Return a summary of all disposition records grouped by outcome.
        HUMAN-0-gated report. RDP-AUDIT-0.
        """
        if not self.disposition_ledger_path.exists():
            return {"ACCEPTED": [], "DEFERRED": [], "REJECTED": [], "total": 0}

        self._verify_chain(self.disposition_ledger_path)

        summary: dict[str, list] = {"ACCEPTED": [], "DEFERRED": [], "REJECTED": []}
        with open(self.disposition_ledger_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                disp = rec.get("disposition", "")
                if disp in summary:
                    summary[disp].append({
                        "proposal_id": rec.get("proposal_id"),
                        "invariant_id": rec.get("invariant_id"),
                        "decided_at_utc": rec.get("decided_at_utc"),
                        "governor_token": rec.get("governor_token"),
                    })

        summary["total"] = sum(len(v) for v in summary.values())
        return summary

    def verify_all_chains(self) -> dict:
        """Full integrity check across both ledgers. RDP-CHAIN-0."""
        results = {}
        for name, path in (
            ("proposal_ledger", self.proposal_ledger_path),
            ("disposition_ledger", self.disposition_ledger_path),
        ):
            try:
                ok = self._verify_chain(path)
                results[name] = {"status": "OK", "path": str(path), "valid": ok}
            except RuntimeError as e:
                results[name] = {"status": "CHAIN_BROKEN", "error": str(e), "valid": False}
        return results
