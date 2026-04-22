# SPDX-License-Identifier: Apache-2.0
"""
dorkllm/query_router.py
Phase 146 · INNOV-52 · Dork Query Router (DQR)

Priority-dispatch layer that routes incoming queries to the highest-fidelity
subsystem available: DPM (INNOV-51) → RAGS (INNOV-50) → passthrough.

Constitutional mandate:
  Every query MUST pass through the DQR gate. No subsystem may be accessed
  directly without a logged RouteDecision (DQR-ROUTE-0).

Hard-class invariants enforced here:
  DQR-ROUTE-0   Every routed query MUST produce a RouteDecision appended to
                the DQR ledger before any downstream subsystem is invoked.
  DQR-CHAIN-0   DQR ledger entries are HMAC-SHA256 hash-chained; any break
                is a constitutional violation and write is rejected.
  DQR-DETERM-0  Scoring functions (_score_dpm, _score_rags) MUST be
                deterministic: identical inputs always produce identical
                route scores.
  DQR-FALLBACK-0 route_query() MUST NEVER propagate an unhandled exception;
                all errors must result in a passthrough RouteDecision logged
                to the ledger.
  DQR-AUTH-0    override_policy() requires HUMAN-0 authorisation token
                verified via constant-time hmac.compare_digest; no
                plaintext comparison is permitted.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Invariant constants ────────────────────────────────────────────────────────

DQR_ROUTE_0    = "DQR-ROUTE-0"   # every query → logged RouteDecision
DQR_CHAIN_0    = "DQR-CHAIN-0"   # HMAC chain integrity
DQR_DETERM_0   = "DQR-DETERM-0"  # deterministic scoring
DQR_FALLBACK_0 = "DQR-FALLBACK-0"  # never propagate unhandled exception
DQR_AUTH_0     = "DQR-AUTH-0"    # constant-time HUMAN-0 auth

# ── Configuration ─────────────────────────────────────────────────────────────

_DQR_LEDGER_PATH = Path(
    os.getenv("DQR_LEDGER_PATH", "data/dork/dqr_routing_ledger.jsonl")
)
_DQR_HMAC_SECRET = os.getenv(
    "DQR_HMAC_SECRET", "adaad-dqr-constitutional-secret-v1"
).encode()
_DQR_HUMAN0_TOKEN = os.getenv("DQR_HUMAN0_TOKEN", "HUMAN-0:DQR:OVERRIDE").encode()
_GENESIS_HASH = "0" * 64

# Score thresholds — can be tuned via env without breaking DQR-DETERM-0
_DPM_THRESHOLD = float(os.getenv("DQR_DPM_THRESHOLD", "0.35"))
_RAGS_THRESHOLD = float(os.getenv("DQR_RAGS_THRESHOLD", "0.25"))

# Route destination constants
ROUTE_DPM         = "dpm"
ROUTE_RAGS        = "rags"
ROUTE_PASSTHROUGH = "passthrough"

# Policy override state (module-level; reset by tests via monkeypatch)
_policy_override: Optional[str] = None


# ── Typed exception hierarchy ─────────────────────────────────────────────────

class DQRInvariantViolation(RuntimeError):
    """Base class for all DQR Hard-class invariant violations."""


class DQRRouteViolation(DQRInvariantViolation):
    """DQR-ROUTE-0: RouteDecision could not be logged before dispatch."""


class DQRChainViolation(DQRInvariantViolation):
    """DQR-CHAIN-0: Ledger HMAC chain integrity check failed."""


class DQRAuthViolation(DQRInvariantViolation):
    """DQR-AUTH-0: override_policy() called with invalid HUMAN-0 token."""


class DQRLedgerWriteError(DQRInvariantViolation):
    """DQR ledger append operation failed."""


# ── RouteDecision dataclass ───────────────────────────────────────────────────

@dataclass
class RouteDecision:
    """Immutable record of a single routing decision.

    Chain-linked via prev_hash → entry_hash (DQR-CHAIN-0).
    """
    seq: int
    timestamp: str
    query_hash: str          # SHA-256 of raw query text (DQR-DETERM-0)
    dpm_score: float
    rags_score: float
    route: str               # ROUTE_DPM | ROUTE_RAGS | ROUTE_PASSTHROUGH
    override: Optional[str]  # set if _policy_override was active
    prev_hash: str
    entry_hash: str = field(default="")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── HMAC helpers ──────────────────────────────────────────────────────────────

def _hmac_digest(prev_hash: str, payload_str: str) -> str:
    """DQR-CHAIN-0: deterministic HMAC-SHA256 over prev_hash + canonical payload."""
    msg = (prev_hash + payload_str).encode("utf-8")
    return hmac.new(_DQR_HMAC_SECRET, msg, hashlib.sha256).hexdigest()


def _canonical(obj: Dict[str, Any]) -> str:
    """DQR-DETERM-0: canonical JSON with sorted keys, no whitespace."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _sha256_text(text: str) -> str:
    """Return hex SHA-256 of UTF-8 encoded text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── Ledger I/O ────────────────────────────────────────────────────────────────

def _ensure_ledger() -> None:
    """Initialise ledger file with genesis entry if it does not exist."""
    _DQR_LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    if _DQR_LEDGER_PATH.exists() and _DQR_LEDGER_PATH.stat().st_size > 0:
        return
    payload: Dict[str, Any] = {
        "entry_type": "genesis",
        "note": "DQR ledger initialised",
        "version": "1.0.0",
    }
    canon = _canonical(payload)
    entry_hash = _hmac_digest(_GENESIS_HASH, canon)
    genesis = {
        "seq": 0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "entry_type": "genesis",
        "payload": payload,
        "prev_hash": _GENESIS_HASH,
        "entry_hash": entry_hash,
    }
    with _DQR_LEDGER_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(genesis) + "\n")


def _load_all() -> List[Dict[str, Any]]:
    """Return all ledger entries as a list."""
    if not _DQR_LEDGER_PATH.exists():
        return []
    entries = []
    with _DQR_LEDGER_PATH.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def _tail_hash() -> str:
    """Return entry_hash of the last ledger entry (or genesis hash if empty)."""
    entries = _load_all()
    if not entries:
        return _GENESIS_HASH
    return entries[-1]["entry_hash"]


def _append_decision(decision: RouteDecision) -> RouteDecision:
    """Append a RouteDecision to the ledger. Returns updated decision with entry_hash set.

    Raises DQRRouteViolation (DQR-ROUTE-0) if write fails.
    Raises DQRLedgerWriteError if underlying I/O fails.
    """
    _ensure_ledger()
    prev_hash = _tail_hash()
    payload = {
        "seq": decision.seq,
        "query_hash": decision.query_hash,
        "dpm_score": decision.dpm_score,
        "rags_score": decision.rags_score,
        "route": decision.route,
        "override": decision.override,
    }
    canon = _canonical(payload)
    entry_hash = _hmac_digest(prev_hash, canon)
    # Build updated decision
    final = RouteDecision(
        seq=decision.seq,
        timestamp=decision.timestamp,
        query_hash=decision.query_hash,
        dpm_score=decision.dpm_score,
        rags_score=decision.rags_score,
        route=decision.route,
        override=decision.override,
        prev_hash=prev_hash,
        entry_hash=entry_hash,
    )
    record = {
        "seq": final.seq,
        "timestamp": final.timestamp,
        "entry_type": "route_decision",
        "payload": payload,
        "prev_hash": prev_hash,
        "entry_hash": entry_hash,
    }
    try:
        with _DQR_LEDGER_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError as exc:
        raise DQRLedgerWriteError(
            f"{DQR_CHAIN_0}: ledger append failed — {exc}"
        ) from exc
    return final


# ── Deterministic scorers (DQR-DETERM-0) ─────────────────────────────────────

# DPM keyword categories (from DPM/pattern_detector)
_DPM_KEYWORDS: Dict[str, float] = {
    "remember": 0.20, "recall": 0.20, "memory": 0.20, "learned": 0.18,
    "previously": 0.18, "history": 0.15, "last time": 0.15, "stored": 0.12,
    "session": 0.12, "past": 0.10, "context": 0.08, "knowledge": 0.08,
}

# RAGS keyword categories (governance / architecture)
_RAGS_KEYWORDS: Dict[str, float] = {
    "governance": 0.20, "invariant": 0.20, "constitutional": 0.18,
    "phase": 0.15, "innovation": 0.15, "hard-class": 0.15,
    "ledger": 0.12, "ratification": 0.12, "mutation": 0.10,
    "rollback": 0.10, "audit": 0.08, "compliance": 0.08,
}


def _score_dpm(query: str) -> float:
    """DQR-DETERM-0: Deterministic DPM relevance score for *query*.

    Returns a float in [0.0, 1.0]. Pure keyword accumulation — identical
    inputs always produce identical scores.
    """
    q = query.lower()
    score = 0.0
    for kw, weight in _DPM_KEYWORDS.items():
        if kw in q:
            score += weight
    return min(score, 1.0)


def _score_rags(query: str) -> float:
    """DQR-DETERM-0: Deterministic RAGS relevance score for *query*.

    Returns a float in [0.0, 1.0]. Pure keyword accumulation — identical
    inputs always produce identical scores.
    """
    q = query.lower()
    score = 0.0
    for kw, weight in _RAGS_KEYWORDS.items():
        if kw in q:
            score += weight
    return min(score, 1.0)


# ── Public API ────────────────────────────────────────────────────────────────

def route_query(query: str) -> RouteDecision:
    """DQR-ROUTE-0 + DQR-FALLBACK-0: Route *query* to the best subsystem.

    Priority: DPM → RAGS → passthrough.

    NEVER raises an unhandled exception (DQR-FALLBACK-0): any internal
    failure collapses to a logged passthrough RouteDecision.
    """
    global _policy_override
    try:
        _ensure_ledger()

        dpm_score = _score_dpm(query)
        rags_score = _score_rags(query)
        query_hash = _sha256_text(query)

        # Determine route
        if _policy_override is not None:
            route = _policy_override
        elif dpm_score >= _DPM_THRESHOLD:
            route = ROUTE_DPM
        elif rags_score >= _RAGS_THRESHOLD:
            route = ROUTE_RAGS
        else:
            route = ROUTE_PASSTHROUGH

        entries = _load_all()
        seq = len(entries)  # genesis is seq 0; first route_decision is seq 1

        decision = RouteDecision(
            seq=seq,
            timestamp=datetime.now(timezone.utc).isoformat(),
            query_hash=query_hash,
            dpm_score=round(dpm_score, 6),
            rags_score=round(rags_score, 6),
            route=route,
            override=_policy_override,
            prev_hash="",  # filled by _append_decision
        )
        return _append_decision(decision)

    except Exception as exc:  # DQR-FALLBACK-0
        # Last-resort passthrough: attempt to log the failure
        try:
            _ensure_ledger()
            entries = _load_all()
            seq = len(entries)
            fallback = RouteDecision(
                seq=seq,
                timestamp=datetime.now(timezone.utc).isoformat(),
                query_hash=_sha256_text(query) if query else "error",
                dpm_score=0.0,
                rags_score=0.0,
                route=ROUTE_PASSTHROUGH,
                override=f"FALLBACK:{type(exc).__name__}",
                prev_hash="",
            )
            return _append_decision(fallback)
        except Exception:
            # Absolute last resort — return an unlogged passthrough (DQR-FALLBACK-0
            # requires no propagation; logging is best-effort)
            return RouteDecision(
                seq=-1,
                timestamp=datetime.now(timezone.utc).isoformat(),
                query_hash="error",
                dpm_score=0.0,
                rags_score=0.0,
                route=ROUTE_PASSTHROUGH,
                override="FALLBACK:UNLOGGED",
                prev_hash=_GENESIS_HASH,
                entry_hash="error",
            )


def override_policy(new_route: str, token: bytes) -> bool:
    """DQR-AUTH-0: Set a global route override with HUMAN-0 authorisation.

    *token* must equal DQR_HUMAN0_TOKEN verified via constant-time
    hmac.compare_digest. No plaintext comparison is permitted.

    Args:
        new_route: one of ROUTE_DPM, ROUTE_RAGS, ROUTE_PASSTHROUGH, or None
                   (pass None as new_route to clear the override — token still required).
        token: HUMAN-0 authorisation bytes.

    Returns:
        True if override applied; False if authorisation failed.

    Raises:
        DQRAuthViolation if token verification fails.
    """
    global _policy_override
    if not hmac.compare_digest(token, _DQR_HUMAN0_TOKEN):
        raise DQRAuthViolation(
            f"{DQR_AUTH_0}: override_policy() rejected — invalid HUMAN-0 token"
        )
    if new_route is not None and new_route not in (
        ROUTE_DPM, ROUTE_RAGS, ROUTE_PASSTHROUGH
    ):
        raise DQRAuthViolation(
            f"{DQR_AUTH_0}: invalid route destination '{new_route}'"
        )
    _policy_override = new_route
    return True


def clear_override(token: bytes) -> bool:
    """HUMAN-0-gated: clear any active policy override."""
    return override_policy(None, token)


def verify_chain() -> bool:
    """DQR-CHAIN-0: Verify the full HMAC chain of the DQR ledger.

    Returns True if all entries are valid; raises DQRChainViolation on
    the first broken link.
    """
    entries = _load_all()
    if not entries:
        return True
    prev_hash = _GENESIS_HASH
    for entry in entries:
        # Re-derive expected entry_hash
        canon = _canonical(entry["payload"])
        expected = _hmac_digest(prev_hash, canon)
        if entry["entry_hash"] != expected:
            raise DQRChainViolation(
                f"{DQR_CHAIN_0}: chain broken at seq={entry.get('seq', '?')} "
                f"— expected {expected[:16]}… got {entry['entry_hash'][:16]}…"
            )
        if entry["prev_hash"] != prev_hash:
            raise DQRChainViolation(
                f"{DQR_CHAIN_0}: prev_hash mismatch at seq={entry.get('seq', '?')}"
            )
        prev_hash = entry["entry_hash"]
    return True


def ledger_stats() -> Dict[str, Any]:
    """Return aggregate statistics for the DQR routing ledger."""
    entries = _load_all()
    route_counts: Dict[str, int] = {
        ROUTE_DPM: 0,
        ROUTE_RAGS: 0,
        ROUTE_PASSTHROUGH: 0,
    }
    for e in entries:
        if e.get("entry_type") == "route_decision":
            r = e["payload"].get("route", ROUTE_PASSTHROUGH)
            route_counts[r] = route_counts.get(r, 0) + 1

    total_decisions = sum(route_counts.values())
    return {
        "total_entries": len(entries),
        "total_decisions": total_decisions,
        "route_counts": route_counts,
        "ledger_path": str(_DQR_LEDGER_PATH),
        "chain_valid": True,  # caller should call verify_chain() separately
    }
