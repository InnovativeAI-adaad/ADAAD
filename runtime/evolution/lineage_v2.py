# SPDX-License-Identifier: Apache-2.0
"""Lineage ledger v2 events and append-only storage helpers."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from runtime import ROOT_DIR
from runtime.governance.deterministic_filesystem import read_file_deterministic
from runtime.tenancy import payload_in_tenant_scope, tenant_partition_path

LOG = logging.getLogger(__name__)

LEDGER_V2_PATH = ROOT_DIR / "security" / "ledger" / "lineage_v2.jsonl"
LINEAGE_V2_PATH = LEDGER_V2_PATH

_TAIL_CACHE_LOCK = threading.Lock()
_TAIL_CACHE: Dict[str, str] = {}


@contextmanager
def _file_lock(path: Path, timeout: float = 10.0):
    lock_path = path.with_suffix(path.suffix + ".lock")
    start_time = time.monotonic()
    while True:
        try:
            # Atomic O_EXCL create
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            try:
                yield
            finally:
                os.close(fd)
                os.unlink(lock_path)
            return
        except FileExistsError:
            if time.monotonic() - start_time > timeout:
                raise RuntimeError(f"lineage_lock_timeout:{lock_path}")
            time.sleep(0.01)


class LineageResolutionError(RuntimeError):
    """Raised when lineage chain resolution fails."""


def _canonical_json(value: Dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash_entry(prev_hash: str, payload: Dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + _canonical_json(payload)).encode("utf-8")).hexdigest()


def _agent_id(entry: Dict[str, Any]) -> str:
    payload = dict(entry.get("payload") or {})
    certificate = dict(payload.get("certificate") or {})
    return str(payload.get("agent_id") or certificate.get("agent_id") or "")


def _mutation_id(entry: Dict[str, Any]) -> str:
    payload = dict(entry.get("payload") or {})
    certificate = dict(payload.get("certificate") or {})
    return str(payload.get("mutation_id") or payload.get("bundle_id") or certificate.get("mutation_id") or certificate.get("bundle_id") or "")


def _parent_mutation_id(entry: Dict[str, Any]) -> str:
    payload = dict(entry.get("payload") or {})
    certificate = dict(payload.get("certificate") or {})
    lineage = dict(payload.get("lineage") or {})
    return str(
        payload.get("parent_mutation_id")
        or payload.get("parent_bundle_id")
        or certificate.get("parent_mutation_id")
        or certificate.get("parent_bundle_id")
        or lineage.get("parent_mutation_id")
        or ""
    )


def resolve_chain(agent_id: str, *, ledger_path: Path | None = None) -> List[str] | None:
    """Resolve lineage hash chain ending at latest mutation for agent_id if available."""
    path = ledger_path or LINEAGE_V2_PATH
    if not path.exists():
        return None

    entries: List[Dict[str, Any]] = []
    prev_hash = "0" * 64
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            entry = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LineageResolutionError("lineage_entry_malformed") from exc
        if not isinstance(entry, dict):
            raise LineageResolutionError("lineage_entry_malformed")
        payload = {k: v for k, v in entry.items() if k != "hash"}
        computed = _hash_entry(prev_hash, payload)
        if str(entry.get("prev_hash") or "") != prev_hash or str(entry.get("hash") or "") != computed:
            raise LineageResolutionError("lineage_hash_mismatch")
        prev_hash = computed
        entries.append(entry)

    if not entries:
        return None

    by_mutation: Dict[str, Dict[str, Any]] = {}
    for entry in entries:
        mutation_id = _mutation_id(entry)
        if mutation_id:
            by_mutation[mutation_id] = entry

    normalized_agent_id = str(agent_id or "").strip()
    if normalized_agent_id:
        tail = next((entry for entry in reversed(entries) if _mutation_id(entry) and _agent_id(entry) == normalized_agent_id), None)
    else:
        tail = next((entry for entry in reversed(entries) if _mutation_id(entry)), None)
    if tail is None:
        return None

    chain: List[str] = []
    visited: set[str] = set()
    cursor = tail
    while cursor is not None:
        mutation_id = _mutation_id(cursor)
        if mutation_id in visited:
            raise LineageResolutionError("lineage_cycle_detected")
        if mutation_id:
            visited.add(mutation_id)

        link_hash = str(cursor.get("hash") or "")
        if not link_hash:
            raise LineageResolutionError("lineage_entry_malformed")
        chain.append(link_hash)
        parent_id = _parent_mutation_id(cursor)
        cursor = by_mutation.get(parent_id) if parent_id else None

    chain.reverse()
    if chain and chain[0] != entries[0].get("hash"):
        chain.insert(0, str(entries[0].get("hash") or ""))
    return chain


def resolve_certified_ancestor_path(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve canonical mutation identity + ancestry links for a lineage entry.

    Expected invariant: ``ancestor_chain`` is ordered oldest->newest, so the tail
    (last element) must match ``parent_mutation_id`` when both are present.
    """

    payload = dict(entry.get("payload") or {})
    certificate = payload.get("certificate") if isinstance(payload.get("certificate"), dict) else {}
    lineage = payload.get("lineage") if isinstance(payload.get("lineage"), dict) else {}

    mutation_id = str(
        payload.get("mutation_id")
        or payload.get("bundle_id")
        or certificate.get("mutation_id")
        or certificate.get("bundle_id")
        or ""
    )
    parent_mutation_id = str(
        payload.get("parent_mutation_id")
        or payload.get("parent_bundle_id")
        or certificate.get("parent_mutation_id")
        or certificate.get("parent_bundle_id")
        or lineage.get("parent_mutation_id")
        or ""
    )

    ancestors_raw = (
        payload.get("ancestor_chain")
        or payload.get("ancestor_mutation_ids")
        or certificate.get("ancestor_chain")
        or certificate.get("ancestor_mutation_ids")
        or lineage.get("ancestor_chain")
        or []
    )
    ancestor_chain = [str(item) for item in ancestors_raw if str(item)] if isinstance(ancestors_raw, list) else []

    certified_signature = str(certificate.get("signature") or "")

    return {
        "mutation_id": mutation_id,
        "parent_mutation_id": parent_mutation_id,
        "ancestor_chain": ancestor_chain,
        "certified_signature": certified_signature,
    }


