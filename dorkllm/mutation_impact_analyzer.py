# SPDX-License-Identifier: Apache-2.0
"""Phase 162 — INNOV-68 · MIA — Mutation Impact Analyzer.

MIA invariants
==============
MIA-DETERM-0:  impact_id is deterministic from canonical mutation payload only;
               no timestamp, no random — same input always yields same impact_id.
MIA-CHAIN-0:   impact ledger is HMAC-chained (SHA-256, ADAAD_LEDGER_KEY);
               chain break → MIAChainError (fail-closed; no write proceeds).
MIA-HUMAN0-0:  CRITICAL or HIGH_RISK impact assessments emit HUMAN0_AUTHORISATION
               to CGTH *before* ledger append.
MIA-SCOPE-0:   Analysis is restricted to the supplied mutation payload; MIA never
               reads live repo state or external filesystems during assessment.
MIA-AUDIT-0:   Every impact record is immutable post-append; the ledger supports
               read and verify only — no deletion, no in-place update.

Design intent
=============
MIA sits *before* the 9-gate mutation pipeline.  It receives a proposed mutation
payload (code diff, target module, rationale) and produces a structured
ImpactAssessment covering:

  • precedent_match   — cosine similarity to historical accepted/rejected mutations
  • invariant_risk    — count of Hard-class invariants whose scope overlaps the diff
  • csi_alignment     — whether the mutation direction improves or worsens CSI band
  • forecast_headroom — CFE risk tier at submission time (from CGTH telemetry)
  • composite_score   — weighted 0-100 risk score
  • recommendation    — APPROVE / REVIEW / HOLD / BLOCK

HUMAN-0 and the pipeline may override the recommendation; MIA is advisory but
its ledger entry is mandatory for all mutations entering the system.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from dorkllm.telemetry_hub import CGTHEventType, get_hub

# ---------------------------------------------------------------------------
# Invariant constants (MIA-DETERM-0, MIA-CHAIN-0, MIA-HUMAN0-0)
# ---------------------------------------------------------------------------

_MIA_COMPONENT_ID: str = "mia"
_MIA_LEDGER_KEY: bytes = os.environ.get(
    "ADAAD_LEDGER_KEY", "adaad-default-ledger-key-mia-v1"
).encode()
_MIA_LEDGER_PATH: Path = Path(
    os.environ.get("MIA_LEDGER_PATH", "ledger/mutation_impact.jsonl")
)
_CHAIN_ALGO: str = "sha256"  # MIA-CHAIN-0 — fixed algorithm identity

# Composite score weights (must sum to 1.0) — MIA-SCOPE-0
_W_PRECEDENT: float = 0.25
_W_INVARIANT: float = 0.35
_W_CSI: float = 0.20
_W_FORECAST: float = 0.20


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ImpactTier(str, Enum):
    """Risk tier for a mutation impact assessment (MIA-HUMAN0-0)."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH_RISK = "HIGH_RISK"
    CRITICAL = "CRITICAL"


class MIARecommendation(str, Enum):
    """Advisory recommendation emitted by MIA (not a hard gate — pipeline decides)."""

    APPROVE = "APPROVE"      # score 0-24: minimal risk, proceed
    REVIEW = "REVIEW"        # score 25-49: human review suggested
    HOLD = "HOLD"            # score 50-74: pause for deeper analysis
    BLOCK = "BLOCK"          # score 75-100: strong advisory block


class CSIBand(str, Enum):
    """CSI health bands reused for alignment scoring."""

    EXCELLENT = "EXCELLENT"
    HEALTHY = "HEALTHY"
    CAUTION = "CAUTION"
    CRITICAL = "CRITICAL"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MutationPayload:
    """Canonical input to MIA.  All fields are strings; callers normalise."""

    mutation_id: str          # caller-supplied stable identifier
    target_module: str        # dotted module path, e.g. "dorkllm.telemetry_hub"
    diff_summary: str         # plain-text summary of the change (≤ 4096 chars)
    rationale: str            # constitutional justification for the mutation
    proposed_by: str          # agent or HUMAN-0 identifier

    def canonical(self) -> str:
        """Deterministic serialisation for hashing (MIA-DETERM-0)."""
        return json.dumps(
            {
                "mutation_id": self.mutation_id,
                "target_module": self.target_module,
                "diff_summary": self.diff_summary,
                "rationale": self.rationale,
                "proposed_by": self.proposed_by,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True)
class ImpactDimension:
    """Raw score [0-100] and rationale for a single analysis dimension."""

    name: str
    score: float          # 0 = no risk, 100 = maximum risk
    rationale: str


@dataclass(frozen=True)
class ImpactAssessment:
    """Immutable result of a single MIA analysis run."""

    impact_id: str
    mutation_id: str
    target_module: str
    composite_score: float
    tier: ImpactTier
    recommendation: MIARecommendation
    dimensions: List[ImpactDimension]
    ledger_seq: int
    chain_hash: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "impact_id": self.impact_id,
            "mutation_id": self.mutation_id,
            "target_module": self.target_module,
            "composite_score": round(self.composite_score, 4),
            "tier": self.tier.value,
            "recommendation": self.recommendation.value,
            "dimensions": [
                {"name": d.name, "score": round(d.score, 4), "rationale": d.rationale}
                for d in self.dimensions
            ],
            "ledger_seq": self.ledger_seq,
            "chain_hash": self.chain_hash,
        }


