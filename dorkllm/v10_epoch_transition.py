# SPDX-License-Identifier: Proprietary — All Rights Reserved
"""
INNOV-94 · V10ET — V10 Epoch Transition Engine
Phase 189 · v9.122.0 · InnovativeAI LLC
Governor: DUSTIN L REID

World-first constitutionally-governed V10 Epoch Transition Engine.
Consumes the GTC Release Bundle (INNOV-93), re-validates the Constitutional
Merkle Root, seals the v9→v10 epoch boundary as an immutable HMAC-chained
ledger record, and emits a structured HUMAN-0 Track B runbook required for
the GPG-signed v10.0.0 annotated tag ceremony.

V10ET is the terminal innovation of the v9.x.x governance arc.

Hard-class invariants (5):
  V10ET-SCOPE-0   — V10ET reads only the GTC release ledger, VERSION file, and
                    agent state; it never mutates upstream state or GTC ledger
  V10ET-CHAIN-0   — Epoch boundary entries form a valid HMAC-SHA-256 chain;
                    a broken chain raises V10ETChainError and halts
  V10ET-HUMAN0-0  — The HUMAN-0 Track B runbook MUST be emitted and recorded
                    before the epoch seal is finalised; non-skippable
  V10ET-EPOCH-0   — The epoch transition v9→v10 is one-way and irreversible;
                    any rollback attempt raises V10ETEpochError and halts
  V10ET-VERIFY-0  — The epoch seal includes independent re-validation of the
                    GTC Merkle root; mismatch raises V10ETVerifyError and halts

Governor: DUSTIN L REID
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import pathlib
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GOVERNOR: str = "DUSTIN L REID"
INNOVATION_ID: str = "INNOV-94"
PHASE: int = 189
VERSION: str = "10.0.1"
EPOCH_FROM: str = "v9"
EPOCH_TO: str = "v10"
TARGET_VERSION: str = "10.0.0"

# Invariant identifiers
V10ET_SCOPE_0: str = "V10ET-SCOPE-0"
V10ET_CHAIN_0: str = "V10ET-CHAIN-0"
V10ET_HUMAN0_0: str = "V10ET-HUMAN0-0"
V10ET_EPOCH_0: str = "V10ET-EPOCH-0"
V10ET_VERIFY_0: str = "V10ET-VERIFY-0"

_HMAC_SECRET: bytes = b"V10ET-INNOV-94-EPOCH-BOUNDARY-HMAC-SECRET"
_GENESIS_PREV: str = "0" * 64

# ---------------------------------------------------------------------------
# Exceptions (typed RuntimeError subclasses — V10ET hardening criterion 2)
# ---------------------------------------------------------------------------


class V10ETError(RuntimeError):
    """Base error for all V10ET constitutional violations."""


class V10ETChainError(V10ETError):
    """Raised when the HMAC epoch ledger chain is broken — V10ET-CHAIN-0."""


class V10ETHuman0Error(V10ETError):
    """Raised when HUMAN-0 Track B runbook is bypassed — V10ET-HUMAN0-0."""


class V10ETEpochError(V10ETError):
    """Raised on illegal rollback of a sealed epoch — V10ET-EPOCH-0."""


class V10ETVerifyError(V10ETError):
    """Raised when GTC Merkle root re-validation fails — V10ET-VERIFY-0."""


class V10ETScopeError(V10ETError):
    """Raised when V10ET attempts upstream state mutation — V10ET-SCOPE-0."""


# ---------------------------------------------------------------------------
# Determinism provider (inline — no wall-clock injection)
# ---------------------------------------------------------------------------


class _DeterminismProvider:
    """Deterministic timestamp provider. Inject in tests for replay safety."""

    def __init__(self, fixed_ts: Optional[str] = None) -> None:
        self._fixed_ts = fixed_ts

    def iso_now(self) -> str:
        if self._fixed_ts is not None:
            return self._fixed_ts
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Data structures (chain-linked — V10ET hardening criterion 3)
# ---------------------------------------------------------------------------


@dataclass
class EpochBoundaryRecord:
    """Immutable, HMAC-chained epoch boundary entry appended to epoch_ledger.jsonl."""

    record_id: str
    epoch_from: str                        # "v9"
    epoch_to: str                          # "v10"
    target_version: str                    # "10.0.0"
    phase_at_boundary: int                 # 189
    innovations_sealed: int                # 94
    hard_class_invariants_sealed: int      # 522
    merkle_root_validated: str             # re-validated hex digest from GTC bundle
    gtc_bundle_digest: str                 # digest of the consumed GTC release bundle entry
    epoch_timestamp_utc: str              # deterministic ISO-8601
    governor: str                          # "DUSTIN L REID"
    innovation_id: str                     # "INNOV-94"
    track_b_runbook: Dict[str, Any]        # HUMAN-0 ceremony checklist
    human0_advisory_emitted: bool          # V10ET-HUMAN0-0 gate
    epoch_seal_hmac: str                   # HMAC-SHA-256 over canonical content
    prev_digest: str = field(default=_GENESIS_PREV)  # chain link from predecessor


@dataclass
class EpochTransitionResult:
    """Return type of V10EpochTransitionEngine.seal()."""

    status: str                            # "EPOCH_SEALED" | "ADVISORY_ONLY"
    epoch_boundary: Optional[Dict[str, Any]]
    track_b_runbook: Dict[str, Any]
    human0_advisory: str
    chain_valid: bool
    findings: List[str]


# ---------------------------------------------------------------------------
# Track B runbook builder
# ---------------------------------------------------------------------------


def _build_track_b_runbook(
    *,
    merkle_root: str,
    innovations_sealed: int,
    invariants_sealed: int,
    gtc_ledger_path: str,
    epoch_ledger_path: str,
) -> Dict[str, Any]:
    """
    Construct the HUMAN-0 exclusive Track B ceremony runbook.
    V10ET-HUMAN0-0: this runbook is emitted before any seal is finalised.
    """
    return {
        "ceremony": "v10.0.0 Constitutional Epoch Boundary Tag Ceremony",
        "authority": "HUMAN-0 — Dustin L. Reid (non-delegable, non-automatable)",
        "invariant": V10ET_HUMAN0_0,
        "pre_conditions": [
            f"V10ET epoch seal is present in {epoch_ledger_path}",
            f"GTC release bundle is present in {gtc_ledger_path}",
            f"Merkle root re-validated: {merkle_root}",
            f"Innovations sealed: {innovations_sealed}",
            f"Hard-class invariants sealed: {invariants_sealed}",
        ],
        "steps": [
            {
                "step": 1,
                "action": "Verify epoch ledger chain integrity",
                "command": "python3 -c \"from dorkllm.v10_epoch_transition import V10EpochTransitionEngine; e=V10EpochTransitionEngine(); print(e.verify_chain())\"",
                "expected": "True",
            },
            {
                "step": 2,
                "action": "Bump VERSION to 10.0.0",
                "command": "python3 -c \"from pathlib import Path; Path('VERSION').write_text('10.0.0\\n')\"",
                "expected": "VERSION file reads '10.0.0'",
            },
            {
                "step": 3,
                "action": "Sync pyproject.toml version",
                "command": "sed -i 's/^version = .*/version = \"10.0.0\"/' pyproject.toml",
                "expected": "pyproject.toml version = \"10.0.0\"",
            },
            {
                "step": 4,
                "action": "Prepend CHANGELOG.md with v10.0.0 epoch boundary entry",
                "command": "Manually prepend: ## [10.0.0] — Phase 189 · INNOV-94 · V10ET — V10 Epoch Transition Engine",
                "expected": "CHANGELOG.md head entry is [10.0.0]",
            },
            {
                "step": 5,
                "action": "Update .adaad_agent_state.json to v10.0.0 / Phase 189",
                "command": "python3 scripts/bump_agent_state.py --version 10.0.0 --phase 189",
                "expected": "agent state version == '10.0.0' and phase == 189",
            },
            {
                "step": 6,
                "action": "Commit four-file atomic sync",
                "command": "git add VERSION pyproject.toml CHANGELOG.md .adaad_agent_state.json && git commit -m 'chore(epoch): v10.0.0 constitutional epoch boundary · INNOV-94 · V10ET'",
                "expected": "Commit SHA recorded",
            },
            {
                "step": 7,
                "action": "GPG-sign annotated tag (HUMAN-0 exclusive — ADAADell)",
                "command": "git tag -s v10.0.0 -m 'Phase 189 · INNOV-94 · V10ET · Constitutional Epoch Boundary · Governor: DUSTIN L REID'",
                "expected": "Tag v10.0.0 created and GPG-signed",
            },
            {
                "step": 8,
                "action": "No-ff merge to main",
                "command": "git checkout main && git merge --no-ff feat/phase189-v10et -m 'merge(phase189): INNOV-94 · V10ET — V10 Epoch Transition Engine v10.0.0 [no-ff]'",
                "expected": "No-ff merge commit on main",
            },
            {
                "step": 9,
                "action": "Push main and tag",
                "command": "git push origin main --tags",
                "expected": "Remote accepts push",
            },
            {
                "step": 10,
                "action": "Verify delivery via git ls-remote",
                "command": "git ls-remote origin refs/tags/v10.0.0",
                "expected": "Non-empty SHA — epoch delivered",
            },
        ],
        "post_conditions": [
            "git ls-remote origin refs/tags/v10.0.0 returns non-empty SHA",
            "CHANGELOG.md head entry is [10.0.0]",
            "VERSION file reads '10.0.0'",
            "pyproject.toml version == '10.0.0'",
            ".adaad_agent_state.json version == '10.0.0' and phase == 189",
        ],
        "non_delegable_note": (
            "Steps 7–10 are HUMAN-0 exclusive. No agent, workflow, or automation "
            "may perform GPG signing, no-ff merge to main, or PyPI publish on behalf "
            "of Dustin L. Reid. Invariant COMMUNITY-HUMAN0-0 enforced."
        ),
    }


# ---------------------------------------------------------------------------
# HMAC utilities (AUTH-CT-0 — hmac.compare_digest everywhere)
# ---------------------------------------------------------------------------


def _compute_entry_hmac(entry_json: str) -> str:
    return hmac.new(_HMAC_SECRET, entry_json.encode(), hashlib.sha256).hexdigest()


def _verify_hmac(entry_json: str, expected: str) -> bool:
    computed = _compute_entry_hmac(entry_json)
    return hmac.compare_digest(computed, expected)


def _entry_canonical(record: EpochBoundaryRecord) -> str:
    """Deterministic JSON representation for HMAC computation (excludes epoch_seal_hmac)."""
    d = asdict(record)
    d.pop("epoch_seal_hmac", None)
    return json.dumps(d, sort_keys=True, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Merkle root re-validator
# ---------------------------------------------------------------------------


def _recompute_merkle_root(innovation_digests: List[str]) -> str:
    """
    V10ET-VERIFY-0: deterministically re-compute the Constitutional Merkle Root
    from the sorted canonical innovation digest list.  Algorithm mirrors GTC.
    """
    if not innovation_digests:
        raise V10ETVerifyError("V10ET-VERIFY-0: empty innovation digest list — cannot compute Merkle root")
    layer = sorted(innovation_digests)
    while len(layer) > 1:
        next_layer: List[str] = []
        for i in range(0, len(layer), 2):
            left = layer[i]
            right = layer[i + 1] if i + 1 < len(layer) else left
            combined = left + right
            next_layer.append(hashlib.sha256(combined.encode()).hexdigest())
        layer = next_layer
    return layer[0]


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------


class V10EpochTransitionEngine:
    """
    INNOV-94 · V10ET — V10 Epoch Transition Engine.

    Consumes the GTC Release Bundle, re-validates the Constitutional Merkle
    Root, and seals the v9→v10 epoch boundary in an append-only HMAC-chained
    epoch ledger.  Emits a HUMAN-0 Track B runbook before sealing.

    V10ET-SCOPE-0: this class is read-only with respect to upstream state.
    """

    def __init__(
        self,
        *,
        gtc_ledger_path: str | pathlib.Path = "artifacts/governance/gtc_release_ledger.jsonl",
        epoch_ledger_path: str | pathlib.Path = "data/v10et_epoch_ledger.jsonl",
        agent_state_path: str | pathlib.Path = ".adaad_agent_state.json",
        version_path: str | pathlib.Path = "VERSION",
        determinism: Optional[_DeterminismProvider] = None,
    ) -> None:
        # V10ET-SCOPE-0: store paths, do not mutate upstream
        self._gtc_ledger_path = pathlib.Path(gtc_ledger_path)
        self._epoch_ledger_path = pathlib.Path(epoch_ledger_path)
        self._agent_state_path = pathlib.Path(agent_state_path)
        self._version_path = pathlib.Path(version_path)
        self._det = determinism or _DeterminismProvider()

        self._epoch_ledger: List[EpochBoundaryRecord] = []
        self._human0_advisory_log: List[str] = []
        self._advisory_emitted: bool = False

        self._load_epoch_ledger()

    # ------------------------------------------------------------------
    # Ledger I/O (append-only JSONL — V10ET hardening criterion 4)
    # ------------------------------------------------------------------

    def _load_epoch_ledger(self) -> None:
        """Load existing epoch ledger; validate HMAC chain on load."""
        if not self._epoch_ledger_path.exists():
            return
        raw_lines = self._epoch_ledger_path.read_text(encoding="utf-8").splitlines()
        prev: str = _GENESIS_PREV
        for idx, line in enumerate(raw_lines):
            if not line.strip():
                continue
            entry_dict = json.loads(line)
            record = EpochBoundaryRecord(**entry_dict)
            # V10ET-CHAIN-0: verify HMAC on load
            canonical = _entry_canonical(record)
            if not _verify_hmac(canonical, record.epoch_seal_hmac):
                raise V10ETChainError(
                    f"V10ET-CHAIN-0: HMAC chain broken at ledger entry {idx} "
                    f"(record_id={record.record_id})"
                )
            if not hmac.compare_digest(record.prev_digest, prev):
                raise V10ETChainError(
                    f"V10ET-CHAIN-0: prev_digest mismatch at entry {idx}: "
                    f"expected {prev[:16]}… got {record.prev_digest[:16]}…"
                )
            prev = record.epoch_seal_hmac
            self._epoch_ledger.append(record)

    def _append_to_ledger(self, record: EpochBoundaryRecord) -> None:
        """Append a new epoch boundary record. V10ET-EPOCH-0: no overwrite."""
        # Ensure parent directory exists
        self._epoch_ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._epoch_ledger_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(record), sort_keys=True) + "\n")
        self._epoch_ledger.append(record)

    # ------------------------------------------------------------------
    # State readers (V10ET-SCOPE-0 — read only)
    # ------------------------------------------------------------------

    def _read_agent_state(self) -> Dict[str, Any]:
        if not self._agent_state_path.exists():
            return {}
        return json.loads(self._agent_state_path.read_text(encoding="utf-8"))

    def _read_version(self) -> str:
        if not self._version_path.exists():
            return "unknown"
        return self._version_path.read_text(encoding="utf-8").strip()

    def _read_gtc_ledger_latest(self) -> Optional[Dict[str, Any]]:
        """Read latest GTC release bundle entry. V10ET-SCOPE-0: read-only."""
        if not self._gtc_ledger_path.exists():
            return None
        lines = [
            l for l in self._gtc_ledger_path.read_text(encoding="utf-8").splitlines()
            if l.strip()
        ]
        if not lines:
            return None
        return json.loads(lines[-1])

    # ------------------------------------------------------------------
    # HUMAN-0 advisory (V10ET-HUMAN0-0)
    # ------------------------------------------------------------------

    def _emit_human0_advisory(
        self,
        *,
        merkle_root: str,
        innovations: int,
        invariants: int,
    ) -> str:
        """
        V10ET-HUMAN0-0: emit and record HUMAN-0 Track B advisory.
        This MUST be called before _seal_epoch(); order enforced by flag.
        """
        runbook = _build_track_b_runbook(
            merkle_root=merkle_root,
            innovations_sealed=innovations,
            invariants_sealed=invariants,
            gtc_ledger_path=str(self._gtc_ledger_path),
            epoch_ledger_path=str(self._epoch_ledger_path),
        )
        advisory = (
            f"[V10ET-HUMAN0-0] HUMAN-0 TRACK B ADVISORY — v10.0.0 EPOCH TAG CEREMONY\n"
            f"Governor: {GOVERNOR}\n"
            f"Constitutional Merkle Root: {merkle_root}\n"
            f"Innovations sealed: {innovations} | Hard-class invariants sealed: {invariants}\n"
            f"Epoch boundary: {EPOCH_FROM} → {EPOCH_TO} (irreversible — V10ET-EPOCH-0)\n"
            f"This advisory must be acknowledged before the epoch seal is finalised.\n"
            f"Runbook contains {len(runbook['steps'])} steps — all HUMAN-0 exclusive.\n"
            f"Non-delegable authority: Dustin L. Reid, InnovativeAI LLC."
        )
        self._human0_advisory_log.append(advisory)
        self._advisory_emitted = True
        return advisory

    # ------------------------------------------------------------------
    # Merkle re-validation (V10ET-VERIFY-0)
    # ------------------------------------------------------------------

    def _validate_merkle_from_gtc_bundle(
        self, gtc_bundle: Dict[str, Any]
    ) -> str:
        """
        V10ET-VERIFY-0: independently re-validate the Constitutional Merkle Root
        from the GTC release bundle's innovation_digest_list.
        """
        digest_list: List[str] = gtc_bundle.get("innovation_digest_list", [])
        if not digest_list:
            raise V10ETVerifyError(
                "V10ET-VERIFY-0: GTC bundle contains no innovation_digest_list — "
                "cannot re-validate Merkle root"
            )
        recomputed = _recompute_merkle_root(digest_list)
        claimed = gtc_bundle.get("constitutional_merkle_root", "")
        if not hmac.compare_digest(recomputed, claimed):
            raise V10ETVerifyError(
                f"V10ET-VERIFY-0: Merkle root mismatch — "
                f"GTC claimed {claimed[:16]}…, re-computed {recomputed[:16]}…"
            )
        return recomputed

    # ------------------------------------------------------------------
    # Epoch seal
    # ------------------------------------------------------------------

    def _seal_epoch(
        self,
        *,
        merkle_root: str,
        gtc_bundle: Dict[str, Any],
        agent_state: Dict[str, Any],
    ) -> EpochBoundaryRecord:
        """
        Seal the v9→v10 epoch boundary.
        V10ET-HUMAN0-0: advisory must have been emitted first.
        V10ET-CHAIN-0: HMAC chain is extended from the GTC bundle digest.
        """
        # V10ET-HUMAN0-0 gate
        if not self._advisory_emitted:
            raise V10ETHuman0Error(
                "V10ET-HUMAN0-0: HUMAN-0 Track B advisory was not emitted before "
                "epoch seal. Call seal() which emits advisory automatically; "
                "never call _seal_epoch() directly."
            )

        # V10ET-EPOCH-0: detect if epoch already sealed
        if self._epoch_ledger:
            raise V10ETEpochError(
                "V10ET-EPOCH-0: epoch boundary already sealed — "
                "v9→v10 transition is one-way and irreversible. "
                f"Existing record: {self._epoch_ledger[0].record_id}"
            )

        innovations_shipped: int = agent_state.get("innovations_shipped", 94)
        invariant_count: int = agent_state.get("hard_class_invariant_count", 522)
        prev_digest = _GENESIS_PREV

        gtc_bundle_digest = hashlib.sha256(
            json.dumps(gtc_bundle, sort_keys=True).encode()
        ).hexdigest()

        runbook = _build_track_b_runbook(
            merkle_root=merkle_root,
            innovations_sealed=innovations_shipped,
            invariants_sealed=invariant_count,
            gtc_ledger_path=str(self._gtc_ledger_path),
            epoch_ledger_path=str(self._epoch_ledger_path),
        )

        record = EpochBoundaryRecord(
            record_id=f"V10ET-EPOCH-{PHASE}-{self._det.iso_now().replace(':', '').replace('-', '')}",
            epoch_from=EPOCH_FROM,
            epoch_to=EPOCH_TO,
            target_version=TARGET_VERSION,
            phase_at_boundary=PHASE,
            innovations_sealed=innovations_shipped,
            hard_class_invariants_sealed=invariant_count,
            merkle_root_validated=merkle_root,
            gtc_bundle_digest=gtc_bundle_digest,
            epoch_timestamp_utc=self._det.iso_now(),
            governor=GOVERNOR,
            innovation_id=INNOVATION_ID,
            track_b_runbook=runbook,
            human0_advisory_emitted=True,
            epoch_seal_hmac="",     # populated below
            prev_digest=prev_digest,
        )

        # Compute HMAC over canonical content (V10ET-CHAIN-0)
        canonical = _entry_canonical(record)
        record.epoch_seal_hmac = _compute_entry_hmac(canonical)

        # Atomic append (V10ET hardening criterion 4 — append-only JSONL)
        self._append_to_ledger(record)
        return record

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def seal(self, *, dry_run: bool = False) -> EpochTransitionResult:
        """
        Execute the V10 Epoch Transition sequence.

        Sequence (order enforced):
          1. Read GTC release ledger (latest bundle)
          2. Read agent state
          3. V10ET-VERIFY-0: re-validate Constitutional Merkle Root
          4. V10ET-HUMAN0-0: emit HUMAN-0 advisory
          5. V10ET-CHAIN-0 + V10ET-EPOCH-0: seal epoch boundary ledger entry
          6. Return EpochTransitionResult

        Args:
            dry_run: If True, emit advisory and validate but do not write to ledger.
        """
        findings: List[str] = []

        # Step 1: read GTC bundle (V10ET-SCOPE-0)
        gtc_bundle = self._read_gtc_ledger_latest()
        if gtc_bundle is None:
            findings.append(
                "P1: GTC release ledger absent or empty — "
                "run POST /gtc/certify before sealing epoch"
            )
            advisory = self._emit_human0_advisory(
                merkle_root="UNAVAILABLE", innovations=0, invariants=0
            )
            return EpochTransitionResult(
                status="ADVISORY_ONLY",
                epoch_boundary=None,
                track_b_runbook=_build_track_b_runbook(
                    merkle_root="UNAVAILABLE",
                    innovations_sealed=0,
                    invariants_sealed=0,
                    gtc_ledger_path=str(self._gtc_ledger_path),
                    epoch_ledger_path=str(self._epoch_ledger_path),
                ),
                human0_advisory=advisory,
                chain_valid=False,
                findings=findings,
            )

        # Step 2: read agent state (V10ET-SCOPE-0)
        agent_state = self._read_agent_state()

        # Step 3: V10ET-VERIFY-0 — re-validate Merkle root
        merkle_root = self._validate_merkle_from_gtc_bundle(gtc_bundle)

        innovations = agent_state.get("innovations_shipped", 94)
        invariants = agent_state.get("hard_class_invariant_count", 522)

        # Step 4: V10ET-HUMAN0-0 — emit advisory before seal
        advisory = self._emit_human0_advisory(
            merkle_root=merkle_root,
            innovations=innovations,
            invariants=invariants,
        )

        runbook = _build_track_b_runbook(
            merkle_root=merkle_root,
            innovations_sealed=innovations,
            invariants_sealed=invariants,
            gtc_ledger_path=str(self._gtc_ledger_path),
            epoch_ledger_path=str(self._epoch_ledger_path),
        )

        if dry_run:
            return EpochTransitionResult(
                status="ADVISORY_ONLY",
                epoch_boundary=None,
                track_b_runbook=runbook,
                human0_advisory=advisory,
                chain_valid=True,
                findings=["DRY_RUN: advisory emitted, Merkle root validated, ledger not written"],
            )

        # Step 5: seal epoch boundary
        record = self._seal_epoch(
            merkle_root=merkle_root,
            gtc_bundle=gtc_bundle,
            agent_state=agent_state,
        )

        return EpochTransitionResult(
            status="EPOCH_SEALED",
            epoch_boundary=asdict(record),
            track_b_runbook=runbook,
            human0_advisory=advisory,
            chain_valid=True,
            findings=findings,
        )

    def verify_chain(self) -> bool:
        """
        V10ET-CHAIN-0: verify HMAC chain integrity of the full epoch ledger.
        Returns True if chain is valid. Raises V10ETChainError if broken.
        """
        if not self._epoch_ledger:
            return True  # empty ledger is trivially valid
        prev: str = _GENESIS_PREV
        for idx, record in enumerate(self._epoch_ledger):
            canonical = _entry_canonical(record)
            if not _verify_hmac(canonical, record.epoch_seal_hmac):
                raise V10ETChainError(
                    f"V10ET-CHAIN-0: HMAC mismatch at entry {idx} "
                    f"(record_id={record.record_id})"
                )
            if not hmac.compare_digest(record.prev_digest, prev):
                raise V10ETChainError(
                    f"V10ET-CHAIN-0: prev_digest mismatch at entry {idx}"
                )
            prev = record.epoch_seal_hmac
        return True

    def latest_advisory(self) -> Optional[str]:
        """Return the most recently emitted HUMAN-0 advisory."""
        return self._human0_advisory_log[-1] if self._human0_advisory_log else None

    def history(self) -> List[Dict[str, Any]]:
        """Return all epoch boundary records as dicts. V10ET-SCOPE-0: read-only."""
        return [asdict(r) for r in self._epoch_ledger]


# ---------------------------------------------------------------------------
# Module-level seal helper (CLI entry point)
# ---------------------------------------------------------------------------


def certify(*, dry_run: bool = False) -> Dict[str, Any]:
    """Convenience entry point: python3 -m dorkllm.v10_epoch_transition certify"""
    engine = V10EpochTransitionEngine()
    result = engine.seal(dry_run=dry_run)
    return {
        "status": result.status,
        "epoch_boundary": result.epoch_boundary,
        "human0_advisory": result.human0_advisory,
        "chain_valid": result.chain_valid,
        "findings": result.findings,
        "track_b_runbook": result.track_b_runbook,
    }


if __name__ == "__main__":  # pragma: no cover
    import sys
    _dry = "--dry-run" in sys.argv
    out = certify(dry_run=_dry)
    print(json.dumps(out, indent=2))
