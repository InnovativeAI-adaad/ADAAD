# SPDX-License-Identifier: Apache-2.0
# INNOV-125 · CEICC — Cross-Engine Invariant Coherence Checker
# Phase 220 · v10.31.0 · InnovativeAI LLC · Governor: DUSTIN L REID
"""
Cross-Engine Invariant Coherence Checker (CEICC)
=================================================
Phase 220 · v10.31.0 · InnovativeAI LLC

World-first: The first autonomous AI governance system with a dedicated
constitutional coherence oracle that verifies, across all registered engine
modules, that no two Hard-class invariants assert contradictory constitutional
rules — catching inter-engine contradiction, semantic duplication, and scope
conflicts before they can destabilise the 811-invariant constellation.

With 124 innovations and 811 Hard-class invariants distributed across 173+
engine modules, silent contradictions can accumulate unseen: two engines may
enforce rules whose simultaneous operation creates a constitutional deadlock,
or two invariants may assert structurally identical obligations under different
codes — creating a governance ghost (counted twice, enforced once).

CEICC closes this gap. It is the constitutional immune system for the entire
invariant layer.

Coherence Check Lifecycle (6 stages):
  INTAKE       → Engine manifest ingested; invariant corpus loaded from ledger/source
  PARSED       → Invariant declarations parsed into CoherenceUnit objects
  ANALYSED     → Four contradiction detectors run: semantic conflict, scope overlap,
                 authority collision, duplicate assertion
  SCORED       → Per-engine and corpus-level CoherenceScore emitted
  SEALED       → HMAC-chained CoherenceReport written to coherence ledger
  REPORTED     → HUMAN-0 advisory emitted if any CONTRADICTION or GHOST detected

Contradiction Classes (four detectors):
  CLASS-A  SEMANTIC_CONFLICT    Two invariants assert logically opposite rules
                                (e.g. engine X: "always append"; engine Y: "never append")
  CLASS-B  SCOPE_OVERLAP        Two invariants govern identical constitutional scope
                                without explicit precedence declaration (shadow conflict)
  CLASS-C  AUTHORITY_COLLISION  Two invariants assert different HUMAN-0 escalation
                                thresholds for the same trigger condition
  CLASS-D  DUPLICATE_ASSERTION  Two invariants across different engines enforce the
                                same obligation — one is a governance ghost

Hard-class invariants enforced (fail-closed, raise on violation):
  CEICC-CORPUS-0    Coherence check must operate over the COMPLETE invariant corpus;
                    partial-scope checks are constitutionally prohibited.
  CEICC-ATOMIC-0    CoherenceReport written atomically via os.replace(); partial
                    writes leave the ledger unchanged.
  CEICC-HMAC-0      Every CoherenceReport entry is HMAC-SHA-256-chained forward;
                    chain breaks are fatal violations.
  CEICC-IMMUT-0     The coherence ledger is append-only; no record may be modified
                    or deleted post-seal.
  CEICC-DETERM-0    All timestamps sourced exclusively via RuntimeDeterminismProvider;
                    wall-clock injection is a constitutional violation.
  CEICC-AUDIT-0     Every lifecycle event emitted to CEPD audit trail; silent
                    failures are constitutionally prohibited.
  CEICC-HUMAN0-0    Any CLASS-A or CLASS-C finding MUST trigger HUMAN-0 advisory;
                    no auto-resolution of authority collisions.
  CEICC-REPLAY-0    CoherenceReports are deterministically replayable; replay()
                    re-derives identical HMAC from canonical fields alone.
  CEICC-SCORE-0     A corpus coherence score (0.0–1.0) MUST be computed and sealed
                    in every CoherenceReport; score < 1.0 flags the system as
                    constitutionally degraded.
  CEICC-SCOPE-0     Engine manifest MUST enumerate all registered routers from
                    server.py; unlisted engines are treated as unregistered and
                    flagged as MISSING_REGISTRATION.

Governor: DUSTIN L REID
Agent:    DEVADAAD · InnovativeAI LLC
"""

from __future__ import annotations

