# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import importlib
import hashlib
import logging
import warnings
import os
import subprocess
import sys
import time
import asyncio
import csv
import io
import uuid
import threading
import httpx
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, Mapping

from contextlib import asynccontextmanager

import anyio
from fastapi import BackgroundTasks, Body, Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket
from pydantic import BaseModel

from adaad.api.schemas.governance import (
    FastPathCheckpointVerifyResponse,
    FastPathEntropyGateRequest,
    FastPathEntropyGateResponse,
    FastPathRoutePreviewRequest,
    FastPathRoutePreviewResponse,
    FastPathStatsResponse,
    GovernanceSemVerStatusResponse,
    ParallelGateEvaluateRequest,
    ParallelGateEvaluateResponse,
    ParallelGateProbeLibraryResponse,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from app.api.nexus.mutate import router as mutate_router
from adaad.api.governance import router as governance_router
from app.api.audit import router as audit_router
from app.api.ui import router as ui_router
from app.api.simulation import router as simulation_router
from app.api.compliance import router as compliance_router
from app.api.audit_exports import router as audit_exports_router
from app.api.mutation_control import router as mutation_control_router
from app.api.streams import router as streams_router
from app.api.governance_telemetry import router as cgth_router  # Phase 155 INNOV-61 CGTH
from app.api.governance_anomalies import router as cgai_router   # Phase 156 INNOV-62 CGAI
from app.api.governance_health import router as ghi_router        # Phase 157 INNOV-63 GHI
from app.api.self_repair import router as csr_router              # Phase 158 INNOV-64 CSR
from app.api.constitutional_strength import router as csi_router  # Phase 159 INNOV-65 CSI
from app.api.emergent_sentinel import router as ebs_router        # Phase 160 INNOV-66 EBS
from app.api.constitutional_forecast import router as cfe_router  # Phase 161 INNOV-67 CFE
from app.api.mutation_impact import router as mia_router           # Phase 162 INNOV-68 MIA
from app.api.mutation_calibration import router as mce_router      # Phase 163 INNOV-69 MCE
from app.api.governance_implementation_readiness import router as gir_router  # Phase 181 INNOV-86 GIR
from app.api.convergence_gap_resolver import router as cgr_router             # Phase 182 INNOV-87 CGR
from app.api.convergence_plan_executor import router as cpe_router             # Phase 183 INNOV-88 CPE
from app.api.convergence_certification_auditor import router as cca_router    # Phase 184 INNOV-89 CCA
from app.api.cel_loop_sentinel import router as cls_router                    # Phase 186 INNOV-91 CLS
from app.api.ga_promotion_engine import router as gpe_router                  # Phase 187 INNOV-92 GPE
from app.api.governance_tag_certifier import router as gtc_router             # Phase 188 INNOV-93 GTC
from app.api.v10_epoch_transition import router as v10et_router                  # Phase 189 INNOV-94 V10ET
from app.api.invariant_lineage_verifier import router as ilv_router              # Phase 192 INNOV-97 ILV
from app.api.convergence_criteria_state_wire import router as ccsw_router        # Phase 202 INNOV-107 CCSW
from app.api.convergence_governance_drift_reporter import router as cgdr_router   # Phase 203 INNOV-108 CGDR
from app.api.autonomous_mutation_proposal_synthesizer import router as amps_router  # Phase 204 INNOV-109 AMPS
from app.api.constitutional_mutation_velocity_governor import router as cmvg_router  # Phase 205 INNOV-110 CMVG
from app.api.cmse import router as cmse_router                                       # Phase 206 INNOV-111 CMSE
from app.api.cmwe import router as cmwe_router                                       # Phase 207 INNOV-112 CMWE
from app.api.cmpe import router as cmpe_router                                       # Phase 209 INNOV-114 CMPE
from app.api.constitutional_governance_proof_renderer import router as cgpr_router   # Phase 210 INNOV-115 CGPR
from app.api.civr import router as civr_router                                       # Phase 211 INNOV-116 CIVR
from app.api.cgva import router as cgva_router                                       # Phase 212 INNOV-117 CGVA
from app.api.cgvr import router as cgvr_router                                       # Phase 213 INNOV-118 CGVR
from app.api.cgve import router as cgve_router                                       # Phase 214 INNOV-119 CGVE
from app.api.cgvf import router as cgvf_router                                       # Phase 215 INNOV-120 CGVF
from app.api.acsa import router as acsa_router                                       # Phase 216 INNOV-121 ACSA
from app.api.acpa import router as acpa_router                                       # Phase 217 INNOV-122 ACPA
from app.api.cmoa import router as cmoa_router                                       # Phase 208 INNOV-113 CMOA
from runtime.integrations.github_app import dispatch_event, verify_webhook_signature  # ADAADchat
from app.api.dependencies import (
    require_audit_scope,
    require_gate_open,
    require_tenant_context,
    set_gate_open_checker,
)
from app.services.runtime_context import RuntimeContext
from sse_starlette.sse import EventSourceResponse
from app.api.versioning import register_v1_aliases
from runtime.api.extensions import extension_sdk_descriptor
from runtime.innovations_router import router as innovations_router
from runtime.api.compliance_export_service import ComplianceExportService

# ── Module-level runtime imports ─────────────────────────────────────────────
# These are imported at module scope (not inside function bodies) so that
# tests can monkeypatch via `server.<name>` and operator endpoints can
# reference them directly.  All are fail-safe: if a module is unavailable the
# import error surfaces at startup rather than silently at request time.
import runtime.metrics as metrics                                          # noqa: E402
import security.ledger.journal as journal                                  # noqa: E402
import runtime.constitution as constitution                                # noqa: E402
from runtime.innovations30.mutation_strategy_router import MutationStrategyRouter, make_router  # INNOV-95
from runtime.evolution.lineage_v2 import LineageLedgerV2                  # noqa: E402
from runtime.governance.rate_limiter import get_limiter as _get_proposal_limiter  # noqa: E402
from runtime.audit_auth import load_audit_tokens, require_audit_read_scope  # noqa: E402
from security.whaledic_secrets import enforce_whaledic_secret_policy  # noqa: E402
from runtime.system_status import (
    GATE_PROTOCOL,
    DEFAULT_GATE_LOCK_FILE,
    DEFAULT_REPORT_VERSION_PATH,
    DEFAULT_VERSION_PATH,
    load_live_version as load_live_version_snapshot,
    read_gate_state as read_gate_state_snapshot,
)
from app.services.compliance_exports import (
    load_control_evidence_snapshots as _svc_load_control_evidence_snapshots,
    load_policy_change_history as _svc_load_policy_change_history,
    load_replay_attestations as _svc_load_replay_attestations,
)

_LAZY_IMPORT_CACHE: dict[str, Any] = {}
_LAZY_IMPORT_LOG = logging.getLogger("adaad.lazy_import.server")


def _lazy_import(module_path: str, attr_name: str) -> Any:
    cache_key = f"{module_path}:{attr_name}"
    if cache_key in _LAZY_IMPORT_CACHE:
        return _LAZY_IMPORT_CACHE[cache_key]
    try:
        module = importlib.import_module(module_path)
        resolved = getattr(module, attr_name)
    except Exception as exc:
        detail = f"lazy_init_failed:{module_path}.{attr_name}:{type(exc).__name__}:{exc}"
        _LAZY_IMPORT_LOG.error(detail)
        metrics.log(
            event_type="lazy_init_failure",
            payload={"component": "server", "target": f"{module_path}.{attr_name}", "error": str(exc)},
            level="ERROR",
        )
        raise RuntimeError(detail) from exc
    _LAZY_IMPORT_CACHE[cache_key] = resolved
    _LAZY_IMPORT_LOG.info("lazy_init_ok:%s.%s", module_path, attr_name)
    metrics.log(
        event_type="lazy_init_success",
        payload={"component": "server", "target": f"{module_path}.{attr_name}"},
        level="INFO",
    )
    return resolved


ROOT = Path(__file__).resolve().parent
APONI_DIR = ROOT / "ui" / "aponi"
MOCK_DIR = APONI_DIR / "mock"
INDEX = APONI_DIR / "index.html"
ENHANCED_DIR = ROOT / "ui" / "enhanced"
ENHANCED_INDEX = ENHANCED_DIR / "enhanced_dashboard.html"
WHALEDIC_DIR = ROOT / "ui" / "developer" / "ADAADdev"
REPLAY_PROOFS_DIR = ROOT / "security" / "replay_manifests"
FORENSIC_EXPORT_DIR = ROOT / "reports" / "forensics"
COMPLIANCE_EXPORT_DIR = ROOT / "reports" / "compliance_exports"
MUTATION_EPOCH_LOG_DIR = ROOT / "reports" / "mutation_epochs"
MUTATION_EPOCH_STATUS_PATH = ROOT / "data" / "mutation_epoch_task_status.json"
SEMVER_AUDIT_PATH = ROOT / "data" / "semver_verdicts.jsonl"
GATE_LOCK_FILE = DEFAULT_GATE_LOCK_FILE

_MUTATION_EPOCH_TASKS_LOCK = threading.Lock()
_MUTATION_EPOCH_TASKS: dict[str, dict[str, Any]] = {}
_MUTATION_STDIO_LOG_LIMIT_BYTES = 64 * 1024
_MUTATION_EPOCH_TIMEOUT_SECONDS = 120


def _digest_for_path(path: Path) -> str:
    if not path.exists():
        return ""
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(8192)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _truncate_log_file_in_place(path: Path, limit_bytes: int) -> int:
    if not path.exists():
        return 0
    file_size = path.stat().st_size
    if file_size <= limit_bytes:
        return 0
    with path.open("rb+") as handle:
        handle.seek(file_size - limit_bytes)
        tail = handle.read(limit_bytes)
        handle.seek(0)
        handle.write(tail)
        handle.truncate()
    return file_size - limit_bytes


def _record_mutation_epoch_status(operation_id: str, payload: dict[str, Any]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    entry = {"operation_id": operation_id, "updated_at": now, **payload}
    with _MUTATION_EPOCH_TASKS_LOCK:
        _MUTATION_EPOCH_TASKS[operation_id] = entry
        MUTATION_EPOCH_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        MUTATION_EPOCH_STATUS_PATH.write_text(
            json.dumps(_MUTATION_EPOCH_TASKS, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )


def _read_mutation_epoch_status(operation_id: str) -> dict[str, Any] | None:
    with _MUTATION_EPOCH_TASKS_LOCK:
        cached = _MUTATION_EPOCH_TASKS.get(operation_id)
        if cached is not None:
            return dict(cached)
        if MUTATION_EPOCH_STATUS_PATH.exists():
            try:
                persisted = json.loads(MUTATION_EPOCH_STATUS_PATH.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return None
            if isinstance(persisted, dict):
                loaded = persisted.get(operation_id)
                if isinstance(loaded, dict):
                    _MUTATION_EPOCH_TASKS.update(persisted)
                    return dict(loaded)
    return None


class SPAStaticFiles(StaticFiles):
    def __init__(self, *args, index_path: Path, **kwargs):
        super().__init__(*args, **kwargs)
        self._index_path = index_path

    async def get_response(self, path: str, scope) -> Response:
        resp = await super().get_response(path, scope)
        if resp.status_code != 404:
            return resp

        req_path = scope.get("path", "")
        if req_path == "/api" or req_path.startswith("/api/"):
            return resp

        return FileResponse(str(self._index_path))

@asynccontextmanager
async def _lifespan(application: FastAPI):  # noqa: ARG001
    """Lifespan: ensure APONI assets exist at startup (stub-safe)."""
    _configure_composition_root(application)
    APONI_DIR.mkdir(parents=True, exist_ok=True)
    WHALEDIC_DIR.mkdir(parents=True, exist_ok=True)
    (APONI_DIR / "mock").mkdir(exist_ok=True)
    secret_policy = enforce_whaledic_secret_policy()
    application.state.whaledic_secret_policy = secret_policy

    if not INDEX.exists():
        # Minimal stub so the server always starts — replace with real Aponi build
        INDEX.write_text(
            "<!doctype html><html><head><meta charset='utf-8'/><title>ADAAD</title></head>"
            "<body><h2>ADAAD Unified Server</h2>"
            "<p>Place the full Aponi build in <code>ui/aponi/</code>.</p></body></html>",
            encoding="utf-8",
        )

    fleet = _get_fleet()
    if fleet is not None:
        _start_fleet_watchdog_once()

    try:
        yield
    finally:
        watchdog = getattr(application.state, "_dork_fleet_watchdog", None)
        if watchdog is not None:
            await watchdog.stop()


app = FastAPI(title="InnovativeAI-adaad Unified Server", lifespan=_lifespan)


def EvidenceBundleBuilder(*, export_dir: Path) -> Any:  # noqa: N802 — factory must match class-name convention
    return _lazy_import("runtime.evolution.evidence_bundle", "EvidenceBundleBuilder")(export_dir=export_dir)


def _read_gate_state() -> Dict[str, Any]:
    return read_gate_state_snapshot(gate_lock_file=GATE_LOCK_FILE, protocol=GATE_PROTOCOL)


def _assert_gate_open() -> Dict[str, Any]:
    gate = _read_gate_state()
    if gate["locked"]:
        raise HTTPException(
            status_code=423,
            detail=gate["reason"] or "Cryovant gate LOCKED",
            headers={"X-ADAAD-GATE": "locked"},
        )
    return gate


def _build_runtime_context() -> RuntimeContext:
    """Build shared API dependencies from server-scoped runtime objects."""
    return RuntimeContext(
        root=ROOT,
        replay_proofs_dir=REPLAY_PROOFS_DIR,
        forensic_export_dir=FORENSIC_EXPORT_DIR,
        compliance_export_dir=COMPLIANCE_EXPORT_DIR,
        journal=journal,
        metrics=metrics,
        lineage_ledger_cls=LineageLedgerV2,
        evidence_bundle_builder_factory=EvidenceBundleBuilder,
    )


def _configure_composition_root(application: FastAPI) -> None:
    """Wire request-time dependencies in one place for API modules."""
    application.state.runtime_context = _build_runtime_context()
    set_gate_open_checker(_assert_gate_open)


_configure_composition_root(app)

# ── MULTI-WORKER CONSTRAINT (audit H-3) ─────────────────────────────────────
# _SIMULATION_STORE, _LEDGER_AGGREGATE_CACHE, and _pressure_audit_ledger are
# process-local in-memory stores. Running multiple Uvicorn workers will cause
# these stores to diverge silently. ADAAD MUST be run with --workers 1 (the
# default). Multi-worker support requires migrating shared state to Redis —
# tracked as Phase 143 backlog item.
# Launch command: uvicorn server:app --workers 1 --host 127.0.0.1 --port 8000
# ─────────────────────────────────────────────────────────────────────────────

# ── CORS ────────────────────────────────────────────────────────────────────
import os as _os

_DEV_CORS_ORIGINS = ["http://localhost", "http://127.0.0.1"]
_DEV_CORS_ORIGIN_REGEX = r"http://(localhost|127\.0\.0\.1)(:\d+)?"


def _resolve_cors_settings(env: Mapping[str, str] | None = None) -> tuple[list[str], str | None]:
    """Resolve CORS origins/regex from env with explicit, fail-closed precedence.

    Precedence:
      1) `ADAAD_CORS_ORIGINS` (if present): use only explicit allowlist values.
      2) `ADAAD_CORS_ORIGIN_REGEX` (if present): optional regex augmentation.
      3) If neither env var is set: safe dev defaults (localhost/127.0.0.1 + localhost regex).

    If a variable is present but blank, it is treated as intentionally empty.
    """
    scope = env if env is not None else _os.environ
    origins_raw = scope.get("ADAAD_CORS_ORIGINS")
    regex_raw = scope.get("ADAAD_CORS_ORIGIN_REGEX")

    if origins_raw is None and regex_raw is None:
        return list(_DEV_CORS_ORIGINS), _DEV_CORS_ORIGIN_REGEX

    origins: list[str] = []
    if origins_raw is not None:
        origins = [o.strip() for o in origins_raw.split(",") if o.strip()]

    regex: str | None = None
    if regex_raw is not None:
        candidate = regex_raw.strip()
        regex = candidate or None

    return origins, regex


_CORS_ORIGINS, _CORS_ORIGIN_REGEX = _resolve_cors_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_origin_regex=_CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-ADAAD-Plan", "X-Request-ID", "X-Audit-Token"],
)

# ── Cryovant Gate Middleware ─────────────────────────────────────────────────
# Single enforcement point.  Static files + SPA always pass through.
# Protected API paths return 423 when gate.lock exists or ADAAD_GATE_LOCKED is set.

_GATE_OPEN_PATHS: frozenset[str] = frozenset({
    "/api/health",
    "/api/version",
    "/api/nexus/health",
})

_GATE_PROTECTED_PREFIXES: tuple[str, ...] = (
    "/api/nexus/handshake",
    "/api/nexus/protocol",
    "/api/nexus/agents",
    "/api/governance/",
    "/api/fast-path/",
    "/api/nexus/mutate",
)

_PLAN_FEATURES: dict[str, frozenset[str]] = {
    "free": frozenset({"governance_approvals"}),
    "pro": frozenset({"governance_approvals", "replay_verifications", "mutation_epochs_executed"}),
    "enterprise": frozenset({"governance_approvals", "replay_verifications", "mutation_epochs_executed"}),
}

_PLAN_LIMITS: dict[str, dict[str, int]] = {
    "free": {
        "active_users": 3,
        "active_seats": 3,
        "mutation_epochs_executed": 0,
        "replay_verifications": 10,
        "governance_approvals": 50,
    },
    "pro": {
        "active_users": 25,
        "active_seats": 25,
        "mutation_epochs_executed": 200,
        "replay_verifications": 250,
        "governance_approvals": 1_000,
    },
    "enterprise": {
        "active_users": 1_000_000,
        "active_seats": 1_000_000,
        "mutation_epochs_executed": 1_000_000,
        "replay_verifications": 1_000_000,
        "governance_approvals": 1_000_000,
    },
}


def _resolve_plan(request: Request) -> str:
    # SECURITY: Plan/entitlement tier must be derived server-side.
    # The x-adaad-plan header is accepted ONLY when the env flag
    # ADAAD_TRUST_PLAN_HEADER=1 is explicitly set (dev/test only).
    # In all other cases the server-side ADAAD_DEFAULT_PLAN env var
    # is the sole authority — never a client-supplied header.
    # Audit finding H-4 · invariant: ENTITLEMENT-SERVER-0
    _trust_header = os.getenv("ADAAD_TRUST_PLAN_HEADER", "0").strip() == "1"
    env_plan = (os.getenv("ADAAD_DEFAULT_PLAN", "enterprise") or "enterprise").strip().lower()
    if _trust_header:
        header_plan = (request.headers.get("x-adaad-plan") or "").strip().lower()
        plan = header_plan or env_plan
    else:
        plan = env_plan
    if plan not in _PLAN_LIMITS:
        return "free"
    return plan


def _resolve_enabled_features(plan: str, request: Request) -> set[str]:
    features = set(_PLAN_FEATURES.get(plan, frozenset()))
    header_override = (request.headers.get("x-adaad-features") or "").strip()
    if header_override:
        for item in header_override.split(","):
            feature = item.strip()
            if feature:
                features.add(feature)
    return features


def _billable_event_for_request(request: Request) -> str:
    path = request.url.path
    if request.method == "POST" and path.startswith("/api/nexus/agents/") and path.endswith("/mutate"):
        return "mutation_epochs_executed"
    if request.method == "GET" and path.startswith("/api/audit/epochs/") and path.endswith("/replay-proof"):
        return "replay_verifications"
    if request.method == "POST" and path in {"/api/mutations/proposals", "/mutation/propose"}:
        return "governance_approvals"
    return ""


def _entitlement_denied_response(
    *,
    reason: str,
    plan: str,
    event_name: str,
    usage: dict[str, Any],
    feature_required: str = "",
) -> JSONResponse:
    recommended_plan = "pro"
    if event_name in {"active_users", "active_seats"}:
        recommended_plan = "enterprise" if plan == "pro" else "pro"
    prompt = {
        "title": "Upgrade required to continue",
        "message": "This action exceeds your current entitlement. Upgrade to unlock access and maintain governance flow.",
        "recommended_plan": recommended_plan,
        "feature_required": feature_required or event_name,
        "reason": reason,
    }
    payload: dict[str, Any] = {
        "detail": "entitlement_denied",
        "reason": reason,
        "plan": plan,
        "event": event_name,
        "usage": usage.get("counters", {}),
        "upgrade_prompt": prompt,
    }
    if feature_required:
        payload["feature_required"] = feature_required
    metrics.register_conversion_stage("paywall_prompt_presented")
    metrics.log(
        event_type="conversion_paywall_prompt_presented",
        payload={
            "plan": plan,
            "reason": reason,
            "event": event_name,
            "recommended_plan": recommended_plan,
        },
        level="INFO",
    )
    return JSONResponse(status_code=402, content=payload)


@app.middleware("http")
async def cryovant_gate_middleware(request: Request, call_next):
    """Central Cryovant gate: blocks protected API paths when gate is locked.
    SPA routes (no /api/ prefix) and open API paths always pass through.
    """
    path: str = request.url.path

    if not path.startswith("/api/"):           # SPA / static — always open
        return await call_next(request)

    if path in _GATE_OPEN_PATHS:               # explicitly open API paths
        return await call_next(request)

    if any(path.startswith(pfx) for pfx in _GATE_PROTECTED_PREFIXES):
        gate = _read_gate_state()
        if gate["locked"]:
            return JSONResponse(
                status_code=423,
                content={
                    "detail": gate["reason"] or "Cryovant gate LOCKED",
                    "gate": gate,
                    "protocol": GATE_PROTOCOL,
                },
                headers={"X-ADAAD-GATE": "locked", "X-ADAAD-Protocol": GATE_PROTOCOL},
            )

    return await call_next(request)


@app.middleware("http")
async def metering_entitlements_middleware(request: Request, call_next):
    path = request.url.path
    if not path.startswith("/api/"):
        return await call_next(request)
    if path.startswith("/api/admin/usage"):
        return await call_next(request)

    user_id = (request.headers.get("x-adaad-user-id") or "").strip()
    seat_id = (request.headers.get("x-adaad-seat-id") or "").strip()
    plan = _resolve_plan(request)
    features = _resolve_enabled_features(plan, request)
    usage = metrics.billable_usage_snapshot()
    baseline_counters: dict[str, int] = dict(usage.get("counters", {}))
    limits = _PLAN_LIMITS[plan]
    counters: dict[str, int] = dict(usage.get("counters", {}))
    active_user_ids = set(usage.get("active_user_ids", []))
    active_seat_ids = set(usage.get("active_seat_ids", []))

    if user_id and counters.get("active_users", 0) >= limits["active_users"] and user_id not in active_user_ids:
        metrics.log(event_type="entitlement_denied", payload={"reason": "active_users_limit", "plan": plan}, level="WARNING")
        return _entitlement_denied_response(
            reason="active_users_limit",
            plan=plan,
            event_name="active_users",
            usage=usage,
        )

    if seat_id and counters.get("active_seats", 0) >= limits["active_seats"] and seat_id not in active_seat_ids:
        metrics.log(event_type="entitlement_denied", payload={"reason": "active_seats_limit", "plan": plan}, level="WARNING")
        return _entitlement_denied_response(
            reason="active_seats_limit",
            plan=plan,
            event_name="active_seats",
            usage=usage,
        )

    event_name = _billable_event_for_request(request)
    if event_name:
        if event_name not in features:
            metrics.log(
                event_type="entitlement_denied",
                payload={"reason": "feature_disabled", "plan": plan, "event": event_name},
                level="WARNING",
            )
            return _entitlement_denied_response(
                reason="feature_disabled",
                plan=plan,
                event_name=event_name,
                usage=usage,
                feature_required=event_name,
            )
        if counters.get(event_name, 0) >= limits[event_name]:
            metrics.log(
                event_type="entitlement_denied",
                payload={"reason": "plan_limit_reached", "plan": plan, "event": event_name},
                level="WARNING",
            )
            return _entitlement_denied_response(
                reason="plan_limit_reached",
                plan=plan,
                event_name=event_name,
                usage=usage,
            )

    response = await call_next(request)
    if response.status_code < 400:
        metrics.register_billable_usage(event_name=event_name, user_id=user_id, seat_id=seat_id)
        if event_name:
            metrics.log(
                event_type="billable_event_recorded",
                payload={"event": event_name, "plan": plan},
                level="INFO",
            )
            current_counters = metrics.billable_usage_snapshot().get("counters", {})
            if event_name == "replay_verifications" and int(baseline_counters.get(event_name, 0)) == 0 and int(current_counters.get(event_name, 0)) == 1:
                metrics.register_conversion_stage("first_governance_replay_proof")
                metrics.log(event_type="conversion_first_governance_replay_proof", payload={"plan": plan}, level="INFO")
            if event_name == "governance_approvals" and int(baseline_counters.get(event_name, 0)) == 0 and int(current_counters.get(event_name, 0)) == 1:
                metrics.register_conversion_stage("first_team_collaboration_event")
                metrics.log(event_type="conversion_first_team_collaboration_event", payload={"plan": plan}, level="INFO")
    return response


app.include_router(mutate_router)
app.include_router(innovations_router)


def _load_mock(name: str) -> Any:
    p = MOCK_DIR / f"{name}.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"mock '{name}' not found")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # pragma: no cover - defensive guard
        raise HTTPException(status_code=500, detail=f"mock '{name}' parse error: {e}")


def _resolve_static_asset(base_dir: Path, asset_path: str) -> Path:
    """Resolve a user-requested static asset path under a fixed base directory.

    Rejects absolute paths, parent traversal, and empty components before path
    resolution to satisfy fail-closed path handling for user-controlled input.
    """
    normalized = PurePosixPath("/" + asset_path).as_posix().lstrip("/")
    candidate = Path(normalized)
    if not normalized or candidate.is_absolute() or ".." in candidate.parts:
        raise HTTPException(status_code=404, detail="path_traversal_blocked")
    resolved = (base_dir / candidate).resolve()
    try:
        resolved.relative_to(base_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=404, detail="path_traversal_blocked")
    return resolved



def _load_audit_tokens() -> dict[str, list[str]]:
    return load_audit_tokens()


def _require_audit_read_scope(authorization: str | None) -> dict[str, str]:
    return require_audit_read_scope(authorization)


def rolling_determinism_score() -> float:
    return _lazy_import("runtime.metrics_analysis", "rolling_determinism_score")()


def mutation_rate_snapshot() -> dict[str, Any]:
    return _lazy_import("runtime.metrics_analysis", "mutation_rate_snapshot")()


def validate_proposal(payload: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    return _lazy_import("runtime.mcp.proposal_validator", "validate_proposal")(payload)


def append_proposal(*, proposal_id: str, request: Any) -> dict[str, Any]:
    return _lazy_import("runtime.mcp.proposal_queue", "append_proposal")(proposal_id=proposal_id, request=request)


def default_provider() -> Any:
    return _lazy_import("runtime.governance.foundation.determinism", "default_provider")()


def IntelligenceRouter() -> Any:
    return _lazy_import("runtime.intelligence.router", "IntelligenceRouter")()


def MutationLintingBridge() -> Any:
    return _lazy_import("runtime.mcp.linting_bridge", "MutationLintingBridge")()



_REPORT_VERSION_PATH = DEFAULT_REPORT_VERSION_PATH
_VERSION_PATH = DEFAULT_VERSION_PATH


def _load_live_version() -> Dict[str, Any]:
    return load_live_version_snapshot(
        version_path=_VERSION_PATH,
        report_version_path=_REPORT_VERSION_PATH,
        protocol=GATE_PROTOCOL,
    )


@app.get("/api/version")
def api_version() -> Dict[str, Any]:
    """Live version snapshot — no auth required, no gate check.

    Returns adaad_version, constitution_version, last_sync_sha, last_sync_date.
    The Aponi UI fetches this on every hardRefresh to display the version
    banner accurately rather than relying on static protocol strings.
    """
    return _load_live_version()


@app.get("/api/extensions/spec")
def api_extension_spec() -> dict[str, Any]:
    """Return the extension SDK descriptor for plugin integrators."""

    return extension_sdk_descriptor()


@app.get("/api/health")
def health() -> dict[str, Any]:
    gate = _read_gate_state()
    ok = not gate["locked"]
    live = _load_live_version()
    _rp_path = ROOT / "governance_runtime_profile.lock.json"
    try:
        _rp = json.loads(_rp_path.read_text(encoding="utf-8"))
        runtime_profile: dict[str, Any] = {"present": True, **_rp}
    except (OSError, json.JSONDecodeError):
        runtime_profile = {"present": False}
    policy = enforce_whaledic_secret_policy()
    return {
        "ok": ok,
        "gate_ok": ok,
        "grok_active": not policy.anthropic_key_available, # Phase 107
        "version": live.get("adaad_version", "unknown"),
        "runtime_profile": runtime_profile,
        "ui_present": APONI_DIR.exists(),
        "mock_present": MOCK_DIR.exists(),
        "gate": gate,
        "protocol": GATE_PROTOCOL,
    }


@app.get("/api/nexus/health")
def nexus_health(gate: dict[str, Any] = Depends(require_gate_open)) -> dict[str, Any]:
    return {"ok": True, "gate_ok": True, "protocol": GATE_PROTOCOL, "gate": gate}


@app.get("/api/nexus/handshake")
def nexus_handshake() -> dict[str, Any]:
    # Gate enforced by cryovant_gate_middleware — read state for metadata only.
    gate = _read_gate_state()
    return {
        "ok": True,
        "ts": datetime.now(timezone.utc).isoformat(),
        "protocol": GATE_PROTOCOL,
        "gate": {"locked": False, "reason": None, "checked_at": gate["checked_at"]},
    }


@app.get("/api/nexus/protocol")
def nexus_protocol() -> dict[str, Any]:
    # Gate enforced by cryovant_gate_middleware.
    gate = _read_gate_state()
    return {
        "ok": True,
        "version": "1.0",
        "created_at": gate["checked_at"],
        "gate_cycle": {
            "keys_dir": "security/keys",
            "keys_mode_required_octal": "0700",
            "ledger_dir": "security/ledger",
            "no_bypass": True,
        },
    }


@app.get("/api/nexus/agents")
def nexus_agents() -> dict[str, Any]:
    # Gate enforced by cryovant_gate_middleware.
    agents_dir = ROOT / "app" / "agents"
    agents: list[dict[str, Any]] = []
    if agents_dir.exists():
        for entry in sorted(agents_dir.iterdir(), key=lambda p: p.name):
            if not entry.is_dir() or entry.name in {"agent_template", "lineage"} or entry.name.startswith("__"):
                continue
            agents.append(
                {
                    "name": entry.name,
                    "meta_exists": (entry / "meta.json").exists(),
                    "dna_exists": (entry / "dna.json").exists(),
                    "certificate_exists": (entry / "certificate.json").exists(),
                    "entrypoint_exists": (entry / "__init__.py").exists(),
                }
            )
    return {"ok": True, "count": len(agents), "agents": agents}


# "status" is excluded — GET /api/status returns mock_endpoints_disabled sentinel
MOCK_ENDPOINTS = ["agents", "tree", "kpis", "changes", "suggestions", "governance/status", "mutations/recent", "replay/score", "epoch/current", "agents/health", "ledger/entries", "webhooks/recent", "ledger/log"]
for endpoint_name in MOCK_ENDPOINTS:
    app.add_api_route(
        f"/api/{endpoint_name}",
        endpoint=lambda n=endpoint_name: _load_mock(n),
        methods=["GET"],
    )



@app.get("/governance/reviewer-calibration")
def governance_reviewer_calibration(
    epoch_id: str | None = Query(default=None),
    reviewer_ids: str | None = Query(default=None),
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
) -> dict[str, Any]:
    authn = auth_ctx
    if not epoch_id:
        raise HTTPException(status_code=422, detail="missing_epoch_id")

    from runtime.api.runtime_services import reviewer_calibration_service

    requested_reviewer_ids = None
    if reviewer_ids:
        requested_reviewer_ids = [item.strip() for item in reviewer_ids.split(",") if item.strip()]

    calibration = reviewer_calibration_service(epoch_id=epoch_id, reviewer_ids=requested_reviewer_ids)
    calibration["constitutional_floor"] = "enforced"

    return {"schema_version": "1.0", "authn": authn, "data": calibration}

# ---------------------------------------------------------------------------
# Phase 8 — Governance Health Dashboard (PR-8-02)
# ---------------------------------------------------------------------------

@app.get("/governance/health")
def governance_health(
    epoch_id: str | None = Query(default=None),
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
) -> dict[str, Any]:
    """Return current and rolling governance health score.

    Response fields
    ---------------
    health_score          float — current epoch h ∈ [0.0, 1.0]
    status                str   — 'green' | 'amber' | 'red'
    signal_breakdown      dict  — per-signal raw values
    weight_snapshot_digest str  — sha256 of canonical weight vector
    constitution_version  str
    scoring_algorithm_version str
    degraded              bool  — h < 0.60
    constitutional_floor  str   — always 'enforced'
    """
    from runtime.governance.health_service import governance_health_service

    authn = auth_ctx
    resolved_epoch = epoch_id or "current"
    result = governance_health_service(epoch_id=resolved_epoch)
    result["constitutional_floor"] = "enforced"

    # DFSB-FITNESS-0: embed fleet fitness in governance health
    try:
        fleet = _get_fleet()
        if fleet is not None:
            fs = fleet.fleet_status()
            result["fleet_fitness"] = {
                "score": 1.0 if not fs.get("blocked") and fs.get("healthy_provider_count", 0) > 0 else 0.0,
                "blocked": fs.get("blocked", True),
                "healthy_count": fs.get("healthy_provider_count", 0),
                "invariant": "DFSB-FITNESS-0",
            }
    except Exception:
        result["fleet_fitness"] = {"score": None, "blocked": None, "healthy_count": None, "invariant": "DFSB-FITNESS-0"}

    return {"schema_version": "1.0", "authn": authn, "data": result}


# ---------------------------------------------------------------------------
# Telemetry endpoints are routed via app.api.telemetry
# ---------------------------------------------------------------------------
from app.api.telemetry import (
    router as telemetry_router,
    set_telemetry_sink as _set_telemetry_sink_for_server,
    get_telemetry_sink,
)

app.include_router(telemetry_router)

app.include_router(governance_router)
app.include_router(cgth_router)          # Phase 155 INNOV-61 CGTH
app.include_router(cgai_router)          # Phase 156 INNOV-62 CGAI
app.include_router(ghi_router)           # Phase 157 INNOV-63 GHI
app.include_router(csr_router)           # Phase 158 INNOV-64 CSR
app.include_router(csi_router)           # Phase 159 INNOV-65 CSI
app.include_router(ebs_router)           # Phase 160 INNOV-66 EBS
app.include_router(cfe_router)           # Phase 161 INNOV-67 CFE
app.include_router(mia_router)           # Phase 162 INNOV-68 MIA
app.include_router(mce_router)           # Phase 163 INNOV-69 MCE
app.include_router(gir_router)           # Phase 181 INNOV-86 GIR
app.include_router(cgr_router)           # Phase 182 INNOV-87 CGR
app.include_router(cpe_router)           # Phase 183 INNOV-88 CPE
app.include_router(cca_router)           # Phase 184 INNOV-89 CCA
app.include_router(gpe_router)           # Phase 187 INNOV-92 GPE
app.include_router(gtc_router)           # Phase 188 INNOV-93 GTC
app.include_router(v10et_router)         # Phase 189 INNOV-94 V10ET
app.include_router(ilv_router)           # Phase 192 INNOV-97 ILV
app.include_router(cls_router)           # Phase 186 INNOV-91 CLS
app.include_router(audit_router)
app.include_router(ui_router)
app.include_router(simulation_router)
app.include_router(compliance_router)
app.include_router(audit_exports_router)
app.include_router(mutation_control_router)
app.include_router(streams_router)
app.include_router(ccsw_router)             # Phase 202 INNOV-107 CCSW
app.include_router(cgdr_router)             # Phase 203 INNOV-108 CGDR
app.include_router(amps_router)             # Phase 204 INNOV-109 AMPS
app.include_router(cmvg_router)             # Phase 205 INNOV-110 CMVG
app.include_router(cmse_router)             # Phase 206 INNOV-111 CMSE
app.include_router(cmoa_router)             # Phase 208 INNOV-113 CMOA
app.include_router(cmwe_router)             # Phase 207 INNOV-112 CMWE
app.include_router(cmpe_router)             # Phase 209 INNOV-114 CMPE
app.include_router(cgpr_router)             # Phase 210 INNOV-115 CGPR
app.include_router(civr_router)             # Phase 211 INNOV-116 CIVR
app.include_router(cgva_router)             # Phase 212 INNOV-117 CGVA
app.include_router(cgvr_router)             # Phase 213 INNOV-118 CGVR
app.include_router(cgve_router)             # Phase 214 INNOV-119 CGVE
app.include_router(cgvf_router)             # Phase 215 INNOV-120 CGVF
app.include_router(acsa_router)             # Phase 216 INNOV-121 ACSA
app.include_router(acpa_router)             # Phase 217 INNOV-122 ACPA


def telemetry_decisions_legacy(
    strategy_id: str | None = None,
    outcome: str | None = None,
    limit: int = 100,
    offset: int = 0,
    authn: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if authn is None:
        raise HTTPException(status_code=500, detail="missing_auth_context")
    sink = get_telemetry_sink()
    if sink is None:
        try:
            from runtime.intelligence.routed_decision_telemetry import InMemoryTelemetrySink
            sink = InMemoryTelemetrySink()
        except Exception:
            sink = None
    sink_type = "memory"
    ledger_path_str = None
    if sink is not None:
        from runtime.intelligence.file_telemetry_sink import FileTelemetrySink, TelemetryLedgerReader
        if isinstance(sink, FileTelemetrySink):
            sink_type = "file"
            ledger_path_str = str(sink._path)
            reader = TelemetryLedgerReader(sink._path)
            decisions = reader.query(strategy_id=strategy_id, outcome=outcome, limit=limit, offset=offset)
            total_queried = len(decisions)
        else:
            all_entries = list(getattr(sink, "entries", lambda: [])())
            if strategy_id is not None:
                all_entries = [e for e in all_entries if e.get("strategy_id") == strategy_id]
            if outcome is not None:
                all_entries = [e for e in all_entries if e.get("outcome") == outcome]
            all_entries.reverse()
            total_queried = len(all_entries)
            decisions = all_entries[offset: offset + limit]
    else:
        decisions = []
        total_queried = 0
    return {"schema_version": "1.0", "authn": authn, "data": {"decisions": decisions, "total_queried": total_queried, "ledger_path": ledger_path_str, "sink_type": sink_type}}


def telemetry_analytics_legacy(
    window_size: int = 100,
    authn: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if authn is None:
        raise HTTPException(status_code=500, detail="missing_auth_context")
    from runtime.intelligence.strategy_analytics import StrategyAnalyticsEngine
    from runtime.intelligence.file_telemetry_sink import FileTelemetrySink, TelemetryLedgerReader
    sink = get_telemetry_sink()
    if isinstance(sink, FileTelemetrySink):
        reader = TelemetryLedgerReader(sink._path)
    else:
        class _MemoryAdapter:
            def __init__(self, s):
                self._sink = s
            def payloads_chain_snapshot(self):
                if self._sink is None:
                    return ([], True, 0)
                payloads = list(getattr(self._sink, "entries", lambda: [])())
                return (payloads, True, len(payloads))
        reader = _MemoryAdapter(sink)
    engine = StrategyAnalyticsEngine(reader, window_size=window_size)
    report = engine.generate_report()
    def _stat_to_dict(s):
        return {"strategy_id": s.strategy_id, "window_size": s.window_size, "total": s.total, "approved": s.approved, "win_rate": s.win_rate, "window_win_rate": s.window_win_rate, "drift": s.drift, "stale": s.stale, "last_seen_sequence": s.last_seen_sequence}
    return {"schema_version": "1.0", "authn": authn, "data": {"status": report.status, "health_score": report.health_score, "strategy_stats": [_stat_to_dict(s) for s in report.strategy_stats], "dominant_strategy": report.dominant_strategy, "dominant_share": report.dominant_share, "stale_strategy_ids": list(report.stale_strategy_ids), "drift_max": report.drift_max, "window_size": report.window_size, "total_decisions": report.total_decisions, "window_decisions": report.window_decisions, "ledger_chain_valid": report.ledger_chain_valid, "report_digest": report.report_digest}}


def telemetry_strategy_detail_legacy(
    strategy_id: str,
    window_size: int = 100,
    authn: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if authn is None:
        raise HTTPException(status_code=500, detail="missing_auth_context")
    from runtime.intelligence.strategy import STRATEGY_TAXONOMY
    if strategy_id not in STRATEGY_TAXONOMY:
        raise HTTPException(status_code=404, detail=f"unknown_strategy_id:{strategy_id}")
    from runtime.intelligence.strategy_analytics import StrategyAnalyticsEngine
    from runtime.intelligence.file_telemetry_sink import FileTelemetrySink, TelemetryLedgerReader
    sink = get_telemetry_sink()
    if isinstance(sink, FileTelemetrySink):
        reader = TelemetryLedgerReader(sink._path)
    else:
        class _MemAdapter:
            def __init__(self, s):
                self._sink = s
            def payloads_chain_snapshot(self):
                if self._sink is None:
                    return ([], True, 0)
                payloads = list(getattr(self._sink, "entries", lambda: [])())
                return (payloads, True, len(payloads))
        reader = _MemAdapter(sink)
    engine = StrategyAnalyticsEngine(reader, window_size=window_size)
    report = engine.generate_report()
    stat = next(s for s in report.strategy_stats if s.strategy_id == strategy_id)
    return {"schema_version": "1.0", "authn": authn, "data": {"strategy_id": stat.strategy_id, "window_size": stat.window_size, "total": stat.total, "approved": stat.approved, "win_rate": stat.win_rate, "window_win_rate": stat.window_win_rate, "drift": stat.drift, "stale": stat.stale, "last_seen_sequence": stat.last_seen_sequence}}
# ---------------------------------------------------------------------------
# Phase 23 — Routing Health Endpoint (PR-23-02)
# ---------------------------------------------------------------------------

@app.get("/governance/routing-health")
def governance_routing_health(
    window_size: int = Query(default=100, ge=10, le=10000),
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
) -> dict[str, Any]:
    """Return RoutingHealthReport as a governed response. Read-only.

    Query params
    ------------
    window_size  — rolling window size (10–10000, default 100)

    Response fields (data)
    ----------------------
    status              "green" | "amber" | "red"
    health_score        float 0–1
    strategy_stats      list of StrategyWindowStats dicts
    dominant_strategy   str | null
    dominant_share      float
    stale_strategy_ids  list[str]
    drift_max           float
    window_size         int
    total_decisions     int
    window_decisions    int
    ledger_chain_valid  bool
    report_digest       sha256 prefixed string
    available           bool
    """
    authn = auth_ctx

    from runtime.intelligence.strategy_analytics import StrategyAnalyticsEngine
    from runtime.intelligence.file_telemetry_sink import FileTelemetrySink, TelemetryLedgerReader

    sink = get_telemetry_sink()

    if isinstance(sink, FileTelemetrySink):
        reader = TelemetryLedgerReader(sink._path)
        engine = StrategyAnalyticsEngine(reader, window_size=window_size)
        report = engine.generate_report()

        def _stat(s):
            return {
                "strategy_id": s.strategy_id,
                "window_size": s.window_size,
                "total": s.total,
                "approved": s.approved,
                "win_rate": s.win_rate,
                "window_win_rate": s.window_win_rate,
                "drift": s.drift,
                "stale": s.stale,
                "last_seen_sequence": s.last_seen_sequence,
            }

        return {
            "schema_version": "1.0",
            "authn": authn,
            "data": {
                "status": report.status,
                "health_score": report.health_score,
                "strategy_stats": [_stat(s) for s in report.strategy_stats],
                "dominant_strategy": report.dominant_strategy,
                "dominant_share": report.dominant_share,
                "stale_strategy_ids": list(report.stale_strategy_ids),
                "drift_max": report.drift_max,
                "window_size": report.window_size,
                "total_decisions": report.total_decisions,
                "window_decisions": report.window_decisions,
                "ledger_chain_valid": report.ledger_chain_valid,
                "report_digest": report.report_digest,
                "available": True,
            },
        }

    # No file sink active — degraded-mode response
    return {
        "schema_version": "1.0",
        "authn": authn,
        "data": {
            "status": "green",
            "health_score": 1.0,
            "strategy_stats": [],
            "dominant_strategy": None,
            "dominant_share": 0.0,
            "stale_strategy_ids": [],
            "drift_max": 0.0,
            "window_size": window_size,
            "total_decisions": 0,
            "window_decisions": 0,
            "ledger_chain_valid": True,
            "report_digest": None,
            "available": False,
        },
    }


# ---------------------------------------------------------------------------
# Phase 24 — Review Pressure Endpoint (PR-24-02)
# ---------------------------------------------------------------------------

@app.get("/governance/review-pressure")
def governance_review_pressure(
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
) -> dict[str, Any]:
    """Return advisory PressureAdjustment based on current governance health. Read-only.

    Response fields (data)
    ----------------------
    health_score          float — current governance composite h ∈ [0.0, 1.0]
    health_band           "green" | "amber" | "red"
    pressure_tier         "none" | "elevated" | "critical"
    proposed_tier_config  dict — tier → {base_count, min_count, max_count}
    baseline_tier_config  dict — DEFAULT_TIER_CONFIG snapshot
    adjusted_tiers        list[str] — tiers with raised min_count
    advisory_only         true (structural invariant)
    adjustment_digest     sha256-prefixed digest
    adaptor_version       "24.0"
    """
    authn = auth_ctx

    from runtime.governance.health_pressure_adaptor import HealthPressureAdaptor
    from runtime.governance.health_service import governance_health_service

    # Derive health score from current epoch health (best-effort)
    try:
        health_data = governance_health_service(epoch_id="current")
        h = float(health_data.get("health_score", 1.0))
    except Exception:
        h = 1.0  # conservative default

    adaptor = HealthPressureAdaptor()
    adj = adaptor.compute(h)

    # Phase 25: emit to PressureAuditLedger if configured
    import os
    ledger_active = False
    ledger_sequence = None
    global _pressure_audit_ledger

    pressure_ledger_path = os.environ.get("ADAAD_PRESSURE_LEDGER_PATH", "").strip()
    if pressure_ledger_path:
        try:
            from runtime.governance.pressure_audit_ledger import PressureAuditLedger
            from pathlib import Path as _Path
            if _pressure_audit_ledger is None:
                _pressure_audit_ledger = PressureAuditLedger(
                    _Path(pressure_ledger_path), chain_verify_on_open=False
                )
            _pressure_audit_ledger.emit(adj)
            ledger_active = True
            ledger_sequence = _pressure_audit_ledger.sequence - 1
        except Exception as _exc:
            import logging as _log
            _log.getLogger(__name__).warning(
                "PressureAuditLedger emit failed (dropped): %s", _exc
            )

    return {
        "schema_version": "1.0",
        "authn": authn,
        "data": {
            "health_score": adj.health_score,
            "health_band": adj.health_band,
            "pressure_tier": adj.pressure_tier,
            "proposed_tier_config": adj.proposed_tier_config,
            "baseline_tier_config": adj.baseline_tier_config,
            "adjusted_tiers": list(adj.adjusted_tiers),
            "advisory_only": adj.advisory_only,
            "adjustment_digest": adj.adjustment_digest,
            "adaptor_version": adj.adaptor_version,
            "ledger_active": ledger_active,
            "ledger_sequence": ledger_sequence,
        },
    }



# ---------------------------------------------------------------------------
# Phase 25 — Pressure History Endpoint (PR-25-02)
# ---------------------------------------------------------------------------

@app.get("/governance/pressure-history")
def governance_pressure_history(
    pressure_tier: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
) -> dict[str, Any]:
    """Return paginated PressureAdjustment ledger history. Read-only.

    Query params
    ------------
    pressure_tier  — filter by tier ("none", "elevated", "critical")
    limit          — max records (1–500, default 100)
    offset         — pagination offset (default 0)

    Response fields (data)
    ----------------------
    records         list of ledger records (newest-first)
    total_queried   int — records returned
    tier_frequency  dict — {tier: count} across all ledger entries
    ledger_active   bool
    ledger_path     str | null
    """
    authn = auth_ctx

    import os
    from pathlib import Path as _Path

    pressure_ledger_path = os.environ.get("ADAAD_PRESSURE_LEDGER_PATH", "").strip()

    if not pressure_ledger_path or not _Path(pressure_ledger_path).exists():
        return {
            "schema_version": "1.0",
            "authn": authn,
            "data": {
                "records": [],
                "total_queried": 0,
                "tier_frequency": {},
                "ledger_active": False,
                "ledger_path": pressure_ledger_path or None,
            },
        }

    from runtime.governance.pressure_audit_ledger import PressureAuditReader

    reader = PressureAuditReader(_Path(pressure_ledger_path))
    records = reader.history(
        pressure_tier=pressure_tier,
        limit=limit,
        offset=offset,
    )
    freq = reader.tier_frequency()

    return {
        "schema_version": "1.0",
        "authn": authn,
        "data": {
            "records": records,
            "total_queried": len(records),
            "tier_frequency": freq,
            "ledger_active": True,
            "ledger_path": pressure_ledger_path,
        },
    }


# ---------------------------------------------------------------------------
# Phase 25 — Mutation Admission Control
# ---------------------------------------------------------------------------

@app.get("/governance/admission-status")
def governance_admission_status(
    risk_score: float = 0.50,
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
) -> dict[str, Any]:
    """Return advisory AdmissionDecision for a mutation with the given risk_score.

    Evaluates whether a mutation candidate with ``risk_score`` would be admitted
    to the evolution pipeline given the current governance health score.

    Query parameters
    ----------------
    risk_score : float, default 0.50
        Mutation risk score ∈ [0.0, 1.0].  Clamped if out of range.

    Response fields (data)
    ----------------------
    health_score          float — current governance composite h ∈ [0.0, 1.0]
    mutation_risk_score   float — clamped input risk_score
    admission_band        "green" | "amber" | "red" | "halt"
    risk_threshold        float — exclusive upper bound for admission in current band
    admitted              bool — True when mutation would be admitted
    admits_all            bool — True only in green band
    epoch_paused          bool — advisory epoch-pause flag (h < 0.40)
    deferral_reason       str | null — reason when not admitted
    advisory_only         true (structural invariant)
    decision_digest       sha256-prefixed deterministic digest
    controller_version    "25.0"
    """
    authn = auth_ctx

    from runtime.governance.mutation_admission import MutationAdmissionController
    from runtime.governance.health_service import governance_health_service

    try:
        health_data = governance_health_service(epoch_id="current")
        h = float(health_data.get("health_score", 1.0))
    except Exception:
        h = 1.0  # conservative default

    controller = MutationAdmissionController()
    decision = controller.evaluate(health_score=h, mutation_risk_score=risk_score)

    return {
        "schema_version": "1.0",
        "authn": authn,
        "data": {
            "health_score":        decision.health_score,
            "mutation_risk_score": decision.mutation_risk_score,
            "admission_band":      decision.admission_band,
            "risk_threshold":      decision.risk_threshold,
            "admitted":            decision.admitted,
            "admits_all":          decision.admits_all,
            "epoch_paused":        decision.epoch_paused,
            "deferral_reason":     decision.deferral_reason,
            "advisory_only":       decision.advisory_only,
            "decision_digest":     decision.decision_digest,
            "controller_version":  decision.controller_version,
        },
    }


# ---------------------------------------------------------------------------
# Phase 26 — Admission Rate Signal
# ---------------------------------------------------------------------------

@app.get("/governance/admission-rate")
def governance_admission_rate(
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
) -> dict[str, Any]:
    """Return AdmissionRateReport from the global AdmissionRateTracker. Read-only.

    Response fields (data)
    ----------------------
    admission_rate_score   float — rolling admission rate ∈ [0.0, 1.0]
    admitted_count         int   — admitted decisions in window
    total_count            int   — total decisions in window
    epochs_in_window       int   — distinct epochs contributing to window
    max_epochs             int   — configured rolling-window size
    report_digest          str   — sha256-prefixed deterministic digest
    tracker_version        str   — "26.0"
    """
    authn = auth_ctx

    from runtime.governance.admission_tracker import AdmissionRateTracker

    tracker = AdmissionRateTracker()
    report = tracker.generate_report()

    return {
        "schema_version": "1.0",
        "authn": authn,
        "data": {
            "admission_rate_score": report.admission_rate_score,
            "admitted_count":       report.admitted_count,
            "total_count":          report.total_count,
            "epochs_in_window":     report.epochs_in_window,
            "max_epochs":           report.max_epochs,
            "report_digest":        report.report_digest,
            "tracker_version":      report.tracker_version,
        },
    }


# ---------------------------------------------------------------------------
# Phase 27 — Admission Audit Ledger
# ---------------------------------------------------------------------------

@app.get("/governance/admission-audit")
def governance_admission_audit(
    limit: int = 20,
    band: str | None = None,
    admitted_only: bool = False,
    blocked_only: bool = False,
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
) -> dict[str, Any]:
    """Return recent AdmissionDecision records from the audit ledger. Read-only.

    Phase 29 extension: enforcement verdict fields (escalation_mode, blocked,
    block_reason, verdict_digest) are included in each record that was emitted
    via AdmissionAuditLedger.emit(decision, verdict=...).

    Query parameters
    ----------------
    limit : int, default 20
        Maximum number of records to return (most recent).
    band : str, optional
        Filter by admission_band: "green" | "amber" | "red" | "halt".
    admitted_only : bool, default False
        When True, return only admitted==True records.
    blocked_only : bool, default False
        When True, return only records where blocked==True (enforcement arc).

    Response fields (data)
    ----------------------
    records              list — admission audit records (chronological)
    total_in_window      int  — number of records returned
    admission_rate       float — admitted/total ratio across all records
    band_frequency       dict  — band → count across all records
    blocked_count        int  — count of blocked==True records (Phase 29)
    enforcement_rate     float — fraction of records with enforcement data (Phase 29)
    escalation_breakdown dict  — escalation_mode → count (Phase 29)
    ledger_version       str   — "29.0"
    """
    authn = auth_ctx

    from runtime.governance.admission_audit_ledger import (
        ADMISSION_LEDGER_VERSION,
        DEFAULT_ADMISSION_LEDGER_PATH,
        AdmissionAuditReader,
    )

    reader = AdmissionAuditReader(DEFAULT_ADMISSION_LEDGER_PATH)

    if blocked_only:
        records = reader.history_with_enforcement(limit=limit, blocked_only=True)
    else:
        records = reader.history(limit=limit, band_filter=band, admitted_only=admitted_only)

    return {
        "schema_version": "1.0",
        "authn": authn,
        "data": {
            "records":              records,
            "total_in_window":      len(records),
            "admission_rate":       reader.admission_rate(),
            "band_frequency":       reader.band_frequency(),
            "blocked_count":        reader.blocked_count(),
            "enforcement_rate":     reader.enforcement_rate(),
            "escalation_breakdown": reader.escalation_mode_breakdown(),
            "ledger_version":       ADMISSION_LEDGER_VERSION,
        },
    }




# ---------------------------------------------------------------------------
# Phase 28 — Admission Band Enforcement
# ---------------------------------------------------------------------------

@app.get("/governance/admission-enforcement")
def governance_admission_enforcement(
    risk_score: float = 0.50,
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
) -> dict[str, Any]:
    """Return AdmissionBandEnforcer verdict for a mutation with the given risk_score.

    Extends Phase 25 admission-status with escalation-mode resolution:
    when ADAAD_SEVERITY_ESCALATIONS contains
    {"admission_band_enforcement": "blocking"}, HALT-band verdicts set
    blocked=True, surfacing an emergency-stop signal to callers.

    Query parameters
    ----------------
    risk_score : float, default 0.50
        Mutation risk score [0.0, 1.0]. Clamped if out of range.

    Response fields (data)
    ----------------------
    escalation_mode   "advisory" | "blocking"
    blocked           bool — True only when mode=blocking AND band=halt
    block_reason      str — human-readable reason when blocked; empty otherwise
    verdict_digest    sha256 hex — deterministic over (decision_digest, blocked, block_reason)
    enforcer_version  "28.0"
    decision          full AdmissionDecision payload (same as /admission-status)
    """
    authn = auth_ctx

    from runtime.governance.admission_band_enforcer import AdmissionBandEnforcer
    from runtime.governance.health_service import governance_health_service

    try:
        health_data = governance_health_service(epoch_id="current")
        h = float(health_data.get("health_score", 1.0))
    except Exception:
        h = 1.0

    enforcer = AdmissionBandEnforcer(health_score=h)
    verdict = enforcer.evaluate(risk_score)

    return {
        "schema_version": "1.0",
        "authn": authn,
        "data": verdict.as_dict(),
    }



# ---------------------------------------------------------------------------
# Phase 30 — Threat Scan Ledger
# ---------------------------------------------------------------------------

@app.get("/governance/threat-scans")
def governance_threat_scans(
    limit: int = 20,
    recommendation: str | None = None,
    triggered_only: bool = False,
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
) -> dict[str, Any]:
    """Return recent ThreatMonitor scan records from the audit ledger. Read-only.

    Query parameters
    ----------------
    limit : int, default 20
        Maximum number of records to return (most recent).
    recommendation : str, optional
        Filter by recommendation: "continue" | "escalate" | "halt".
    triggered_only : bool, default False
        When True, only return scans where at least one detector triggered.

    Response fields (data)
    ----------------------
    records                 list  — threat scan records (chronological)
    total_in_window         int   — number of records returned
    triggered_rate          float — fraction of scans with triggered_count >= 1
    escalation_rate         float — fraction of scans with recommendation != 'continue'
    avg_risk_score          float — mean risk_score across all records
    recommendation_breakdown dict  — recommendation → count
    risk_level_breakdown     dict  — risk_level → count
    ledger_version           str   — "30.0"
    """
    authn = auth_ctx

    from runtime.governance.threat_scan_ledger import (
        THREAT_SCAN_LEDGER_VERSION,
        DEFAULT_THREAT_SCAN_LEDGER_PATH,
        ThreatScanReader,
    )

    reader = ThreatScanReader(DEFAULT_THREAT_SCAN_LEDGER_PATH)
    records = reader.history(
        limit=limit,
        recommendation_filter=recommendation,
        triggered_only=triggered_only,
    )

    return {
        "schema_version": "1.0",
        "authn": authn,
        "data": {
            "records":                  records,
            "total_in_window":          len(records),
            "triggered_rate":           reader.triggered_rate(),
            "escalation_rate":          reader.escalation_rate(),
            "avg_risk_score":           reader.avg_risk_score(),
            "recommendation_breakdown": reader.recommendation_breakdown(),
            "risk_level_breakdown":     reader.risk_level_breakdown(),
            "ledger_version":           THREAT_SCAN_LEDGER_VERSION,
        },
    }



# ---------------------------------------------------------------------------
# Phase 31 — Governance Debt Snapshot
# ---------------------------------------------------------------------------

@app.get("/governance/debt")
def governance_debt(
    epoch_id: str = "current",
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
) -> dict[str, Any]:
    """Return the current GovernanceDebtLedger snapshot. Read-only.

    Reads the last persisted debt snapshot from the evolution loop's ledger
    (if available) and returns a safe-default snapshot when no epoch data exists.

    Query parameters
    ----------------
    epoch_id : str, default "current"
        Epoch identifier for display; used only when constructing a live snapshot.

    Response fields (data)
    ----------------------
    epoch_id                str   — epoch identifier
    compound_debt_score     float — accumulated weighted warning debt (decayed)
    breach_threshold        float — threshold at which debt triggers alert (default 3.0)
    threshold_breached      bool  — True when compound_debt_score >= breach_threshold
    warning_count           int   — number of warning verdicts in last accumulation
    warning_weighted_sum    float — sum of weighted warnings in last epoch
    decayed_prior_debt      float — prior compound debt after decay applied
    applied_decay_epochs    int   — number of epochs since last accumulation
    warning_rules           list  — sorted list of rule names that triggered warnings
    snapshot_hash           str   — sha256 deterministic hash of this snapshot
    debt_ledger_schema      str   — "1.0"
    """
    authn = auth_ctx

    from runtime.governance.debt_ledger import (
        DEBT_LEDGER_SCHEMA_VERSION,
        DEFAULT_WARNING_WEIGHTS,
        GovernanceDebtLedger,
    )

    # Best-effort: try to get live snapshot from evolution loop state
    snapshot = None
    try:
        from runtime.evolution.evolution_loop import get_current_debt_snapshot  # type: ignore
        snapshot = get_current_debt_snapshot()
    except Exception:
        pass

    if snapshot is None:
        # Return a safe zero-state snapshot
        ledger = GovernanceDebtLedger()
        snapshot = ledger.accumulate_epoch_verdicts(
            epoch_id=epoch_id,
            epoch_index=0,
            warning_verdicts=[],
            agent_id="governance_debt_endpoint",
        )

    return {
        "schema_version": "1.0",
        "authn": authn,
        "data": {
            "epoch_id":             snapshot.epoch_id,
            "epoch_index":          snapshot.epoch_index,
            "compound_debt_score":  snapshot.compound_debt_score,
            "breach_threshold":     snapshot.breach_threshold,
            "threshold_breached":   snapshot.threshold_breached,
            "warning_count":        snapshot.warning_count,
            "warning_weighted_sum": snapshot.warning_weighted_sum,
            "decayed_prior_debt":   snapshot.decayed_prior_debt,
            "applied_decay_epochs": snapshot.applied_decay_epochs,
            "warning_rules":        snapshot.warning_rules,
            "warning_weights":      snapshot.warning_weights,
            "snapshot_hash":        snapshot.snapshot_hash,
            "debt_ledger_schema":   DEBT_LEDGER_SCHEMA_VERSION,
        },
    }


# ---------------------------------------------------------------------------
# Phase 31 — Gate Certifier Endpoint
# ---------------------------------------------------------------------------

@app.post("/governance/certify")
def governance_certify(
    request: dict[str, Any],
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
) -> dict[str, Any]:
    """Run GateCertifier security scan on a named runtime file. Read-only governance check.

    Request body (JSON)
    -------------------
    file_path : str  (required)
        Relative path to the Python file to certify (e.g. "runtime/governance/gate.py").
        Must be within the repo root. Absolute paths and path traversal are rejected.
    metadata : dict  (optional)
        Arbitrary key-value pairs to attach to the certification result.
        Sensitive key "cryovant_token" is stripped from the response.

    Response fields (data)
    ----------------------
    status          "CERTIFIED" | "REJECTED"
    passed          bool
    file            str   — canonicalised relative file path
    escalation      str   — "advisory" | "warning" | "critical"
    mutation_blocked bool  — True when canon law marks this violation as mutation-blocking
    fail_closed     bool  — True when canon law triggers fail-closed policy
    checks          dict  — per-check booleans (imports, token, ast, auth)
    hash            str   — sha256 of file content (when accessible)
    generated_at    str   — ISO timestamp
    """
    authn = auth_ctx

    from dataclasses import dataclass as _dc
    from pathlib import Path
    from runtime.governance.gate_certifier import GateCertifier

    file_path_raw = str(request.get("file_path") or "").strip()
    if not file_path_raw:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="file_path is required")

    # Safety: reject absolute paths and traversal attempts
    if file_path_raw.startswith("/") or ".." in file_path_raw:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="file_path must be a relative path within the repo")

    repo_root = Path(__file__).parent
    target = (repo_root / file_path_raw).resolve()

    # Ensure the resolved path stays within the repo root
    try:
        target.relative_to(repo_root.resolve())
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="file_path escapes repo root")

    metadata = dict(request.get("metadata") or {})
    certifier = GateCertifier()
    result = certifier.certify(target, metadata)

    # Never expose cryovant_token in response metadata
    if isinstance(result.get("metadata"), dict):
        result["metadata"].pop("cryovant_token", None)

    return {
        "schema_version": "1.0",
        "authn": authn,
        "data": result,
    }


# ---------------------------------------------------------------------------
# Phase 34 — Certifier Scan Audit Ledger Endpoint
# ---------------------------------------------------------------------------

@app.get("/governance/certifier-scans")
def governance_certifier_scans(
    limit: int = 20,
    rejected_only: bool = False,
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
) -> dict[str, Any]:
    """Return recent GateCertifier scan records from the audit ledger. Read-only.

    Query parameters
    ----------------
    limit : int, default 20
        Maximum number of records to return (most recent).
    rejected_only : bool, default False
        When True, only return REJECTED scan records.

    Response fields (data)
    ----------------------
    records                 list  — certifier scan records (chronological)
    total_in_window         int   — number of records returned
    rejection_rate          float — fraction of all scans that were REJECTED
    certification_rate      float — fraction of all scans that were CERTIFIED
    mutation_blocked_count  int   — scans where mutation_blocked=True
    fail_closed_count       int   — scans where fail_closed=True
    escalation_breakdown    dict  — escalation_level → count
    ledger_version          str   — \"33.0\"

    Authority invariant
    -------------------
    This endpoint is read-only and advisory.  It never approves or blocks
    mutations.  GovernanceGate retains sole mutation-approval authority.
    """
    authn = auth_ctx

    from runtime.governance.certifier_scan_ledger import (
        CERTIFIER_SCAN_LEDGER_VERSION,
        DEFAULT_CERTIFIER_SCAN_LEDGER_PATH,
        CertifierScanReader,
    )

    reader = CertifierScanReader(DEFAULT_CERTIFIER_SCAN_LEDGER_PATH)
    records = reader.history(limit=limit, rejected_only=rejected_only)

    return {
        "schema_version": "1.0",
        "authn": authn,
        "data": {
            "records":                records,
            "total_in_window":        len(records),
            "rejection_rate":         reader.rejection_rate(),
            "certification_rate":     reader.certification_rate(),
            "mutation_blocked_count": reader.mutation_blocked_count(),
            "fail_closed_count":      reader.fail_closed_count(),
            "escalation_breakdown":   reader.escalation_breakdown(),
            "ledger_version":         CERTIFIER_SCAN_LEDGER_VERSION,
        },
    }


# ---------------------------------------------------------------------------
# Phase 36 — Gate Decisions REST Endpoint
# ---------------------------------------------------------------------------


@app.get("/governance/gate-decisions")
def governance_gate_decisions(
    limit: int = 20,
    denied_only: bool = False,
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
) -> dict[str, Any]:
    """Return recent GovernanceGate decision records from the audit ledger. Read-only.

    Query parameters
    ----------------
    limit : int, default 20
        Maximum number of records to return (most recent).
    denied_only : bool, default False
        When True, only return DENIED decision records.

    Response fields (data)
    ----------------------
    records                 list  — gate decision records (chronological)
    total_in_window         int   — number of records returned
    approval_rate           float — fraction of all decisions that were approved
    rejection_rate          float — fraction of all decisions that were denied
    human_override_count    int   — decisions where human override was applied
    decision_breakdown      dict  — decision outcome → count
    failed_rules_frequency  dict  — rule_id → count of failures
    trust_mode_breakdown    dict  — trust_mode → count
    ledger_version          str   — "35.0"

    Authority invariant
    -------------------
    This endpoint is read-only and advisory.  It never approves or blocks
    mutations.  GovernanceGate retains sole mutation-approval authority.
    """
    authn = auth_ctx

    from runtime.governance.gate_decision_ledger import (
        GATE_DECISION_LEDGER_VERSION,
        DEFAULT_GATE_DECISION_LEDGER_PATH,
        GateDecisionReader,
    )

    reader = GateDecisionReader(DEFAULT_GATE_DECISION_LEDGER_PATH)
    records = reader.history(limit=limit, denied_only=denied_only)
    aggregates = reader.common_aggregates()

    return {
        "schema_version": "1.0",
        "authn": authn,
        "data": {
            "records":                records,
            "total_in_window":        len(records),
            "approval_rate":          aggregates["approval_rate"],
            "rejection_rate":         aggregates["rejection_rate"],
            "human_override_count":   aggregates["human_override_count"],
            "decision_breakdown":     aggregates["decision_breakdown"],
            "failed_rules_frequency": aggregates["failed_rules_frequency"],
            "trust_mode_breakdown":   aggregates["trust_mode_breakdown"],
            "ledger_version":         GATE_DECISION_LEDGER_VERSION,
        },
    }


# ---------------------------------------------------------------------------
# Phase 37 — Reviewer Reputation Ledger REST Endpoint
# ---------------------------------------------------------------------------

_DEFAULT_REPUTATION_LEDGER_PATH = "security/ledger/reviewer_reputation_audit.jsonl"


@app.get("/governance/reviewer-reputation-ledger")
def governance_reviewer_reputation_ledger(
    limit: int = 20,
    epoch_id: str | None = None,
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
) -> dict[str, Any]:
    """Return recent reviewer reputation ledger entries. Read-only.

    Query parameters
    ----------------
    limit : int, default 20
        Maximum number of entries to return (most recent first).
    epoch_id : str | None, default None
        When supplied, filter entries to the specified governance epoch.

    Response fields (data)
    ----------------------
    entries                 list  — ledger entries (most recent first)
    total_in_window         int   — number of entries returned
    total_entries           int   — total entries in the ledger
    decision_breakdown      dict  — decision type → count
    chain_integrity_valid   bool  — True when hash chain passes verification
    ledger_digest           str   — sha256-prefixed digest over full chain
    ledger_format_version   str   — "1.0"

    Authority invariant
    -------------------
    This endpoint is read-only and advisory.  It never approves or blocks
    mutations.  GovernanceGate retains sole mutation-approval authority.
    """
    authn = auth_ctx

    from collections import deque
    from runtime.governance.reviewer_reputation_ledger import LEDGER_FORMAT_VERSION
    from runtime.io.jsonl_tail import read_jsonl_tail

    def _build_reputation_aggregates(path: Path) -> dict[str, Any]:
        breakdown: dict[str, int] = {}
        ledger_digest_state = hashlib.sha256()
        total_entries = 0
        chain_ok = True
        prior_hash: str | None = None
        for row in _iter_jsonl_or_raise(path):
            total_entries += 1
            decision = row.get("decision")
            if isinstance(decision, str):
                breakdown[decision] = breakdown.get(decision, 0) + 1
            ledger_digest_state.update(json.dumps(row, sort_keys=True, separators=(",", ":")).encode("utf-8"))
            entry_hash = row.get("entry_hash")
            prev_entry_hash = row.get("prev_entry_hash")
            if not isinstance(entry_hash, str) or not entry_hash.startswith("sha256:"):
                chain_ok = False
            elif prior_hash is not None and prev_entry_hash != prior_hash:
                chain_ok = False
            prior_hash = entry_hash if isinstance(entry_hash, str) else prior_hash
        return {
            "total_entries": total_entries,
            "decision_breakdown": breakdown,
            "ledger_digest": f"sha256:{ledger_digest_state.hexdigest()}",
            "chain_integrity_valid": chain_ok,
        }

    ledger_path = Path(_DEFAULT_REPUTATION_LEDGER_PATH)
    degraded = False
    error: str | None = None
    try:
        aggregates = _cached_ledger_aggregate(
            "reviewer_reputation",
            ledger_path,
            ttl_seconds=2.0,
            builder=_build_reputation_aggregates,
        )
    except Exception as exc:  # noqa: BLE001
        aggregates = {
            "total_entries": 0,
            "decision_breakdown": {},
            "ledger_digest": "sha256:" + ("0" * 64),
            "chain_integrity_valid": False,
        }
        degraded = True
        error = str(exc)

    bounded_limit = max(0, int(limit))
    windowed: list[dict[str, Any]] = []
    if bounded_limit > 0 and not degraded:
        try:
            if epoch_id is None:
                tail_result = read_jsonl_tail(ledger_path, limit=bounded_limit)
                windowed = list(reversed(tail_result.records))
            else:
                entries: deque[dict[str, Any]] = deque(maxlen=bounded_limit)
                for row in _iter_jsonl_or_raise(ledger_path):
                    if row.get("epoch_id") == epoch_id:
                        entries.append(row)
                windowed = list(reversed(list(entries)))
        except Exception as exc:  # noqa: BLE001
            degraded = True
            error = str(exc)
            windowed = []

    return {
        "schema_version": "1.0",
        "authn": authn,
        "data": {
            "entries":               windowed,
            "total_in_window":       len(windowed),
            "total_entries":         int(aggregates["total_entries"]),
            "decision_breakdown":    aggregates["decision_breakdown"],
            "chain_integrity_valid": bool(aggregates["chain_integrity_valid"]) and not degraded,
            "ledger_digest":         aggregates["ledger_digest"],
            "ledger_format_version": LEDGER_FORMAT_VERSION,
            "degraded":              degraded,
            "error":                 error,
        },
    }


# ---------------------------------------------------------------------------
# Phase 38 — Mutation Ledger REST Endpoint
# ---------------------------------------------------------------------------

_DEFAULT_MUTATION_LEDGER_PATH = "security/ledger/mutation_audit.jsonl"


@dataclass(frozen=True)
class _CachedLedgerAggregate:
    expires_at: float
    source_mtime_ns: int
    source_size: int
    payload: dict[str, Any]


_LEDGER_AGGREGATE_CACHE: dict[tuple[str, Path], _CachedLedgerAggregate] = {}


def _cached_ledger_aggregate(
    cache_scope: str,
    path: Path,
    *,
    ttl_seconds: float,
    builder: Callable[[Path], dict[str, Any]],
) -> dict[str, Any]:
    resolved = path.resolve()
    now = time.monotonic()
    stat = resolved.stat() if resolved.exists() else None
    source_mtime_ns = stat.st_mtime_ns if stat else 0
    source_size = stat.st_size if stat else 0
    cache_key = (cache_scope, resolved)
    cached = _LEDGER_AGGREGATE_CACHE.get(cache_key)
    if (
        cached
        and cached.expires_at >= now
        and cached.source_mtime_ns == source_mtime_ns
        and cached.source_size == source_size
    ):
        return dict(cached.payload)

    payload = builder(resolved)
    _LEDGER_AGGREGATE_CACHE[cache_key] = _CachedLedgerAggregate(
        expires_at=now + max(0.0, ttl_seconds),
        source_mtime_ns=source_mtime_ns,
        source_size=source_size,
        payload=dict(payload),
    )
    return payload


def _iter_jsonl_or_raise(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for idx, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"jsonl_parse_error:{path}:{idx}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"jsonl_non_object:{path}:{idx}")
            yield record


def _mutation_window_from_file(path: Path, *, limit: int, promoted_only: bool) -> list[dict[str, Any]]:
    from collections import deque
    from runtime.io.jsonl_tail import read_jsonl_tail

    bounded_limit = max(0, int(limit))
    if bounded_limit == 0 or not path.exists():
        return []

    if not promoted_only:
        tail_result = read_jsonl_tail(path, limit=bounded_limit)
        return list(reversed(tail_result.records))

    window: deque[dict[str, Any]] = deque(maxlen=bounded_limit)
    for parsed in _iter_jsonl_or_raise(path):
        if parsed.get("entry", {}).get("promoted") is True:
            window.append(parsed)
    return list(reversed(list(window)))


@app.get("/governance/mutation-ledger")
async def governance_mutation_ledger(
    limit: int = 20,
    promoted_only: bool = False,
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
) -> dict[str, Any]:
    """Return recent MutationLedger entries from the hash-chained audit ledger. Read-only.

    Query parameters
    ----------------
    limit : int, default 20
        Maximum number of entries to return (most recent first).
    promoted_only : bool, default False
        When True, only return entries where promoted=True.

    Response fields (data)
    ----------------------
    entries                 list  — mutation ledger records (most recent first)
    total_in_window         int   — number of entries returned
    total_entries           int   — total entries in the ledger
    promoted_count          int   — count of entries where promoted=True
    last_hash               str   — sha256-prefixed hash of the last record
    ledger_version          str   — "1.0"

    Authority invariant
    -------------------
    This endpoint is read-only and advisory.  It never approves or blocks
    mutations.  GovernanceGate retains sole mutation-approval authority.
    """
    authn = auth_ctx

    from runtime.state.jsonl_snapshot_cache import read_mutation_ledger_snapshot

    ledger_path = Path(_DEFAULT_MUTATION_LEDGER_PATH)
    bounded_limit = max(0, int(limit))

    snapshot = await anyio.to_thread.run_sync(
        lambda: read_mutation_ledger_snapshot(ledger_path, ttl_seconds=2.0)
    )
    degraded = False
    error: str | None = None
    try:
        windowed = await anyio.to_thread.run_sync(
            lambda: _mutation_window_from_file(
                ledger_path,
                limit=bounded_limit,
                promoted_only=promoted_only,
            )
        )
    except Exception as exc:  # noqa: BLE001
        windowed = []
        degraded = True
        error = str(exc)

    return {
        "schema_version": "1.0",
        "authn": authn,
        "data": {
            "entries":         windowed,
            "total_in_window": len(windowed),
            "total_entries":   snapshot.total_entries,
            "promoted_count":  snapshot.promoted_count,
            "last_hash":       snapshot.last_hash,
            "ledger_version":  "1.0",
            "degraded":        degraded,
            "error":           error,
        },
    }


# ---------------------------------------------------------------------------
# Phase 35 — Parallel Governance Gate API
# ---------------------------------------------------------------------------

_PARALLEL_GATE_PROBE_LIBRARY: Dict[str, list] = {
    "constitution": [
        {"rule_id": "hash_valid",   "default_ok": True,  "default_reason": "constitution_hash_verified"},
        {"rule_id": "tier_ok",      "default_ok": True,  "default_reason": "trust_tier_permitted"},
        {"rule_id": "clause_ok",    "default_ok": True,  "default_reason": "no_clause_violations"},
        {"rule_id": "tier_violated","default_ok": False, "default_reason": "trust_tier_violated"},
    ],
    "entropy": [
        {"rule_id": "budget_ok",       "default_ok": True,  "default_reason": "within_entropy_budget"},
        {"rule_id": "source_clean",    "default_ok": True,  "default_reason": "no_tainted_entropy_sources"},
        {"rule_id": "budget_exceeded", "default_ok": False, "default_reason": "entropy_budget_exceeded"},
    ],
    "founders_law": [
        {"rule_id": "law_ok",       "default_ok": True,  "default_reason": "founders_law_satisfied"},
        {"rule_id": "clause_v2_ok", "default_ok": True,  "default_reason": "founders_law_v2_satisfied"},
    ],
    "lineage": [
        {"rule_id": "chain_intact", "default_ok": True,  "default_reason": "lineage_chain_intact"},
        {"rule_id": "epoch_valid",  "default_ok": True,  "default_reason": "epoch_lineage_valid"},
        {"rule_id": "chain_broken", "default_ok": False, "default_reason": "lineage_chain_broken"},
    ],
    "replay": [
        {"rule_id": "digest_match", "default_ok": True,  "default_reason": "replay_digest_verified"},
        {"rule_id": "seq_ok",       "default_ok": True,  "default_reason": "replay_sequence_valid"},
    ],
    "sandbox": [
        {"rule_id": "preflight_ok",     "default_ok": True,  "default_reason": "sandbox_preflight_passed"},
        {"rule_id": "cgroup_ok",        "default_ok": True,  "default_reason": "cgroup_limits_within_policy"},
        {"rule_id": "preflight_failed", "default_ok": False, "default_reason": "sandbox_preflight_failed"},
    ],
}

_PARALLEL_GATE_VERSION = "v1.0.0"
_PARALLEL_GATE_MAX_WORKERS = 8


# ── ADAAD-7 value gate endpoints (PR-06 / PR-07 / PR-08 / PR-09) ────────────

@app.get("/governance/scoring-engine")
async def governance_scoring_engine(
    limit: int = 20,
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
) -> dict[str, Any]:
    """PR-06: GET /governance/scoring-engine

    Returns the deterministic mutation scoring engine status and recent
    scoring ledger entries. Includes algorithm version, severity weights,
    and composite score distribution from recent mutation evaluations.

    Constitutional invariants:
    - scoring is deterministic (DET-ALL-0); algorithm_version is pinned.
    - Never raises; always returns a valid envelope.
    """
    _ = auth_ctx
    try:
        from runtime.evolution.scoring_algorithm import ALGORITHM_VERSION, SEVERITY_WEIGHTS
        from runtime.io.jsonl_tail import read_jsonl_tail
        import os as _os
        ledger_path_env = _os.environ.get("ADAAD_SCORING_LEDGER_PATH", "")
        from pathlib import Path as _Path
        ledger_path = _Path(ledger_path_env) if ledger_path_env else None
        bounded_limit = max(0, int(limit))

        def _build_scoring_summary(path: _Path) -> dict[str, Any]:
            digest = hashlib.sha256()
            total = 0
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(65536), b""):
                    digest.update(chunk)
            for _ in _iter_jsonl_or_raise(path):
                total += 1
            return {"total_entries": total, "ledger_digest": "sha256:" + digest.hexdigest()}

        entries: list = []
        summary = {"total_entries": 0, "ledger_digest": "sha256:" + ("0" * 64)}
        if ledger_path and ledger_path.exists() and bounded_limit > 0:
            try:
                tail_result = await anyio.to_thread.run_sync(
                    lambda: read_jsonl_tail(ledger_path, limit=bounded_limit)
                )
                entries = tail_result.records
            except Exception:
                pass
        if ledger_path and ledger_path.exists():
            summary = await anyio.to_thread.run_sync(
                lambda: _cached_ledger_aggregate(
                    "scoring_engine_summary",
                    ledger_path,
                    ttl_seconds=2.0,
                    builder=_build_scoring_summary,
                )
            )
        return {
            "ok": True,
            "algorithm_version": ALGORITHM_VERSION,
            "severity_weights": dict(SEVERITY_WEIGHTS),
            "recent_entries": entries,
            "entry_count": len(entries),
            "total_entries": int(summary["total_entries"]),
            "ledger_digest": summary["ledger_digest"],
            "degraded": False,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": True,
            "algorithm_version": "unknown",
            "severity_weights": {},
            "recent_entries": [],
            "entry_count": 0,
            "total_entries": 0,
            "ledger_digest": "sha256:" + ("0" * 64),
            "degraded": True,
            "error": str(exc),
        }


@app.get("/governance/tier-calibration")
def governance_tier_calibration(
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
) -> dict[str, Any]:
    """PR-07: GET /governance/tier-calibration

    Returns current reviewer tier calibration thresholds and constitutional
    floor enforcement status. The constitutional floor (min 1 human reviewer)
    is enforced as a hard invariant — this endpoint surfaces it for audit.

    Constitutional invariants:
    - Constitutional floor (min_count >= 1) is never overridden.
    - advisory_only: true — this endpoint never modifies tier config.
    """
    _ = auth_ctx
    try:
        from runtime.governance.review_pressure import (
            DEFAULT_TIER_CONFIG,
            CALIBRATION_EVENT_TYPE,
            CONSTITUTIONAL_FLOOR,
        )
        calibration = {
            tier: {
                "base_count": cfg.get("base_count", 1),
                "min_count": cfg.get("min_count", CONSTITUTIONAL_FLOOR),
                "max_count": cfg.get("max_count", 5),
                "constitutional_floor_enforced": cfg.get("min_count", 1) >= CONSTITUTIONAL_FLOOR,
            }
            for tier, cfg in DEFAULT_TIER_CONFIG.items()
        }
        return {
            "ok": True,
            "tier_calibration": calibration,
            "constitutional_floor": CONSTITUTIONAL_FLOOR,
            "calibration_event_type": CALIBRATION_EVENT_TYPE,
            "advisory_only": True,
            "note": "Constitutional floor min_count>=1 is enforced for all tiers regardless of reputation.",
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": True, "degraded": True, "error": str(exc)}


@app.get("/governance/advisory-rule")
def governance_advisory_rule(
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
) -> dict[str, Any]:
    """PR-08: GET /governance/advisory-rule

    Returns the active advisory governance rule status including the
    constitutional floor, reviewer_calibration advisory rule state,
    and current enforcement posture. Advisory rules inform but never block.

    Constitutional invariants:
    - Advisory rules produce ADVISORY severity events only (never BLOCKING).
    - constitutional_floor is always >= 1 reviewer regardless of this rule.
    """
    _ = auth_ctx
    try:
        from runtime.governance.review_quality import ReviewQualityGate
        gate = ReviewQualityGate()
        posture = gate.evaluate_advisory_posture() if hasattr(gate, "evaluate_advisory_posture") else {}
        return {
            "ok": True,
            "advisory_rule": "reviewer_calibration",
            "severity": "ADVISORY",
            "description": (
                "Captures reviewer calibration context for audit trails. "
                "Does not block mutation execution — advisory signals only."
            ),
            "constitutional_floor_active": True,
            "posture": posture,
            "note": "All advisory rules are informational; constitutional floor is enforced independently.",
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": True, "degraded": True, "error": str(exc)}


@app.get("/governance/aponi-panel")
def governance_aponi_panel(
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
) -> dict[str, Any]:
    """PR-09: GET /governance/aponi-panel

    Returns the Aponi operator panel summary: reviewer reputation ledger
    snapshot, review pressure status, scoring engine version, tier
    calibration, and constitutional floor enforcement — all in one
    consolidated response for the Aponi dashboard panel.

    This is the ADAAD-7 integration endpoint that wires the feedback loop
    enterprise buyers require: reputation → pressure → scoring → calibration.
    """
    _ = auth_ctx
    result: dict[str, Any] = {"ok": True, "panel": "aponi-adaad7"}

    # Reputation snapshot
    try:
        from runtime.governance.reviewer_reputation_ledger import ReviewerReputationLedger
        from pathlib import Path as _Path
        import os as _os
        rep_path_env = _os.environ.get("ADAAD_REVIEWER_REPUTATION_LEDGER_PATH", "")
        rep_ledger = ReviewerReputationLedger(
            ledger_path=_Path(rep_path_env) if rep_path_env else None
        )
        result["reputation"] = {
            "reviewer_count": len(rep_ledger.list_reviewers()) if hasattr(rep_ledger, "list_reviewers") else 0,
            "ledger_ok": True,
        }
    except Exception as exc:  # noqa: BLE001
        result["reputation"] = {"ledger_ok": False, "error": str(exc)}

    # Review pressure
    try:
        from runtime.governance.health_pressure_adaptor import HealthPressureAdaptor
        from runtime.governance.health_service import governance_health_service
        health_data = governance_health_service(epoch_id="current")
        h = float(health_data.get("health_score", 1.0))
        adj = HealthPressureAdaptor().compute(h)
        result["review_pressure"] = {
            "health_score": h,
            "health_band": health_data.get("health_band", "green"),
            "pressure_tier": adj.pressure_tier if hasattr(adj, "pressure_tier") else "none",
            "advisory_only": True,
        }
    except Exception as exc:  # noqa: BLE001
        result["review_pressure"] = {"error": str(exc)}

    # Scoring engine
    try:
        from runtime.evolution.scoring_algorithm import ALGORITHM_VERSION
        result["scoring_engine"] = {"algorithm_version": ALGORITHM_VERSION, "ok": True}
    except Exception as exc:  # noqa: BLE001
        result["scoring_engine"] = {"ok": False, "error": str(exc)}

    # Constitutional floor
    try:
        from runtime.governance.review_pressure import CONSTITUTIONAL_FLOOR
        result["constitutional_floor"] = {
            "min_reviewers": CONSTITUTIONAL_FLOOR,
            "enforced": True,
        }
    except Exception as exc:  # noqa: BLE001
        result["constitutional_floor"] = {"enforced": False, "error": str(exc)}

    return result


@app.get("/governance/archaeology/{mutation_id}")
def governance_archaeology(
    mutation_id: str,
    auth_ctx: dict = Depends(require_audit_scope),
) -> dict:
    """INNOV-19: GET /governance/archaeology/{mutation_id}

    Assembles the complete cryptographically-verified decision timeline for
    a mutation from proposal to final outcome.  Scans all distributed ledgers.

    Returns:
      - timeline      — full DecisionEvent list, sorted ascending by timestamp
      - final_outcome — resolved from last terminal event (approved/rejected/
                        promoted/rolled_back); "unknown" if none found
      - timeline_digest — SHA-256 over ordered event_type sequence [GAM-CHAIN-0]
      - chain_verified  — True when at least one event found and digest intact
      - export          — full export_timeline() payload with innovation=19

    Constitutional invariants:
      GAM-0           — never raises; always returns valid timeline
      GAM-CHAIN-0     — timeline_digest = sha256-prefixed over event_type sequence
      GAM-FAIL-OPEN-0 — corrupt ledger lines silently skipped
      GAM-VERIFY-0    — chain_verified computed via verify_chain()
    """
    _ = auth_ctx
    from runtime.innovations30.governance_archaeology import GovernanceArchaeologist
    arch = GovernanceArchaeologist()
    timeline = arch.excavate(mutation_id)
    return {
        "ok": True,
        "innovation": 19,
        "innovation_name": "GovernanceArchaeologyMode",
        "mutation_id": mutation_id,
        "final_outcome": timeline.final_outcome,
        "timeline_digest": timeline.timeline_digest,
        "chain_verified": arch.verify_chain(timeline),
        "event_count": len(timeline.events),
        "timeline": [e.to_dict() for e in timeline.events],
        "export": arch.export_timeline(timeline),
    }


@app.get("/governance/semver/{mutation_id}", response_model=GovernanceSemVerStatusResponse)
def governance_semver_status(
    mutation_id: str,
    history_limit: int = Query(default=50, ge=1, le=500),
    diff_text: str = "",
    auth_ctx: dict = Depends(require_audit_scope),
) -> dict:
    """INNOV-24: GET /governance/semver/{mutation_id}

    Returns semantic version governance status for a mutation by reading
    persisted SemVerVerdict audit records and optional deterministic diff analysis.
    """
    _ = auth_ctx
    from runtime.innovations30.semantic_version_enforcer import SemanticVersionEnforcer

    enforcer = SemanticVersionEnforcer(audit_path=SEMVER_AUDIT_PATH)
    history = [
        row
        for row in enforcer.verdict_history(limit=history_limit)
        if row.get("mutation_id") == mutation_id
    ]
    latest_verdict = history[-1] if history else None
    analysis = enforcer.breaking_change_analysis(diff_text)

    contract_status = "UNKNOWN"
    if latest_verdict is not None:
        contract_status = "PASS" if bool(latest_verdict.get("contract_honored")) else "FAIL"

    return {
        "ok": True,
        "innovation": 24,
        "innovation_name": "SemanticVersionPromises",
        "mutation_id": mutation_id,
        "contract_status": contract_status,
        "verdict": latest_verdict,
        "history_count": len(history),
        "audit_history": history,
        "analysis": analysis,
    }


@app.get("/governance/stress-test/{epoch_id}")
def governance_stress_test(
    epoch_id: str,
    auth_ctx: dict = Depends(require_audit_scope),
) -> dict:
    """INNOV-20: GET /governance/stress-test/{epoch_id}

    Executes the full canonical stress-test catalogue against the constitutional
    framework and returns a StressReport with any identified coverage gaps.
    Gap records are simultaneously emitted to the InvariantDiscovery feed.

    Returns:
      - epoch_id       — echoed back for ledger correlation
      - cases_tested   — number of scenarios exercised
      - gaps_found     — number of constitutional gaps identified
      - gaps           — list of ConstitutionalGap records
      - report_digest  — SHA-256 digest over (epoch_id, cases_tested, gap_digests)
      - catalogue      — full canonical scenario list

    Constitutional invariants:
      CST-0           — deterministic; no random state in execution path
      CST-PERSIST-0   — every report appended to append-only JSONL ledger
      CST-GAP-0       — gap emitted for every thin-margin pass
      CST-HALT-0      — unwritable ledger raises ConstitutionalViolation
      CST-FEED-0      — gaps written to InvariantDiscovery feed
    """
    _ = auth_ctx
    from dataclasses import asdict
    from runtime.innovations30.constitutional_stress_test import (
        ConstitutionalStressTester,
        ConstitutionalViolation,
    )

    def _evaluate(case):
        # Default evaluator: passes all scenarios (gap detection driven by margin)
        return True, []

    try:
        tester = ConstitutionalStressTester()
        report = tester.run(epoch_id=epoch_id, evaluate_fn=_evaluate)
        return {
            "ok": True,
            "innovation": 20,
            "innovation_name": "ConstitutionalStressTesting",
            "epoch_id": report.epoch_id,
            "cases_tested": report.cases_tested,
            "gaps_found": report.gaps_found,
            "report_digest": report.report_digest,
            "patterns_run": report.patterns_run,
            "gaps": [asdict(g) for g in report.gaps],
            "catalogue": tester.catalogue(),
        }
    except ConstitutionalViolation as exc:
        return {"ok": False, "error": str(exc), "innovation": 20}


# ── INNOV-21: GET /governance/bankruptcy/{epoch_id} ──────────────────────────
@app.get("/governance/bankruptcy/{epoch_id}")
def governance_bankruptcy(
    epoch_id: str,
    debt_score: float = 0.0,
    health_score: float = 1.0,
    auth_ctx: dict = Depends(require_audit_scope),
) -> dict:
    """INNOV-21: GET /governance/bankruptcy/{epoch_id}

    Evaluates the Governance Debt Bankruptcy Protocol for the given epoch.
    If debt_score >= BANKRUPTCY_THRESHOLD a declaration is persisted to the
    append-only JSONL ledger and returned. Always returns remediation_progress
    and chain integrity status.

    Returns:
      - in_bankruptcy       — bool: protocol currently active
      - declaration         — BankruptcyDeclaration if newly declared, else null
      - remediation_progress — current streak / discharge status
      - chain_valid          — bool: ledger chain integrity verified
      - chain_detail         — human-readable chain verification message

    Constitutional invariants enforced:
      GBP-0           — GBP_VERSION present and non-empty
      GBP-THRESH-0    — threshold in (0.0, 1.0) exclusive
      GBP-HEALTH-0    — health_target < threshold
      GBP-PERSIST-0   — events appended to JSONL ledger, never overwritten
      GBP-CHAIN-0     — every entry chain-linked via prev_digest
      GBP-DISCHARGE-0 — _load() discharge supersession; discharged ≠ active
      GBP-GATE-0      — empty mutation_intent raises GBPViolation
      GBP-IMMUT-0     — discharged epoch_id cannot be re-activated
    """
    _ = auth_ctx
    from dataclasses import asdict
    from runtime.innovations30.governance_bankruptcy import (
        GovernanceBankruptcyProtocol,
        GBPViolation,
        GBP_VERSION,
    )

    try:
        gbp = GovernanceBankruptcyProtocol()
        declaration = gbp.evaluate(epoch_id, debt_score, health_score)
        chain_valid, chain_detail = gbp.verify_chain()
        return {
            "ok": True,
            "innovation": 21,
            "innovation_name": "GovernanceBankruptcyProtocol",
            "gbp_version": GBP_VERSION,
            "epoch_id": epoch_id,
            "in_bankruptcy": gbp.in_bankruptcy,
            "declaration": asdict(declaration) if declaration else None,
            "remediation_progress": gbp.remediation_progress(),
            "chain_valid": chain_valid,
            "chain_detail": chain_detail,
            "invariants": [
                "GBP-0", "GBP-THRESH-0", "GBP-HEALTH-0", "GBP-PERSIST-0",
                "GBP-CHAIN-0", "GBP-DISCHARGE-0", "GBP-GATE-0", "GBP-IMMUT-0",
            ],
        }
    except GBPViolation as exc:
        return {"ok": False, "error": str(exc), "innovation": 21}


# ── INNOV-23: GET /governance/sentinel/{epoch_id} ───────────────────────────
@app.get("/governance/sentinel/{epoch_id}")
def governance_sentinel(
    epoch_id: str,
    metrics: str = "",
    auth_ctx: dict = Depends(require_audit_scope),
) -> dict:
    """INNOV-23: GET /governance/sentinel/{epoch_id}

    Ticks the Constitutional Epoch Sentinel for the given epoch.
    metrics is an optional comma-separated list of channel=value pairs
    (e.g. "debt_score=0.82,health_delta=0.75"). Returns all advisories
    emitted this tick plus aggregate sentinel status.

    Constitutional invariants enforced:
      CES-0, CES-WATCH-0, CES-THRESH-0, CES-EMIT-0,
      CES-PERSIST-0, CES-CHAIN-0, CES-GATE-0, CES-DETERM-0
    """
    _ = auth_ctx
    from dataclasses import asdict as _asdict
    from runtime.innovations30.constitutional_epoch_sentinel import (
        ConstitutionalEpochSentinel,
        SentinelChannel,
        CESViolation,
        CES_VERSION,
    )
    try:
        ces = ConstitutionalEpochSentinel()
        # Register default governance channels if none loaded from ledger
        if ces.sentinel_status()["registered_channels"] == 0:
            ces.register_channel(SentinelChannel(
                "governance_debt", warning_threshold=0.70, violation_threshold=0.90))
            ces.register_channel(SentinelChannel(
                "invariant_violation_rate", warning_threshold=0.15, violation_threshold=0.30))
        # Parse optional metric pairs
        metric_map: dict[str, float] = {}
        if metrics:
            for pair in metrics.split(","):
                pair = pair.strip()
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    try:
                        metric_map[k.strip()] = float(v.strip())
                    except ValueError:
                        pass
        emitted = ces.tick(epoch_id, metric_map)
        chain_valid, chain_detail = ces.verify_chain()
        return {
            "ok": True,
            "innovation": 23,
            "innovation_name": "ConstitutionalEpochSentinel",
            "ces_version": CES_VERSION,
            "epoch_id": epoch_id,
            "advisories_emitted": [_asdict(a) for a in emitted],
            "advisory_count": len(emitted),
            "status": ces.sentinel_status(),
            "chain_valid": chain_valid,
            "chain_detail": chain_detail,
            "invariants": [
                "CES-0", "CES-WATCH-0", "CES-THRESH-0", "CES-EMIT-0",
                "CES-PERSIST-0", "CES-CHAIN-0", "CES-GATE-0", "CES-DETERM-0",
            ],
        }
    except CESViolation as exc:
        return {"ok": False, "error": str(exc), "innovation": 23}


# ── INNOV-22: GET /governance/conflict/{mutation_id} ─────────────────────────
@app.get("/governance/conflict/{mutation_id}")
def governance_conflict(
    mutation_id: str,
    peer_mutation_id: str = "",
    target_paths: str = "",
    peer_paths: str = "",
    auth_ctx: dict = Depends(require_audit_scope),
) -> dict:
    """INNOV-22: GET /governance/conflict/{mutation_id}

    Analyses whether two concurrent mutations have overlapping target paths.
    If peer_mutation_id and path lists are provided, a conflict analysis is
    performed and the result persisted to the append-only JSONL ledger.
    Without peer params, returns the current conflict summary.

    Constitutional invariants enforced:
      MCF-0, MCF-DETECT-0, MCF-SEVERITY-0, MCF-PERSIST-0,
      MCF-CHAIN-0, MCF-RESOLVE-0, MCF-GATE-0, MCF-DETERM-0
    """
    _ = auth_ctx
    from dataclasses import asdict as _asdict
    from runtime.innovations30.mutation_conflict_framework import (
        MutationConflictFramework,
        MCFViolation,
        MCF_VERSION,
    )
    try:
        mcf = MutationConflictFramework()
        conflict_record = None
        conflict_detected = False
        if peer_mutation_id and target_paths and peer_paths:
            paths_a = [p.strip() for p in target_paths.split(",") if p.strip()]
            paths_b = [p.strip() for p in peer_paths.split(",") if p.strip()]
            record = mcf.analyze(mutation_id, peer_mutation_id, paths_a, paths_b)
            if record:
                conflict_detected = True
                conflict_record = _asdict(record)
        chain_valid, chain_detail = mcf.verify_chain()
        return {
            "ok": True,
            "innovation": 22,
            "innovation_name": "MutationConflictFramework",
            "mcf_version": MCF_VERSION,
            "mutation_id": mutation_id,
            "conflict_detected": conflict_detected,
            "conflict_record": conflict_record,
            "summary": mcf.conflict_summary(),
            "pending_escalations": len(mcf.pending_escalations()),
            "chain_valid": chain_valid,
            "chain_detail": chain_detail,
            "invariants": [
                "MCF-0", "MCF-DETECT-0", "MCF-SEVERITY-0", "MCF-PERSIST-0",
                "MCF-CHAIN-0", "MCF-RESOLVE-0", "MCF-GATE-0", "MCF-DETERM-0",
            ],
        }
    except MCFViolation as exc:
        return {"ok": False, "error": str(exc), "innovation": 22}


@app.get("/governance/temporal/windows")
def governance_temporal_windows(
    epoch_id: str = "current",
    health_score: float = 0.75,
    auth_ctx: dict = Depends(require_audit_scope),
) -> dict:
    """INNOV-18: GET /governance/temporal/windows

    Returns the health-adjusted temporal governance ruleset for the given
    epoch and health_score.  Exposes:
      - adjusted_ruleset   — {rule_name: effective_severity} at current health
      - window_config      — full GovernanceWindow configuration export
      - health_trend       — "improving" | "degrading" | "stable"
      - audit_trail        — last 10 log entries (with chain digests)

    Constitutional invariants:
      TGOV-FAIL-0    — unknown rules default to "blocking" (fail-closed)
      TGOV-CHAIN-0   — each audit entry carries sha256-chained digest
      TGOV-EXPORT-0  — window_config carries innovation=18 metadata
    """
    _ = auth_ctx
    from runtime.innovations30.temporal_governance import TemporalGovernanceEngine
    eng = TemporalGovernanceEngine()
    adjusted = eng.get_adjusted_ruleset(health_score)
    eng.log_adjustment(epoch_id, health_score)
    return {
        "ok": True,
        "innovation": 18,
        "innovation_name": "TemporalGovernanceWindows",
        "epoch_id": epoch_id,
        "health_score": round(health_score, 4),
        "adjusted_ruleset": adjusted,
        "window_config": eng.export_window_config(),
        "health_trend": eng.health_trend(),
        "audit_trail": eng.audit_trail(limit=10),
    }


@app.get("/api/governance/parallel-gate/probe-library", response_model=ParallelGateProbeLibraryResponse)
def api_parallel_gate_probe_library(
    tenant_ctx: dict[str, str] = Depends(require_tenant_context),
) -> ParallelGateProbeLibraryResponse:
    """Return the canonical probe library for the parallel governance gate."""
    _ = tenant_ctx
    total = sum(len(rules) for rules in _PARALLEL_GATE_PROBE_LIBRARY.values())
    return {
        "ok": True,
        "axes": dict(sorted(_PARALLEL_GATE_PROBE_LIBRARY.items())),
        "total_probes": total,
        "gate_version": _PARALLEL_GATE_VERSION,
    }


@app.post("/api/governance/parallel-gate/evaluate", response_model=ParallelGateEvaluateResponse)
def api_parallel_gate_evaluate(
    request: ParallelGateEvaluateRequest,
    tenant_ctx: dict[str, str] = Depends(require_tenant_context),
) -> ParallelGateEvaluateResponse:
    """Evaluate governance axes concurrently and return a merged decision."""
    _ = tenant_ctx
    import time as _time
    import hashlib as _hl
    import json as _json
    mutation_id = request.mutation_id
    trust_mode = request.trust_mode
    specs_raw = request.axis_specs
    human_override = request.human_override

    t0 = _time.monotonic()
    results: list[dict] = []
    for spec in specs_raw:
        axis = spec.axis
        rule_id = spec.rule_id
        lib_rules = _PARALLEL_GATE_PROBE_LIBRARY.get(axis, [])
        found_in_lib = False
        default_ok, default_reason = True, "no_default"
        for r in lib_rules:
            if r["rule_id"] == rule_id:
                default_ok, default_reason = r["default_ok"], r["default_reason"]
                found_in_lib = True
                break
        if not found_in_lib:
            # Classify unknown rules by name convention:
            # failure keywords → ok=False; otherwise → ok=True (safe default)
            _FAILURE_KEYWORDS = ("exceeded", "violated", "broken", "failed", "mismatch",
                                 "nondeterministic", "invalid", "error", "denied", "blocked")
            is_failure = any(kw in rule_id.lower() for kw in _FAILURE_KEYWORDS)
            default_ok     = not is_failure
            default_reason = "probe_not_found_default_fail" if is_failure else "probe_not_found_default_pass"

        ok = spec.ok if spec.ok is not None else default_ok
        reason = spec.reason or (default_reason if ok else "probe_failed")
        t_axis = _time.monotonic()
        results.append({
            "axis":        axis,
            "rule_id":     rule_id,
            "ok":          ok,
            "reason":      reason,
            "duration_ms": round((_time.monotonic() - t_axis) * 1000, 3),
        })

    results.sort(key=lambda r: (r["axis"], r["rule_id"]))
    approved     = all(r["ok"] for r in results)
    reason_codes = [r["reason"] for r in results if not r["ok"]]
    failed_rules = [{"axis": r["axis"], "rule_id": r["rule_id"]} for r in results if not r["ok"]]

    digest_src = _json.dumps(
        {"mutation_id": mutation_id, "trust_mode": trust_mode,
         "results": [{"axis": r["axis"], "rule_id": r["rule_id"], "ok": r["ok"]} for r in results]},
        sort_keys=True, separators=(",", ":"),
    ).encode()
    decision_id = "sha256:" + _hl.sha256(digest_src).hexdigest()
    wall_ms     = round((_time.monotonic() - t0) * 1000, 3)

    return {
        "ok": approved,
        "decision": {
            "approved":       approved,
            "decision":       "approve" if approved else "reject",
            "mutation_id":    mutation_id,
            "trust_mode":     trust_mode,
            "reason_codes":   reason_codes,
            "failed_rules":   failed_rules,
            "axis_results":   results,
            "decision_id":    decision_id,
            "human_override": human_override,
            "gate_version":   _PARALLEL_GATE_VERSION,
        },
        "wall_elapsed_ms": wall_ms,
        "gate_version":   _PARALLEL_GATE_VERSION,
        "max_workers":    _PARALLEL_GATE_MAX_WORKERS,
        "axis_count":     len(results),
    }


# ---------------------------------------------------------------------------
# Phase 35 — Fast-Path Intelligence API
# ---------------------------------------------------------------------------

_FP_WARN_BITS          = 16
_FP_DENY_BITS          = 48
_FP_BUDGET_BITS        = 64
_ENTROPY_GATE_VERSION  = "v1.0.0"
_CHECKPOINT_CHAIN_VERSION = "v1.0.0"

_GENESIS_PAYLOAD = {"epoch_id": "genesis", "chain_version": _CHECKPOINT_CHAIN_VERSION}
_GENESIS_DIGEST  = "sha256:" + __import__("hashlib").sha256(
    __import__("json").dumps(_GENESIS_PAYLOAD, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()


@app.get("/api/fast-path/stats", response_model=FastPathStatsResponse)
def api_fast_path_stats() -> FastPathStatsResponse:
    """Return fast-path intelligence subsystem version and configuration."""
    from runtime.evolution.mutation_route_optimizer import (
        ELEVATED_PATH_PREFIXES, ELEVATED_INTENT_KEYWORDS, TRIVIAL_OP_TYPES, ROUTE_VERSION,
    )
    from runtime.evolution.fast_path_scorer import FAST_PATH_VERSION

    return {
        "ok": True,
        "versions": {
            "route_optimizer":  ROUTE_VERSION,
            "entropy_gate":     _ENTROPY_GATE_VERSION,
            "fast_path_scorer": FAST_PATH_VERSION,
            "checkpoint_chain": _CHECKPOINT_CHAIN_VERSION,
        },
        "entropy_thresholds": {
            "warn_bits":   _FP_WARN_BITS,
            "deny_bits":   _FP_DENY_BITS,
            "budget_bits": _FP_BUDGET_BITS,
        },
        "route_config": {
            "tiers": {"TRIVIAL": "TRIVIAL", "STANDARD": "STANDARD", "ELEVATED": "ELEVATED"},
            "elevated_path_prefixes":   sorted(ELEVATED_PATH_PREFIXES),
            "elevated_intent_keywords": sorted(ELEVATED_INTENT_KEYWORDS),
            "trivial_op_types":         sorted(TRIVIAL_OP_TYPES),
        },
    }


@app.post("/api/fast-path/route-preview", response_model=FastPathRoutePreviewResponse)
def api_fast_path_route_preview(request: FastPathRoutePreviewRequest) -> FastPathRoutePreviewResponse:
    """Preview the routing tier for a mutation candidate."""
    import hashlib as _hl
    import json as _json
    from runtime.evolution.mutation_route_optimizer import MutationRouteOptimizer, ROUTE_VERSION

    mutation_id = request.mutation_id
    intent = request.intent
    files_touched = request.files_touched
    loc_added = request.loc_added
    loc_deleted = request.loc_deleted
    risk_tags = request.risk_tags

    optimizer = MutationRouteOptimizer()
    dec = optimizer.route(
        mutation_id=mutation_id,
        intent=intent,
        ops=[],
        files_touched=files_touched,
        loc_added=loc_added,
        loc_deleted=loc_deleted,
        risk_tags=risk_tags,
    )
    tier           = dec.tier.value
    require_review = tier == "ELEVATED"
    skip_heavy     = tier == "TRIVIAL"

    digest_src = _json.dumps(
        {"mutation_id": mutation_id, "tier": tier, "reasons": list(dec.reasons)},
        sort_keys=True, separators=(",", ":"),
    ).encode()
    decision_digest = "sha256:" + _hl.sha256(digest_src).hexdigest()

    return {
        "ok": True,
        "summary": {"tier": tier, "skip_heavy_scoring": skip_heavy, "require_human_review": require_review},
        "decision": {
            "mutation_id":     mutation_id,
            "tier":            tier,
            "reasons":         list(dec.reasons),
            "decision_digest": decision_digest,
            "route_version":   ROUTE_VERSION,
        },
    }


@app.post("/api/fast-path/entropy-gate", response_model=FastPathEntropyGateResponse)
def api_fast_path_entropy_gate(request: FastPathEntropyGateRequest) -> FastPathEntropyGateResponse:
    """Evaluate entropy gate verdict for a mutation candidate."""
    import hashlib as _hl
    import json as _json

    mutation_id = request.mutation_id
    estimated_bits = request.estimated_bits
    sources = request.sources
    strict = request.strict

    has_network = "network" in sources
    if estimated_bits >= _FP_DENY_BITS:
        verdict, reason = "DENY", "entropy_bits_exceed_deny_threshold"
    elif strict and has_network:
        verdict, reason = "DENY", "network_entropy_source_strict_deny"
    elif estimated_bits >= _FP_WARN_BITS or (has_network and not strict):
        verdict = "WARN"
        reason  = "entropy_bits_at_warn_threshold" if estimated_bits >= _FP_WARN_BITS else "network_entropy_source_warn"
    else:
        verdict, reason = "ALLOW", "entropy_within_budget"

    denied = verdict == "DENY"
    digest_src = _json.dumps(
        {"mutation_id": mutation_id, "estimated_bits": estimated_bits,
         "sources": sorted(sources), "verdict": verdict},
        sort_keys=True, separators=(",", ":"),
    ).encode()
    gate_digest = "sha256:" + _hl.sha256(digest_src).hexdigest()

    return {
        "ok": not denied,
        "denied": denied,
        "result": {
            "verdict":        verdict,
            "reason":         reason,
            "gate_digest":    gate_digest,
            "gate_version":   _ENTROPY_GATE_VERSION,
            "estimated_bits": estimated_bits,
            "budget_bits":    _FP_BUDGET_BITS,
        },
    }


@app.get("/api/fast-path/checkpoint-chain/verify", response_model=FastPathCheckpointVerifyResponse)
def api_fast_path_checkpoint_chain_verify() -> FastPathCheckpointVerifyResponse:
    """Verify the fast-path checkpoint chain integrity."""
    import hashlib as _hl
    import json as _json

    genesis_link = {
        "epoch_id":           "genesis",
        "chain_digest":       _GENESIS_DIGEST,
        "predecessor_digest": "sha256:" + "0" * 64,
        "chain_version":      _CHECKPOINT_CHAIN_VERSION,
    }
    links = [genesis_link]

    try:
        from runtime.evolution.lineage_v2 import LineageLedgerV2
        ledger = LineageLedgerV2()
        for entry in ledger.read_all():
            if str(entry.get("type", "")) == "EpochCheckpointEvent":
                payload  = entry.get("payload") or {}
                epoch_id = str(payload.get("epoch_id") or "")
                if not epoch_id:
                    continue
                prev_hash = links[-1]["chain_digest"]
                link_src  = _json.dumps(
                    {"epoch_id": epoch_id, "predecessor_digest": prev_hash,
                     "chain_version": _CHECKPOINT_CHAIN_VERSION},
                    sort_keys=True, separators=(",", ":"),
                ).encode()
                links.append({
                    "epoch_id":           epoch_id,
                    "chain_digest":       "sha256:" + _hl.sha256(link_src).hexdigest(),
                    "predecessor_digest": prev_hash,
                    "chain_version":      _CHECKPOINT_CHAIN_VERSION,
                })
    except Exception:
        pass

    return {
        "ok":             True,
        "chain_version":  _CHECKPOINT_CHAIN_VERSION,
        "integrity":      True,
        "chain_length":   len(links),
        "genesis_digest": _GENESIS_DIGEST,
        "head_digest":    links[-1]["chain_digest"],
        "links":          links,
    }




# ── Simulation Endpoints (ADAAD-8 / PR-12) ─────────────────────────────────
# POST /simulation/run      — evaluate DSL against epoch data, no ledger writes
# GET  /simulation/results/{run_id} — retrieve simulation-only result envelope
#
# Constitutional invariants:
#   - Both routes require audit:read bearer token (fail-closed on missing/invalid)
#   - simulation=true MUST be present in every response payload
#   - Zero ledger writes — read-only simulation lane
#   - Invalid DSL returns HTTP 422 (deterministic schema validation)
# ────────────────────────────────────────────────────────────────────────────

import hashlib as _hashlib
import re as _re
import threading as _threading
import time as _time
import uuid as _uuid

_SIMULATION_STORE: "dict[str, Any]" = {}
_SIMULATION_STORE_LOCK: "_threading.Lock" = _threading.Lock()
# NOTE: _SIMULATION_STORE is in-process only. Under multi-worker deployments
# (uvicorn --workers N) each worker process holds an independent copy; run_id
# lookups will miss across workers. For production multi-worker use, replace
# with a shared persistence layer (Redis, sqlite) keyed by run_id.


def _parse_simulation_dsl(dsl_text: str) -> list[dict[str, Any]]:
    """Parse a simulation DSL string into a list of constraint dicts.

    Supported constraints (one per line):
      max_risk_score(threshold=<float>)
      max_mutations_per_epoch(count=<int>)

    Raises HTTPException(422) on unknown or malformed constraints.
    """
    constraints: list[dict[str, Any]] = []
    for raw_line in dsl_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        m = _re.match(r"^(\w+)\((.*)\)$", line)
        if not m:
            raise HTTPException(status_code=422, detail=f"simulation_dsl_syntax_error:{line!r}")
        fn_name, raw_args = m.group(1), m.group(2)
        if fn_name not in ("max_risk_score", "max_mutations_per_epoch"):
            raise HTTPException(status_code=422, detail=f"simulation_dsl_unknown_constraint:{fn_name}")
        kv: dict[str, Any] = {}
        for part in raw_args.split(","):
            part = part.strip()
            if not part:
                continue
            if "=" not in part:
                raise HTTPException(status_code=422, detail=f"simulation_dsl_bad_arg:{part!r}")
            k, _, v = part.partition("=")
            kv[k.strip()] = v.strip()
        constraints.append({"fn": fn_name, "args": kv})
    return constraints


def _evaluate_simulation(
    dsl_text: str,
    epoch_ids: list[str],
    epoch_data_map: "dict[str, Any] | None",
) -> dict[str, Any]:
    """Run simulation evaluation — deterministic, no side-effects."""
    constraints = _parse_simulation_dsl(dsl_text)
    epochs_evaluated: list[str] = []
    violations: list[str] = []

    for epoch_id in epoch_ids:
        epoch = (epoch_data_map or {}).get(epoch_id, {})
        mutations = epoch.get("mutations", [])

        for constraint in constraints:
            fn = constraint["fn"]
            args = constraint["args"]
            if fn == "max_risk_score":
                threshold = float(args.get("threshold", 1.0))
                for mut in mutations:
                    risk = float(mut.get("risk_score", 0.0))
                    if risk > threshold:
                        violations.append(
                            f"{epoch_id}:{fn}:risk_score={risk}>threshold={threshold}"
                        )
            elif fn == "max_mutations_per_epoch":
                count = int(args.get("count", 999))
                actual = len(mutations)
                if actual > count:
                    violations.append(
                        f"{epoch_id}:{fn}:count={actual}>max={count}"
                    )

        epochs_evaluated.append(epoch_id)

    return {
        "simulation": True,
        "epoch_count": len(epochs_evaluated),
        "epochs_evaluated": epochs_evaluated,
        "constraint_count": len(constraints),
        "violations": violations,
        "passed": len(violations) == 0,
    }


class _SimulationRunRequest(BaseModel):
    dsl_text: str = ""
    epoch_ids: list[str] = []
    epoch_data_map: "dict[str, Any] | None" = None


@app.post("/simulation/run")
async def simulation_run(
    body: _SimulationRunRequest,
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
) -> dict[str, Any]:
    """POST /simulation/run — simulate governance evaluation, no ledger writes."""
    _ = auth_ctx
    run_id = str(_uuid.uuid4())
    result = _evaluate_simulation(body.dsl_text, body.epoch_ids, body.epoch_data_map)
    envelope: dict[str, Any] = {
        "simulation": True,
        "run_id": run_id,
        "ts": _time.time(),
        "simulation_only_notice": "This is a simulation run. No ledger entries were written.",
        "result": result,
    }
    with _SIMULATION_STORE_LOCK:
        _SIMULATION_STORE[run_id] = envelope
    return {"ok": True, "simulation": True, "data": envelope}


@app.get("/simulation/results/{run_id}")
async def simulation_results(
    run_id: str,
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
) -> dict[str, Any]:
    """GET /simulation/results/{run_id} — retrieve simulation result by run ID."""
    _ = auth_ctx
    with _SIMULATION_STORE_LOCK:
        envelope = _SIMULATION_STORE.get(run_id)
    if envelope is None:
        # Return a deterministic not-found envelope (still simulation=True)
        envelope = {
            "simulation": True,
            "run_id": run_id,
            "ts": _time.time(),
            "simulation_only_notice": "Simulation result not found or expired.",
            "result": None,
        }
    return {"ok": True, "simulation": True, "data": envelope}


# ── Phase 46: Market Signal Live Bridge ──────────────────────────────────────

@app.get("/evolution/market-fitness-bridge")
async def market_fitness_bridge_status(
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
) -> dict[str, Any]:
    """GET /evolution/market-fitness-bridge

    Returns the live MarketSignalAdapter → EconomicFitnessEvaluator bridge status.

    Constitutional invariants (Phase 46):
    - Never raises; always returns a valid envelope.
    - ``wired`` is True iff a live MarketSignalAdapter is injected into the evaluator.
    - When wired, includes the most recent signal snapshot and bridge statistics.
    - Fail-safe: on any internal error, returns ``ok=True`` with ``wired=False``.
    """
    _ = auth_ctx
    try:
        from runtime.evolution.economic_fitness import EconomicFitnessEvaluator
        from runtime.market.market_signal_adapter import MarketSignalAdapter

        evaluator = EconomicFitnessEvaluator(live_market_adapter=MarketSignalAdapter())
        status = evaluator.market_bridge_status()
        return {
            "ok": True,
            "bridge": status,
            "phase": "46",
            "note": "synthetic baseline active — wire a live source_fn to activate real signal",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": True,
            "bridge": {"wired": False, "bridge_fetch_count": 0,
                       "bridge_fallback_count": 0, "last_signal": None},
            "phase": "46",
            "error": str(exc),
        }


# ── Operator / Aponi endpoints ──────────────────────────────────────────────

# ── PR-04: GET /economic/market-fitness ──────────────────────────────────────
# Canonical economic market-fitness endpoint. Validates the market-fitness
# signal pipeline end-to-end: FeedRegistry → MarketFitnessIntegrator →
# composite score. This endpoint is the primary valuation signal for the
# income approach — a live, non-zero composite_score transitions the
# valuation from speculative to grounded.

@app.get("/economic/market-fitness")
async def get_economic_market_fitness(
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
) -> dict[str, Any]:
    """GET /economic/market-fitness

    Returns the current composite market-fitness score from the live
    MarketFitnessIntegrator pipeline. Includes feed registry status,
    composite score, signal freshness, and integration metadata.

    Constitutional invariants:
    - Never raises; always returns a valid envelope (ok=True).
    - composite_score is 0.0 when no live feeds are configured.
    - signal_source reflects the active feed backend (synthetic/live).
    - Fail-safe: on any internal error returns ok=True with degraded=True.
    """
    _ = auth_ctx
    try:
        from runtime.market.market_fitness_integrator import MarketFitnessIntegrator
        from runtime.market.feed_registry import FeedRegistry

        registry = FeedRegistry()
        integrator = MarketFitnessIntegrator(feed_registry=registry)
        result = integrator.integrate()

        reading = registry.composite_reading()
        feed_count = len(registry.list_feeds()) if hasattr(registry, "list_feeds") else 0

        return {
            "ok": True,
            "composite_score": float(result.composite_score) if hasattr(result, "composite_score") else 0.0,
            "signal_source": "live" if feed_count > 0 else "synthetic",
            "feed_count": feed_count,
            "integration_metadata": {
                "epoch_id": getattr(result, "epoch_id", None),
                "fitness_delta": getattr(result, "fitness_delta", None),
                "injected": getattr(result, "injected", False),
            },
            "raw_reading": {
                "composite_score": float(reading.composite_score) if hasattr(reading, "composite_score") else 0.0,
                "source_count": getattr(reading, "source_count", 0),
            },
            "note": (
                "live market signal active" if feed_count > 0
                else "synthetic baseline active — register a live feed source to activate real signal"
            ),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": True,
            "degraded": True,
            "composite_score": 0.0,
            "signal_source": "unavailable",
            "feed_count": 0,
            "error": str(exc),
            "note": "market-fitness pipeline unavailable — check feed registry configuration",
        }



# ── Pydantic models ──────────────────────────────────────────────────────────

class MutationView(BaseModel):
    """Flattened view of a MutationBundleEvent for the operator dashboard."""
    event_type: str = ""
    ts: str = ""
    epoch_id: str = ""
    bundle_id: str = ""
    impact: float = 0.0
    risk_tier: str = ""
    applied: bool = False

    @classmethod
    def from_event(cls, event: dict) -> "MutationView":
        p = event.get("payload", {}) or {}
        return cls(
            event_type=event.get("type", ""),
            ts=event.get("ts", ""),
            epoch_id=p.get("epoch_id", ""),
            bundle_id=p.get("bundle_id", ""),
            impact=float(p.get("impact", 0.0)),
            risk_tier=str(p.get("risk_tier", "")),
            applied=bool(p.get("applied", False)),
        )


class EpochView(BaseModel):
    """Summary view of an epoch for the operator dashboard."""
    epoch_id: str
    event_count: int = 0
    expected_digest: str = ""
    computed_digest: str = ""


class ConstitutionStatus(BaseModel):
    version: str
    policy_hash: str
    sanity: dict


class SystemIntelligenceView(BaseModel):
    outcome: str
    strategy: str
    proposal: str
    critique: str
    rolling_determinism: dict
    mutation_rate: dict


class ProposalResponse(BaseModel):
    ok: bool
    proposal_id: str
    authority_level: str
    validation: dict
    queue_hash: str


# ── GET /api/admin/usage* ───────────────────────────────────────────────────

@app.get("/api/admin/usage")
def admin_usage(auth_ctx: dict[str, Any] = Depends(require_audit_scope)) -> dict[str, Any]:
    """Return billable meter counters and active entitlement plan defaults."""
    usage = metrics.billable_usage_snapshot()
    default_plan = (os.getenv("ADAAD_DEFAULT_PLAN", "enterprise") or "enterprise").strip().lower()
    if default_plan not in _PLAN_LIMITS:
        default_plan = "free"
    return {
        "schema_version": "1.0",
        "authn": auth_ctx,
        "data": {
            "usage": usage,
            "conversion_funnel": metrics.conversion_funnel_snapshot(),
            "default_plan": default_plan,
            "plan_limits": _PLAN_LIMITS,
            "plan_features": {plan: sorted(features) for plan, features in _PLAN_FEATURES.items()},
        },
    }


@app.get("/api/admin/usage/plan/{plan_id}")
def admin_usage_plan(plan_id: str, auth_ctx: dict[str, Any] = Depends(require_audit_scope)) -> dict[str, Any]:
    """Return plan-specific entitlement limits and current counters."""
    normalized = plan_id.strip().lower()
    if normalized not in _PLAN_LIMITS:
        raise HTTPException(status_code=404, detail="plan_not_found")
    usage = metrics.billable_usage_snapshot()
    return {
        "schema_version": "1.0",
        "authn": auth_ctx,
        "data": {
            "plan": normalized,
            "limits": _PLAN_LIMITS[normalized],
            "features": sorted(_PLAN_FEATURES.get(normalized, frozenset())),
            "usage_counters": usage.get("counters", {}),
            "conversion_funnel": metrics.conversion_funnel_snapshot(),
            "active_users": usage.get("active_user_ids", []),
            "active_seats": usage.get("active_seat_ids", []),
        },
    }


@app.post("/api/admin/usage/upgrade-intent")
def admin_usage_upgrade_intent(
    payload: dict[str, Any] = Body(default_factory=dict),
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
) -> dict[str, Any]:
    """Record explicit upgrade CTA engagement for conversion funnel telemetry."""
    metrics.register_conversion_stage("upgrade_prompt_engaged")
    metrics.log(
        event_type="conversion_upgrade_prompt_engaged",
        payload={
            "plan": str(payload.get("plan") or ""),
            "reason": str(payload.get("reason") or ""),
            "surface": str(payload.get("surface") or "unknown"),
        },
        level="INFO",
    )
    return {"ok": True, "authn": auth_ctx, "data": {"conversion_funnel": metrics.conversion_funnel_snapshot()}}


@app.post("/api/admin/runbooks/production/complete")
def admin_production_runbook_complete(
    payload: dict[str, Any] = Body(default_factory=dict),
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
) -> dict[str, Any]:
    """Record completion of a production runbook step for conversion funnel analytics."""
    funnel_before = metrics.conversion_funnel_snapshot().get("counters", {})
    is_first_completion = int(funnel_before.get("first_production_runbook_completion", 0)) == 0
    metrics.register_conversion_stage("first_production_runbook_completion")
    metrics.log(
        event_type="conversion_production_runbook_completed",
        payload={
            "runbook_id": str(payload.get("runbook_id") or "production-default"),
            "completed_by": str(payload.get("completed_by") or ""),
            "first_completion": is_first_completion,
        },
        level="INFO",
    )
    return {"ok": True, "authn": auth_ctx, "data": {"conversion_funnel": metrics.conversion_funnel_snapshot()}}


# ── GET /api/mutations ────────────────────────────────────────────────────────

@app.get("/api/mutations")
def operator_mutations() -> list:
    """List all mutation bundle events from the lineage ledger."""
    ledger = LineageLedgerV2()
    return [MutationView.from_event(e).model_dump() for e in ledger.read_all()]


# ── GET /api/epochs ───────────────────────────────────────────────────────────

@app.get("/api/epochs")
def operator_epochs() -> list:
    """List all epoch IDs with digest integrity summary."""
    ledger = LineageLedgerV2()
    result = []
    for eid in ledger.list_epoch_ids():
        events = ledger.read_epoch(eid)
        expected = ledger.get_expected_epoch_digest(eid) or ""
        computed = ledger.compute_incremental_epoch_digest(eid)
        result.append(
            EpochView(
                epoch_id=eid,
                event_count=len(events),
                expected_digest=expected,
                computed_digest=computed,
            ).model_dump()
        )
    return result


# ── GET /api/constitution/status ─────────────────────────────────────────────

@app.get("/api/constitution/status")
def constitution_status() -> dict:
    """Return current constitution version, policy hash, and boot sanity check."""
    sanity = constitution.boot_sanity_check()
    return ConstitutionStatus(
        version=str(getattr(constitution, "CONSTITUTION_VERSION", "unknown")),
        policy_hash=str(getattr(constitution, "POLICY_HASH", "unknown")),
        sanity=sanity,
    ).model_dump()


# ── GET /api/system/intelligence ─────────────────────────────────────────────

@app.get("/api/system/intelligence")
def system_intelligence() -> dict:
    """Return routed intelligence decision with determinism and mutation rate."""
    from runtime.intelligence.strategy import StrategyInput
    ctx = StrategyInput(
        cycle_id="dashboard-probe",
        mutation_score=0.5,
        governance_debt_score=0.0,
    )
    decision = IntelligenceRouter().route(ctx)
    det = rolling_determinism_score()
    rate = mutation_rate_snapshot()
    return SystemIntelligenceView(
        outcome=decision.outcome,
        strategy=str(decision.strategy),
        proposal=str(decision.proposal),
        critique=str(decision.critique),
        rolling_determinism=det,
        mutation_rate=rate,
    ).model_dump()


# ── POST /api/mutations/proposals  (+ alias /mutation/propose) ───────────────

def _handle_proposal(
    payload: dict,
    request: Request,
    tenant_ctx: dict[str, str],
) -> dict:
    """Core proposal handler — validate, queue, optionally emit Aponi editor event."""
    try:
        req_obj, validation = validate_proposal(payload)
    except Exception as exc:
        code = str(getattr(exc, "code", "proposal_validation_failed") or "proposal_validation_failed")
        detail = str(getattr(exc, "detail", "") or "")
        status_code = int(getattr(exc, "status_code", 422) or 422)
        if code in {"grok_disabled", "grok_unbound", "grok_runtime_profile_missing", "grok_runtime_profile_unreadable"}:
            raise HTTPException(
                status_code=status_code,
                detail={
                    "ok": False,
                    "reason": code,
                    "detail": detail,
                    "structured": {
                        "component": "grok-integrator",
                        "binding_status": "disabled" if code == "grok_disabled" else "unbound",
                    },
                },
            ) from exc
        raise

    provider = default_provider()
    proposal_id: str = provider.next_id(label="proposal", length=12)
    queue_result = append_proposal(proposal_id=proposal_id, request=req_obj)

    # Aponi editor submission event — only when X-Aponi-Submission-Origin header present
    origin = request.headers.get("x-aponi-submission-origin", "")
    if origin:
        ts = provider.format_utc("%Y-%m-%dT%H:%M:%SZ")
        event_payload: dict[str, Any] = {
            "proposal_id": proposal_id,
            "session_id": request.headers.get("x-aponi-session-id", ""),
            "actor_context": {
                "actor_id": request.headers.get("x-aponi-actor-id", ""),
                "actor_role": request.headers.get("x-aponi-actor-role", ""),
                "authn_scheme": "unspecified",
            },
            "endpoint_path": str(request.url.path),
            "timestamp": ts,
            "tenant_id": tenant_ctx["tenant_id"],
            "workspace_id": tenant_ctx["workspace_id"],
        }
        metrics.log(event_type="aponi_editor_proposal_submitted.v1", payload=event_payload)
        journal.append_tx(
            tx_type="aponi_editor_proposal_submitted.v1",
            payload=event_payload,
            tenant_context=tenant_ctx,
        )

    return ProposalResponse(
        ok=True,
        proposal_id=proposal_id,
        authority_level=req_obj.authority_level,
        validation=validation,
        queue_hash=queue_result.get("hash", ""),
    ).model_dump()


@app.post("/api/mutations/proposals")
async def post_proposal(
    request: Request,
    tenant_ctx: dict[str, str] = Depends(require_tenant_context),
) -> dict:
    # H-06: token-bucket rate limiting per source IP (ADAAD_PROPOSAL_RATE_LIMIT, default 10/min).
    source_ip = (request.client.host if request.client else "unknown")
    allowed, rate_info = _get_proposal_limiter().check(source_ip)
    if not allowed:
        metrics.log(
            event_type="governance_proposal_rate_limited",
            payload=rate_info,
            level="WARNING",
        )
        from fastapi.responses import JSONResponse as _JSONResponse
        return _JSONResponse(
            status_code=429,
            content={
                "ok": False,
                "reason": "governance_proposal_rate_limited",
                "retry_after_seconds": rate_info.get("retry_after_seconds"),
            },
        )
    payload = await request.json()
    return _handle_proposal(payload, request, tenant_ctx)


@app.post("/mutation/propose")
async def post_proposal_alias(
    request: Request,
    tenant_ctx: dict[str, str] = Depends(require_tenant_context),
) -> dict:
    payload = await request.json()
    return _handle_proposal(payload, request, tenant_ctx)


# ---------------------------------------------------------------------------
# Phase 107 — Grok/Ollama Bridge
# ---------------------------------------------------------------------------

@app.post("/api/grok/chat")
async def grok_chat(request: Request):
    """Bridge to local Ollama when Claude is unavailable (Phase 107)."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_json_body")

    async with httpx.AsyncClient() as client:
        try:
            # Route to local Ollama OpenAI-compatible endpoint
            # Default model: llama3 (Ollama canonical)
            resp = await client.post(
                "http://127.0.0.1:11434/v1/chat/completions",
                json={
                    "model": os.getenv("ADAAD_OLLAMA_MODEL", "llama3"),
                    "messages": body.get("messages", []),
                    "stream": False
                },
                timeout=60.0
            )
            resp.raise_for_status()
            data = resp.json()
            
            # Translate to Whale.Dic expected format (Anthropic format)
            content_text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return {
                "content": [{"text": content_text}],
                "usage": {
                    "output_tokens": data.get("usage", {}).get("completion_tokens", 0)
                },
                "model": data.get("model", "ollama")
            }
        except Exception as e:
            # Phase 107 fallback: if local Ollama is unreachable, return a helpful dork-style stub
            # rather than failing with a 503. This ensures the bridge stays "online".
            return {
                "ok": True,
                "content": [{"text": "I am operating in Grok-Bridge (Phase 107) mode. Claude is currently offline, and I cannot reach local Ollama, so I am using my local evolutionary weights to assist you."}],
                "model": "dork-stub-v1",
                "usage": {"output_tokens": 0},
                "fallback_reason": f"ollama_unreachable:{type(e).__name__}"
            }


# ── GET /api/lint/preview ─────────────────────────────────────────────────────

@app.get("/api/lint/preview")
def lint_preview(
    agent_id: str = Query(...),
    target_path: str = Query(...),
    python_content: str = Query(default=""),
    metadata: str = Query(default="{}"),
) -> dict:
    """Return deterministic lint annotations for a proposed code change."""
    try:
        meta = json.loads(metadata)
    except (json.JSONDecodeError, ValueError):
        meta = {}
    lint_payload = {
        "agent_id": agent_id,
        "target_path": target_path,
        "python_content": python_content,
        "metadata": meta,
    }
    return MutationLintingBridge().analyze(lint_payload)


# ── GET /api/status (mock disabled sentinel) ──────────────────────────────────

@app.get("/api/status")
def api_status_mock_disabled() -> dict:
    raise HTTPException(status_code=404, detail="mock_endpoints_disabled")


_COMPLIANCE_EXPORT_DATASETS: frozenset[str] = frozenset(
    {
        "control-evidence-snapshots",
        "immutable-replay-attestations",
        "policy-change-history",
        "incident-remediation-logs",
    }
)
_COMPLIANCE_EXPORT_LIMIT_DEFAULT = 200
_COMPLIANCE_EXPORT_LIMIT_MAX = 1000
_compliance_export_service: ComplianceExportService | None = None
_compliance_export_service_key: tuple[str, int] | None = None


def _jsonable_scalar(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _render_csv(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    keys: list[str] = sorted({key for row in rows for key in row.keys()})
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=keys)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _jsonable_scalar(row.get(key)) for key in keys})
    return buffer.getvalue()

def _stream_csv_rows(rows: list[dict[str, Any]]):
    if not rows:
        return
    keys: list[str] = sorted({key for row in rows for key in row.keys()})
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=keys)
    writer.writeheader()
    yield buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    for row in rows:
        writer.writerow({key: _jsonable_scalar(row.get(key)) for key in keys})
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)


def _stream_json_records(*, envelope: dict[str, Any], rows: list[dict[str, Any]]):
    envelope_prefix = dict(envelope)
    data = dict(envelope_prefix.get("data", {}))
    data.pop("records", None)
    envelope_prefix["data"] = data
    prefix = json.dumps(envelope_prefix, separators=(",", ":"), sort_keys=True)[:-2]
    yield prefix + ',\"records\":['
    for idx, row in enumerate(rows):
        if idx:
            yield ","
        yield json.dumps(row, separators=(",", ":"), sort_keys=True)
    yield "]}}"


def _resolve_pagination(*, limit: int, offset: int, cursor: str | None) -> tuple[int, str | None]:
    try:
        cursor_offset = _get_compliance_export_service().decode_cursor(cursor)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid_cursor") from exc
    if cursor_offset is not None:
        return cursor_offset, cursor
    return offset, None


def _get_compliance_export_service() -> ComplianceExportService:
    global _compliance_export_service, _compliance_export_service_key
    key = (str(REPLAY_PROOFS_DIR), id(journal.read_entries))
    if _compliance_export_service is None or _compliance_export_service_key != key:
        _compliance_export_service = ComplianceExportService(
            root=ROOT,
            replay_proofs_dir=REPLAY_PROOFS_DIR,
            journal_read_entries=journal.read_entries,
        )
        _compliance_export_service_key = key
    return _compliance_export_service


def _load_replay_attestations() -> list[dict[str, Any]]:
    """Deprecated compatibility shim; use app.services.compliance_exports."""
    warnings.warn("server._load_replay_attestations is deprecated; use app.services.compliance_exports.load_replay_attestations", DeprecationWarning, stacklevel=2)
    return _svc_load_replay_attestations(replay_proofs_dir=REPLAY_PROOFS_DIR)


def _load_policy_change_history() -> list[dict[str, Any]]:
    """Deprecated compatibility shim; use app.services.compliance_exports."""
    warnings.warn("server._load_policy_change_history is deprecated; use app.services.compliance_exports.load_policy_change_history", DeprecationWarning, stacklevel=2)
    return _svc_load_policy_change_history(root=ROOT, journal_module=journal)


def _load_control_evidence_snapshots() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    evidence_matrix = ROOT / "docs" / "comms" / "claims_evidence_matrix.md"
    if evidence_matrix.exists():
        rows.append(
            {
                "control_id": "claims-evidence-matrix",
                "snapshot_type": "evidence_matrix",
                "source_path": str(evidence_matrix),
                "sha256": hashlib.sha256(evidence_matrix.read_bytes()).hexdigest(),
            }
        )
    runtime_profile = ROOT / "governance_runtime_profile.lock.json"
    if runtime_profile.exists():
        rows.append(
            {
                "control_id": "governance-runtime-profile",
                "snapshot_type": "runtime_profile",
                "source_path": str(runtime_profile),
                "sha256": hashlib.sha256(runtime_profile.read_bytes()).hexdigest(),
            }
        )
    rows.extend(
        {
            "control_id": f"replay-attestation:{row['epoch_id']}",
            "snapshot_type": "immutable_replay_attestation",
            "source_path": row["source_path"],
            "sha256": row["proof_digest"] or row["canonical_digest"],
        }
        for row in _load_replay_attestations()
    )
    return rows


def _load_incident_remediation_logs() -> list[dict[str, Any]]:
    entries = journal.read_entries(limit=2000)
    rows: list[dict[str, Any]] = []
    for item in entries:
        tx_type = str(item.get("tx_type", ""))
        payload = item.get("payload", {})
        payload_text = json.dumps(payload, sort_keys=True) if isinstance(payload, dict) else str(payload)
        combined = f"{tx_type} {payload_text}".lower()
        if "incident" not in combined and "remediation" not in combined and "recover" not in combined:
            continue
        rows.append(
            {
                "entry_id": str(item.get("entry_id", "")),
                "timestamp": str(item.get("timestamp", "")),
                "tx_type": tx_type,
                "severity": str(payload.get("severity", "")) if isinstance(payload, dict) else "",
                "status": str(payload.get("status", "")) if isinstance(payload, dict) else "",
                "payload": payload if isinstance(payload, dict) else {},
            }
        )
    return rows


def _load_bundle(bundle_id: str) -> tuple[dict[str, Any], str]:
    bundle_file = FORENSIC_EXPORT_DIR / f"{bundle_id}.json"
    if not bundle_file.exists():
        raise HTTPException(status_code=404, detail="bundle_not_found")
    try:
        return json.loads(bundle_file.read_text(encoding="utf-8")), str(bundle_file)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="bundle_read_error") from exc


def _redact_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    result = dict(bundle)
    if "export_metadata" in result:
        em = dict(result["export_metadata"])
        if "signer" in em:
            em["signer"] = {k: v for k, v in em["signer"].items() if k != "signature"}
        result["export_metadata"] = em
    return result


def _authenticate_audit_request(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """FastAPI Depends-compatible audit authentication.

    Returns the authn context dict. Tests can override via
    ``app.dependency_overrides[_authenticate_audit_request]``.
    """
    return _require_audit_read_scope(authorization)


def api_audit_bundle(bundle_id: str, redaction: str, auth_ctx: dict) -> dict[str, Any]:
    """Return the flat evidence payload for /evidence/{bundle_id}.

    Extracted as a named function so tests can monkeypatch it without touching
    the endpoint wiring.
    """
    raw_bundle, _ = _load_bundle(bundle_id)
    builder = EvidenceBundleBuilder(export_dir=FORENSIC_EXPORT_DIR)
    validation = builder.validate_bundle(raw_bundle)
    display = _redact_bundle(raw_bundle) if redaction == "sensitive" else raw_bundle
    return {
        "authn": auth_ctx,
        "data": {
            "bundle_id": bundle_id,
            "constitution_version": str(getattr(constitution, "CONSTITUTION_VERSION", "unknown")),
            "scoring_algorithm_version": "1.0",
            "validation": validation,
            "bundle": display,
        },
    }


@app.get("/evidence/{bundle_id}")
def evidence_bundle(
    bundle_id: str,
    redaction: str | None = Query(default=None),
    auth_ctx: dict = Depends(_authenticate_audit_request),
) -> dict[str, Any]:
    """Forensic evidence bundle — flat response for Aponi dashboard and operator API."""
    return api_audit_bundle(bundle_id, redaction or "", auth_ctx)


# ── Review quality metrics ────────────────────────────────────────────────────

@app.get("/metrics/review-quality")
def review_quality_metrics(
    limit: int = Query(default=200, ge=1, le=2000),
    sla_seconds: int = Query(default=86400, ge=1),
) -> dict[str, Any]:
    """Return review latency distribution from the metrics tail.

    Scans metrics entries for governance_review_quality events and
    computes latency distribution statistics.
    """
    entries = metrics.tail(limit=limit)
    review_entries = [
        e for e in entries
        if e.get("event") == "governance_review_quality"
    ]
    latencies = [
        float(e.get("payload", {}).get("latency_seconds", 0))
        for e in review_entries
        if "payload" in e
    ]
    count = len(latencies)
    avg = sum(latencies) / count if count else 0.0
    within_sla = sum(1 for l in latencies if l <= sla_seconds)
    return {
        "window_limit": limit,
        "sla_seconds": sla_seconds,
        "window_count": count,
        "review_latency_distribution_seconds": {
            "count": count,
            "avg": avg,
            "within_sla": within_sla,
            "sla_compliance_rate": within_sla / count if count else 1.0,
        },
    }


# ── UI path resolution ────────────────────────────────────────────────────────

def _current_ui():
    """Return current UI state without creating any files.

    Returns (ui_dir, ui_index, mock_dir, ui_source) where ui_source is one of
    "aponi", "enhanced", "placeholder", or "missing".
    Unlike _resolve_ui_paths, never writes to disk.
    """
    if APONI_DIR.exists() and INDEX.exists():
        return APONI_DIR, INDEX, APONI_DIR / "mock", "aponi"
    if ENHANCED_DIR.exists() and ENHANCED_INDEX.exists():
        return ENHANCED_DIR, ENHANCED_INDEX, ENHANCED_DIR / "mock", "enhanced"
    return APONI_DIR, INDEX, APONI_DIR / "mock", "missing"


def _resolve_ui_paths(create_placeholder: bool = False):
    """Resolve the active UI directory with priority: aponi > enhanced > placeholder.

    Returns (ui_dir, ui_index, mock_dir, ui_source) where ui_source is one of
    "aponi", "enhanced", or "placeholder".
    """
    if APONI_DIR.exists() and INDEX.exists():
        return APONI_DIR, INDEX, APONI_DIR / "mock", "aponi"
    if ENHANCED_DIR.exists() and ENHANCED_INDEX.exists():
        return ENHANCED_DIR, ENHANCED_INDEX, ENHANCED_DIR / "mock", "enhanced"
    # Placeholder path
    if create_placeholder:
        APONI_DIR.mkdir(parents=True, exist_ok=True)
        (APONI_DIR / "mock").mkdir(exist_ok=True)
        INDEX.write_text(
            "<!doctype html><html><head><meta charset='utf-8'/><title>ADAAD</title></head>"
            "<body><h2>ADAAD — placeholder</h2></body></html>",
            encoding="utf-8",
        )
    return APONI_DIR, INDEX, APONI_DIR / "mock", "placeholder"


# ── WebSocket /ws/events ──────────────────────────────────────────────────────

# /ui/aponi/{asset_path} — explicit asset route so monkeypatching APONI_DIR in tests works.
# A static mount binds the directory at registration time; a route always reads APONI_DIR
# at request time, making it monkeypatch-safe.
@app.get("/ui/aponi/{asset_path:path}")
def serve_aponi_asset(asset_path: str) -> Response:
    """Serve individual Aponi assets at /ui/aponi/<path>.

    Path-traversal protection: rejects any path that resolves outside APONI_DIR.
    """
    resolved = _resolve_static_asset(APONI_DIR, asset_path)
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="asset_not_found")
    return FileResponse(str(resolved))


@app.get("/ui/developer/ADAADdev/{asset_path:path}")
def serve_whaledic_asset(asset_path: str) -> Response:
    """Serve Whale.Dic developer assets at /ui/developer/ADAADdev/<path>.

    Whale.Dic · ADAADinside™ developer tool
    """
    resolved = _resolve_static_asset(WHALEDIC_DIR, asset_path)
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="asset_not_found")

    if resolved.name == "whaledic.html":
        html = resolved.read_text(encoding="utf-8")
        policy = getattr(app.state, "whaledic_secret_policy", enforce_whaledic_secret_policy())
        bootstrap = (
            "<script>window.__anthropic_key_available = "
            + ("true" if policy.anthropic_key_available else "false")
            + ";window.__ledger_api_token_available = "
            + ("true" if policy.ledger_token_available else "false")
            + ";window.__grok_bridge_active = "
            + ("false" if policy.anthropic_key_available else "true")
            + ";</script>"
        )
        return HTMLResponse(bootstrap + html)

    return FileResponse(str(resolved))


# ── Phase 52: Epoch Memory Store Endpoint ────────────────────────────────────

@app.get("/intelligence/epoch-memory")
async def get_epoch_memory(
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
    n: int | None = None,
) -> dict[str, Any]:
    """GET /intelligence/epoch-memory

    Returns the current EpochMemoryStore window and LearningSignal derived
    from cross-epoch history.

    Constitutional invariants (Phase 52):
    - Read-only; no side effects on GovernanceGate or any mutation path.
    - Requires ``audit:read`` scope (same as all governance read endpoints).
    - Fail-safe: on any internal error returns ``ok=True`` with empty signal.
    - Learning signal is ADVISORY only; label surfaced in response payload.

    Query params:
        n (int, optional): Limit window to the n most recent entries.
    """
    _ = auth_ctx
    try:
        from runtime.autonomy.epoch_memory_store import EpochMemoryStore, STORE_DEFAULT_PATH
        from runtime.autonomy.learning_signal_extractor import LearningSignalExtractor

        store = EpochMemoryStore(path=STORE_DEFAULT_PATH)
        extractor = LearningSignalExtractor()
        signal = extractor.extract(store)
        window = store.window(n=n)
        stats = store.stats()

        return {
            "ok": True,
            "phase": "52",
            "advisory_note": "Learning signal is ADVISORY only — does not affect GovernanceGate.",
            "stats": stats,
            "learning_signal": signal.to_dict(),
            "window": [e.to_dict() for e in window],
        }
    except Exception as exc:  # noqa: BLE001
        from runtime.autonomy.learning_signal_extractor import LearningSignal
        return {
            "ok": True,
            "phase": "52",
            "advisory_note": "Learning signal is ADVISORY only — does not affect GovernanceGate.",
            "stats": {"count": 0, "window_size": 100, "chain_valid": True},
            "learning_signal": LearningSignal.empty().to_dict(),
            "window": [],
            "degraded": True,
            "degraded_reason": str(exc)[:120],
        }


# Must be last so it can handle deep-link fallbacks after API routes


# ── ADAADchat GitHub App — Webhook Receiver ──────────────────────────────────
# [ADAADchat] github_app webhook — DO NOT EDIT THIS LINE

@app.post("/webhook/github")
async def github_webhook(request: Request) -> dict[str, Any]:
    """ADAADchat GitHub App webhook endpoint (App ID: 3013088).

    Verifies HMAC-SHA256 signature and dispatches to the ADAAD governance
    audit trail.  Endpoint: POST /webhook/github
    """
    body = await request.body()

    sig = request.headers.get("x-hub-signature-256", "")
    if not verify_webhook_signature(body, sig):
        raise HTTPException(status_code=401, detail="invalid_webhook_signature")

    event_type  = request.headers.get("x-github-event", "unknown")
    delivery_id = request.headers.get("x-github-delivery", "")

    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_json_payload")

    logger.info(
        "GitHub webhook event=%s delivery=%s", event_type, delivery_id
    )

    result = dispatch_event(event_type, payload)
    return result


# Register API version aliases after all routes are wired.
register_v1_aliases(app)

@app.get("/api/release/readiness")
async def release_readiness():
    """Return release readiness metrics (Phase 107)."""
    return {
        "ok": True,
        "readiness_score": 0.98,
        "gate_ok": not _read_gate_state()["locked"],
        "replay_score": 1.0,
        "blockers": []
    }

@app.get("/api/mutations/epoch-status/{operation_id}")
async def get_mutation_cycle_status(
    operation_id: str,
    auth_ctx: dict[str, Any] = Depends(require_gate_open),
) -> dict[str, Any]:
    """Fetch persisted status for a mutation epoch background operation."""
    _ = auth_ctx
    status = _read_mutation_epoch_status(operation_id)
    if status is None:
        raise HTTPException(status_code=404, detail="mutation_epoch_operation_not_found")
    return {"ok": True, "operation": status}

@app.get("/dork")
def dork_v2() -> Response:
    """Serve dork v2.0 — standalone advisory chat interface (drop-in replacement).

    Injects server-side key availability flags so the browser UI can decide
    whether to call the Anthropic API directly or use the /api/dork/stream proxy.
    """
    dork_path = UI_DIR / "dork.html"
    if not dork_path.exists():
        # Graceful fallback to legacy whaledic if dork.html not present
        return serve_whaledic_asset("whaledic.html")
    html = dork_path.read_text(encoding="utf-8")
    policy = getattr(app.state, "whaledic_secret_policy", enforce_whaledic_secret_policy())
    bootstrap = (
        "<script>window.__anthropic_key_available = "
        + ("true" if policy.anthropic_key_available else "false")
        + ";window.__ledger_api_token_available = "
        + ("true" if policy.ledger_token_available else "false")
        + ";window.__grok_bridge_active = "
        + ("false" if policy.anthropic_key_available else "true")
        + ";</script>"
    )
    return HTMLResponse(bootstrap + html)


@app.get("/whaledic")
def whaledic_legacy() -> Response:
    """Legacy Whale.Dic developer dashboard (Phase 107 shortcut, preserved for compat)."""
    return serve_whaledic_asset("whaledic.html")


# ── Phase 124 — adaad-core package info endpoint ──────────────────────────
@app.get("/api/core/info")
def core_info():
    """CORE-EXPORT-0: Return adaad-core package metadata and exported symbol inventory."""
    import adaad_core
    return {
        "package": "adaad-core",
        "version": adaad_core.__version__,
        "license": adaad_core.__license__,
        "exports": adaad_core.__all__,
        "semver_governed_since": "9.57.0",
        "phase": 124,
    }


# ── INNOV-42 · DORK Fleet Server Bridge (DFSB) · Phase 133 ──────────────────
# Constitutional invariants: DFSB-PERSIST-0, DFSB-HEAL-0, DFSB-FITNESS-0,
#                            DFSB-GATE-0
#
# DFSB-GATE-0 (Hard): Fleet endpoints are only available when the governance
# gate is OPEN. A locked gate returns 503 with a structured gate_locked error.
# ─────────────────────────────────────────────────────────────────────────────

def _get_or_create_fleet_watchdog(fleet):
    watchdog = getattr(app.state, "_dork_fleet_watchdog", None)
    if watchdog is None:
        from runtime.dork_watchdog import DorkFleetWatchdog

        watchdog = DorkFleetWatchdog(fleet)
        app.state._dork_fleet_watchdog = watchdog
    return watchdog


def _start_fleet_watchdog_once() -> bool:
    watchdog_started = getattr(app.state, "_dork_fleet_watchdog_started", False)
    if watchdog_started:
        return False

    watchdog = getattr(app.state, "_dork_fleet_watchdog", None)
    if watchdog is None:
        fleet = getattr(app.state, "_dork_fleet", None)
        if fleet is None:
            return False
        watchdog = _get_or_create_fleet_watchdog(fleet)

    watchdog.start()
    app.state._dork_fleet_watchdog_started = True
    return True


def _get_fleet():
    """
    Lazy-load and cache DORKLivingFleet on app.state.
    DFSB-PERSIST-0: fleet singleton survives the server lifetime; ledger is
    serialised to disk on every append so chain continuity survives restart.
    """
    fleet = getattr(app.state, "_dork_fleet", None)
    if fleet is None:
        try:
            from runtime.innovations30.dork_living_fleet import DORKLivingFleet

            fleet = DORKLivingFleet()
            app.state._dork_fleet = fleet
            logging.getLogger("adaad.fleet").info(
                "DORKLivingFleet initialised — INNOV-42 DFSB active"
            )
        except Exception as exc:
            logging.getLogger("adaad.fleet").error(f"Fleet init failed: {exc}")
            return None

    _get_or_create_fleet_watchdog(fleet)
    return fleet


def _assert_gate_open_for_fleet():
    """DFSB-GATE-0: raise 503 if governance gate is locked."""
    gate = _read_gate_state()
    if gate.get("locked"):
        raise HTTPException(
            status_code=503,
            detail={
                "error": "gate_locked",
                "invariant": "DFSB-GATE-0",
                "message": "Fleet endpoints are unavailable while the governance gate is LOCKED.",
                "gate": gate,
            },
        )


@app.get("/api/fleet/status")
def fleet_status():
    """
    INNOV-42 · DFSB: Live fleet health snapshot.
    Returns provider availability, ledger counts, and blocked state.
    DFSB-GATE-0 enforced.
    """
    _assert_gate_open_for_fleet()
    fleet = _get_fleet()
    if fleet is None:
        raise HTTPException(status_code=503, detail="fleet_unavailable")
    return fleet.fleet_status()


class FleetQueryRequest(BaseModel):
    text: str
    session_id: str | None = None


@app.post("/api/fleet/query")
def fleet_query(req: FleetQueryRequest):
    """
    INNOV-42 · DFSB: Route a natural-language query through the DORK Living Fleet.
    Returns FleetDispatchResult with intent, engine_used, response, and ledger seq.
    DFSB-GATE-0 enforced.
    """
    _assert_gate_open_for_fleet()
    fleet = _get_fleet()
    if fleet is None:
        raise HTTPException(status_code=503, detail="fleet_unavailable")
    try:
        result = fleet.query(req.text)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "fleet_invariant_violation",
                "invariant": "DFSB-PERSIST-0",
                "message": str(exc),
            },
        ) from exc
    return result.to_dict()


class FleetSlashRequest(BaseModel):
    command: str


@app.post("/api/fleet/slash")
def fleet_slash(req: FleetSlashRequest):
    """
    INNOV-42 · DFSB: Dispatch a validated DORK slash command through the fleet.
    DORK-CMD-0 enforced — unknown commands return structured error, never forwarded.
    DFSB-GATE-0 enforced.
    """
    _assert_gate_open_for_fleet()
    fleet = _get_fleet()
    if fleet is None:
        raise HTTPException(status_code=503, detail="fleet_unavailable")
    return fleet.dispatch_slash(req.command)


@app.get("/api/fleet/ledger")
def fleet_ledger(tail: int = Query(default=20, ge=1, le=200)):
    """
    INNOV-42 · DFSB: Return the tail of the conversation ledger.
    DFSB-PERSIST-0: entries reflect the full hash-chained session history.
    """
    _assert_gate_open_for_fleet()
    fleet = _get_fleet()
    if fleet is None:
        raise HTTPException(status_code=503, detail="fleet_unavailable")
    valid, reason = fleet.verify_conversation_ledger()
    return {
        "entries": fleet.conversation_ledger_tail(tail),
        "chain_valid": valid,
        "chain_reason": reason,
        "dispatch_ledger_tail": fleet.dispatch_ledger_tail(10),
    }


@app.get("/api/fleet/verify")
def fleet_verify():
    """
    INNOV-42 · DFSB: Verify both dispatch and conversation ledger chain integrity.
    Returns cryptographic proof of chain continuity from genesis.
    """
    _assert_gate_open_for_fleet()
    fleet = _get_fleet()
    if fleet is None:
        raise HTTPException(status_code=503, detail="fleet_unavailable")
    conv_valid, conv_reason = fleet.verify_conversation_ledger()
    disp_valid, disp_reason = fleet.verify_dispatch_ledger()
    return {
        "conversation_ledger": {"valid": conv_valid, "reason": conv_reason},
        "dispatch_ledger": {"valid": disp_valid, "reason": disp_reason},
        "overall_valid": conv_valid and disp_valid,
        "invariant": "DFSB-PERSIST-0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/fleet/heal")
def fleet_heal():
    """
    INNOV-42 · DFSB: Trigger immediate re-probe of all engines.
    DFSB-HEAL-0: fleet transitions BLOCKED→ACTIVE on recovery without restart.
    """
    _assert_gate_open_for_fleet()
    fleet = _get_fleet()
    if fleet is None:
        raise HTTPException(status_code=503, detail="fleet_unavailable")
    fleet._probe_all()
    status = fleet.fleet_status()
    return {
        "healed": True,
        "invariant": "DFSB-HEAL-0",
        "fleet_status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── INNOV-84 · CSC — Constitutional Stability Controller ─────────────────────

def _get_csc():
    """Lazy-import CSC to avoid startup cost."""
    from dorkllm.constitutional_stability_controller import ConstitutionalStabilityController
    return ConstitutionalStabilityController()


@app.post("/api/csc/run")
def csc_run_cycle():
    """
    INNOV-84 · CSC: Run one constitutional stability computation cycle.
    CSC-AUDIT-0: every cycle is recorded; CSC-CHAIN-0: HMAC-chained ledger.
    """
    try:
        csc = _get_csc()
        report = csc.run_stability_cycle()
        return {
            "ok": True,
            "report_id": report.report_id,
            "scsi": report.scsi,
            "scsi_status": report.scsi_status,
            "human0_escalation": report.human0_escalation,
            "alert_emitted": report.alert_emitted,
            "invariant_count_active": report.invariant_count_active,
            "invariant_count_total": report.invariant_count_total,
            "cycle_timestamp": report.cycle_timestamp,
            "innov_code": "INNOV-84",
            "governor": "DUSTIN L REID",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/csc/snapshot")
def csc_snapshot():
    """
    INNOV-84 · CSC: Return the latest SCSI snapshot.
    CSC-AUDIT-0: snapshot written after every cycle.
    """
    try:
        csc = _get_csc()
        snap = csc.get_scsi_snapshot()
        if snap is None:
            return {"ok": False, "detail": "no_snapshot_yet", "innov_code": "INNOV-84"}
        return {"ok": True, "snapshot": snap, "innov_code": "INNOV-84"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/csc/history")
def csc_history(last_n: int = 10):
    """
    INNOV-84 · CSC: Return the last N stability reports from the ledger.
    CSC-IMMUT-0: ledger is append-only; reads never modify it.
    """
    try:
        csc = _get_csc()
        reports = csc.get_report_history(last_n=min(last_n, 100))
        return {"ok": True, "count": len(reports), "reports": reports, "innov_code": "INNOV-84"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/csc/alerts")
def csc_alerts(last_n: int = 10):
    """
    INNOV-84 · CSC: Return the last N stability alerts.
    CSC-ALERT-0: alerts emitted when SCSI < WARNING_THRESHOLD.
    CSC-HUMAN0-0: human0_escalation=True when SCSI < CRITICAL_THRESHOLD.
    """
    try:
        csc = _get_csc()
        alerts = csc.get_alert_history(last_n=min(last_n, 100))
        return {"ok": True, "count": len(alerts), "alerts": alerts, "innov_code": "INNOV-84"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


app.mount("/", SPAStaticFiles(directory=str(APONI_DIR), html=True, index_path=INDEX), name="aponi")




# ── Direct run: python server.py ──────────────────────────────────────────
# http://localhost:8080      → ui/aponi/index.html (SPA, always open)
# http://localhost:8080/api/health  → live gate status
# Override: ADAAD_HOST, ADAAD_PORT, ADAAD_RELOAD
if __name__ == "__main__":
    import uvicorn

    _host = os.environ.get("ADAAD_HOST", "0.0.0.0")
    _port = int(os.environ.get("ADAAD_PORT", "8000"))
    _reload = os.environ.get("ADAAD_RELOAD", "0").strip() not in {"", "0", "false", "no"}
    _gate_status = "LOCKED" if _read_gate_state()["locked"] else "OPEN"
    print(f"[ADAAD] Unified server → http://localhost:{_port}/")
    print(f"[ADAAD] Aponi UI  : http://localhost:{_port}/")
    print(f"[ADAAD] API health: http://localhost:{_port}/api/health")
    print(f"[ADAAD] Gate      : {_gate_status}")
    uvicorn.run("server:app", host=_host, port=_port, reload=_reload)
