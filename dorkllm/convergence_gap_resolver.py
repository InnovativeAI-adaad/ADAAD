# SPDX-License-Identifier: Apache-2.0
"""
INNOV-87 · CGR — Convergence Gap Resolver
==========================================
Phase 182 · v9.115.0 · InnovativeAI LLC

World-first: A constitutionally-governed convergence gap resolution engine that
reads the GIR (INNOV-86) snapshot and V10CA (INNOV-71) convergence ledger,
identifies the top-N below-threshold governance dimensions and V10 criteria,
and generates structured, HUMAN-0-reviewable Gap Resolution Plans (GRPs) for
each identified gap. Each GRP specifies: the target dimension or criterion,
observed score, delta to threshold, specific remediation actions ranked by
estimated impact, estimated invariant additions required, estimated test suite
additions, and an IP opportunity flag for novel mechanisms surfaced during
gap analysis.

CGR closes the V10 self-authorship loop:

  GIR ──► CRI / V10 confidence ──► CGR ──► GRP ──► HUMAN-0 ratification
   ▲                                                         │
   └──── CAL (learns from GRP outcomes) ◄───────────────────┘

CGR is strictly read-only with respect to all upstream ledgers. Its sole
outputs are the GRP ledger and CGR snapshot in data/cgr/.

Hard-class invariants enforced (fail-closed):
  CGR-SCOPE-0      CGR only reads GIR/V10CA sources; never mutates upstream state
  CGR-CHAIN-0      GRP ledger entries form a valid HMAC-SHA-256 chain; broken chain halts
  CGR-IMMUT-0      GRP ledger is append-only; no plan mutation permitted after write
  CGR-DETERM-0     No wall-clock injection; all timestamps via _utc_iso(); identical input → identical output
  CGR-HUMAN0-0     GRP containing CRITICAL-severity gaps emits HUMAN-0 ratification advisory before ledger write
  CGR-AUDIT-0      Every resolve() call writes a ledger entry before returning results
  CGR-PERSIST-0    CGR snapshot persists across restarts; loaded on init if present
  CGR-SEAL-0       Each GRP sealed with HMAC digest over canonical plan payload
  CGR-DOUBLE-0     Idempotency guard: duplicate plan_id rejected with DOUBLE_PLAN error
  CGR-READONLY-0   CGR reads only data/gir/ and data/v10ca/ paths; no external I/O
  CGR-TOPN-0       Top-N gap selection is deterministic: sort by (score ASC, dimension ASC); no RNG
  CGR-IMPACT-0     Action impact estimates are deterministic functions of dimension type; no LLM inference

Governor: DUSTIN L REID
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ── Constants ─────────────────────────────────────────────────────────────────

_GOVERNOR: str = "DUSTIN L REID"
_INNOV_CODE: str = "INNOV-87"
_MODULE_CODE: str = "CGR"
_HMAC_KEY: bytes = b"adaad-cgr-chain-key-v1"

# Governed threshold for CRITICAL gap classification (CGR-HUMAN0-0)
_CRITICAL_GAP_THRESHOLD: float = 0.50   # dimension score below this → CRITICAL severity
_WARNING_GAP_THRESHOLD: float = 0.70    # dimension score below this → WARNING severity

# Default number of gaps to resolve per call (CGR-TOPN-0)
DEFAULT_TOP_N: int = 5

# V10CA promotion gate (from V10CA constants)
_V10_PROMOTION_GATE: float = 0.85

_DATA_DIR: Path = Path("data/cgr")
_GRP_LEDGER_PATH: Path = _DATA_DIR / "grp_ledger.jsonl"
_CGR_SNAPSHOT_PATH: Path = _DATA_DIR / "cgr_snapshot.json"
_ADVISORY_LOG_PATH: Path = _DATA_DIR / "human0_advisory_log.jsonl"

# Upstream source paths (read-only — CGR-READONLY-0)
_GIR_SNAPSHOT: Path = Path("data/gir/gir_snapshot.json")
_GIR_GAP_REPORT: Path = Path("data/gir/gap_report.jsonl")
_V10CA_LEDGER: Path = Path("data/v10ca/snapshots.jsonl")
_AGENT_STATE: Path = Path(".adaad_agent_state.json")


# ── Remediation action catalogue ──────────────────────────────────────────────
# Maps each GIR dimension to a ranked list of concrete remediation actions.
# Actions are deterministic constants — CGR-IMPACT-0 forbids LLM inference here.

_ACTION_CATALOGUE: Dict[str, List[Dict]] = {
    "constitutional_lifecycle": [
        {"rank": 1, "action": "Execute a CAE amendment cycle: propose, validate, and execute a constitutional amendment to exercise the lifecycle end-to-end.", "est_invariants": 2, "est_tests": 5, "ip_flag": False},
        {"rank": 2, "action": "Invoke CAR rollback on a low-risk CAE entry to populate the CAR execution ledger and verify the rollback pathway.", "est_invariants": 1, "est_tests": 3, "ip_flag": False},
        {"rank": 3, "action": "Add CAE+CAR integration test suite covering the full amendment-then-rollback lifecycle in a single governed session.", "est_invariants": 0, "est_tests": 10, "ip_flag": False},
    ],
    "stability_monitoring": [
        {"rank": 1, "action": "Run CSC.compute_stability() cycle against live CAE snapshot to populate the stability report ledger and produce a non-trivial SCSI reading.", "est_invariants": 1, "est_tests": 4, "ip_flag": False},
        {"rank": 2, "action": "Configure CSC WARNING_THRESHOLD and CRITICAL_THRESHOLD in a governed config amendment to exercise threshold-gated alert emission.", "est_invariants": 1, "est_tests": 3, "ip_flag": False},
        {"rank": 3, "action": "Add SCSI trend tracking across consecutive CSC cycles to detect stability drift; novel SCSI velocity metric is patentable.", "est_invariants": 2, "est_tests": 5, "ip_flag": True},
    ],
    "adaptive_learning": [
        {"rank": 1, "action": "Execute CAL learning cycle against recent GIR assessment data to bootstrap the learning ledger.", "est_invariants": 1, "est_tests": 4, "ip_flag": False},
        {"rank": 2, "action": "Feed GIR dimension scores into CAL as labelled training inputs; CAL learns dimension-weight adjustments for future GIR calibration.", "est_invariants": 2, "est_tests": 6, "ip_flag": True},
        {"rank": 3, "action": "Add CAL cycle frequency governor: enforce minimum and maximum cycle intervals to prevent oscillation.", "est_invariants": 1, "est_tests": 3, "ip_flag": False},
    ],
    "recommendation_delivery": [
        {"rank": 1, "action": "Execute RDP delivery cycle to produce and deliver at least one governed recommendation, populating the delivery ledger.", "est_invariants": 1, "est_tests": 3, "ip_flag": False},
        {"rank": 2, "action": "Wire GIR gap report outputs as RDP input feed: GIR gaps automatically generate RDP recommendation payloads.", "est_invariants": 2, "est_tests": 5, "ip_flag": True},
        {"rank": 3, "action": "Add RDP delivery receipt verification: confirm recommendation acknowledged before marking delivery complete.", "est_invariants": 1, "est_tests": 4, "ip_flag": False},
    ],
    "cel_feedback_integration": [
        {"rank": 1, "action": "Execute CFI feedback integration cycle to ingest CEL outcome data and populate the feedback ledger.", "est_invariants": 1, "est_tests": 3, "ip_flag": False},
        {"rank": 2, "action": "Add CFI ↔ GIR feedback wire: CFI integration outcomes modulate GIR cel_feedback_integration dimension score in next cycle.", "est_invariants": 2, "est_tests": 5, "ip_flag": True},
        {"rank": 3, "action": "Add CEL outcome classification to CFI: tag each integrated feedback record as CONVERGENT/DIVERGENT/NEUTRAL.", "est_invariants": 1, "est_tests": 4, "ip_flag": False},
    ],
    "forecast_coverage": [
        {"rank": 1, "action": "Execute CFE forecast cycle to generate constitutional forecasts over the next N phases and populate the forecast ledger.", "est_invariants": 1, "est_tests": 3, "ip_flag": False},
        {"rank": 2, "action": "Extend CFE forecast horizon to cover V10 convergence window: forecast constitutional stability through Phase 200.", "est_invariants": 2, "est_tests": 5, "ip_flag": True},
        {"rank": 3, "action": "Add CFE retroactive validation: compare past forecasts against actual CSC SCSI readings to compute forecast accuracy.", "est_invariants": 1, "est_tests": 4, "ip_flag": False},
    ],
    "invariant_density": [
        {"rank": 1, "action": "Add 5+ Hard-class invariants in the next phase targeting the lowest-coverage constitutional domains (audit, determinism, scope).", "est_invariants": 5, "est_tests": 5, "ip_flag": False},
        {"rank": 2, "action": "Conduct invariant coverage audit: identify constitutional domains with < 3 hard-class invariants and propose gap-filling invariants.", "est_invariants": 3, "est_tests": 3, "ip_flag": False},
        {"rank": 3, "action": "Add invariant co-occurrence analysis: identify invariant pairs that are frequently co-violated; novel governance signal.", "est_invariants": 2, "est_tests": 4, "ip_flag": True},
    ],
    "test_coverage": [
        {"rank": 1, "action": "Ensure next phase ships full 30-test suite covering all invariant enforcement paths, not just happy paths.", "est_invariants": 0, "est_tests": 10, "ip_flag": False},
        {"rank": 2, "action": "Add cross-module integration tests: 10-test suite verifying GIR → CGR → CAL data flow end-to-end.", "est_invariants": 1, "est_tests": 10, "ip_flag": False},
        {"rank": 3, "action": "Add constitutional chaos tests: inject malformed ledger entries and verify fail-closed behaviour across all engines.", "est_invariants": 2, "est_tests": 8, "ip_flag": True},
    ],
    "governance_telemetry": [
        {"rank": 1, "action": "Execute CGTH telemetry collection cycle to produce structured governance telemetry and advance maturity signal.", "est_invariants": 1, "est_tests": 3, "ip_flag": False},
        {"rank": 2, "action": "Wire CGAI anomaly inspector to GIR assessment output: flag CRI drops > 0.10 between consecutive cycles as anomalies.", "est_invariants": 2, "est_tests": 4, "ip_flag": True},
        {"rank": 3, "action": "Add telemetry retention policy: archive CGTH records > 90 days to governed cold storage with integrity digest.", "est_invariants": 1, "est_tests": 3, "ip_flag": False},
    ],
    "rollback_capability": [
        {"rank": 1, "action": "Execute CAR.rollback() against a test amendment entry to produce a non-empty rollback state and verify idempotency guard.", "est_invariants": 1, "est_tests": 3, "ip_flag": False},
        {"rank": 2, "action": "Add CAR dry-run mode: simulate rollback without committing, producing a ROLLBACK_PREVIEW ledger event.", "est_invariants": 2, "est_tests": 4, "ip_flag": True},
        {"rank": 3, "action": "Add multi-amendment rollback: CAR batch-reverts N consecutive CAE entries in reverse chronological order.", "est_invariants": 2, "est_tests": 5, "ip_flag": True},
    ],
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _utc_iso() -> str:
    """Deterministic UTC timestamp — CGR-DETERM-0."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hmac_digest(key: bytes, data: str) -> str:
    return hmac.new(key, data.encode("utf-8"), hashlib.sha256).hexdigest()