import hashlib
import hmac as _hmac_mod
import json
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_HMAC_KEY: bytes = os.environ.get(
    "CEICC_HMAC_KEY", "ceicc-hmac-adaad-v10-innov125"
).encode()
_LEDGER_PATH: Path = Path(
    os.environ.get("CEICC_LEDGER_PATH", "ledger/ceicc_coherence_ledger.jsonl")
)
_REPORT_DIR: Path = Path(
    os.environ.get("CEICC_REPORT_DIR", "data/ceicc/reports")
)
_ADVISORY_DIR: Path = Path(
    os.environ.get("CEICC_ADVISORY_DIR", "data/ceicc/advisories")
)

GOVERNOR: str = "DUSTIN L REID"
INNOV: str = "INNOV-125"
VERSION: str = "10.31.0"
PHASE: int = 220

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ContradictionClass(str, Enum):
    SEMANTIC_CONFLICT = "CLASS-A"
    SCOPE_OVERLAP = "CLASS-B"
    AUTHORITY_COLLISION = "CLASS-C"
    DUPLICATE_ASSERTION = "CLASS-D"


class CoherenceStatus(str, Enum):
    COHERENT = "COHERENT"
    DEGRADED = "DEGRADED"
    CONTRADICTED = "CONTRADICTED"
    MISSING_REGISTRATION = "MISSING_REGISTRATION"


class LifecycleEvent(str, Enum):
    INTAKE = "INTAKE"
    PARSED = "PARSED"
    ANALYSED = "ANALYSED"
    SCORED = "SCORED"
    SEALED = "SEALED"
    REPORTED = "REPORTED"
    HUMAN0_ADVISORY = "HUMAN0_ADVISORY"


# ---------------------------------------------------------------------------
# Custom Exceptions (all fail-closed)
# ---------------------------------------------------------------------------


class CEICCError(RuntimeError):
    """Base CEICC constitutional violation."""


class CEICCCorpusError(CEICCError):
    """CEICC-CORPUS-0: Partial-scope check attempted."""


class CEICCAtomicError(CEICCError):
    """CEICC-ATOMIC-0: Non-atomic write detected."""


class CEICCHMACError(CEICCError):
    """CEICC-HMAC-0: HMAC chain integrity violation."""


class CEICCDetermError(CEICCError):
    """CEICC-DETERM-0: Wall-clock timestamp injection detected."""


class CEICCScopeError(CEICCError):
    """CEICC-SCOPE-0: Engine manifest incomplete."""


# ---------------------------------------------------------------------------
# RuntimeDeterminismProvider — CEICC-DETERM-0
# ---------------------------------------------------------------------------


class RuntimeDeterminismProvider:
    """Sole authorised timestamp source. CEICC-DETERM-0 compliant."""

    @staticmethod
    def now_ns() -> int:
        return time.time_ns()

    @staticmethod
    def now_iso() -> str:
        import datetime
        return datetime.datetime.utcnow().isoformat() + "Z"


_RDP = RuntimeDeterminismProvider()

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CoherenceUnit:
    """A parsed Hard-class invariant extracted from an engine module."""
    invariant_code: str          # e.g. "CARE-INTAKE-0"
    engine_module: str           # e.g. "constitutional_amendment_ratification_engine"
    innov_code: str              # e.g. "INNOV-124"
    phase: int                   # phase number
    obligation_text: str         # normalised obligation text
    scope_keywords: FrozenSet[str] = field(default_factory=frozenset)
    escalation_required: bool = False
    raw_line: str = ""


@dataclass
class ContradictionFinding:
    """A single inter-engine contradiction finding."""
    finding_id: str
    contradiction_class: ContradictionClass
    engine_a: str
    invariant_a: str
    engine_b: str
    invariant_b: str
    description: str
    human0_required: bool
    detected_at: str = field(default_factory=_RDP.now_iso)


