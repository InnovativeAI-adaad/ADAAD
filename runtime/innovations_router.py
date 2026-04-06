# SPDX-License-Identifier: Apache-2.0
"""Phase 68 — Innovations API Router.

Exposes bearer-auth-gated endpoints backed by ADAADInnovationEngine:

  GET  /innovations/oracle          — ADAAD Oracle: query evolutionary history
  GET  /innovations/oracle/history  — Replay past oracle answers from ledger
  GET  /innovations/story-mode      — Aponi Story Mode: CEL evidence as narrative arcs
  GET  /innovations/federation-map  — Federated Evolution Map galaxy data
  POST /innovations/seeds/register  — Capability Seed lineage registration

Constitutional invariants
=========================
ORACLE-AUTH-0       All endpoints require `audit:read` bearer token scope.
ORACLE-DETERM-0     Oracle answers are deterministic for equal query + events.
ORACLE-PERSIST-0    Every oracle query writes one record to OracleLedger before
                    the response is returned (Phase 71).
ORACLE-REPLAY-0     GET /oracle/history replays ledger JSONL (read-only).
STORY-LEDGER-0      Story Mode reads CEL evidence ledger; no writes performed.
FED-MAP-READONLY-0  Federation Map is read-only; no side effects.
SEED-REG-0          Seeds registered via POST /innovations/seeds/register are
                    always Tier-2 (delegated to seed_registry_adapter).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header

from runtime.capability.capability_registry import CapabilityRegistry
from runtime.capability.seed_registry_adapter import register_seeds_bulk
from runtime.innovations import ADAADInnovationEngine, CapabilitySeed
from runtime.oracle_ledger import OracleLedger
from runtime.oracle_memory import summarize_oracle_memory
from runtime.seed_promotion import SeedPromotionQueue, get_promotion_queue
from runtime.seed_review import ReviewAuthorityError, SeedNotFoundError, record_review
from runtime.seed_proposal_bridge import SeedNotApprovedError, build_proposal_request
from runtime.seed_cel_injector import inject_seed_proposal_into_context
from runtime.personality_profiles import PersonalityProfileStore
from runtime.audit_auth import require_audit_read_scope, require_audit_write_scope
from ui.features.story_mode import build_federated_evolution_map, build_story_arcs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/innovations", tags=["innovations"])

# Shared engine instance (stateless — no side effects on calls)
_engine = ADAADInnovationEngine()

# Shared in-process capability registry for seed registration
_seed_registry = CapabilityRegistry()
_profile_store = PersonalityProfileStore()

# Phase 71 — Oracle persistence ledger (ORACLE-PERSIST-0, ORACLE-REPLAY-0)
_oracle_ledger = OracleLedger()

# Phase 72 — Seed promotion queue singleton (SEED-PROMO-0, SEED-PROMO-HUMAN-0)
_promotion_queue: SeedPromotionQueue = get_promotion_queue()


# ---------------------------------------------------------------------------
# Auth helper (mirrors pattern from server.py)
# ---------------------------------------------------------------------------

def _require_audit_read(authorization: Optional[str]) -> None:
    """Raise 401/403 if bearer token missing or scope not audit:read.

    ORACLE-AUTH-0: all innovations endpoints require audit:read scope.
    """
    require_audit_read_scope(authorization)


# ---------------------------------------------------------------------------
# Oracle event loader (reads CEL evidence ledger JSONL)
# ---------------------------------------------------------------------------

def _load_oracle_events(limit: int = 500) -> List[Dict[str, Any]]:
    """Load events from the CEL evidence ledger for Oracle queries.

    STORY-LEDGER-0: read-only; no writes performed.
    """
    import json

    ledger_path = Path(os.getenv("ADAAD_CEL_LEDGER", "data/cel_evidence.jsonl"))
    if not ledger_path.exists():
        return []
    events: List[Dict[str, Any]] = []
    try:
        lines = ledger_path.read_text(encoding="utf-8").splitlines()
        for line in lines[-limit:]:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except Exception:  # noqa: BLE001
                    continue
    except Exception as exc:  # noqa: BLE001
        logger.warning("innovations_router: ledger read failed — %s", exc)
    return events


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/oracle")
def oracle_query(
    q: str = "divergence",
    limit: int = 100,
    horizon: int = 120,
    seed_input: str = "oracle-vision",
    epoch_id: str = "",
    gate_ok: Optional[bool] = None,
    replay_score: Optional[float] = None,
    active_phase: str = "",
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """ADAAD Oracle: deterministic Q&A over evolutionary history.

    ORACLE-AUTH-0: requires audit:read bearer token.
    ORACLE-DETERM-0: equal q + ledger state → equal answer.
    ORACLE-PERSIST-0: every query appends one record to OracleLedger.

    Query examples:
      ?q=divergence          — last 10 divergence events
      ?q=rejected            — last 20 rejected mutations
      ?q=performance         — agent contribution ranking
    """
    _require_audit_read(authorization)
    events = _load_oracle_events(limit=limit)
    answer = _engine.answer_oracle(q, events)
    projection = _engine.run_vision_mode(events, horizon_epochs=horizon, seed_input=seed_input)
    trajectory_score: Optional[float] = None
    try:
        trajectory_score = float(projection.trajectory_score)
    except Exception:  # noqa: BLE001
        pass

    # ORACLE-PERSIST-0: append answer to replay ledger before returning.
    _oracle_ledger.append(
        query=q,
        answer=answer,
        events=events,
        vision_trajectory_score=trajectory_score,
        query_type=str(answer.get("query_type", "generic")),
        answer_summary=str(answer.get("message", ""))[:240],
        epoch_context={
            "epoch_id": epoch_id,
            "active_phase": active_phase,
            "gate_ok": gate_ok,
            "replay_score": replay_score,
        },
    )

    return {
        "query": q,
        "event_window": len(events),
        "answer": answer,
        "vision_projection": _engine.as_serializable(projection),
    }


@router.get("/oracle/history")
def oracle_history(
    limit: int = 100,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Replay past oracle answers from the persistence ledger.

    ORACLE-REPLAY-0: read-only; returns JSONL records in append order.
    ORACLE-AUTH-0: requires audit:read bearer token.

    Returns the last *limit* oracle records sorted oldest-first so callers
    can verify determinism of repeated queries.
    """
    _require_audit_read(authorization)
    records = _oracle_ledger.replay(limit=limit)
    return {
        "record_count": len(records),
        "ledger_path": str(_oracle_ledger.path),
        "records": records,
    }