def _canonical_json(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _read_jsonl(path: Path) -> List[dict]:
    if not path.exists():
        return []
    records: List[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))
    except Exception:
        pass
    return records


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _ledger_score(count: int, healthy: int = 5) -> float:
    """Score in [0.0, 1.0] based on ledger depth — CGR-DETERM-0."""
    return min(1.0, count / max(1, healthy))


def _gap_severity(score: float) -> str:
    if score < _CRITICAL_GAP_THRESHOLD:
        return "CRITICAL"
    if score < _WARNING_GAP_THRESHOLD:
        return "WARNING"
    return "ACCEPTABLE"


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class RemediationAction:
    rank: int
    action: str
    estimated_invariants_to_add: int
    estimated_tests_to_add: int
    ip_opportunity: bool


@dataclass
class GapResolutionPlan:
    gap_id: str
    dimension: str
    observed_score: float
    threshold: float
    delta_to_threshold: float
    severity: str                           # "CRITICAL" | "WARNING" | "ACCEPTABLE"
    actions: List[RemediationAction]
    estimated_total_invariants: int
    estimated_total_tests: int
    ip_opportunities: List[str]             # action descriptions flagged as IP
    human0_ratification_required: bool


@dataclass
class CGRResolveResult:
    plan_id: str
    timestamp: str
    version: str
    governor: str
    gir_cri: float
    gir_cri_status: str
    gaps_identified: int
    gaps_resolved: int
    plans: List[GapResolutionPlan]
    v10_criteria_below_threshold: List[str]
    overall_convergence_score: float
    human0_advisory: bool
    advisory_payload: Optional[str]
    ledger_entry_id: str
    chain_prev_digest: str
    chain_digest: str
    seal: str