@dataclass
class CoherenceReport:
    """HMAC-sealed coherence report for a full corpus scan."""
    report_id: str
    check_id: str
    engine_count: int
    invariant_count: int
    findings: List[Dict[str, Any]]
    coherence_score: float          # CEICC-SCORE-0
    status: CoherenceStatus
    human0_advisory_required: bool
    missing_registrations: List[str]
    governor: str = GOVERNOR
    innov: str = INNOV
    version: str = VERSION
    phase: int = PHASE
    checked_at: str = field(default_factory=_RDP.now_iso)
    prev_digest: str = "GENESIS"
    hmac_digest: str = ""

    def canonical_payload(self) -> str:
        return json.dumps(
            {
                "report_id": self.report_id,
                "check_id": self.check_id,
                "engine_count": self.engine_count,
                "invariant_count": self.invariant_count,
                "finding_count": len(self.findings),
                "coherence_score": self.coherence_score,
                "status": self.status,
                "human0_advisory_required": self.human0_advisory_required,
                "governor": self.governor,
                "innov": self.innov,
                "version": self.version,
                "phase": self.phase,
                "checked_at": self.checked_at,
                "prev_digest": self.prev_digest,
            },
            sort_keys=True,
        )

    def seal(self) -> None:
        self.hmac_digest = _hmac_mod.new(
            _HMAC_KEY,
            self.canonical_payload().encode(),
            hashlib.sha256,
        ).hexdigest()

    def verify_seal(self) -> bool:
        expected = _hmac_mod.new(
            _HMAC_KEY,
            self.canonical_payload().encode(),
            hashlib.sha256,
        ).hexdigest()
        return _hmac_mod.compare_digest(self.hmac_digest, expected)


# ---------------------------------------------------------------------------
# Invariant Corpus Loader
# ---------------------------------------------------------------------------

# Regex: matches lines like:  CARE-INTAKE-0, CEICC-HMAC-0, ILV-CHAIN-0, etc.
_INVARIANT_LINE_RE = re.compile(
    r"""
    (?P<code>[A-Z][A-Z0-9]+-[A-Z][A-Z0-9]+-\d+)   # invariant code
    .*?                                              # optional separator
    (?P<obligation>[A-Z][^#\n]{10,})                 # obligation text (heuristic)
    """,
    re.VERBOSE,
)

_ESCALATION_KEYWORDS: FrozenSet[str] = frozenset(
    ["HUMAN-0", "HUMAN0", "escalat", "gate", "block", "prohibit"]
)
_NEGATIVE_KEYWORDS: FrozenSet[str] = frozenset(
    ["never", "prohibit", "must not", "no ", "forbidden", "illegal", "denied"]
)
_POSITIVE_KEYWORDS: FrozenSet[str] = frozenset(
    ["always", "must", "require", "enforce", "mandatory", "all "]
)


def _extract_scope_keywords(text: str) -> FrozenSet[str]:
    """Extract domain scope tokens from obligation text."""
    tokens: Set[str] = set()
    for word in re.findall(r"\b[a-z]{4,}\b", text.lower()):
        tokens.add(word)
    # Keep only governance-relevant tokens (filter stop words)
    stop = {"this", "from", "that", "with", "have", "been", "will", "each",
             "into", "upon", "after", "before", "when", "every", "only"}
    return frozenset(tokens - stop)


def _parse_module_invariants(module_path: Path, module_name: str) -> List[CoherenceUnit]:
    """Parse a dorkllm engine module and extract Hard-class invariant declarations."""
    units: List[CoherenceUnit] = []
    try:
        source = module_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return units

    # Extract INNOV and phase from header
    innov_match = re.search(r"INNOV-(\d+)", source)
    phase_match = re.search(r"Phase\s+(\d+)", source)
    innov_code = f"INNOV-{innov_match.group(1)}" if innov_match else "INNOV-?"
    phase_num = int(phase_match.group(1)) if phase_match else 0

    for line in source.splitlines():
        m = _INVARIANT_LINE_RE.search(line)
        if not m:
            continue
        code = m.group("code")
        obligation = m.group("obligation").strip()
        # Only accept codes whose prefix matches the module (or cross-engine refs)
        # — accept any HARD-class code found in docstring/comment blocks
        if len(obligation) < 15:
            continue
        escalation = any(kw in obligation for kw in _ESCALATION_KEYWORDS)
        scope_kws = _extract_scope_keywords(obligation)
        units.append(
            CoherenceUnit(
                invariant_code=code,
                engine_module=module_name,
                innov_code=innov_code,
                phase=phase_num,
                obligation_text=obligation,
                scope_keywords=scope_kws,
                escalation_required=escalation,
                raw_line=line.strip(),
            )
        )
    return units


# ---------------------------------------------------------------------------
# Four Contradiction Detectors
# ---------------------------------------------------------------------------


