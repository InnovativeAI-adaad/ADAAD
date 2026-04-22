# SPDX-License-Identifier: Apache-2.0
"""FastAPI MCP proposal writer server."""

from __future__ import annotations

import argparse
import json
import logging
import os
from contextlib import asynccontextmanager
from json import JSONDecodeError
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from runtime.mcp.candidate_ranker import rank_candidates
from runtime.governance.foundation.determinism import RuntimeDeterminismProvider, default_provider, require_replay_safe_provider
from runtime.mcp.mutation_analyzer import analyze_mutation
from runtime.mcp.proposal_queue import append_proposal
from runtime.mcp.proposal_validator import ProposalValidationError, validate_proposal
from runtime.mcp.rejection_explainer import explain_rejection
from runtime.mcp.tools_registry import tools_list_response
from runtime.mcp import evolution_pipeline_tools
from security import cryovant
from security.unified_auth import require_action
from runtime.innovations30.live_execution_feed import get_feed_engine, probe as lef_probe
from runtime.innovations30.mutation_explainability import get_explainer as mxe_explainer, probe as mxe_probe
from runtime.innovations30.governance_circuit_breaker import CircuitBreakerEngine as _GCBEngine, GCBAuthViolation, GCBOpenViolation

LOG = logging.getLogger(__name__)


def _authorize_request(request: Request) -> None:
    if request.url.path == "/health":
        return
    if request.url.path.startswith("/events/cel-feed"):
        return
    action = "read" if request.method.upper() in {"GET", "HEAD", "OPTIONS"} else "write"
    try:
        require_action(request.headers.get("Authorization"), action=action)
    except HTTPException as exc:
        detail = str(exc.detail)
        if detail == "invalid_token":
            detail = "invalid_jwt"
        if detail == "expired_token":
            detail = "expired_jwt"
        LOG.warning(
            "mcp_authz_failed",
            extra={"reason_code": detail, "status_code": exc.status_code, "method": request.method},
        )
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc


@asynccontextmanager
async def lifespan(_app: FastAPI):
    key_path = cryovant.KEYS_DIR / "signing-key.pem"
    if not key_path.exists():
        raise RuntimeError("audit_log_signing_key_absent")
    yield


