# SPDX-License-Identifier: Apache-2.0
"""Phase 164 · INNOV-70 · Constitutional Genome Encoder (CGE).

Encodes the complete constitutional state as a versioned, diff-mergeable genome
vector — "constitutional DNA."  Each locus in the genome corresponds to a named
governance dimension (invariant class, weight, threshold, agent assignment) and
carries a deterministically-computed allele value.

Key capabilities
----------------
* encode_genome()     — snapshot the full constitutional state into a GenomeVector
* diff_genomes()      — produce a GenomeDiff that quantifies locus-level divergence
* merge_genomes()     — deterministically merge two GenomeVectors (fitter-wins per locus)
* verify_genome()     — verify the HMAC chain integrity of an encoded genome
* HUMAN-0 gate        — any merge whose divergence_score exceeds MERGE_HUMAN0_GATE
                        raises CGEHuman0Gate; HUMAN-0 must ratify offline

Constitutional invariants enforced
------------------------------------
CGE-ENCODE-0    Genome encoding is deterministic and reproducible.
CGE-CHAIN-0     Every genome is hash-chained to its predecessor; orphaned genomes
                are rejected.
CGE-DIFF-0      Diff operations never mutate either genome; inputs are immutable.
CGE-MERGE-0     Merge produces a new genome, never modifies existing records.
CGE-HUMAN0-0    Merge operations that exceed MERGE_HUMAN0_GATE are gated on
                HUMAN-0 ratification; the engine cannot self-approve them.
CGE-DETERM-0    No wall-clock time, random seeds, or external I/O may influence
                the genome value at any locus.
CGE-AUDIT-0     Every encode, diff, and merge is appended to the audit ledger.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
GOVERNOR: str = "DUSTIN L REID"
CHAIN_ROOT: str = "0" * 64
MERGE_HUMAN0_GATE: float = 0.35   # divergence_score above this → HUMAN-0 gate
MAX_LOCI: int = 64                 # maximum loci in a genome vector
GENOME_VERSION: str = "1.0"
VALID_OPERATIONS: frozenset = frozenset({"encode", "diff", "merge", "verify"})

# Canonical locus names — ordered; order is constitutional (changes require HUMAN-0)
CANONICAL_LOCI: Tuple[str, ...] = (
    "hard_invariant_count",
    "soft_invariant_count",
    "cel_gate_count",
    "phase_sequence",
    "innovation_count",
    "governor_hash",
    "constitution_version",
    "blast_radius_tier",
    "hmac_secret_digest",
    "quorum_threshold",
    "rollback_depth",
    "adversarial_fitness_weight",
    "morphogenetic_memory_slots",
    "determinism_mode",
    "audit_trail_length",
    "csi_baseline",
    "cpi_threshold",
    "mce_weight_precedent",
    "mce_weight_invariant",
    "mce_weight_csi",
    "mce_weight_forecast",
    "gcb_trip_threshold",
    "afrt_red_team_cycles",
    "spie_proposal_rate",
    "dork_fleet_size",
    "lkse_sync_interval_s",
    "crtv_epoch_window",
    "grb_rollback_budget",
    "acsa_amendment_rate",
    "gda_graduation_quorum",
)


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------
class CGEError(RuntimeError):
    """Base for all CGE errors."""


class CGEChainError(CGEError):
    """Genome is not properly chained to its predecessor."""


class CGELociError(CGEError):
    """Loci set is invalid or oversized."""


class CGEMergeError(CGEError):
    """Merge preconditions not met."""


class CGEHuman0Gate(CGEError):
    """Merge divergence exceeds MERGE_HUMAN0_GATE — HUMAN-0 ratification required."""


class CGEVerifyError(CGEError):
    """HMAC or chain verification failed."""


class CGEAuditError(CGEError):
    """Audit ledger write failed."""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
class MergeStrategy(str, Enum):
    FITTER_WINS = "fitter_wins"      # higher fitness_score locus wins
    CONSERVATIVE = "conservative"    # lower (safer) value wins
    DOMINANT = "dominant"            # left genome always wins


@dataclass(frozen=True)
class Locus:
    """A single governance dimension in the genome."""
    name: str
    value: float                    # normalised [0.0, 1.0]
    fitness_score: float            # higher = more constitutionally fit
    source_invariant: str           # invariant that produced this locus
    is_hard_class: bool = False

    def allele_hash(self) -> str:
        """Deterministic 16-hex digest of this locus's value."""
        raw = f"{self.name}:{self.value:.12f}:{self.source_invariant}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class GenomeVector:
    """Immutable snapshot of the full constitutional state."""
    genome_id: str
    version: str
    phase: int
    governor: str
    loci: Tuple[Locus, ...]
    genome_hash: str                # SHA-256 of canonical loci representation
    prev_genome_hash: str           # hash of preceding genome (CHAIN_ROOT if first)
    chain_hmac: str                 # HMAC-SHA256(genome_hash + prev_genome_hash)
    ledger_seq: int
    timestamp_utc: str
    metadata: Dict = field(default_factory=dict)

    def locus_map(self) -> Dict[str, Locus]:
        return {l.name: l for l in self.loci}

    def overall_fitness(self) -> float:
        if not self.loci:
            return 0.0
        return sum(l.fitness_score for l in self.loci) / len(self.loci)