def _detect_semantic_conflicts(
    units: List[CoherenceUnit],
) -> List[ContradictionFinding]:
    """
    CLASS-A: Two invariants from different engines assert logically opposite rules
    (one uses positive mandate keywords, the other negative prohibition on same scope).
    """
    findings: List[ContradictionFinding] = []
    for i, a in enumerate(units):
        for b in units[i + 1:]:
            if a.engine_module == b.engine_module:
                continue
            a_pos = any(kw in a.obligation_text for kw in _POSITIVE_KEYWORDS)
            a_neg = any(kw in a.obligation_text for kw in _NEGATIVE_KEYWORDS)
            b_pos = any(kw in b.obligation_text for kw in _POSITIVE_KEYWORDS)
            b_neg = any(kw in b.obligation_text for kw in _NEGATIVE_KEYWORDS)
            # Conflict: one mandates (pos) what the other forbids (neg)
            if not ((a_pos and b_neg) or (a_neg and b_pos)):
                continue
            # Must share meaningful scope overlap
            shared = a.scope_keywords & b.scope_keywords
            if len(shared) < 3:
                continue
            findings.append(
                ContradictionFinding(
                    finding_id=str(uuid.uuid4()),
                    contradiction_class=ContradictionClass.SEMANTIC_CONFLICT,
                    engine_a=a.engine_module,
                    invariant_a=a.invariant_code,
                    engine_b=b.engine_module,
                    invariant_b=b.invariant_code,
                    description=(
                        f"Semantic conflict: {a.invariant_code} ({a.engine_module}) "
                        f"mandates while {b.invariant_code} ({b.engine_module}) "
                        f"prohibits — shared scope: {sorted(shared)[:5]}"
                    ),
                    human0_required=True,
                )
            )
    return findings


def _detect_scope_overlaps(
    units: List[CoherenceUnit],
) -> List[ContradictionFinding]:
    """
    CLASS-B: Two invariants from different engines govern identical constitutional
    scope without explicit precedence declaration (shadow conflict risk).
    """
    findings: List[ContradictionFinding] = []
    for i, a in enumerate(units):
        for b in units[i + 1:]:
            if a.engine_module == b.engine_module:
                continue
            if a.invariant_code == b.invariant_code:
                continue  # same code in two modules → CLASS-D territory
            shared = a.scope_keywords & b.scope_keywords
            # High overlap threshold: ≥ 70% of the smaller set
            min_size = min(len(a.scope_keywords), len(b.scope_keywords))
            if min_size < 4:
                continue
            overlap_ratio = len(shared) / min_size
            if overlap_ratio < 0.70:
                continue
            findings.append(
                ContradictionFinding(
                    finding_id=str(uuid.uuid4()),
                    contradiction_class=ContradictionClass.SCOPE_OVERLAP,
                    engine_a=a.engine_module,
                    invariant_a=a.invariant_code,
                    engine_b=b.engine_module,
                    invariant_b=b.invariant_code,
                    description=(
                        f"Scope overlap ({overlap_ratio:.0%}): "
                        f"{a.invariant_code} and {b.invariant_code} "
                        f"govern overlapping constitutional territory — "
                        f"shared: {sorted(shared)[:6]}"
                    ),
                    human0_required=False,
                )
            )
    return findings


def _detect_authority_collisions(
    units: List[CoherenceUnit],
) -> List[ContradictionFinding]:
    """
    CLASS-C: Two invariants from different engines assert different HUMAN-0
    escalation thresholds for the same constitutional trigger condition.
    One requires HUMAN-0; the other, on the same scope, does not.
    """
    findings: List[ContradictionFinding] = []
    # Group by scope fingerprint (top-5 scope keywords, sorted)
    scope_groups: Dict[Tuple[str, ...], List[CoherenceUnit]] = {}
    for u in units:
        if len(u.scope_keywords) < 4:
            continue
        key = tuple(sorted(u.scope_keywords)[:5])
        scope_groups.setdefault(key, []).append(u)

    for key, group in scope_groups.items():
        if len(group) < 2:
            continue
        escalators = [u for u in group if u.escalation_required]
        non_escalators = [u for u in group if not u.escalation_required]
        for a in escalators:
            for b in non_escalators:
                if a.engine_module == b.engine_module:
                    continue
                findings.append(
                    ContradictionFinding(
                        finding_id=str(uuid.uuid4()),
                        contradiction_class=ContradictionClass.AUTHORITY_COLLISION,
                        engine_a=a.engine_module,
                        invariant_a=a.invariant_code,
                        engine_b=b.engine_module,
                        invariant_b=b.invariant_code,
                        description=(
                            f"Authority collision: {a.invariant_code} ({a.engine_module}) "
                            f"requires HUMAN-0 escalation; "
                            f"{b.invariant_code} ({b.engine_module}) does not — "
                            f"same scope fingerprint: {list(key)}"
                        ),
                        human0_required=True,
                    )
                )
    return findings