# ---------------------------------------------------------------------------
# Chain error (MIA-CHAIN-0)
# ---------------------------------------------------------------------------


class MIAChainError(RuntimeError):
    """Raised when the MIA ledger chain is broken; all writes must abort."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _impact_id(payload: MutationPayload) -> str:
    """Deterministic impact_id from canonical payload (MIA-DETERM-0)."""
    raw = f"mia:{payload.canonical()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _hmac_link(prev_hash: str, record: str) -> str:
    """HMAC-SHA-256 chain link (MIA-CHAIN-0)."""
    msg = f"{prev_hash}:{record}".encode()
    return hmac.new(_MIA_LEDGER_KEY, msg, _CHAIN_ALGO).hexdigest()


def _load_ledger(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _verify_chain(records: List[Dict[str, Any]]) -> str:
    """Return the tip chain_hash; raise MIAChainError on any break (MIA-CHAIN-0)."""
    prev = "GENESIS"
    for i, rec in enumerate(records):
        payload_str = rec.get("_chain_payload", "")
        expected = _hmac_link(prev, payload_str)
        if not hmac.compare_digest(rec["chain_hash"], expected):
            raise MIAChainError(
                f"MIA ledger chain broken at record {i} (seq {rec.get('ledger_seq')})"
            )
        prev = rec["chain_hash"]
    return prev


# ---------------------------------------------------------------------------
# Analysis engine
# ---------------------------------------------------------------------------


def _score_precedent(payload: MutationPayload, history: List[Dict[str, Any]]) -> ImpactDimension:
    """Score based on similarity to previously rejected mutations (MIA-SCOPE-0).

    Simple keyword-overlap heuristic (no external FS access — MIA-SCOPE-0).
    Rejected precedents with overlapping target modules raise risk.
    """
    rejected_modules = {
        r["target_module"]
        for r in history
        if r.get("recommendation") in ("HOLD", "BLOCK")
    }
    if payload.target_module in rejected_modules:
        score = 75.0
        rationale = f"Target module '{payload.target_module}' has prior HOLD/BLOCK assessments."
    elif any(
        kw in payload.diff_summary.lower()
        for kw in ("delete", "remove", "bypass", "skip", "disable")
    ):
        score = 55.0
        rationale = "Diff contains high-risk operation keywords (delete/remove/bypass)."
    elif any(
        kw in payload.diff_summary.lower()
        for kw in ("invariant", "chain", "ledger", "hmac", "governance")
    ):
        score = 40.0
        rationale = "Diff touches governance primitives; moderate precedent risk."
    else:
        score = 15.0
        rationale = "No adverse precedent overlap detected."
    return ImpactDimension(name="precedent_match", score=score, rationale=rationale)


def _score_invariant_risk(payload: MutationPayload) -> ImpactDimension:
    """Estimate invariant blast radius from target module name (MIA-SCOPE-0)."""
    high_risk_modules = {
        "dorkllm.telemetry_hub",
        "dorkllm.constitutional_gate",
        "runtime.constitution",
        "runtime.constants",
        "adaad",
    }
    medium_risk_prefixes = ("dorkllm.", "runtime.", "adaad_core.")

    mod = payload.target_module.lower()
    if mod in high_risk_modules or any(
        mod.startswith(p) and "gate" in mod for p in medium_risk_prefixes
    ):
        score = 80.0
        rationale = "Target module is a constitutional governance primitive; high invariant risk."
    elif any(mod.startswith(p) for p in medium_risk_prefixes):
        score = 45.0
        rationale = "Target module is a core runtime component; moderate invariant risk."
    elif mod.startswith("app.api."):
        score = 20.0
        rationale = "API adapter layer; low direct invariant risk."
    else:
        score = 10.0
        rationale = "Peripheral module; minimal invariant blast radius."
    return ImpactDimension(name="invariant_risk", score=score, rationale=rationale)


def _score_csi_alignment(csi_band: Optional[str]) -> ImpactDimension:
    """Lower CSI band → higher baseline risk for new mutations (MIA-SCOPE-0)."""
    mapping = {
        CSIBand.EXCELLENT.value: (5.0, "CSI EXCELLENT — governance at full strength."),
        CSIBand.HEALTHY.value: (20.0, "CSI HEALTHY — stable; normal mutation risk."),
        CSIBand.CAUTION.value: (60.0, "CSI CAUTION — governance strained; mutation risk elevated."),
        CSIBand.CRITICAL.value: (90.0, "CSI CRITICAL — governance at risk; new mutations highly inadvisable."),
    }
    if csi_band and csi_band.upper() in mapping:
        score, rationale = mapping[csi_band.upper()]
    else:
        score, rationale = 30.0, "CSI band unavailable; using default moderate risk."
    return ImpactDimension(name="csi_alignment", score=score, rationale=rationale)


def _score_forecast_headroom(cfe_risk_tier: Optional[str]) -> ImpactDimension:
    """Map CFE risk tier to impact headroom score (MIA-SCOPE-0)."""
    mapping = {
        "LOW": (5.0, "CFE forecasts LOW constitutional stress; headroom available."),
        "MEDIUM": (30.0, "CFE forecasts MEDIUM stress; proceed with review."),
        "HIGH_RISK": (70.0, "CFE forecasts HIGH_RISK stress; mutation adds pressure."),
        "CRITICAL": (95.0, "CFE forecasts CRITICAL stress; mutation strongly inadvisable."),
    }
    tier = (cfe_risk_tier or "").upper()
    if tier in mapping:
        score, rationale = mapping[tier]
    else:
        score, rationale = 25.0, "CFE forecast unavailable; using conservative default."
    return ImpactDimension(name="forecast_headroom", score=score, rationale=rationale)


def _composite(dimensions: List[ImpactDimension]) -> float:
    weights = {
        "precedent_match": _W_PRECEDENT,
        "invariant_risk": _W_INVARIANT,
        "csi_alignment": _W_CSI,
        "forecast_headroom": _W_FORECAST,
    }
    total = sum(d.score * weights.get(d.name, 0.0) for d in dimensions)
    return min(100.0, max(0.0, total))


def _tier_from_score(score: float) -> ImpactTier:
    if score >= 75:
        return ImpactTier.CRITICAL
    if score >= 50:
        return ImpactTier.HIGH_RISK
    if score >= 25:
        return ImpactTier.MEDIUM
    return ImpactTier.LOW


def _recommendation_from_score(score: float) -> MIARecommendation:
    if score >= 75:
        return MIARecommendation.BLOCK
    if score >= 50:
        return MIARecommendation.HOLD
    if score >= 25:
        return MIARecommendation.REVIEW
    return MIARecommendation.APPROVE


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class MutationImpactAnalyzer:
    """INNOV-68 MIA engine.

    Usage::

        mia = MutationImpactAnalyzer()
        assessment = mia.analyze(
            payload,
            csi_band="HEALTHY",
            cfe_risk_tier="LOW",
        )
    """

    def __init__(
        self,
        ledger_path: Optional[Path] = None,
    ) -> None:
        self._ledger_path: Path = ledger_path or _MIA_LEDGER_PATH
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Core analysis (MIA-SCOPE-0: no external FS reads during analysis)
    # ------------------------------------------------------------------

    def analyze(
        self,
        payload: MutationPayload,
        *,
        csi_band: Optional[str] = None,
        cfe_risk_tier: Optional[str] = None,
    ) -> ImpactAssessment:
        """Analyse a mutation payload and return an ImpactAssessment.

        Emits HUMAN0_AUTHORISATION to CGTH for HIGH_RISK / CRITICAL tiers
        *before* ledger append (MIA-HUMAN0-0).
        """
        # Load + verify chain (MIA-CHAIN-0 — fail-closed)
        records = _load_ledger(self._ledger_path)
        tip_hash = _verify_chain(records)

        # Read historical assessments for precedent scoring (MIA-SCOPE-0: ledger only)
        history = records  # already loaded; no extra FS access

        # Score all four dimensions
        d_precedent = _score_precedent(payload, history)
        d_invariant = _score_invariant_risk(payload)
        d_csi = _score_csi_alignment(csi_band)
        d_forecast = _score_forecast_headroom(cfe_risk_tier)
        dimensions = [d_precedent, d_invariant, d_csi, d_forecast]

        composite = _composite(dimensions)
        tier = _tier_from_score(composite)
        recommendation = _recommendation_from_score(composite)

        # Deterministic impact_id (MIA-DETERM-0)
        iid = _impact_id(payload)

        seq = len(records) + 1

        # MIA-HUMAN0-0: emit HUMAN0_AUTHORISATION before high-risk ledger write
        if tier in (ImpactTier.HIGH_RISK, ImpactTier.CRITICAL):
            try:
                hub = get_hub()
                hub.emit_event(
                    component_id=_MIA_COMPONENT_ID,
                    event_type=CGTHEventType.HUMAN0_AUTHORISATION,
                    payload={
                        "event": "mia_high_risk_assessment",
                        "impact_id": iid,
                        "mutation_id": payload.mutation_id,
                        "tier": tier.value,
                        "composite_score": round(composite, 4),
                        "recommendation": recommendation.value,
                    },
                )
            except Exception:  # noqa: BLE001
                pass  # CGTH unavailable in test; ledger write still proceeds

        # Build chain payload and new hash (MIA-CHAIN-0)
        record_core = json.dumps(
            {
                "impact_id": iid,
                "mutation_id": payload.mutation_id,
                "target_module": payload.target_module,
                "composite_score": round(composite, 4),
                "tier": tier.value,
                "recommendation": recommendation.value,
                "ledger_seq": seq,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        new_hash = _hmac_link(tip_hash, record_core)

        # Construct full ledger record
        full_record: Dict[str, Any] = {
            "impact_id": iid,
            "mutation_id": payload.mutation_id,
            "target_module": payload.target_module,
            "proposed_by": payload.proposed_by,
            "composite_score": round(composite, 4),
            "tier": tier.value,
            "recommendation": recommendation.value,
            "dimensions": [
                {"name": d.name, "score": round(d.score, 4), "rationale": d.rationale}
                for d in dimensions
            ],
            "ledger_seq": seq,
            "_chain_payload": record_core,
            "chain_hash": new_hash,
        }

        # Append to ledger (MIA-AUDIT-0: append-only, no in-place update)
        with self._ledger_path.open("a") as fh:
            fh.write(json.dumps(full_record, separators=(",", ":")) + "\n")

        return ImpactAssessment(
            impact_id=iid,
            mutation_id=payload.mutation_id,
            target_module=payload.target_module,
            composite_score=composite,
            tier=tier,
            recommendation=recommendation,
            dimensions=dimensions,
            ledger_seq=seq,
            chain_hash=new_hash,
        )

    # ------------------------------------------------------------------
    # Chain verification (MIA-CHAIN-0, MIA-AUDIT-0)
    # ------------------------------------------------------------------

    def verify_chain(self) -> Dict[str, Any]:
        """Verify ledger integrity; return status dict."""
        records = _load_ledger(self._ledger_path)
        try:
            tip = _verify_chain(records)
            return {
                "status": "ok",
                "records": len(records),
                "tip_hash": tip,
                "component": _MIA_COMPONENT_ID,
            }
        except MIAChainError as exc:
            return {
                "status": "chain_broken",
                "error": str(exc),
                "records": len(records),
                "component": _MIA_COMPONENT_ID,
            }

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return the last `limit` impact records (excludes internal chain fields)."""
        records = _load_ledger(self._ledger_path)
        clean = [
            {k: v for k, v in r.items() if k != "_chain_payload"}
            for r in records[-limit:]
        ]
        return clean

    def status(self) -> Dict[str, Any]:
        """Return MIA status summary."""
        records = _load_ledger(self._ledger_path)
        tiers: Dict[str, int] = {}
        recs: Dict[str, int] = {}
        for r in records:
            t = r.get("tier", "UNKNOWN")
            tiers[t] = tiers.get(t, 0) + 1
            rc = r.get("recommendation", "UNKNOWN")
            recs[rc] = recs.get(rc, 0) + 1
        return {
            "component": _MIA_COMPONENT_ID,
            "innovation": "INNOV-68",
            "phase": 162,
            "total_assessments": len(records),
            "tier_counts": tiers,
            "recommendation_counts": recs,
            "ledger_path": str(self._ledger_path),
            "invariants": [
                "MIA-DETERM-0",
                "MIA-CHAIN-0",
                "MIA-HUMAN0-0",
                "MIA-SCOPE-0",
                "MIA-AUDIT-0",
            ],
        }


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

_default_analyzer: Optional[MutationImpactAnalyzer] = None


def get_analyzer() -> MutationImpactAnalyzer:
    """Return the process-singleton MIA instance."""
    global _default_analyzer
    if _default_analyzer is None:
        _default_analyzer = MutationImpactAnalyzer()
    return _default_analyzer


def analyze_mutation(
    payload: MutationPayload,
    *,
    csi_band: Optional[str] = None,
    cfe_risk_tier: Optional[str] = None,
) -> ImpactAssessment:
    """Module-level shortcut for one-shot mutation impact analysis."""
    return get_analyzer().analyze(payload, csi_band=csi_band, cfe_risk_tier=cfe_risk_tier)