class LineageIntegrityError(RuntimeError):
    """Raised when lineage_v2 ledger integrity verification fails."""


class LineageRecoveryHook(Protocol):
    """Interface for invoking lineage recovery workflows after integrity failures."""

    def on_lineage_integrity_failure(self, *, ledger_path: Path, error: LineageIntegrityError) -> None:
        """Handle a lineage integrity failure (for example, snapshot restore)."""


@dataclass(frozen=True)
class LineageEvent:
    event_type: str
    payload: Dict[str, Any]


@dataclass(frozen=True)
class EpochStartEvent:
    epoch_id: str
    ts: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EpochEndEvent:
    epoch_id: str
    ts: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FederationOrigin:
    """Provenance record for a mutation that originated in a remote repository.

    Phase 5 — Multi-Repo Federation lineage extension.

    Fields
    ------
    source_repo:
        Canonical repository identifier (e.g. ``InnovativeAI-adaad/ADAAD-payments``).
    source_epoch_id:
        Epoch identifier in the *source* repo at the time the mutation was accepted
        and proposed for federation.
    source_mutation_id:
        Mutation / bundle identifier in the source repo's GovernanceGate approval
        record.  Used for cross-repo deduplication and replay tracing.
    source_chain_digest:
        SHA-256 tip digest of the source repo's lineage ledger at the epoch boundary
        when the mutation was packaged.  Enables federated determinism verification
        (Phase 5 evidence matrix gate).
    federation_gate_id:
        Identifier of the ``FederationMutationBroker`` gate event that authorised
        propagation.  Absent (empty string) for locally-accepted mutations.

    Serialisation contract
    ----------------------
    ``FederationOrigin`` is serialised inside ``MutationBundleEvent.certificate``
    under the key ``"federation_origin"`` so existing lineage consumers that do not
    understand Phase 5 fields remain unaffected.  When ``federation_origin`` is
    ``None`` on a ``MutationBundleEvent``, the mutation is local-only and the key
    is omitted from the serialised form entirely.
    """

    source_repo: str
    source_epoch_id: str
    source_mutation_id: str
    source_chain_digest: str
    federation_gate_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic canonical serialisation — sort_keys applied by caller."""
        return {
            "federation_gate_id": self.federation_gate_id,
            "source_chain_digest": self.source_chain_digest,
            "source_epoch_id": self.source_epoch_id,
            "source_mutation_id": self.source_mutation_id,
            "source_repo": self.source_repo,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FederationOrigin":
        return cls(
            source_repo=str(data["source_repo"]),
            source_epoch_id=str(data["source_epoch_id"]),
            source_mutation_id=str(data["source_mutation_id"]),
            source_chain_digest=str(data["source_chain_digest"]),
            federation_gate_id=str(data.get("federation_gate_id", "")),
        )


@dataclass(frozen=True)
class MutationBundleEvent:
    epoch_id: str
    bundle_id: str
    impact: float
    certificate: Dict[str, Any]
    strategy_set: List[str] = field(default_factory=list)
    bundle_digest: str = ""
    epoch_digest: str = ""
    # Phase 5: present only for cross-repo federated mutations; None for local.
    federation_origin: Optional[FederationOrigin] = None

    def is_federated(self) -> bool:
        """Return True when this mutation was proposed by a remote repository."""
        return self.federation_origin is not None

    def to_certificate_dict(self) -> Dict[str, Any]:
        """Return certificate dict enriched with federation_origin when present.

        This method is the canonical serialisation surface for Phase 5 lineage
        consumers.  Callers that only read ``certificate`` directly continue to
        work; this method is the *write* path used by ``LineageLedgerV2``.
        """
        cert: Dict[str, Any] = dict(self.certificate)
        if self.federation_origin is not None:
            cert["federation_origin"] = self.federation_origin.to_dict()
        return cert


@dataclass(frozen=True)
class SeedCompetitionEpochEvent:
    """Phase 80 — Competition epoch ledger entry.

    Records the outcome of a multi-seed competitive evaluation epoch.
    Written to LineageLedgerV2 *before* any candidate is promoted
    (COMP-LEDGER-0 invariant).

    Attributes
    ----------
    epoch_id:           Unique competition epoch identifier.
    candidate_ids:      Ordered list of all competing seed IDs (deterministic).
    ranked_ids:         Fitness-ranked order (highest score first).
    winner_id:          Promoted candidate (top of ranked_ids).
    fitness_scores:     Mapping seed_id → float fitness score.
    gate_verdict:       'pass' | 'fail' | 'deferred'.
    competition_digest: SHA-256 hex of canonical(candidate_ids + fitness_scores).
    phase:              ADAAD phase at which competition ran.
    version:            ADAAD version string.
    """

    epoch_id: str
    candidate_ids: List[str]
    ranked_ids: List[str]
    winner_id: str
    fitness_scores: Dict[str, float]
    gate_verdict: str
    competition_digest: str
    phase: int
    version: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "epoch_id": self.epoch_id,
            "candidate_ids": list(self.candidate_ids),
            "ranked_ids": list(self.ranked_ids),
            "winner_id": self.winner_id,
            "fitness_scores": dict(self.fitness_scores),
            "gate_verdict": self.gate_verdict,
            "competition_digest": self.competition_digest,
            "phase": self.phase,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SeedCompetitionEpochEvent":
        return cls(
            epoch_id=data["epoch_id"],
            candidate_ids=data["candidate_ids"],
            ranked_ids=data["ranked_ids"],
            winner_id=data["winner_id"],
            fitness_scores=data["fitness_scores"],
            gate_verdict=data["gate_verdict"],
            competition_digest=data["competition_digest"],
            phase=data["phase"],
            version=data["version"],
        )


class LineageLedgerV2:
    def __init__(
        self,
        ledger_path: Path | None = None,
        tenant_context: dict[str, str] | None = None,
    ) -> None:
        base_path = ledger_path or LEDGER_V2_PATH
        self.ledger_path = tenant_partition_path(base_path, tenant_context)
        self.tenant_context = dict(tenant_context or {})
        self._epoch_digest_index: Dict[str, str] = {}
        self._verified_tail_hash: str | None = None

    def _ensure(self) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.ledger_path.exists():
            self.ledger_path.touch()

    def _last_hash(self) -> str:
        key = str(self.ledger_path.resolve())
        with _TAIL_CACHE_LOCK:
            cached = _TAIL_CACHE.get(key)
        if cached is not None:
            self._verified_tail_hash = cached
            return cached
        self.verify_integrity()
        with _TAIL_CACHE_LOCK:
            cached = _TAIL_CACHE.get(key) or ("0" * 64)
        self._verified_tail_hash = cached
        return cached

    def verify_integrity(self, recovery_hook: LineageRecoveryHook | None = None, max_lines: int | None = None) -> None:
        """Recompute chain from genesis and verify each stored hash.

        When max_lines is supplied the scan stops early after that many lines.
        The warm-cache pointer is advanced to the last verified entry in the
        scanned prefix so that subsequent _last_hash() calls can chain appends
        from the verified boundary without re-scanning.
        """
        self._ensure()
        key = str(self.ledger_path.resolve())
        prev_hash = "0" * 64
        with self.ledger_path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                if max_lines is not None and line_no > max_lines:
                    partial_tail = prev_hash or ("0" * 64)
                    with _TAIL_CACHE_LOCK:
                        _TAIL_CACHE[key] = partial_tail
                    self._verified_tail_hash = partial_tail
                    LOG.warning(
                        "lineage_verify_integrity_truncated",
                        extra={
                            "line_no": line_no,
                            "max_lines": max_lines,
                            "partial_tail_hash": prev_hash[:16],
                            "verified_lines": line_no - 1,
                        },
                    )
                    return
                entry_text = line.strip()
                if not entry_text:
                    continue
                try:
                    entry = json.loads(entry_text)
                except json.JSONDecodeError as exc:
                    error = LineageIntegrityError(f"lineage_invalid_json:line{line_no}:{exc}")
                    if recovery_hook is not None:
                        recovery_hook.on_lineage_integrity_failure(ledger_path=self.ledger_path, error=error)
                    raise error from exc
                if not isinstance(entry, dict):
                    error = LineageIntegrityError(f"lineage_malformed_entry:line{line_no}")
                    if recovery_hook is not None:
                        recovery_hook.on_lineage_integrity_failure(ledger_path=self.ledger_path, error=error)
                    raise error
                entry_prev_hash = str(entry.get("prev_hash") or "")
                entry_hash = str(entry.get("hash") or "")
                if not hmac.compare_digest(entry_prev_hash, prev_hash):
                    error = LineageIntegrityError(f"lineage_prev_hash_mismatch:line{line_no}")
                    if recovery_hook is not None:
                        recovery_hook.on_lineage_integrity_failure(ledger_path=self.ledger_path, error=error)
                    raise error
                payload = {key: value for key, value in entry.items() if key != "hash"}
                computed = self._compute_hash(prev_hash, payload)
                if not hmac.compare_digest(entry_hash, computed):
                    error = LineageIntegrityError(f"lineage_hash_mismatch:line{line_no}")
                    if recovery_hook is not None:
                        recovery_hook.on_lineage_integrity_failure(ledger_path=self.ledger_path, error=error)
                    raise error
                prev_hash = entry_hash
        with _TAIL_CACHE_LOCK:
            _TAIL_CACHE[key] = prev_hash
        self._verified_tail_hash = prev_hash

    # Contracts:
    # POST: _TAIL_CACHE[key] is updated after any non-raising call.

    @staticmethod
    def _compute_hash(prev_hash: str, entry: Dict[str, Any]) -> str:
        material = (prev_hash + json.dumps(entry, ensure_ascii=False, sort_keys=True)).encode("utf-8")
        return hashlib.sha256(material).hexdigest()

    @staticmethod
    def _hash_event(payload: Dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

    def append(self, event: LineageEvent) -> Dict[str, Any]:
        return self.append_event(event.event_type, event.payload)

    def append_event(self, event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        key = str(self.ledger_path.resolve())
        # COORDINATION-01: use a lock to ensure atomic append and cache update.
        with _file_lock(self.ledger_path):
            with _TAIL_CACHE_LOCK:
                # Re-read last hash to avoid stale appends from other components
                # in the same process that don't share the same LineageLedgerV2 instance.
                prev_hash = self._last_hash_internal()
                entry: Dict[str, Any] = {
                    "type": event_type,
                    "payload": payload,
                    "prev_hash": prev_hash,
                }
                entry["hash"] = self._compute_hash(prev_hash, entry)
                with self.ledger_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
                # Advance the warm cache to the newly written entry hash.
                _TAIL_CACHE[key] = entry["hash"]
                self._verified_tail_hash = entry["hash"]

        if event_type == "MutationBundleEvent":
            epoch_id = str(payload.get("epoch_id") or "")
            digest = str(payload.get("epoch_digest") or "")
            if epoch_id and digest:
                self._update_epoch_digest(epoch_id, digest)
        return entry

    def _last_hash_internal(self) -> str:
        # Assumes caller holds _TAIL_CACHE_LOCK and optionally _file_lock.
        # We always re-scan the tail to ensure we have the absolute truth
        # before appending, which coordinates multiple instances/processes.
        return self._scan_tail_unlocked()

    def _scan_tail_unlocked(self) -> str:
        """Read the last complete JSON line and extract its hash.
        
        Optimised to avoid full file scans by reading backwards from EOF.
        """
        self._ensure()
        try:
            size = self.ledger_path.stat().st_size
        except OSError:
            return "0" * 64
            
        if size == 0:
            return "0" * 64
        
        # We read in chunks from the end. 16KB should cover most SandboxEvidenceEvents.
        # If not, we fall back to a full scan or larger search.
        chunk_size = 16384
        with self.ledger_path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            pointer = handle.tell()
            
            # Skip trailing newlines
            while pointer > 0:
                handle.seek(max(0, pointer - 1))
                char = handle.read(1)
                if char not in (b"\n", b"\r"):
                    break
                pointer -= 1
            
            if pointer == 0:
                return "0" * 64
                
            # Scan backwards for the start of the last line
            end_of_line = pointer
            start_of_line = -1
            
            search_ptr = end_of_line
            while search_ptr > 0 and (end_of_line - search_ptr) < chunk_size:
                to_read = min(search_ptr, 1024)
                search_ptr -= to_read
                handle.seek(search_ptr)
                chunk = handle.read(to_read)
                
                # Find last newline in this chunk
                last_nl = chunk.rfind(b"\n")
                if last_nl != -1:
                    # Found it!
                    start_of_line = search_ptr + last_nl + 1
                    break
            
            if start_of_line == -1:
                # If record is > 16KB or start of file, fall back to slower scan.
                handle.seek(0)
                prev_hash = "0" * 64
                for line in handle:
                    line = line.strip()
                    if not line: continue
                    try:
                        entry = json.loads(line)
                        prev_hash = str(entry.get("hash") or prev_hash)
                    except Exception: continue
                return prev_hash

            handle.seek(start_of_line)
            line_data = handle.read(end_of_line - start_of_line).decode("utf-8", errors="ignore").strip()
            try:
                entry = json.loads(line_data)
                return str(entry.get("hash") or ("0" * 64))
            except Exception:
                # Corrupt line at tail — full scan to find last valid state
                handle.seek(0)
                prev_hash = "0" * 64
                for line in handle:
                    line = line.strip()
                    if not line: continue
                    try:
                        entry = json.loads(line)
                        prev_hash = str(entry.get("hash") or prev_hash)
                    except Exception: continue
                return prev_hash

    def append_typed_event(self, event) -> Dict[str, Any]:
        """Append a typed lineage event to the ledger.

        Phase 5 extension: ``MutationBundleEvent`` with a non-None
        ``federation_origin`` field is serialised via
        :meth:`MutationBundleEvent.to_certificate_dict` so that the
        ``federation_origin`` provenance is embedded inside the ``certificate``
        dict.  Consumers that only read ``certificate`` directly are unaffected.
        """
        event_type = event.__class__.__name__
        if isinstance(event, MutationBundleEvent):
            payload: Dict[str, Any] = {
                "epoch_id": event.epoch_id,
                "bundle_id": event.bundle_id,
                "impact": event.impact,
                "certificate": event.to_certificate_dict(),
                "strategy_set": list(event.strategy_set),
                "bundle_digest": event.bundle_digest,
                "epoch_digest": event.epoch_digest,
            }
            return self.append_event(event_type, payload)
        return self.append_event(event_type, asdict(event))

    def _read_entries_unverified(self) -> List[Dict[str, Any]]:
        self._ensure()
        entries: List[Dict[str, Any]] = []
        for line in read_file_deterministic(self.ledger_path).splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if isinstance(entry, dict):
                if self.tenant_context and not payload_in_tenant_scope(entry, self.tenant_context):
                    continue
                entries.append(entry)
        return entries

    def get_verified_tail_hash(self) -> str | None:
        return self._verified_tail_hash

    def read_all(self) -> List[Dict[str, Any]]:
        self.verify_integrity()
        return self._read_entries_unverified()

    def read_epoch(self, epoch_id: str) -> List[Dict[str, Any]]:
        return [entry for entry in self.read_all() if entry.get("payload", {}).get("epoch_id") == epoch_id]

    def list_epoch_ids(self) -> List[str]:
        seen: List[str] = []
        for entry in self.read_all():
            epoch_id = entry.get("payload", {}).get("epoch_id")
            if isinstance(epoch_id, str) and epoch_id and epoch_id not in seen:
                seen.append(epoch_id)
        return seen

    def get_expected_epoch_digest(self, epoch_id: str) -> str | None:
        return self.get_epoch_digest(epoch_id)

    def compute_bundle_digest(self, bundle_event: Dict[str, Any]) -> str:
        canonical = {
            "epoch_id": bundle_event.get("epoch_id"),
            "bundle_id": bundle_event.get("bundle_id") or bundle_event.get("certificate", {}).get("bundle_id"),
            "impact": bundle_event.get("impact") or bundle_event.get("impact_score"),
            "strategy_set": bundle_event.get("strategy_set") or bundle_event.get("certificate", {}).get("strategy_set") or [],
            "strategy_snapshot_hash": bundle_event.get("certificate", {}).get("strategy_snapshot_hash", ""),
            "strategy_version_set": bundle_event.get("certificate", {}).get("strategy_version_set", []),
            "certificate": bundle_event.get("certificate") or {},
        }
        material = json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return "sha256:" + hashlib.sha256(material).hexdigest()

    def append_bundle_with_digest(self, epoch_id: str, bundle_event: Dict[str, Any]) -> str:
        previous = self.get_epoch_digest(epoch_id) or "sha256:0"
        bundle_digest = self.compute_bundle_digest(bundle_event)
        chained = hashlib.sha256((previous + bundle_digest).encode("utf-8")).hexdigest()
        epoch_digest = "sha256:" + chained

        payload = dict(bundle_event)
        payload["epoch_id"] = epoch_id
        payload["bundle_digest"] = bundle_digest
        payload["epoch_digest"] = epoch_digest

        self.append_event("MutationBundleEvent", payload)
        self._update_epoch_digest(epoch_id, epoch_digest)
        return epoch_digest

    def get_epoch_digest(self, epoch_id: str) -> Optional[str]:
        if epoch_id in self._epoch_digest_index:
            return self._epoch_digest_index[epoch_id]
        digest: Optional[str] = None
        for entry in self.read_epoch(epoch_id):
            payload = entry.get("payload", {})
            if entry.get("type") == "MutationBundleEvent" and payload.get("epoch_digest"):
                digest = str(payload["epoch_digest"])
            if entry.get("type") == "EpochCheckpointEvent" and payload.get("epoch_digest"):
                digest = str(payload["epoch_digest"])
        if digest:
            self._epoch_digest_index[epoch_id] = digest
        return digest

    def append_competition_epoch(self, event: "SeedCompetitionEpochEvent") -> dict:
        """Append a SeedCompetitionEpochEvent to the ledger.

        COMP-LEDGER-0: Must be called before any candidate is promoted.
        """
        return self.append_event("SeedCompetitionEpochEvent", event.to_dict())

    def _update_epoch_digest(self, epoch_id: str, digest: str) -> None:
        self._epoch_digest_index[epoch_id] = digest

    def compute_incremental_epoch_digest_unverified(self, epoch_id: str) -> str:
        """Recompute epoch digest from recorded bundle payloads without hash-chain integrity checks."""

        digest = "sha256:0"
        entries = self._read_entries_unverified()
        for entry in entries:
            if entry.get("payload", {}).get("epoch_id") != epoch_id:
                continue
            if entry.get("type") != "MutationBundleEvent":
                continue
            payload = dict(entry.get("payload") or {})
            bundle_digest = self.compute_bundle_digest(payload)
            digest = "sha256:" + hashlib.sha256((digest + bundle_digest).encode("utf-8")).hexdigest()
        return digest

    def compute_incremental_epoch_digest(self, epoch_id: str) -> str:
        """Recompute epoch digest after verifying append-only ledger chain integrity."""

        self.verify_integrity()
        return self.compute_incremental_epoch_digest_unverified(epoch_id)

    def compute_cumulative_epoch_digest(self, epoch_id: str) -> str:
        return self.compute_incremental_epoch_digest(epoch_id)

    def compute_epoch_digest(self, epoch_id: str) -> str:
        events = self.read_epoch(epoch_id)
        digest_input: List[Dict[str, Any]] = []
        for event in events:
            payload = dict(event.get("payload") or {})
            digest_input.append(
                {
                    "type": event.get("type"),
                    "payload": payload,
                }
            )
        material = json.dumps(digest_input, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(material).hexdigest()

    def compute_digest(self, epoch_id: str) -> str:
        return self.compute_epoch_digest(epoch_id)


    # ------------------------------------------------------------------
    # PR-PHASE4-07: Lineage-based semantic proximity scoring
    # ------------------------------------------------------------------

    def semantic_proximity_score(
        self,
        candidate_content: str,
        *,
        window: int = 10,
    ) -> dict[str, float]:
        """Compute lineage-based semantic proximity bonuses.

        Compares ``candidate_content`` AST metrics against a rolling mean
        of the last ``window`` accepted mutations stored in the ledger.

        Returns
        -------
        dict with keys:
            proximity_bonus   float ∈ [0.0, 0.15]  — reward for being semantically
                              close to recently accepted lineage
            exploration_bonus float ∈ [0.0, 0.10]  — reward for semantic novelty
        """
        try:
            from runtime.evolution.semantic_diff import SemanticDiffEngine as _SDE
        except Exception:  # noqa: BLE001
            return {"proximity_bonus": 0.0, "exploration_bonus": 0.0}

        # ── Gather recent accepted entries ────────────────────────────
        try:
            entries = self._read_entries_unverified()
        except Exception:  # noqa: BLE001
            return {"proximity_bonus": 0.0, "exploration_bonus": 0.0}

        accepted_entries = [
            e for e in entries
            if e.get("type") in {"mutation_accepted", "mutation_bundle"}
            or (isinstance(e.get("payload"), dict)
                and e["payload"].get("accepted") is True)
        ][-window:]

        if not accepted_entries:
            # No lineage yet — return small exploration bonus for first mutation
            return {"proximity_bonus": 0.0, "exploration_bonus": 0.05}

        # ── Score candidate content ───────────────────────────────────
        engine = _SDE()
        try:
            candidate_diff = engine.diff(before_source="", after_source=candidate_content)
            candidate_risk = candidate_diff.risk_score
            candidate_complexity = candidate_diff.complexity_score
        except Exception:  # noqa: BLE001
            return {"proximity_bonus": 0.0, "exploration_bonus": 0.0}

        # ── Compute rolling mean of accepted lineage AST metrics ──────
        # Use stored risk/complexity values if available, else 0.5 defaults
        risk_vals: list[float] = []
        complexity_vals: list[float] = []
        for entry in accepted_entries:
            payload = entry.get("payload") or entry
            risk_vals.append(float(payload.get("risk_score", 0.5) or 0.5))
            complexity_vals.append(float(payload.get("complexity", 0.5) or 0.5))

        mean_risk = sum(risk_vals) / len(risk_vals)
        mean_complexity = sum(complexity_vals) / len(complexity_vals)

        # ── Cosine-like similarity in 2D (risk, complexity) ──────────
        dot = candidate_risk * mean_risk + candidate_complexity * mean_complexity
        mag_a = (candidate_risk**2 + candidate_complexity**2) ** 0.5
        mag_b = (mean_risk**2 + mean_complexity**2) ** 0.5
        if mag_a < 1e-9 or mag_b < 1e-9:
            similarity = 0.5
        else:
            similarity = max(0.0, min(1.0, dot / (mag_a * mag_b)))

        # ── Map similarity to bonuses ─────────────────────────────────
        # High similarity  → proximity_bonus (similar to accepted ancestors)
        # Low similarity   → exploration_bonus (semantically novel)
        proximity_bonus  = round(min(0.15, similarity * 0.15), 6)
        exploration_bonus = round(min(0.10, (1.0 - similarity) * 0.10), 6)

        return {
            "proximity_bonus": proximity_bonus,
            "exploration_bonus": exploration_bonus,
        }


__all__ = [
    "LineageLedgerV2",
    "LineageEvent",
    "EpochStartEvent",
    "EpochEndEvent",
    "MutationBundleEvent",
    "SeedCompetitionEpochEvent",
    "LEDGER_V2_PATH",
    "LINEAGE_V2_PATH",
    "LineageIntegrityError",
    "LineageRecoveryHook",
    "LineageResolutionError",
    "resolve_chain",
]