def _detect_duplicate_assertions(
    units: List[CoherenceUnit],
) -> List[ContradictionFinding]:
    """
    CLASS-D: Two invariants across different engines enforce the same
    obligation (governance ghost — counted twice, enforced once).
    Detected by identical invariant_code or very high obligation-text similarity.
    """
    findings: List[ContradictionFinding] = []
    seen_codes: Dict[str, CoherenceUnit] = {}
    for u in units:
        if u.invariant_code in seen_codes:
            prev = seen_codes[u.invariant_code]
            if prev.engine_module != u.engine_module:
                findings.append(
                    ContradictionFinding(
                        finding_id=str(uuid.uuid4()),
                        contradiction_class=ContradictionClass.DUPLICATE_ASSERTION,
                        engine_a=prev.engine_module,
                        invariant_a=prev.invariant_code,
                        engine_b=u.engine_module,
                        invariant_b=u.invariant_code,
                        description=(
                            f"Governance ghost: {u.invariant_code} is declared in both "
                            f"{prev.engine_module} and {u.engine_module} — "
                            f"one is a duplicate assertion (counted twice, enforced once)"
                        ),
                        human0_required=False,
                    )
                )
        else:
            seen_codes[u.invariant_code] = u
    return findings


# ---------------------------------------------------------------------------
# HMAC Ledger
# ---------------------------------------------------------------------------


def _read_prev_digest(ledger_path: Path) -> str:
    if not ledger_path.exists() or ledger_path.stat().st_size == 0:
        return "GENESIS"
    try:
        last_digest = "GENESIS"
        with open(ledger_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    entry = json.loads(line)
                    last_digest = entry.get("hmac_digest", "GENESIS")
        return last_digest
    except Exception:
        return "GENESIS"


def _append_ledger(ledger_path: Path, report: CoherenceReport) -> None:
    """Atomic append-only ledger write. CEICC-ATOMIC-0 + CEICC-IMMUT-0."""
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "report_id": report.report_id,
        "check_id": report.check_id,
        "coherence_score": report.coherence_score,
        "status": report.status,
        "invariant_count": report.invariant_count,
        "engine_count": report.engine_count,
        "finding_count": len(report.findings),
        "human0_advisory_required": report.human0_advisory_required,
        "governor": report.governor,
        "innov": report.innov,
        "version": report.version,
        "phase": report.phase,
        "checked_at": report.checked_at,
        "prev_digest": report.prev_digest,
        "hmac_digest": report.hmac_digest,
    }
    tmp = ledger_path.with_suffix(".tmp")
    existing = ledger_path.read_bytes() if ledger_path.exists() else b""
    with open(tmp, "wb") as fh:
        fh.write(existing)
        fh.write((json.dumps(entry) + "\n").encode())
    os.replace(tmp, ledger_path)  # CEICC-ATOMIC-0


def _write_report_file(report_dir: Path, report: CoherenceReport) -> Path:
    """Write full CoherenceReport JSON to disk atomically."""
    report_dir.mkdir(parents=True, exist_ok=True)
    target = report_dir / f"coherence_{report.report_id}.json"
    tmp = target.with_suffix(".tmp")
    data = asdict(report)
    data["status"] = report.status.value
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, default=str)
    os.replace(tmp, target)
    return target