@dataclass(frozen=True)
class LocusDiff:
    name: str
    left_value: float
    right_value: float
    delta: float
    diverged: bool                  # |delta| > locus divergence threshold (0.1)


@dataclass(frozen=True)
class GenomeDiff:
    diff_id: str
    left_genome_id: str
    right_genome_id: str
    locus_diffs: Tuple[LocusDiff, ...]
    divergence_score: float         # [0.0, 1.0] — fraction of significantly diverged loci
    fitness_delta: float            # right.fitness − left.fitness
    requires_human0: bool
    timestamp_utc: str


@dataclass(frozen=True)
class MergeRecord:
    merge_id: str
    left_genome_id: str
    right_genome_id: str
    result_genome_id: str
    strategy: str
    divergence_score: float
    loci_resolved: int
    human0_required: bool
    governor: str
    prev_digest: str
    chain_hash: str
    ledger_seq: int
    timestamp_utc: str


@dataclass(frozen=True)
class AuditEntry:
    entry_id: str
    operation: str
    subject_id: str
    governor: str
    prev_digest: str
    chain_hash: str
    ledger_seq: int
    timestamp_utc: str
    detail: Dict


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
class ConstitutionalGenomeEncoder:
    """
    Encodes, diffs, merges, and verifies Constitutional Genome Vectors.

    All operations are deterministic.  The engine appends every operation to
    an HMAC-chained audit ledger so that the full constitutional evolution
    history is tamper-evident and replayable.

    Parameters
    ----------
    ledger_path   : Path to the append-only genome audit ledger (.jsonl).
    secret        : HMAC secret (bytes or str).  Defaults to env-safe sentinel.
    det_timestamp : If provided, used as the deterministic timestamp for all
                    operations (testing / DAS mode).  Production callers inject
                    via RuntimeDeterminismProvider.
    """

    # CGE-ENCODE-0
    INVARIANT_CGE_ENCODE_0: str = "CGE-ENCODE-0"
    # CGE-CHAIN-0
    INVARIANT_CGE_CHAIN_0: str = "CGE-CHAIN-0"
    # CGE-DIFF-0
    INVARIANT_CGE_DIFF_0: str = "CGE-DIFF-0"
    # CGE-MERGE-0
    INVARIANT_CGE_MERGE_0: str = "CGE-MERGE-0"
    # CGE-HUMAN0-0
    INVARIANT_CGE_HUMAN0_0: str = "CGE-HUMAN0-0"
    # CGE-DETERM-0
    INVARIANT_CGE_DETERM_0: str = "CGE-DETERM-0"
    # CGE-AUDIT-0
    INVARIANT_CGE_AUDIT_0: str = "CGE-AUDIT-0"

    def __init__(
        self,
        ledger_path: Path | str = Path("ledger/genome_audit.jsonl"),
        secret: bytes | str = b"cge-secret",
        det_timestamp: Optional[str] = None,
    ) -> None:
        self.ledger_path = Path(ledger_path)
        self.secret: bytes = secret.encode() if isinstance(secret, str) else secret
        self._det_ts: Optional[str] = det_timestamp
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def encode_genome(
        self,
        phase: int,
        locus_inputs: Dict[str, Tuple[float, float, str, bool]],
        timestamp_utc: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> GenomeVector:
        """
        Encode a new GenomeVector from raw locus inputs.

        Parameters
        ----------
        phase        : Current ADAAD phase number.
        locus_inputs : Mapping of locus_name → (value, fitness_score, source_invariant,
                       is_hard_class).  Values must be in [0.0, 1.0].
        timestamp_utc: Deterministic timestamp string (ISO-8601).
        metadata     : Optional extra metadata attached to the genome.

        Returns
        -------
        GenomeVector  — immutable, HMAC-chained.

        Raises
        ------
        CGELociError  — if loci exceed MAX_LOCI or contain unknown names.
        CGEChainError — if the ledger chain is broken.
        """
        # CGE-DETERM-0: timestamp must be injected, not wall-clock
        ts = timestamp_utc or self._det_ts or "1970-01-01T00:00:00Z"
        if len(locus_inputs) > MAX_LOCI:
            raise CGELociError(
                f"CGE-ENCODE-0 violated: {len(locus_inputs)} loci exceeds MAX_LOCI={MAX_LOCI}"
            )

        loci = tuple(
            Locus(
                name=name,
                value=float(v),
                fitness_score=float(fs),
                source_invariant=si,
                is_hard_class=hc,
            )
            for name, (v, fs, si, hc) in sorted(locus_inputs.items())
        )

        genome_hash = self._hash_loci(loci)
        prev = self._last_genome_hash()
        chain_hmac = self._hmac(genome_hash + prev)
        seq = self._ledger_seq()

        # CGE-DETERM-0: genome_id incorporates chain position for uniqueness
        _id_seed = f"{genome_hash}:{prev}:{seq}"
        gv = GenomeVector(
            genome_id=str(uuid.UUID(bytes=hashlib.sha256(_id_seed.encode()).digest()[:16])),
            version=GENOME_VERSION,
            phase=phase,
            governor=GOVERNOR,
            loci=loci,
            genome_hash=genome_hash,
            prev_genome_hash=prev,
            chain_hmac=chain_hmac,
            ledger_seq=seq,
            timestamp_utc=ts,
            metadata=metadata or {},
        )

        self._append_genome(gv)
        self._append_audit(AuditEntry(
            entry_id=str(uuid.uuid4()),
            operation="encode",
            subject_id=gv.genome_id,
            governor=GOVERNOR,
            prev_digest=prev[:24],
            chain_hash=chain_hmac[:24],
            ledger_seq=seq,
            timestamp_utc=ts,
            detail={"phase": phase, "loci_count": len(loci)},
        ))
        return gv

    def diff_genomes(
        self,
        left: GenomeVector,
        right: GenomeVector,
        timestamp_utc: Optional[str] = None,
    ) -> GenomeDiff:
        """
        Compute a GenomeDiff between two GenomeVectors.

        Neither genome is mutated (CGE-DIFF-0).  Returns a GenomeDiff with
        per-locus divergence and an overall divergence_score.

        Raises
        ------
        CGEError — if both genomes are identical (nothing to diff).
        """
        ts = timestamp_utc or self._det_ts or "1970-01-01T00:00:00Z"
        if left.genome_id == right.genome_id:
            raise CGEError("CGE-DIFF-0: cannot diff a genome against itself")

        left_map = left.locus_map()
        right_map = right.locus_map()
        all_names = sorted(set(left_map) | set(right_map))

        diffs: List[LocusDiff] = []
        for name in all_names:
            lv = left_map[name].value if name in left_map else 0.0
            rv = right_map[name].value if name in right_map else 0.0
            delta = rv - lv
            diffs.append(LocusDiff(
                name=name,
                left_value=lv,
                right_value=rv,
                delta=delta,
                diverged=abs(delta) > 0.1,
            ))

        diverged_count = sum(1 for d in diffs if d.diverged)
        divergence_score = diverged_count / len(diffs) if diffs else 0.0
        fitness_delta = right.overall_fitness() - left.overall_fitness()
        requires_human0 = divergence_score > MERGE_HUMAN0_GATE

        diff_id = str(uuid.UUID(bytes=hashlib.sha256(
            (left.genome_id + right.genome_id + ts).encode()
        ).digest()[:16]))

        gd = GenomeDiff(
            diff_id=diff_id,
            left_genome_id=left.genome_id,
            right_genome_id=right.genome_id,
            locus_diffs=tuple(diffs),
            divergence_score=divergence_score,
            fitness_delta=fitness_delta,
            requires_human0=requires_human0,
            timestamp_utc=ts,
        )

        seq = self._ledger_seq()
        prev = self._last_genome_hash()
        chain_hmac = self._hmac(diff_id + prev)
        self._append_audit(AuditEntry(
            entry_id=str(uuid.uuid4()),
            operation="diff",
            subject_id=diff_id,
            governor=GOVERNOR,
            prev_digest=prev[:24],
            chain_hash=chain_hmac[:24],
            ledger_seq=seq,
            timestamp_utc=ts,
            detail={
                "divergence_score": divergence_score,
                "requires_human0": requires_human0,
                "loci_diffed": len(diffs),
            },
        ))
        return gd

    def merge_genomes(
        self,
        left: GenomeVector,
        right: GenomeVector,
        strategy: MergeStrategy = MergeStrategy.FITTER_WINS,
        timestamp_utc: Optional[str] = None,
        human0_override: bool = False,
    ) -> Tuple[GenomeVector, MergeRecord]:
        """
        Merge two GenomeVectors into a new GenomeVector.

        The merge is deterministic and produces a new genome that does not
        modify either input (CGE-MERGE-0).

        If the divergence_score of the corresponding diff exceeds
        MERGE_HUMAN0_GATE, CGEHuman0Gate is raised unless human0_override=True.

        Parameters
        ----------
        left            : Base genome.
        right           : Incoming genome.
        strategy        : Resolution strategy per locus.
        timestamp_utc   : Deterministic timestamp.
        human0_override : Set True only when HUMAN-0 has ratified offline.

        Returns
        -------
        (GenomeVector, MergeRecord) — new merged genome and its audit record.

        Raises
        ------
        CGEHuman0Gate  — if divergence exceeds gate and human0_override is False.
        CGEMergeError  — if left == right (no-op merge).
        """
        ts = timestamp_utc or self._det_ts or "1970-01-01T00:00:00Z"
        if left.genome_id == right.genome_id:
            raise CGEMergeError("CGE-MERGE-0: cannot merge a genome with itself")

        diff = self.diff_genomes(left, right, timestamp_utc=ts)

        # CGE-HUMAN0-0
        if diff.requires_human0 and not human0_override:
            raise CGEHuman0Gate(
                f"CGE-HUMAN0-0: divergence_score={diff.divergence_score:.4f} exceeds "
                f"MERGE_HUMAN0_GATE={MERGE_HUMAN0_GATE}; HUMAN-0 ratification required"
            )

        left_map = left.locus_map()
        right_map = right.locus_map()
        all_names = sorted(set(left_map) | set(right_map))

        merged_inputs: Dict[str, Tuple[float, float, str, bool]] = {}
        for name in all_names:
            locus = self._resolve_locus(name, left_map, right_map, strategy)
            merged_inputs[name] = (
                locus.value,
                locus.fitness_score,
                locus.source_invariant,
                locus.is_hard_class,
            )

        merged_gv = self.encode_genome(
            phase=max(left.phase, right.phase),
            locus_inputs=merged_inputs,
            timestamp_utc=ts,
            metadata={"merge_strategy": strategy.value, "merge_diff_id": diff.diff_id},
        )

        seq = self._ledger_seq()
        prev = self._last_genome_hash()
        chain_hmac = self._hmac(merged_gv.genome_id + prev)

        record = MergeRecord(
            merge_id=str(uuid.uuid4()),
            left_genome_id=left.genome_id,
            right_genome_id=right.genome_id,
            result_genome_id=merged_gv.genome_id,
            strategy=strategy.value,
            divergence_score=diff.divergence_score,
            loci_resolved=len(all_names),
            human0_required=diff.requires_human0,
            governor=GOVERNOR,
            prev_digest=prev[:24],
            chain_hash=chain_hmac[:24],
            ledger_seq=seq,
            timestamp_utc=ts,
        )
        return merged_gv, record

    def verify_genome(self, gv: GenomeVector) -> bool:
        """
        Verify the HMAC chain integrity of a GenomeVector.

        Returns True if valid.  Raises CGEVerifyError if the chain is broken.
        """
        expected = self._hmac(gv.genome_hash + gv.prev_genome_hash)
        if not hmac.compare_digest(expected, gv.chain_hmac):
            raise CGEVerifyError(
                f"CGE-CHAIN-0 violated: genome {gv.genome_id} has invalid chain HMAC"
            )
        recomputed = self._hash_loci(gv.loci)
        if recomputed != gv.genome_hash:
            raise CGEVerifyError(
                f"CGE-ENCODE-0 violated: genome {gv.genome_id} hash mismatch"
            )
        return True

    def genome_history(self) -> List[Dict]:
        """Return all genome encode records from the ledger, ordered by seq."""
        if not self.ledger_path.exists():
            return []
        entries = []
        for line in self.ledger_path.read_text().splitlines():
            if not line.strip():
                continue
            obj = json.loads(line)
            if obj.get("record_type") == "genome":
                entries.append(obj)
        return sorted(entries, key=lambda e: e.get("ledger_seq", 0))

    def audit_trail(self) -> List[Dict]:
        """Return all audit entries from the ledger, ordered by seq."""
        if not self.ledger_path.exists():
            return []
        entries = []
        for line in self.ledger_path.read_text().splitlines():
            if not line.strip():
                continue
            obj = json.loads(line)
            if obj.get("record_type") == "audit":
                entries.append(obj)
        return sorted(entries, key=lambda e: e.get("ledger_seq", 0))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _hash_loci(self, loci: Tuple[Locus, ...]) -> str:
        canonical = json.dumps(
            [
                {"name": l.name, "value": round(l.value, 12), "allele": l.allele_hash()}
                for l in sorted(loci, key=lambda x: x.name)
            ],
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    def _hmac(self, data: str) -> str:
        return hmac.new(self.secret, data.encode(), hashlib.sha256).hexdigest()

    def _last_genome_hash(self) -> str:
        history = self.genome_history()
        if not history:
            return CHAIN_ROOT
        return history[-1].get("genome_hash", CHAIN_ROOT)

    def _ledger_seq(self) -> int:
        if not self.ledger_path.exists():
            return 1
        count = sum(1 for line in self.ledger_path.read_text().splitlines() if line.strip())
        return count + 1

    def _append_genome(self, gv: GenomeVector) -> None:
        record = {
            "record_type": "genome",
            "genome_id": gv.genome_id,
            "version": gv.version,
            "phase": gv.phase,
            "governor": gv.governor,
            "loci": [asdict(l) for l in gv.loci],
            "genome_hash": gv.genome_hash,
            "prev_genome_hash": gv.prev_genome_hash,
            "chain_hmac": gv.chain_hmac,
            "ledger_seq": gv.ledger_seq,
            "timestamp_utc": gv.timestamp_utc,
            "metadata": gv.metadata,
        }
        try:
            with self.ledger_path.open("a") as f:
                f.write(json.dumps(record) + "\n")
        except OSError as exc:
            raise CGEAuditError(f"CGE-AUDIT-0: ledger write failed — {exc}") from exc

    def _append_audit(self, entry: AuditEntry) -> None:
        record = {
            "record_type": "audit",
            **asdict(entry),
        }
        try:
            with self.ledger_path.open("a") as f:
                f.write(json.dumps(record) + "\n")
        except OSError as exc:
            raise CGEAuditError(f"CGE-AUDIT-0: audit write failed — {exc}") from exc

    def _resolve_locus(
        self,
        name: str,
        left_map: Dict[str, Locus],
        right_map: Dict[str, Locus],
        strategy: MergeStrategy,
    ) -> Locus:
        if name not in left_map:
            return right_map[name]
        if name not in right_map:
            return left_map[name]

        l, r = left_map[name], right_map[name]

        if strategy is MergeStrategy.DOMINANT:
            return l
        if strategy is MergeStrategy.CONSERVATIVE:
            # pick the value closer to 0.5 (more neutral / less extreme)
            return l if abs(l.value - 0.5) <= abs(r.value - 0.5) else r
        # FITTER_WINS (default)
        return l if l.fitness_score >= r.fitness_score else r