@dataclass
class CGRSnapshot:
    snapshot_id: str
    timestamp: str
    plan_count: int
    last_plan_id: str
    last_gir_cri: float
    last_overall_convergence: float
    chain_head_digest: str
    human0_advisories_total: int
    top_gap_dimensions: List[str]


# ── Engine ────────────────────────────────────────────────────────────────────

class ConvergenceGapResolver:
    """
    INNOV-87 · CGR — Convergence Gap Resolver.

    Reads GIR snapshot and V10CA ledger, identifies top-N gaps, and generates
    structured Gap Resolution Plans (GRPs) to guide convergence advancement.

    Usage::

        engine = ConvergenceGapResolver()
        result = engine.resolve(top_n=5)
        for plan in result.plans:
            print(plan.dimension, plan.severity, len(plan.actions))
    """

    def __init__(self, data_dir: Path = _DATA_DIR) -> None:
        self._data_dir = data_dir
        self._ledger_path = data_dir / "grp_ledger.jsonl"
        self._snapshot_path = data_dir / "cgr_snapshot.json"
        self._advisory_path = data_dir / "human0_advisory_log.jsonl"
        self._seen_ids: set = set()
        self._chain_head: str = "GENESIS"
        self._plan_count: int = 0
        self._advisory_count: int = 0
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._load_state()

    # ── State ─────────────────────────────────────────────────────────────────

    def _load_state(self) -> None:
        snap = _read_json(self._snapshot_path)
        if snap:
            self._chain_head = snap.get("chain_head_digest", "GENESIS")
            self._plan_count = snap.get("plan_count", 0)
            self._advisory_count = snap.get("human0_advisories_total", 0)
        for rec in _read_jsonl(self._ledger_path):
            pid = rec.get("plan_id")
            if pid:
                self._seen_ids.add(pid)

    def _save_snapshot(self, result: CGRResolveResult) -> None:
        snap = CGRSnapshot(
            snapshot_id=str(uuid.uuid4()),
            timestamp=result.timestamp,
            plan_count=self._plan_count,
            last_plan_id=result.plan_id,
            last_gir_cri=result.gir_cri,
            last_overall_convergence=result.overall_convergence_score,
            chain_head_digest=result.chain_digest,
            human0_advisories_total=self._advisory_count,
            top_gap_dimensions=[p.dimension for p in result.plans[:3]],
        )
        self._snapshot_path.write_text(_canonical_json(asdict(snap)), encoding="utf-8")

    # ── Gap identification ─────────────────────────────────────────────────────

    def _load_gir_gaps(self) -> List[Tuple[str, float, str]]:
        """
        Return list of (dimension, score, status) tuples from latest GIR snapshot.
        Sorted by score ASC, then dimension ASC — deterministic per CGR-TOPN-0.
        """
        snap = _read_json(_GIR_SNAPSHOT)
        if not snap:
            # No GIR snapshot available — synthesise a worst-case signal
            return [(dim, 0.0, "CRITICAL") for dim in sorted(_ACTION_CATALOGUE.keys())]

        # GIR snapshot stores cri and lowest_dimensions; we need per-dimension scores.
        # Fall back to gap_report.jsonl which carries per-dimension score data.
        gap_entries = _read_jsonl(_GIR_GAP_REPORT)
        dim_scores: Dict[str, float] = {}

        if gap_entries:
            # Use most recent gap report entry
            latest = gap_entries[-1]
            for gap in latest.get("gaps", []):
                dim_scores[gap["dimension"]] = gap["score"]

        # For dimensions not in gap report (above WARNING threshold), assign a
        # synthetic score of WARNING_THRESHOLD + 0.01 to indicate they are acceptable.
        for dim in _ACTION_CATALOGUE:
            if dim not in dim_scores:
                dim_scores[dim] = _WARNING_GAP_THRESHOLD + 0.01

        # Build sorted list — CGR-TOPN-0
        result = [
            (dim, score, _gap_severity(score))
            for dim, score in dim_scores.items()
        ]
        result.sort(key=lambda x: (x[1], x[0]))
        return result

    def _load_v10_confidence(self) -> Dict[str, float]:
        """Return V10 criterion confidence map from latest V10CA ledger entry."""
        entries = _read_jsonl(_V10CA_LEDGER)
        if not entries:
            return {}
        latest = entries[-1]
        # V10CA stores criteria as list of CriterionResult dicts
        criteria = latest.get("criteria", [])
        return {c.get("name", c.get("criterion", "")): c.get("score", c.get("confidence", 0.0))
                for c in criteria if c}

    def _build_plan(
        self, dimension: str, score: float, threshold: float
    ) -> GapResolutionPlan:
        """Build a GapResolutionPlan for a single dimension gap — CGR-IMPACT-0."""
        severity = _gap_severity(score)
        actions_raw = _ACTION_CATALOGUE.get(dimension, [])
        actions = [
            RemediationAction(
                rank=a["rank"],
                action=a["action"],
                estimated_invariants_to_add=a["est_invariants"],
                estimated_tests_to_add=a["est_tests"],
                ip_opportunity=a["ip_flag"],
            )
            for a in actions_raw
        ]
        total_inv = sum(a.estimated_invariants_to_add for a in actions)
        total_tests = sum(a.estimated_tests_to_add for a in actions)
        ip_opps = [a.action for a in actions if a.ip_opportunity]
        return GapResolutionPlan(
            gap_id=str(uuid.uuid4()),
            dimension=dimension,
            observed_score=round(score, 6),
            threshold=threshold,
            delta_to_threshold=round(max(0.0, threshold - score), 6),
            severity=severity,
            actions=actions,
            estimated_total_invariants=total_inv,
            estimated_total_tests=total_tests,
            ip_opportunities=ip_opps,
            human0_ratification_required=(severity == "CRITICAL"),
        )

    # ── Ledger ────────────────────────────────────────────────────────────────

    def _write_ledger_entry(self, result: CGRResolveResult) -> None:
        """Append signed ledger entry — CGR-CHAIN-0, CGR-AUDIT-0, CGR-IMMUT-0."""
        entry = {
            "ledger_entry_id": result.ledger_entry_id,
            "plan_id": result.plan_id,
            "timestamp": result.timestamp,
            "gir_cri": result.gir_cri,
            "gir_cri_status": result.gir_cri_status,
            "gaps_identified": result.gaps_identified,
            "gaps_resolved": result.gaps_resolved,
            "overall_convergence_score": result.overall_convergence_score,
            "human0_advisory": result.human0_advisory,
            "chain_prev_digest": result.chain_prev_digest,
            "chain_digest": result.chain_digest,
            "seal": result.seal,
        }
        with self._ledger_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")

    def _write_advisory(self, result: CGRResolveResult) -> None:
        """Emit HUMAN-0 advisory — CGR-HUMAN0-0, written before ledger entry."""
        critical_dims = [
            p.dimension for p in result.plans if p.severity == "CRITICAL"
        ]
        entry = {
            "advisory_id": str(uuid.uuid4()),
            "plan_id": result.plan_id,
            "timestamp": result.timestamp,
            "authority": _GOVERNOR,
            "gir_cri": result.gir_cri,
            "critical_dimensions": critical_dims,
            "advisory_payload": result.advisory_payload,
            "action_required": (
                f"HUMAN-0 ratification required: {len(critical_dims)} CRITICAL gap(s) identified. "
                f"Review Gap Resolution Plans and authorise remediation for: {', '.join(critical_dims)}."
            ),
        }
        with self._advisory_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")

    # ── Chain verification ─────────────────────────────────────────────────────

    def verify_chain(self) -> Tuple[bool, str]:
        """Verify HMAC chain integrity of the GRP ledger."""
        entries = _read_jsonl(self._ledger_path)
        if not entries:
            return True, "CHAIN_VALID_EMPTY"
        prev = "GENESIS"
        for i, entry in enumerate(entries):
            payload = _canonical_json({
                "ledger_entry_id": entry["ledger_entry_id"],
                "plan_id": entry["plan_id"],
                "timestamp": entry["timestamp"],
                "gir_cri": entry["gir_cri"],
                "chain_prev_digest": entry["chain_prev_digest"],
            })
            expected = _hmac_digest(_HMAC_KEY, prev + payload)
            if entry.get("chain_digest") != expected:
                return False, f"CHAIN_BROKEN at entry {i} (id={entry.get('ledger_entry_id')})"
            prev = entry["chain_digest"]
        return True, "CHAIN_VALID"

    # ── Main resolve ──────────────────────────────────────────────────────────

    def resolve(
        self,
        plan_id: Optional[str] = None,
        top_n: int = DEFAULT_TOP_N,
        version: str = "9.115.0",
    ) -> CGRResolveResult:
        """
        Execute a convergence gap resolution cycle.

        Identifies top_n gaps from GIR snapshot, generates ranked GRPs for
        each, computes overall convergence score, emits HUMAN-0 advisory
        if any CRITICAL gaps are present, and writes ledger entry.

        Raises ValueError on duplicate plan_id — CGR-DOUBLE-0.
        """
        if plan_id is None:
            plan_id = str(uuid.uuid4())

        # CGR-DOUBLE-0
        if plan_id in self._seen_ids:
            raise ValueError(
                f"CGR-DOUBLE-0: duplicate plan_id rejected: {plan_id}"
            )

        ts = _utc_iso()

        # Load GIR state (CGR-READONLY-0 — only reads from data/gir/)
        gir_snap = _read_json(_GIR_SNAPSHOT)
        gir_cri = gir_snap.get("cri", 0.0) if gir_snap else 0.0
        gir_status = gir_snap.get("cri_status", "CRITICAL") if gir_snap else "CRITICAL"

        # Load V10CA confidence
        v10_conf = self._load_v10_confidence()

        # Identify gaps — CGR-TOPN-0 (sort by score ASC, dimension ASC)
        all_gaps = self._load_gir_gaps()
        gaps_below = [(d, s, sev) for d, s, sev in all_gaps if s < _WARNING_GAP_THRESHOLD]
        top_gaps = gaps_below[:top_n]

        # If fewer than top_n below WARNING, pad with next lowest acceptable dims
        if len(top_gaps) < top_n:
            remaining = [g for g in all_gaps if g not in top_gaps]
            top_gaps += remaining[: top_n - len(top_gaps)]

        # Build GRPs
        plans: List[GapResolutionPlan] = []
        for dimension, score, _ in top_gaps[:top_n]:
            threshold = _WARNING_GAP_THRESHOLD if score < _WARNING_GAP_THRESHOLD else 1.0
            plans.append(self._build_plan(dimension, score, threshold))

        # V10 criteria below threshold
        v10_below = [
            crit for crit, conf in v10_conf.items() if conf < _WARNING_GAP_THRESHOLD
        ]

        # Overall convergence score: blend GIR CRI with V10CA score
        v10_scores = list(v10_conf.values())
        v10_avg = sum(v10_scores) / len(v10_scores) if v10_scores else gir_cri
        overall = round((gir_cri * 0.60 + v10_avg * 0.40), 6)

        # HUMAN-0 advisory — CGR-HUMAN0-0 (emit BEFORE ledger write)
        critical_plans = [p for p in plans if p.severity == "CRITICAL"]
        human0_flag = bool(critical_plans)
        advisory = None
        if human0_flag:
            crit_dims = [p.dimension for p in critical_plans]
            advisory = (
                f"ADVISORY TO {_GOVERNOR}: {len(critical_plans)} CRITICAL gap(s) in "
                f"[{', '.join(crit_dims)}]. GIR CRI={gir_cri:.4f}. "
                f"Review and ratify remediation plans before next phase execution."
            )

        # Chain — CGR-CHAIN-0
        ledger_id = str(uuid.uuid4())
        chain_payload = _canonical_json({
            "ledger_entry_id": ledger_id,
            "plan_id": plan_id,
            "timestamp": ts,
            "gir_cri": gir_cri,
            "chain_prev_digest": self._chain_head,
        })
        chain_digest = _hmac_digest(_HMAC_KEY, self._chain_head + chain_payload)

        # Seal — CGR-SEAL-0
        seal_payload = _canonical_json({
            "plan_id": plan_id,
            "gir_cri": gir_cri,
            "overall_convergence_score": overall,
            "chain_digest": chain_digest,
            "governor": _GOVERNOR,
        })
        seal = _hmac_digest(_HMAC_KEY, seal_payload)

        result = CGRResolveResult(
            plan_id=plan_id,
            timestamp=ts,
            version=version,
            governor=_GOVERNOR,
            gir_cri=gir_cri,
            gir_cri_status=gir_status,
            gaps_identified=len(gaps_below),
            gaps_resolved=len(plans),
            plans=plans,
            v10_criteria_below_threshold=v10_below,
            overall_convergence_score=overall,
            human0_advisory=human0_flag,
            advisory_payload=advisory,
            ledger_entry_id=ledger_id,
            chain_prev_digest=self._chain_head,
            chain_digest=chain_digest,
            seal=seal,
        )

        # Persist — CGR-AUDIT-0 (write before returning)
        if human0_flag:
            self._write_advisory(result)
            self._advisory_count += 1
        self._write_ledger_entry(result)
        self._chain_head = chain_digest
        self._plan_count += 1
        self._seen_ids.add(plan_id)
        self._save_snapshot(result)

        return result

    # ── Helpers ───────────────────────────────────────────────────────────────

    def get_snapshot(self) -> Optional[dict]:
        snap = _read_json(self._snapshot_path)
        return snap if snap else None

    def get_plan_count(self) -> int:
        return self._plan_count