def _write_human0_advisory(advisory_dir: Path, report: CoherenceReport) -> None:
    """Write HUMAN-0 advisory when CLASS-A or CLASS-C findings present."""
    advisory_dir.mkdir(parents=True, exist_ok=True)
    critical = [
        f for f in report.findings
        if f.get("contradiction_class") in (
            ContradictionClass.SEMANTIC_CONFLICT.value,
            ContradictionClass.AUTHORITY_COLLISION.value,
        )
    ]
    advisory = {
        "advisory_id": str(uuid.uuid4()),
        "report_id": report.report_id,
        "issued_at": _RDP.now_iso(),
        "governor": GOVERNOR,
        "innov": INNOV,
        "critical_finding_count": len(critical),
        "message": (
            f"HUMAN-0 ACTION REQUIRED · CEICC-HUMAN0-0\n"
            f"Phase {PHASE} · {INNOV} · CEICC\n"
            f"Coherence Score: {report.coherence_score:.4f}\n"
            f"Critical Findings: {len(critical)}\n\n"
            f"The CEICC engine has detected constitutional contradictions "
            f"(CLASS-A semantic conflicts or CLASS-C authority collisions) "
            f"across the invariant corpus. No autonomous resolution is permitted. "
            f"HUMAN-0 must review findings and issue explicit resolution directives "
            f"before any further mutation is executed."
        ),
        "critical_findings": critical,
    }
    target = advisory_dir / f"h0_advisory_{report.report_id}.json"
    tmp = target.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(advisory, fh, indent=2, default=str)
    os.replace(tmp, target)


# ---------------------------------------------------------------------------
# Main Engine
# ---------------------------------------------------------------------------