@router.get("/oracle/memory")
def oracle_memory(
    limit: int = 10,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Summarize recurring oracle themes and trend indicators."""
    _require_audit_read(authorization)
    records = _oracle_ledger.replay(limit=max(limit, 10))
    memory = summarize_oracle_memory(records, window=limit)
    return {
        "ledger_path": str(_oracle_ledger.path),
        "memory": memory,
    }


@router.get("/story-mode")
def story_mode(
    limit: int = 200,
    horizon: int = 120,
    seed_input: str = "story-vision",
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Aponi Story Mode: CEL evidence ledger as narrative arc timeline.

    STORY-LEDGER-0: reads ledger, never writes.
    ORACLE-AUTH-0: requires audit:read bearer token.
    """
    _require_audit_read(authorization)
    events = _load_oracle_events(limit=limit)
    arcs = build_story_arcs(events)
    engine_arcs = _engine.story_mode(events)
    projection = _engine.run_vision_mode(events, horizon_epochs=horizon, seed_input=seed_input)
    return {
        "arc_count": len(arcs),
        "arcs": arcs,
        "engine_timeline": engine_arcs,
        "event_window": len(events),
        "vision_projection": _engine.as_serializable(projection),
    }


@router.get("/federation-map")
def federation_map(
    limit: int = 500,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Federated Evolution Map: cross-repo event galaxy data.

    FED-MAP-READONLY-0: read-only. No side effects.
    ORACLE-AUTH-0: requires audit:read bearer token.

    Returns stars (repos), paths (mutation flows), divergence flares.
    """
    _require_audit_read(authorization)
    events = _load_oracle_events(limit=limit)
    galaxy = build_federated_evolution_map(events)
    return {
        "star_count": len(galaxy["stars"]),
        "path_count": len(galaxy["paths"]),
        "galaxy": galaxy,
        "event_window": len(events),
    }


@router.post("/seeds/register")
def register_seeds(
    seeds: List[Dict[str, Any]] | None = Body(default=None),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Register Capability Seeds in the lineage ledger.

    SEED-REG-0: all seeds registered as Tier-2 nodes.
    SEED-IDEM-0: re-registering an existing seed_id is idempotent.
    ORACLE-AUTH-0: requires audit:read bearer token.

    Request body: list of seed objects:
      [{"seed_id": "...", "intent": "...", "scaffold": "...",
        "author": "...", "lane": "governance"}]
    """
    _require_audit_read(authorization)
    seeds = seeds or []
    seed_objects: List[CapabilitySeed] = []
    parse_errors: List[Dict[str, Any]] = []

    for raw in seeds:
        try:
            seed_objects.append(CapabilitySeed(
                seed_id=str(raw["seed_id"]),
                intent=str(raw.get("intent", "")),
                scaffold=str(raw.get("scaffold", "")),
                author=str(raw.get("author", "operator")),
                lane=str(raw.get("lane", "experimental")),
            ))
        except Exception as exc:  # noqa: BLE001
            parse_errors.append({"raw": raw, "error": str(exc)})

    results = register_seeds_bulk(_seed_registry, seed_objects)
    registered = [r for r in results if r["registered"]]

    # Phase 70 — emit seed_planted frame for each new seed
    for seed in seed_objects:
        if any(r["seed_id"] == seed.seed_id and r["registered"] for r in results):
            try:
                from runtime.innovations_bus import emit_seed_planted  # noqa: PLC0415
                emit_seed_planted(seed.seed_id, seed.lane, seed.intent, seed.author)
            except Exception:  # noqa: BLE001
                pass

    return {
        "submitted": len(seeds),
        "registered": len(registered),
        "results": results,
        "parse_errors": parse_errors,
        "registry_size": len(_seed_registry.list_ids()),
    }


@router.get("/personality-profiles")
def personality_profiles(
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Return persisted personality profiles + deterministic epoch impact history."""
    _require_audit_read(authorization)
    snapshot = _profile_store.snapshot()
    history = list(snapshot.get("history", []))
    per_agent: Dict[str, Dict[str, int]] = {}
    for row in history:
        aid = str(row.get("agent_id", ""))
        if not aid:
            continue
        bucket = per_agent.setdefault(aid, {"wins": 0, "losses": 0})
        if row.get("outcome") == "win":
            bucket["wins"] += 1
        elif row.get("outcome") == "loss":
            bucket["losses"] += 1
    return {
        "schema_version": snapshot.get("schema_version", "v1"),
        "profiles": snapshot.get("profiles", []),
        "history": history[-120:],
        "agent_totals": per_agent,
    }


@router.get("/seeds")
def list_seeds(
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """List all registered Capability Seeds (Tier-2 nodes with SEED-REG-0 tag).

    ORACLE-AUTH-0: requires audit:read bearer token.
    """
    _require_audit_read(authorization)
    seed_nodes = [
        {
            "capability_id": n.capability_id,
            "version": n.version,
            "description": n.contract.description,
            "tier": n.contract.tier,
            "tags": sorted(n.governance_tags),
            "telemetry": n.telemetry,
            "node_hash": n.node_hash,
        }
        for n in _seed_registry.list_nodes()
        if "SEED-REG-0" in n.governance_tags
    ]
    return {
        "seed_count": len(seed_nodes),
        "seeds": seed_nodes,
    }


@router.get("/seeds/promoted")
def list_promoted_seeds(
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """List Capability Seeds in the promotion queue (Phase 72).

    SEED-PROMO-HUMAN-0: all entries have status=pending_human_review.
                        This endpoint is advisory only; no action is taken.
    SEED-PROMO-ORDER-0: entries returned oldest-first (FIFO enqueue order).
    ORACLE-AUTH-0:      requires audit:read bearer token.
    """
    _require_audit_read(authorization)
    entries = _promotion_queue.list()
    return {
        "queue_depth": len(entries),
        "threshold": _promotion_queue.threshold,
        "entries": entries,
        "advisory_notice": (
            "SEED-PROMO-HUMAN-0: this queue is advisory only. "
            "No mutation is created or applied without explicit human approval."
        ),
    }


def _require_audit_write(authorization: Optional[str]) -> None:
    """Require audit:write scope (Phase 73 — SEED-REVIEW-AUTH-0)."""
    require_audit_write_scope(authorization)


@router.post("/seeds/promoted/{seed_id}/review")
def review_promoted_seed(
    seed_id: str,
    body: Dict[str, Any] = Body(default_factory=dict),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Record a human review decision for a promoted seed (Phase 73).

    SEED-REVIEW-AUTH-0:  requires audit:write bearer token scope.
    SEED-REVIEW-HUMAN-0: operator_id must be non-empty — no self-approval.
    SEED-REVIEW-0:       decision written to lineage ledger before status change.
    SEED-REVIEW-IDEM-0:  reviewing an already-terminal seed is a no-op.
    SEED-REVIEW-BUS-0:   bus frame emitted after ledger write.

    Request body::

        {
          "status":      "approved" | "rejected",
          "operator_id": "dustin",
          "notes":       "optional free-text rationale"
        }
    """
    _require_audit_write(authorization)

    status = str(body.get("status", "")).strip()
    operator_id = str(body.get("operator_id", "")).strip()
    notes = str(body.get("notes", ""))

    if status not in ("approved", "rejected"):
        from fastapi import HTTPException  # noqa: PLC0415
        raise HTTPException(
            status_code=422,
            detail="status must be 'approved' or 'rejected'",
        )

    try:
        decision = record_review(
            seed_id,
            status=status,
            operator_id=operator_id,
            notes=notes,
            queue=_promotion_queue,
        )
    except SeedNotFoundError:
        from fastapi import HTTPException  # noqa: PLC0415
        raise HTTPException(status_code=404, detail=f"seed_id {seed_id!r} not in promotion queue")
    except ReviewAuthorityError as exc:
        from fastapi import HTTPException  # noqa: PLC0415
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        from fastapi import HTTPException  # noqa: PLC0415
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "seed_id": seed_id,
        "decision": decision,
        "queue_depth": len(_promotion_queue),
    }


@router.post("/seeds/promoted/{seed_id}/propose")
def generate_seed_proposal(
    seed_id: str,
    body: Dict[str, Any] = Body(default_factory=dict),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Generate a ProposalRequest from an approved seed (Phase 74).

    SEED-REVIEW-AUTH-0: requires audit:write bearer token scope.
    SEED-PROP-0:        seed must have status='approved' in promotion queue.
    SEED-PROP-HUMAN-0:  returned ProposalRequest is advisory only — no mutation
                        is applied without GovernanceGate + HUMAN-0.
    SEED-PROP-LEDGER-0: SeedProposalEvent written to lineage ledger before return.
    SEED-PROP-BUS-0:    seed_proposal_generated bus frame emitted after ledger write.

    Request body (optional)::

        { "epoch_id": "ep-156" }

    Returns the ProposalRequest fields (cycle_id, strategy_id, context) and an
    advisory notice confirming no mutation is applied automatically.
    """
    _require_audit_write(authorization)

    epoch_id = str(body.get("epoch_id", "")).strip()

    try:
        request = build_proposal_request(
            seed_id, epoch_id=epoch_id, queue=_promotion_queue
        )
    except KeyError:
        from fastapi import HTTPException  # noqa: PLC0415
        raise HTTPException(status_code=404, detail=f"seed_id {seed_id!r} not in promotion queue")
    except SeedNotApprovedError as exc:
        from fastapi import HTTPException  # noqa: PLC0415
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        from fastapi import HTTPException  # noqa: PLC0415
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "seed_id":      seed_id,
        "cycle_id":     request.cycle_id,
        "strategy_id":  request.strategy_id,
        "context":      dict(request.context),
        "advisory_notice": (
            "SEED-PROP-HUMAN-0: this ProposalRequest is advisory only. "
            "No mutation is applied without GovernanceGate approval and human sign-off."
        ),
    }


@router.post("/seeds/promoted/{seed_id}/inject")
def inject_seed_into_epoch(
    seed_id: str,
    body: Dict[str, Any] = Body(default_factory=dict),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Prepare an epoch context dict with an approved seed's ProposalRequest (Phase 75).

    SEED-REVIEW-AUTH-0: requires audit:write bearer token scope.
    SEED-CEL-0:         canonical injection via inject_seed_proposal_into_context().
    SEED-CEL-AUDIT-0:   SeedCELInjectionEvent written to lineage ledger.
    SEED-CEL-HUMAN-0:   returned context is advisory — pass to run_epoch(context=).

    Request body (optional)::

        {
          "epoch_id":     "ep-156",
          "base_context": { ...optional existing epoch context... }
        }

    Returns the context dict ready for ``LiveWiredCEL.run_epoch(context=ctx)``.
    """
    _require_audit_write(authorization)

    epoch_id    = str(body.get("epoch_id", "")).strip()
    base_ctx    = dict(body.get("base_context") or {})

    try:
        request = build_proposal_request(
            seed_id, epoch_id=epoch_id, queue=_promotion_queue
        )
    except KeyError:
        from fastapi import HTTPException  # noqa: PLC0415
        raise HTTPException(status_code=404, detail=f"seed_id {seed_id!r} not in promotion queue")
    except SeedNotApprovedError as exc:
        from fastapi import HTTPException  # noqa: PLC0415
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        ctx = inject_seed_proposal_into_context(request, base_context=base_ctx)
    except RuntimeError as exc:
        from fastapi import HTTPException  # noqa: PLC0415
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "seed_id":   seed_id,
        "cycle_id":  request.cycle_id,
        "strategy_id": request.strategy_id,
        "epoch_context": ctx,
        "advisory_notice": (
            "SEED-CEL-HUMAN-0: pass epoch_context to LiveWiredCEL.run_epoch(context=). "
            "No mutation is applied without GovernanceGate + HUMAN-0."
        ),
    }


@router.post("/seeds/{seed_id}/cel-outcome")
def record_seed_cel_outcome(
    seed_id: str,
    body: Dict[str, Any] = Body(default_factory=dict),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Record the outcome of a CEL epoch that ran with an injected seed proposal (Phase 76).

    SEED-REVIEW-AUTH-0:   requires audit:write bearer token scope.
    SEED-OUTCOME-0:       canonical outcome recording via record_cel_outcome().
    SEED-OUTCOME-LINK-0:  seed_id, cycle_id, epoch_id are all required.
    SEED-OUTCOME-AUDIT-0: SeedCELOutcomeEvent written to lineage ledger before return.
    SEED-OUTCOME-IDEM-0:  duplicate (seed_id, cycle_id) returns existing record.

    Request body::

        {
          "cycle_id":       "sha256hex...",
          "epoch_id":       "ep-157",
          "outcome_status": "success" | "partial" | "failed" | "skipped",
          "fitness_delta":  0.042,        (optional, default 0.0)
          "mutation_count": 3,            (optional, default 0)
          "notes":          "..."         (optional)
        }
    """
    _require_audit_write(authorization)

    from runtime.seed_cel_outcome import (  # noqa: PLC0415
        record_cel_outcome,
        SeedOutcomeLinkError,
        SeedOutcomeStatusError,
    )

    cycle_id       = str(body.get("cycle_id",       "")).strip()
    epoch_id       = str(body.get("epoch_id",       "")).strip()
    outcome_status = str(body.get("outcome_status", "")).strip()
    fitness_delta  = float(body.get("fitness_delta",  0.0))
    mutation_count = int(body.get("mutation_count",   0))
    notes          = str(body.get("notes",            ""))

    try:
        outcome = record_cel_outcome(
            seed_id,
            cycle_id,
            epoch_id,
            outcome_status,
            fitness_delta=fitness_delta,
            mutation_count=mutation_count,
            notes=notes,
        )
    except (SeedOutcomeLinkError, SeedOutcomeStatusError) as exc:
        from fastapi import HTTPException  # noqa: PLC0415
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        from fastapi import HTTPException  # noqa: PLC0415
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "seed_id":         seed_id,
        "outcome":         outcome,
        "advisory_notice": (
            "SEED-OUTCOME-0: outcome recorded to lineage ledger. "
            "Fitness delta and mutation data are informational; "
            "no retroactive mutation is applied."
        ),
    }


__all__ = ["router"]