def create_app(
    server_name: str = "mcp-proposal-writer",
    *,
    provider: RuntimeDeterminismProvider | None = None,
    replay_mode: str = "off",
    recovery_tier: str | None = None,
) -> FastAPI:
    runtime_provider = provider or default_provider()
    require_replay_safe_provider(runtime_provider, replay_mode=replay_mode, recovery_tier=recovery_tier)
    app = FastAPI(title=server_name, lifespan=lifespan)
    app.state.determinism_provider = runtime_provider

    @app.middleware("http")
    async def jwt_middleware(request: Request, call_next):
        try:
            _authorize_request(request)
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        return await call_next(request)

    @app.get("/health")
    async def health() -> Dict[str, Any]:
        return {"ok": True, "server": server_name}

    @app.get("/tools/list")
    async def tools_list() -> Dict[str, Any]:
        return tools_list_response(server_name)

    @app.post("/mutation/propose")
    async def mutation_propose(payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            request, verdict = validate_proposal(payload)
        except ProposalValidationError as exc:
            body: Dict[str, Any] = {"ok": False, "error": exc.code, "detail": exc.detail}
            if exc.code == "pre_check_failed":
                try:
                    body["verdicts"] = json.loads(exc.detail)
                except JSONDecodeError as parse_exc:
                    LOG.warning(
                        "proposal pre-check verdict parse failed",
                        extra={
                            "reason_code": "pre_check_verdict_parse_failed",
                            "error_type": type(parse_exc).__name__,
                            "validation_error_code": exc.code,
                        },
                    )
            raise HTTPException(status_code=exc.status_code, detail=body)
        proposal_id = runtime_provider.next_id(label="mcp-proposal", length=32)
        queue_entry = append_proposal(proposal_id=proposal_id, request=request)
        return {
            "ok": True,
            "proposal_id": proposal_id,
            "authority_level": request.authority_level,
            "verdict": verdict,
            "queue_hash": queue_entry["hash"],
        }

    @app.post("/mutation/analyze")
    async def mutation_analyze(payload: Dict[str, Any]) -> Dict[str, Any]:
        return analyze_mutation(payload)

    @app.post("/mutation/explain-rejection")
    async def mutation_explain_rejection(payload: Dict[str, Any]) -> Dict[str, Any]:
        mutation_id = str(payload.get("mutation_id") or "")
        try:
            return explain_rejection(mutation_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="mutation_not_found") from exc

    @app.post("/mutation/rank")
    async def mutation_rank(payload: Dict[str, Any]) -> Dict[str, Any]:
        mutation_ids = payload.get("mutation_ids")
        if not isinstance(mutation_ids, list):
            raise HTTPException(status_code=400, detail="mutation_ids_required")
        try:
            return rank_candidates([str(mid) for mid in mutation_ids])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # --- Evolution pipeline tools (read-only observability) -----------------

    @app.get("/evolution/fitness-landscape")
    async def evo_fitness_landscape() -> Dict[str, Any]:
        return evolution_pipeline_tools.fitness_landscape_summary()

    @app.get("/evolution/weight-state")
    async def evo_weight_state() -> Dict[str, Any]:
        return evolution_pipeline_tools.weight_state()

    @app.get("/evolution/recommend")
    async def evo_recommend() -> Dict[str, Any]:
        return evolution_pipeline_tools.epoch_recommend()

    @app.get("/evolution/bandit-state")
    async def evo_bandit_state() -> Dict[str, Any]:
        return evolution_pipeline_tools.bandit_state()

    @app.get("/evolution/telemetry-health")
    async def evo_telemetry_health() -> Dict[str, Any]:
        return evolution_pipeline_tools.telemetry_health()

    # ------------------------------------------------------------------
    # Phase 148 / INNOV-54 — Live Execution Feed (LEF) SSE routes
    # LEF-NOWRITE-0: event_stream() drains only; no ledger writes here.
    # CEL-FEED-0:    subscribers are passive observers.
    # ------------------------------------------------------------------

    @app.get("/events/cel-feed")
    async def cel_feed_stream(phase: int = 148) -> StreamingResponse:
        """SSE endpoint: stream CEL step events for *phase* in real time."""
        engine = get_feed_engine(phase)
        q = await engine.subscribe()

        async def _generate():
            async for chunk in engine.event_stream(q):
                yield chunk

        return StreamingResponse(
            _generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.get("/events/cel-feed/health")
    async def cel_feed_health(phase: int = 148) -> Dict[str, Any]:
        """INNOV-COMPLETE-0 health probe for the LEF engine."""
        return lef_probe()

    @app.get("/events/cel-feed/chain")
    async def cel_feed_chain(phase: int = 148) -> Dict[str, Any]:
        """LEF-CHAIN-0 full ledger chain verification for *phase*."""
        engine = get_feed_engine(phase)
        return engine.verify_ledger_chain()

    # ------------------------------------------------------------------
    # Phase 149 / INNOV-55 — Mutation Explainability Engine (MXE) routes
    # MXE-SCOPE-0: only mutation proposal verdicts; no CEL state access.
    # MXE-AUDIT-0: every verdict persists an explanation before returning.
    # ------------------------------------------------------------------

    @app.post("/mutation/explain")
    async def mutation_explain(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Generate and persist a constitutional explanation for a mutation verdict."""
        mutation_id = payload.get("mutation_id", "")
        verdict = payload.get("verdict", "")
        gate_report = payload.get("gate_report", {})
        confidence = float(payload.get("confidence", 1.0))
        if not mutation_id:
            raise HTTPException(status_code=422, detail="mutation_id required")
        if verdict not in {"ACCEPT", "REJECT", "BLOCK"}:
            raise HTTPException(status_code=422, detail="verdict must be ACCEPT|REJECT|BLOCK")
        expl = mxe_explainer().explain(
            mutation_id, verdict, gate_report=gate_report, confidence=confidence
        )
        return {"ok": True, "explanation": expl.to_dict()}

    @app.get("/mutation/explanations/{mutation_id}")
    async def mutation_explanation_get(mutation_id: str) -> Dict[str, Any]:
        """Retrieve stored explanation by mutation_id — MXE-IMMUT-0."""
        expl = mxe_explainer().get(mutation_id)
        if expl is None:
            raise HTTPException(status_code=404, detail="explanation_not_found")
        return {"ok": True, "explanation": expl.to_dict()}

    @app.get("/mutation/explanations")
    async def mutation_explanations_list(limit: int = 50) -> Dict[str, Any]:
        """List recent explanations — MXE-DETERM-0 sorted by timestamp desc."""
        records = mxe_explainer().list_explanations(limit=limit)
        return {"ok": True, "count": len(records), "explanations": records}

    @app.get("/mutation/explanations/chain")
    async def mutation_explanations_chain() -> Dict[str, Any]:
        """MXE-CHAIN-0 full ledger chain verification."""
        return mxe_explainer().verify_chain()

    @app.get("/mutation/explanations/health")
    async def mutation_explanations_health() -> Dict[str, Any]:
        """INNOV-COMPLETE-0 health probe for MXE engine."""
        return mxe_probe()

    # ------------------------------------------------------------------
    # GCB routes — Phase 150 / INNOV-56 · Governance Circuit Breaker
    # ------------------------------------------------------------------

    _gcb_engine: _GCBEngine = _GCBEngine()

    @app.post("/circuit/violation")
    async def circuit_record_violation(request: Request) -> Dict[str, Any]:
        """GCB-FAILCLOSE-0 + GCB-READONLY-0: record an invariant violation signal.

        Body JSON: {"namespace": str, "violation_id": str}
        Returns whether the circuit was tripped by this event.
        """
        body = await request.json()
        namespace = str(body.get("namespace", "UNKNOWN"))
        violation_id = str(body.get("violation_id", ""))
        tripped = _gcb_engine.record_violation(namespace, violation_id)
        return {
            "recorded": True,
            "namespace": namespace,
            "violation_id": violation_id,
            "circuit_tripped": tripped,
            "circuit_state": _gcb_engine.state,
        }

    @app.get("/circuit/status")
    async def circuit_status() -> Dict[str, Any]:
        """Read-only circuit status snapshot (GCB-READONLY-0)."""
        return _gcb_engine.get_status()

    @app.get("/circuit/health")
    async def circuit_health() -> Dict[str, Any]:
        """INNOV-COMPLETE-0 health probe for GCB engine."""
        return _gcb_engine.health_check()

    @app.get("/circuit/chain")
    async def circuit_chain_verify() -> Dict[str, Any]:
        """GCB-CHAIN-0 full ledger verification."""
        return _gcb_engine.verify_ledger_chain()

    @app.post("/circuit/reset")
    async def circuit_reset(request: Request) -> Dict[str, Any]:
        """GCB-HUMAN0-0: reset OPEN circuit. Requires HUMAN-0 token.

        Body JSON: {"human0_token": str}
        """
        body = await request.json()
        token = str(body.get("human0_token", ""))
        try:
            _gcb_engine.reset_circuit(token)
            return {"reset": True, "circuit_state": _gcb_engine.state}
        except GCBAuthViolation as exc:
            return {"reset": False, "error": str(exc), "circuit_state": _gcb_engine.state}


    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MCP server")
    parser.add_argument("--server", default="mcp-proposal-writer")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8091)
    args = parser.parse_args()

    import uvicorn

    replay_mode = os.getenv("ADAAD_REPLAY_MODE", "off")
    recovery_tier = os.getenv("ADAAD_RECOVERY_TIER")
    uvicorn.run(
        create_app(
            args.server,
            provider=default_provider(),
            replay_mode=replay_mode,
            recovery_tier=recovery_tier,
        ),
        host=args.host,
        port=args.port,
    )


if __name__ == "__main__":
    main()