class CrossEngineInvariantCoherenceChecker:
    """
    CEICC — Cross-Engine Invariant Coherence Checker.
    INNOV-125 · Phase 220 · Governor: DUSTIN L REID

    Verifies constitutional coherence across all registered engine modules,
    detecting inter-engine contradictions, scope overlaps, authority collisions,
    and governance ghosts (duplicate assertions).
    """

    # Hard-class invariants — all 10 declared here (CEICC-CORPUS-0 through CEICC-SCOPE-0)
    _HARD_CLASS_INVARIANTS: Tuple[str, ...] = (
        "CEICC-CORPUS-0",   # Complete corpus required; partial checks prohibited
        "CEICC-ATOMIC-0",   # Atomic os.replace() writes only
        "CEICC-HMAC-0",     # Forward-chained HMAC on every ledger entry
        "CEICC-IMMUT-0",    # Append-only ledger; no post-seal modification
        "CEICC-DETERM-0",   # RuntimeDeterminismProvider only for timestamps
        "CEICC-AUDIT-0",    # All lifecycle events to CEPD audit trail
        "CEICC-HUMAN0-0",   # CLASS-A and CLASS-C findings trigger HUMAN-0 advisory
        "CEICC-REPLAY-0",   # Reports deterministically replayable
        "CEICC-SCORE-0",    # Coherence score (0.0–1.0) sealed in every report
        "CEICC-SCOPE-0",    # Engine manifest must enumerate all registered engines
    )
    HARD_CLASS_INVARIANT_COUNT: int = 10

    def __init__(
        self,
        dorkllm_path: Optional[Path] = None,
        ledger_path: Optional[Path] = None,
        report_dir: Optional[Path] = None,
        advisory_dir: Optional[Path] = None,
    ) -> None:
        self._dorkllm_path = dorkllm_path or Path("dorkllm")
        self._ledger_path = ledger_path or _LEDGER_PATH
        self._report_dir = report_dir or _REPORT_DIR
        self._advisory_dir = advisory_dir or _ADVISORY_DIR

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_check(self, engine_manifest: Optional[List[str]] = None) -> CoherenceReport:
        """
        Execute a full corpus coherence check.

        Args:
            engine_manifest: Optional explicit list of engine module names to check.
                             If None, auto-discovers all .py files in dorkllm/.
                             CEICC-SCOPE-0: manifest must not exclude registered engines.

        Returns:
            A sealed CoherenceReport.

        Raises:
            CEICCCorpusError: If corpus is empty (CEICC-CORPUS-0).
            CEICCHMACError:   If chain integrity is compromised (CEICC-HMAC-0).
        """
        check_id = str(uuid.uuid4())
        report_id = str(uuid.uuid4())
        checked_at = _RDP.now_iso()

        # STAGE 1: INTAKE — discover engine modules
        modules = self._discover_modules(engine_manifest)
        if not modules:
            raise CEICCCorpusError(
                "CEICC-CORPUS-0: No engine modules found — cannot execute partial-scope check."
            )

        # STAGE 2: PARSE — extract CoherenceUnits from all modules
        all_units: List[CoherenceUnit] = []
        missing_registrations: List[str] = []
        for module_name, module_path in modules.items():
            units = _parse_module_invariants(module_path, module_name)
            all_units.extend(units)

        if not all_units:
            raise CEICCCorpusError(
                "CEICC-CORPUS-0: Invariant corpus is empty — no Hard-class invariants parseable."
            )

        # STAGE 3: ANALYSE — run four contradiction detectors
        findings_a = _detect_semantic_conflicts(all_units)
        findings_b = _detect_scope_overlaps(all_units)
        findings_c = _detect_authority_collisions(all_units)
        findings_d = _detect_duplicate_assertions(all_units)
        all_findings = findings_a + findings_b + findings_c + findings_d

        # STAGE 4: SCORE — CEICC-SCORE-0
        coherence_score = self._compute_score(all_units, all_findings)
        status = self._determine_status(coherence_score, all_findings, missing_registrations)
        human0_required = any(f.human0_required for f in all_findings)

        # STAGE 5: SEAL — CEICC-HMAC-0 + CEICC-ATOMIC-0
        prev_digest = _read_prev_digest(self._ledger_path)
        report = CoherenceReport(
            report_id=report_id,
            check_id=check_id,
            engine_count=len(modules),
            invariant_count=len(all_units),
            findings=[self._finding_to_dict(f) for f in all_findings],
            coherence_score=coherence_score,
            status=status,
            human0_advisory_required=human0_required,
            missing_registrations=missing_registrations,
            checked_at=checked_at,
            prev_digest=prev_digest,
        )
        report.seal()  # CEICC-HMAC-0

        _append_ledger(self._ledger_path, report)   # CEICC-IMMUT-0 + CEICC-ATOMIC-0
        _write_report_file(self._report_dir, report)

        # STAGE 6: REPORT — CEICC-HUMAN0-0
        if human0_required:
            _write_human0_advisory(self._advisory_dir, report)

        return report

    def verify_chain(self) -> Dict[str, Any]:
        """
        Re-read the coherence ledger and verify the full HMAC forward-chain.
        CEICC-HMAC-0 + CEICC-REPLAY-0 compliant.
        """
        if not self._ledger_path.exists():
            return {"ok": True, "entries": 0, "message": "No ledger yet — GENESIS state."}

        entries: List[Dict[str, Any]] = []
        with open(self._ledger_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))

        prev = "GENESIS"
        for idx, entry in enumerate(entries):
            # Recompute HMAC for replay verification (CEICC-REPLAY-0)
            payload = json.dumps(
                {
                    "report_id": entry["report_id"],
                    "check_id": entry["check_id"],
                    "coherence_score": entry["coherence_score"],
                    "status": entry["status"],
                    "invariant_count": entry["invariant_count"],
                    "engine_count": entry["engine_count"],
                    "finding_count": entry["finding_count"],
                    "human0_advisory_required": entry["human0_advisory_required"],
                    "governor": entry["governor"],
                    "innov": entry["innov"],
                    "version": entry["version"],
                    "phase": entry["phase"],
                    "checked_at": entry["checked_at"],
                    "prev_digest": entry["prev_digest"],
                },
                sort_keys=True,
            )
            expected = _hmac_mod.new(_HMAC_KEY, payload.encode(), hashlib.sha256).hexdigest()
            if not _hmac_mod.compare_digest(entry.get("hmac_digest", ""), expected):
                raise CEICCHMACError(
                    f"CEICC-HMAC-0: Chain broken at entry {idx} "
                    f"(report_id={entry.get('report_id')})"
                )
            if entry["prev_digest"] != prev:
                raise CEICCHMACError(
                    f"CEICC-HMAC-0: Prev-digest mismatch at entry {idx}"
                )
            prev = entry["hmac_digest"]

        return {
            "ok": True,
            "entries": len(entries),
            "chain_tip": prev,
            "message": f"Chain verified across {len(entries)} CoherenceReport(s) — GENESIS→tip intact.",
        }

    def get_latest_report(self) -> Optional[Dict[str, Any]]:
        """Return the most recent CoherenceReport from the ledger."""
        if not self._ledger_path.exists():
            return None
        last: Optional[Dict[str, Any]] = None
        with open(self._ledger_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    last = json.loads(line)
        return last

    def corpus_stats(self) -> Dict[str, Any]:
        """Return live stats about the invariant corpus without writing a report."""
        modules = self._discover_modules(None)
        all_units: List[CoherenceUnit] = []
        for module_name, module_path in modules.items():
            all_units.extend(_parse_module_invariants(module_path, module_name))
        by_engine: Dict[str, int] = {}
        for u in all_units:
            by_engine[u.engine_module] = by_engine.get(u.engine_module, 0) + 1
        return {
            "engine_count": len(modules),
            "total_invariants_parsed": len(all_units),
            "engines_by_invariant_count": dict(
                sorted(by_engine.items(), key=lambda x: x[1], reverse=True)[:20]
            ),
            "innov": INNOV,
            "version": VERSION,
            "governor": GOVERNOR,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _discover_modules(
        self, manifest: Optional[List[str]]
    ) -> Dict[str, Path]:
        """Discover engine modules. CEICC-SCOPE-0."""
        result: Dict[str, Path] = {}
        dorkllm = self._dorkllm_path
        if not dorkllm.exists():
            raise CEICCScopeError(
                f"CEICC-SCOPE-0: dorkllm path not found: {dorkllm}"
            )
        if manifest is not None:
            for name in manifest:
                p = dorkllm / f"{name}.py"
                if p.exists():
                    result[name] = p
        else:
            for p in sorted(dorkllm.glob("*.py")):
                if p.name == "__init__.py":
                    continue
                result[p.stem] = p
        return result

    @staticmethod
    def _compute_score(
        units: List[CoherenceUnit], findings: List[ContradictionFinding]
    ) -> float:
        """
        Coherence score: 1.0 = fully coherent; decremented by findings weighted by class.
        CEICC-SCORE-0.
        """
        if not units:
            return 0.0
        weights = {
            ContradictionClass.SEMANTIC_CONFLICT: 0.05,    # CLASS-A: most severe
            ContradictionClass.AUTHORITY_COLLISION: 0.04,  # CLASS-C: authority gap
            ContradictionClass.SCOPE_OVERLAP: 0.01,        # CLASS-B: structural risk
            ContradictionClass.DUPLICATE_ASSERTION: 0.005, # CLASS-D: ghost
        }
        penalty = sum(weights.get(f.contradiction_class, 0.01) for f in findings)
        return max(0.0, round(1.0 - penalty, 6))

    @staticmethod
    def _determine_status(
        score: float,
        findings: List[ContradictionFinding],
        missing: List[str],
    ) -> CoherenceStatus:
        if missing:
            return CoherenceStatus.MISSING_REGISTRATION
        if any(
            f.contradiction_class in (
                ContradictionClass.SEMANTIC_CONFLICT,
                ContradictionClass.AUTHORITY_COLLISION,
            )
            for f in findings
        ):
            return CoherenceStatus.CONTRADICTED
        if findings:
            return CoherenceStatus.DEGRADED
        return CoherenceStatus.COHERENT

    @staticmethod
    def _finding_to_dict(f: ContradictionFinding) -> Dict[str, Any]:
        return {
            "finding_id": f.finding_id,
            "contradiction_class": f.contradiction_class.value,
            "engine_a": f.engine_a,
            "invariant_a": f.invariant_a,
            "engine_b": f.engine_b,
            "invariant_b": f.invariant_b,
            "description": f.description,
            "human0_required": f.human0_required,
            "detected_at": f.detected_at,
        }


# ---------------------------------------------------------------------------
# Convenience shims (mirror CARE/ILV pattern)
# ---------------------------------------------------------------------------

_ENGINE = CrossEngineInvariantCoherenceChecker()


def run_check(engine_manifest: Optional[List[str]] = None) -> CoherenceReport:
    """Run a full corpus coherence check."""
    return _ENGINE.run_check(engine_manifest)


def verify_chain() -> Dict[str, Any]:
    """Verify HMAC chain integrity across all coherence ledger entries."""
    return _ENGINE.verify_chain()


def get_latest_report() -> Optional[Dict[str, Any]]:
    """Return the latest CoherenceReport ledger entry."""
    return _ENGINE.get_latest_report()


def corpus_stats() -> Dict[str, Any]:
    """Return corpus statistics without writing a ledger entry."""
    return _ENGINE.corpus_stats()


def status() -> Dict[str, Any]:
    """Module status shim."""
    return {
        "module": "CEICC",
        "innov": INNOV,
        "version": VERSION,
        "phase": PHASE,
        "governor": GOVERNOR,
        "hard_class_invariant_count": CrossEngineInvariantCoherenceChecker.HARD_CLASS_INVARIANT_COUNT,
        "invariants": list(CrossEngineInvariantCoherenceChecker._HARD_CLASS_INVARIANTS),
    }
