# SPDX-License-Identifier: Apache-2.0
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Minimal HTTP dashboard served with the standard library.
"""

import argparse
import concurrent.futures
import datetime as dt
import importlib
import json
import logging
import os
import re
import threading
import time
from hashlib import sha256
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List
from urllib import error as urlerror, request as urlrequest
from urllib.parse import parse_qs, urlparse

from app import APP_ROOT
from runtime import constitution
from runtime import metrics
from runtime.constants import APONI_PORT
from runtime.governance.event_taxonomy import (
    EVENT_TYPE_CONSTITUTION_ESCALATION,
    EVENT_TYPE_OPERATOR_OVERRIDE,
    EVENT_TYPE_REPLAY_DIVERGENCE,
    EVENT_TYPE_REPLAY_FAILURE,
    normalize_event_type,
)
from runtime.governance.instability_calculator import load_instability_policy
from runtime.governance.policy_artifact import GovernancePolicyError, load_governance_policy
from runtime.governance.response_schema_validator import validate_response
from runtime.governance.simulation.operator_forecast import run_operator_simulation
from runtime.evolution.epoch import CURRENT_EPOCH_PATH
from security.ledger import journal
from runtime.system_status import (
    GATE_PROTOCOL,
    DEFAULT_GATE_LOCK_FILE,
    DEFAULT_REPORT_VERSION_PATH,
    DEFAULT_VERSION_PATH,
    load_live_version,
)

ELEMENT_ID = "Metal"
FEDERATION_PANEL_SECTION_ID = "federation-panel"
_LAZY_IMPORT_CACHE: Dict[str, Any] = {}

BRIEF_ALERT_CODES = {
    "gate_locked": "gate_locked",
    "replay_divergence_spike": "replay_divergence_spike",
    "evidence_incomplete": "evidence_incomplete",
    "open_findings": "open_findings",
}


def _lazy_import(module_path: str, attr_name: str) -> Any:
    cache_key = f"{module_path}:{attr_name}"
    if cache_key in _LAZY_IMPORT_CACHE:
        return _LAZY_IMPORT_CACHE[cache_key]
    try:
        module = importlib.import_module(module_path)
        resolved = getattr(module, attr_name)
    except Exception as exc:
        detail = f"lazy_init_failed:{module_path}.{attr_name}:{type(exc).__name__}:{exc}"
        logging.getLogger(__name__).error(detail)
        metrics.log(
            event_type="lazy_init_failure",
            payload={"component": "ui.aponi_dashboard", "target": f"{module_path}.{attr_name}", "error": str(exc)},
            level="ERROR",
            element_id=ELEMENT_ID,
        )
        raise RuntimeError(detail) from exc
    _LAZY_IMPORT_CACHE[cache_key] = resolved
    metrics.log(
        event_type="lazy_init_success",
        payload={"component": "ui.aponi_dashboard", "target": f"{module_path}.{attr_name}"},
        level="INFO",
        element_id=ELEMENT_ID,
    )
    return resolved


def LineageLedgerV2(*args, **kwargs):  # type: ignore[no-redef]
    return _lazy_import("runtime.evolution", "LineageLedgerV2")(*args, **kwargs)


def ReplayEngine(*args, **kwargs):  # type: ignore[no-redef]
    return _lazy_import("runtime.evolution", "ReplayEngine")(*args, **kwargs)


def EvidenceBundleBuilder(*args, **kwargs):  # type: ignore[no-redef]
    return _lazy_import("runtime.evolution", "EvidenceBundleBuilder")(*args, **kwargs)


def _evidence_bundle_error_type():
    return _lazy_import("runtime.evolution", "EvidenceBundleError")


def build_evidence_graph_projection(*args, **kwargs):
    return _lazy_import("runtime.evolution.evidence_graph", "build_evidence_graph_projection")(*args, **kwargs)


def resolve_certified_ancestor_path(*args, **kwargs):
    return _lazy_import("runtime.evolution.lineage_v2", "resolve_certified_ancestor_path")(*args, **kwargs)


def _replay_proofs_dir() -> Path:
    return _lazy_import("runtime.evolution.replay_attestation", "REPLAY_PROOFS_DIR")


def load_replay_proof(*args, **kwargs):
    return _lazy_import("runtime.evolution.replay_attestation", "load_replay_proof")(*args, **kwargs)


def verify_replay_proof_bundle(*args, **kwargs):
    return _lazy_import("runtime.evolution.replay_attestation", "verify_replay_proof_bundle")(*args, **kwargs)


def replay_diff_export(*args, **kwargs):
    return _lazy_import("ui.features.evidence_panel", "replay_diff_export")(*args, **kwargs)


def state_fingerprint(*args, **kwargs):
    return _lazy_import("ui.features.evidence_panel", "state_fingerprint")(*args, **kwargs)


def replay_divergence(*args, **kwargs):
    return _lazy_import("ui.features.replay_panel", "replay_divergence")(*args, **kwargs)


def evolution_timeline(*args, **kwargs):
    return _lazy_import("ui.features.timeline", "evolution_timeline")(*args, **kwargs)

# ── Cryovant Gate ────────────────────────────────────────────────────────────
# Mirrors server.py: locks legacy dashboard API when gate.lock exists or
# ADAAD_GATE_LOCKED env-var is truthy.  "/" and "/index.html" always pass.

_DASHBOARD_GATE_LOCK_FILE = Path(os.environ.get("ADAAD_GATE_LOCK_FILE", str(DEFAULT_GATE_LOCK_FILE)))
_DASHBOARD_GATE_PROTOCOL = GATE_PROTOCOL


def _read_gate_state() -> Dict[str, Any]:
    from runtime.system_status import read_gate_state as _read_gate_state_snapshot

    return _read_gate_state_snapshot(
        gate_lock_file=_DASHBOARD_GATE_LOCK_FILE,
        protocol=_DASHBOARD_GATE_PROTOCOL,
    )

HUMAN_DASHBOARD_TITLE = "Aponi Governance Nerve Center"

# Version-resolution paths (used by /version endpoint and state injection)
_ADAAD_VERSION_PATH: Path = DEFAULT_VERSION_PATH
_REPORT_VERSION_PATH: Path = DEFAULT_REPORT_VERSION_PATH
_AGENT_STATE_PATH: Path = APP_ROOT.parent / ".adaad_agent_state.json"


def _load_live_version() -> Dict[str, Any]:
    live = load_live_version(version_path=_ADAAD_VERSION_PATH, report_version_path=_REPORT_VERSION_PATH)
    live["source"] = "runtime"
    return live


SEMANTIC_DRIFT_CLASSES: tuple[str, ...] = (
    "config_drift",
    "governance_drift",
    "trait_drift",
    "runtime_artifact_drift",
    "uncategorized_drift",
)
GOVERNANCE_POLICY_ERROR: str | None = None
GOVERNANCE_POLICY = None
_GOVERNANCE_POLICY_LOADED = False


def _load_governance_policy_cached():
    global GOVERNANCE_POLICY, GOVERNANCE_POLICY_ERROR, _GOVERNANCE_POLICY_LOADED
    if _GOVERNANCE_POLICY_LOADED:
        return GOVERNANCE_POLICY
    try:
        GOVERNANCE_POLICY = load_governance_policy()
        GOVERNANCE_POLICY_ERROR = None
        metrics.log(
            event_type="lazy_init_success",
            payload={"component": "ui.aponi_dashboard", "target": "governance_policy"},
            level="INFO",
            element_id=ELEMENT_ID,
        )
    except GovernancePolicyError as policy_exc:
        GOVERNANCE_POLICY = None
        GOVERNANCE_POLICY_ERROR = str(policy_exc)
        metrics.log(
            event_type="lazy_init_failure",
            payload={"component": "ui.aponi_dashboard", "target": "governance_policy", "error": str(policy_exc)},
            level="ERROR",
            element_id=ELEMENT_ID,
        )
    _GOVERNANCE_POLICY_LOADED = True
    return GOVERNANCE_POLICY


def _require_governance_policy():
    if GOVERNANCE_POLICY is not None:
        return GOVERNANCE_POLICY
    policy = _load_governance_policy_cached()
    if policy is None:
        detail = GOVERNANCE_POLICY_ERROR or "governance policy unavailable"
        raise GovernancePolicyError(f"policy unavailable (fail-closed): {detail}")
    return policy


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _build_session_brief_payload(
    *,
    state: dict[str, Any],
    intelligence: dict[str, Any],
    risk: dict[str, Any],
    replay: dict[str, Any],
) -> dict[str, Any]:
    gate_locked = bool(state.get("locked", False) or state.get("gate_locked", False))
    gate_reason = str(state.get("reason", "") or state.get("gate_reason", "")).strip()
    replay_divergence_count = _to_int(replay.get("divergence_event_count", 0))
    replay_failure_rate = _to_float(risk.get("replay_failure_rate", 0.0))
    readiness_score = _to_float(state.get("readiness_score", risk.get("instability", 0.0)), 0.0)
    blocker_count = _to_int(state.get("blocker_count", len(state.get("blocked_dependencies", []) or [])), 0)
    evidence_complete = bool(state.get("evidence_complete", state.get("release_evidence_complete", True)))
    open_findings = _to_int(state.get("open_findings_count", len(state.get("open_findings", []) or [])), 0)
    replay_mode = str(intelligence.get("replay_mode", state.get("replay_mode", "audit"))).lower()

    alerts: list[dict[str, Any]] = []
    if gate_locked:
        alerts.append(
            {
                "code": BRIEF_ALERT_CODES["gate_locked"],
                "severity": "critical",
                "title": "Gate locked",
                "summary": gate_reason or "Cryovant governance gate is locked.",
                "cta": ["Show blockers", "What to fix first"],
            }
        )
    if replay_divergence_count > 0 or replay_failure_rate >= 0.05:
        alerts.append(
            {
                "code": BRIEF_ALERT_CODES["replay_divergence_spike"],
                "severity": "warning" if replay_divergence_count <= 3 else "critical",
                "title": "Replay divergence detected",
                "summary": f"{replay_divergence_count} divergence events and replay failure rate {replay_failure_rate:.3f}.",
                "cta": ["Explain replay divergence", "Show blockers"],
            }
        )
    if not evidence_complete:
        alerts.append(
            {
                "code": BRIEF_ALERT_CODES["evidence_incomplete"],
                "severity": "warning",
                "title": "Evidence incomplete",
                "summary": "Release evidence is not complete for current lane.",
                "cta": ["Show blockers", "What to fix first"],
            }
        )
    if open_findings > 0:
        alerts.append(
            {
                "code": BRIEF_ALERT_CODES["open_findings"],
                "severity": "warning",
                "title": "Open findings",
                "summary": f"{open_findings} findings remain unresolved.",
                "cta": ["Show blockers", "What to fix first"],
            }
        )

    severity_weight = {"critical": 300, "warning": 200, "info": 100}
    for item in alerts:
        impact = (
            (100 if gate_locked else 0)
            + min(100, replay_divergence_count * 15)
            + min(100, open_findings * 10)
            + (50 if not evidence_complete else 0)
        )
        item["deterministic_score"] = severity_weight.get(str(item.get("severity", "info")), 100) + impact
    alerts.sort(key=lambda item: (-int(item["deterministic_score"]), str(item["code"])))

    summary = {
        "date_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"),
        "gate_status": "locked" if gate_locked else "open",
        "replay_mode": replay_mode,
        "replay_divergence_count": replay_divergence_count,
        "replay_failure_rate": round(replay_failure_rate, 6),
        "readiness_score": round(readiness_score, 6),
        "blocker_count": blocker_count,
        "open_findings_count": open_findings,
        "evidence_complete": evidence_complete,
        "top_alert_code": alerts[0]["code"] if alerts else "none",
    }
    recommendations = [
        {
            "id": "fix_gate_first",
            "severity": "critical" if gate_locked else "warning",
            "deterministic_score": (500 if gate_locked else 250) + (blocker_count * 10),
            "label": "What to fix first",
            "reason": "Unlock gate and clear blockers before mutation/promotion actions.",
        },
        {
            "id": "triage_replay",
            "severity": "warning",
            "deterministic_score": 200 + int(replay_divergence_count * 20 + replay_failure_rate * 100),
            "label": "Explain replay divergence",
            "reason": "Divergence must be triaged before readiness can recover.",
        },
        {
            "id": "review_findings",
            "severity": "warning" if open_findings > 0 else "info",
            "deterministic_score": 120 + (open_findings * 15),
            "label": "Show blockers",
            "reason": "Open findings and dependency blockers define next safe action.",
        },
    ]
    recommendations.sort(key=lambda item: (-int(item["deterministic_score"]), str(item["id"])))
    return {"ok": True, "summary": summary, "alerts": alerts, "recommendations": recommendations}
CONTROL_AGENT_ID_RE = re.compile(r"^[a-z0-9_\-]{3,64}$")
CONTROL_COMMAND_ID_RE = re.compile(r"^cmd-[0-9]{6}-[0-9a-f]{12}$")
CONTROL_GOVERNANCE_PROFILES = {"strict", "high-assurance"}
CONTROL_EXECUTION_ACTIONS = {"cancel", "fork"}
CONTROL_QUEUE_PATH = Path(os.environ.get("APONI_COMMAND_QUEUE_PATH", str(APP_ROOT.parent / "data" / "aponi_command_queue.jsonl")))
FREE_CAPABILITY_SOURCES_PATH = Path(os.environ.get("APONI_FREE_SOURCES_PATH", str(APP_ROOT.parent / "data" / "free_capability_sources.json")))
SKILL_PROFILES_PATH = Path(os.environ.get("APONI_SKILL_PROFILES_PATH", str(APP_ROOT.parent / "data" / "governed_skill_profiles.json")))
REPLAY_INSPECTOR_JS_PATH = APP_ROOT.parent / "ui" / "aponi" / "replay_inspector.js"
CONTROL_CAPABILITIES_MAX = 8
CONTROL_TEXT_FIELD_MAX = 240
MCP_MUTATION_ENDPOINTS = {"/mcp/tools/call", "/mcp/context/record"}
CONTROL_DATA_SCHEMA_VERSION = "1"
CONTROL_MODES = {"builder", "automation", "analysis", "growth"}
CONTROL_JWT_TTL_SECONDS = 300
CONTROL_NONCE_TTL_SECONDS = 300
CONTROL_NONCE_CACHE_LIMIT = 1024
CONTROL_BACKGROUND_TIMEOUT_SECONDS = 5.0
CONTROL_ALLOWED_ROLES = {"viewer", "operator", "approver", "admin"}
CONTROL_WRITE_ROLES = {"operator", "admin"}
CONTROL_SIGNOFF_ROLES = {"approver", "admin"}
CONTROL_HIGH_IMPACT_ACTIONS = {"fork", "cancel"}
CONTROL_REQUIRE_SIGNOFF = os.environ.get("APONI_CONTROL_REQUIRE_SIGNOFF", "0").strip() == "1"
UX_EVENT_TYPES = {
    "feature_entry",
    "feature_completion",
    "interaction",
    "undo",
    "first_success",
    "abandoned_config",
}


INSTABILITY_POLICY_ERROR: str | None = None
INSTABILITY_POLICY = None
_INSTABILITY_POLICY_LOADED = False


def _load_instability_policy_cached():
    global INSTABILITY_POLICY, INSTABILITY_POLICY_ERROR, _INSTABILITY_POLICY_LOADED
    if _INSTABILITY_POLICY_LOADED:
        return INSTABILITY_POLICY
    try:
        INSTABILITY_POLICY = load_instability_policy()
        INSTABILITY_POLICY_ERROR = None
        metrics.log(
            event_type="lazy_init_success",
            payload={"component": "ui.aponi_dashboard", "target": "instability_policy"},
            level="INFO",
            element_id=ELEMENT_ID,
        )
    except GovernancePolicyError as instability_policy_exc:
        INSTABILITY_POLICY = None
        INSTABILITY_POLICY_ERROR = str(instability_policy_exc)
        logging.getLogger(__name__).error(
            "ADAAD: instability policy failed to load lazily: %s", instability_policy_exc
        )
        metrics.log(
            event_type="lazy_init_failure",
            payload={
                "component": "ui.aponi_dashboard",
                "target": "instability_policy",
                "error": str(instability_policy_exc),
            },
            level="ERROR",
            element_id=ELEMENT_ID,
        )
    _INSTABILITY_POLICY_LOADED = True
    return INSTABILITY_POLICY


def _require_instability_policy():
    if INSTABILITY_POLICY is not None:
        return INSTABILITY_POLICY
    policy = _load_instability_policy_cached()
    if policy is None:
        detail = INSTABILITY_POLICY_ERROR or "instability policy unavailable"
        raise GovernancePolicyError(f"policy unavailable (fail-closed): {detail}")
    return policy


def _extract_schema_version(raw: object) -> str:
    if isinstance(raw, dict):
        value = raw.get("_schema_version")
        if isinstance(value, str):
            return value
    return ""


def _resolve_aponi_port() -> int:
    return int(os.environ.get("APONI_PORT", str(APONI_PORT)))


def _schema_version_status(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {"path": str(path), "exists": False, "schema_version": "", "ok": False}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"path": str(path), "exists": True, "schema_version": "", "ok": False}
    version = _extract_schema_version(raw)
    return {
        "path": str(path),
        "exists": True,
        "schema_version": version,
        "expected_schema_version": CONTROL_DATA_SCHEMA_VERSION,
        "ok": version == CONTROL_DATA_SCHEMA_VERSION,
    }








def _simulation_max_epoch_range() -> int:
    simulation_epoch_range_android = 2
    simulation_epoch_range_linux = 5
    override = os.environ.get("APONI_MAX_SIMULATION_EPOCH_RANGE", "").strip()
    if override:
        try:
            return max(1, int(override))
        except ValueError:
            return simulation_epoch_range_android if os.path.exists("/system/build.prop") else simulation_epoch_range_linux
    return simulation_epoch_range_android if os.path.exists("/system/build.prop") else simulation_epoch_range_linux


def _active_constitution_context() -> Dict[str, str]:
    return {
        "constitution_version": constitution.CONSTITUTION_VERSION,
        "policy_hash": constitution.POLICY_HASH,
    }


def _default_simulation_constraints() -> List[Dict[str, str]]:
    context = _active_constitution_context()
    return [
        {
            "type": "constitution_context",
            "constitution_version": context["constitution_version"],
            "policy_hash": context["policy_hash"],
        }
    ]


def _simulation_api_request(method: str, path: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    simulation_api_base_url = os.environ.get("APONI_SIMULATION_API_BASE", "").strip().rstrip("/")
    if not simulation_api_base_url:
        return {"ok": False, "error": "simulation_api_unconfigured"}
    request_url = f"{simulation_api_base_url}{path}"
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, sort_keys=True).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request_obj = urlrequest.Request(request_url, method=method, data=data, headers=headers)
    try:
        with urlrequest.urlopen(request_obj, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urlerror.HTTPError as exc:
        try:
            err_payload = json.loads(exc.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            err_payload = {"ok": False, "error": "simulation_upstream_http_error", "status": exc.code}
        err_payload.setdefault("ok", False)
        return err_payload
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {"ok": False, "error": "simulation_upstream_unavailable", "detail": str(exc)}


def _review_percentile(sorted_values: List[float], percentile: float) -> float:
    if not sorted_values:
        return 0.0
    n = len(sorted_values)
    rank = max(1, int((percentile / 100.0) * n + 0.999999999))
    return float(sorted_values[min(rank, n) - 1])


def compute_review_quality_payload(
    events: List[Dict[str, Any]],
    *,
    sla_seconds: int = 86_400,
    window_limit: int = 500,
) -> Dict[str, Any]:
    latencies: List[float] = []
    reviewer_counts: Dict[str, int] = {}
    total_comments = 0
    total_comment_events = 0
    overrides = 0
    within_sla = 0

    for event in events:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}

        latency = payload.get("latency_seconds")
        if isinstance(latency, (int, float)):
            value = max(0.0, float(latency))
            latencies.append(value)
            if value <= sla_seconds:
                within_sla += 1

        reviewer = payload.get("reviewer")
        if isinstance(reviewer, str) and reviewer.strip():
            key = reviewer.strip()
            reviewer_counts[key] = reviewer_counts.get(key, 0) + 1

        comment_count = payload.get("comment_count")
        if isinstance(comment_count, (int, float)):
            total_comments += max(0, int(comment_count))
            total_comment_events += 1

        if bool(payload.get("overridden")):
            overrides += 1

    latencies.sort()
    total_reviews = len(latencies)
    p95 = _review_percentile(latencies, 95.0)
    p99 = _review_percentile(latencies, 99.0)

    largest_reviewer_share = 0.0
    hhi = 0.0
    if reviewer_counts:
        reviewer_total = sum(reviewer_counts.values())
        shares = [count / reviewer_total for count in reviewer_counts.values()]
        largest_reviewer_share = max(shares)
        hhi = sum(share * share for share in shares)

    reviewed_within_sla_percent = (within_sla / total_reviews * 100.0) if total_reviews else 0.0
    average_comment_count = (total_comments / total_comment_events) if total_comment_events else 0.0
    override_rate_percent = (overrides / total_reviews * 100.0) if total_reviews else 0.0

    return {
        "window_limit": int(window_limit),
        "sla_seconds": int(sla_seconds),
        "window_count": total_reviews,
        "review_latency_distribution_seconds": {
            "count": total_reviews,
            "p95": round(p95, 6),
            "p99": round(p99, 6),
        },
        "reviewed_within_sla_percent": round(reviewed_within_sla_percent, 3),
        "reviewer_participation_concentration": {
            "largest_reviewer_share": round(largest_reviewer_share, 6),
            "hhi": round(hhi, 6),
            "distribution": dict(sorted(reviewer_counts.items())),
        },
        "review_depth_proxies": {
            "average_comment_count": round(average_comment_count, 6),
            "override_rate_percent": round(override_rate_percent, 3),
        },
    }

def _load_free_capability_sources() -> Dict[str, Dict[str, object]]:
    if not FREE_CAPABILITY_SOURCES_PATH.exists():
        return {}
    try:
        raw = json.loads(FREE_CAPABILITY_SOURCES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    normalized: Dict[str, Dict[str, object]] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or key.startswith("_") or not isinstance(value, dict):
            continue
        normalized[key] = value
    return normalized






def _allowed_control_origins(host_header: str) -> set[str]:
    configured = os.environ.get("APONI_ALLOWED_ORIGINS", "")
    allowed = {item.strip() for item in configured.split(",") if item.strip()}
    host = host_header.strip()
    if host:
        allowed.add(f"http://{host}")
        allowed.add(f"https://{host}")
    return allowed


def _origin_from_header(value: str) -> str:
    try:
        parsed = urlparse(value)
    except ValueError:
        return ""
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return ""


def _canonical_agent_id(seed: str) -> str:
    normalized = re.sub(r"[^a-z0-9_-]+", "_", seed.strip().lower()).strip("_")
    if len(normalized) < 3:
        normalized = f"{normalized}_agent" if normalized else "triage_agent"
    return normalized[:64]


def _heuristic_prompt_plan(prompt: str, skill_profiles: Dict[str, Dict[str, object]]) -> Dict[str, object]:
    text = prompt.strip()
    lower = text.lower()
    action = "create_agent" if any(word in lower for word in ("create", "build", "new agent", "spawn")) else "run_task"
    profile_keys = sorted(skill_profiles.keys())
    selected_profile = profile_keys[0] if profile_keys else ""
    for key in profile_keys:
        if key.lower() in lower:
            selected_profile = key
            break
    profile = skill_profiles.get(selected_profile, {}) if selected_profile else {}
    domains = profile.get("knowledge_domains") if isinstance(profile, dict) else []
    abilities = profile.get("abilities") if isinstance(profile, dict) else []
    capabilities = profile.get("capabilities") if isinstance(profile, dict) else []
    domain = domains[0] if isinstance(domains, list) and domains else "general"
    ability = abilities[0] if isinstance(abilities, list) and abilities else "analyze"
    selected_caps = capabilities[:3] if isinstance(capabilities, list) else []
    seed_words = re.findall(r"[a-zA-Z0-9_-]{3,}", lower)
    candidate = next((word for word in seed_words if word.endswith("agent")), "triage_agent")
    task_text = text if text else "Review current system state and recommend next governed action."
    return {
        "provider": "heuristic",
        "command": {
            "type": action,
            "agent_id": _canonical_agent_id(candidate),
            "governance_profile": "strict",
            "skill_profile": selected_profile,
            "knowledge_domain": str(domain),
            "ability": str(ability),
            "capabilities": [str(item) for item in selected_caps],
            "task": task_text,
            "purpose": task_text,
        },
        "rationale": [
            "Prompt planner inferred command type from intent words.",
            "Selected skill profile by keyword match (fallback to first profile).",
            "Filled domain/ability/capabilities from governed profile defaults.",
        ],
    }


def _extract_json_object(text: str) -> Dict[str, object] | None:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        value = json.loads(stripped)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        pass
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        try:
            value = json.loads(stripped[start : end + 1])
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _open_llm_prompt_plan(prompt: str, skill_profiles: Dict[str, Dict[str, object]]) -> Dict[str, object]:
    endpoint = os.environ.get("APONI_OPEN_LLM_URL", "").strip()
    if not endpoint:
        raise ValueError("open_llm_not_configured")
    model = os.environ.get("APONI_OPEN_LLM_MODEL", "open-source")
    api_key = os.environ.get("APONI_OPEN_LLM_API_KEY", "").strip()
    schema_hint = {
        "type": "run_task|create_agent",
        "agent_id": "lowercase_id",
        "skill_profile": "one_of_profiles",
        "knowledge_domain": "string",
        "ability": "string",
        "capabilities": ["string"],
        "task": "string",
        "purpose": "string"
    }
    prompt_payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Return ONLY JSON object matching schema."},
            {"role": "user", "content": json.dumps({"prompt": prompt, "skill_profiles": list(skill_profiles.keys()), "schema": schema_hint}, ensure_ascii=False)},
        ],
        "temperature": 0.1,
    }
    req = urlrequest.Request(endpoint, data=json.dumps(prompt_payload).encode("utf-8"), headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {api_key}"} if api_key else {})}, method="POST")
    try:
        with urlrequest.urlopen(req, timeout=8) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (OSError, urlerror.URLError) as exc:
        raise ValueError(f"open_llm_request_failed:{exc}") from exc
    parsed = _extract_json_object(raw)
    if parsed is None:
        envelope = _extract_json_object(raw) or {}
        content = ""
        if isinstance(envelope.get("choices"), list) and envelope["choices"]:
            first = envelope["choices"][0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    content = str(message.get("content") or "")
        parsed = _extract_json_object(content)
    if parsed is None:
        raise ValueError("open_llm_invalid_response")
    command = parsed.get("command") if isinstance(parsed.get("command"), dict) else parsed
    if not isinstance(command, dict):
        raise ValueError("open_llm_invalid_command")
    return {"provider": "open_llm", "command": command, "rationale": ["Open LLM planner response accepted."]}


def _plan_control_prompt(prompt: str, skill_profiles: Dict[str, Dict[str, object]]) -> Dict[str, object]:
    try:
        return _open_llm_prompt_plan(prompt, skill_profiles)
    except ValueError:
        return _heuristic_prompt_plan(prompt, skill_profiles)
def _load_skill_profiles() -> Dict[str, Dict[str, object]]:
    if not SKILL_PROFILES_PATH.exists():
        return {}
    try:
        raw = json.loads(SKILL_PROFILES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    normalized: Dict[str, Dict[str, object]] = {}
    for key, value in raw.items():
        if isinstance(key, str) and (not key.startswith("_")) and isinstance(value, dict):
            normalized[key] = value
    return normalized



def _skill_capability_matrix() -> Dict[str, Dict[str, object]]:
    profiles = _load_skill_profiles()
    sources = _load_free_capability_sources()
    matrix: Dict[str, Dict[str, object]] = {}
    for skill_profile in sorted(profiles.keys()):
        profile = profiles.get(skill_profile) or {}
        allowed_capabilities = profile.get("allowed_capabilities")
        capabilities: List[str] = []
        if isinstance(allowed_capabilities, list):
            capabilities = sorted(str(item) for item in allowed_capabilities if isinstance(item, str) and item in sources)
        abilities = profile.get("abilities")
        knowledge_domains = profile.get("knowledge_domains")
        matrix[skill_profile] = {
            "abilities": sorted(str(item) for item in (abilities or []) if isinstance(item, str)),
            "knowledge_domains": sorted(str(item) for item in (knowledge_domains or []) if isinstance(item, str)),
            "capabilities": capabilities,
        }
    return matrix

def _normalized_field(raw_payload: Dict[str, object], key: str, *, lower: bool = False) -> str:
    value = str(raw_payload.get(key, "")).strip()
    if lower:
        value = value.lower()
    return value[:CONTROL_TEXT_FIELD_MAX]


def _validate_ux_event(raw_payload: object) -> Dict[str, object]:
    if not isinstance(raw_payload, dict):
        return {"ok": False, "error": "invalid_payload"}
    event_type = _normalized_field(raw_payload, "event_type", lower=True)
    if event_type not in UX_EVENT_TYPES:
        return {"ok": False, "error": "invalid_event_type", "allowed": sorted(UX_EVENT_TYPES)}
    session_id = _normalized_field(raw_payload, "session_id")
    if not session_id:
        return {"ok": False, "error": "missing_session_id"}
    feature = _normalized_field(raw_payload, "feature", lower=True)
    if not feature:
        return {"ok": False, "error": "missing_feature"}
    metadata_raw = raw_payload.get("metadata")
    metadata = metadata_raw if isinstance(metadata_raw, dict) else {}
    return {
        "ok": True,
        "event": {
            "event_type": event_type,
            "session_id": session_id,
            "feature": feature,
            "metadata": metadata,
        },
    }


def _ux_summary(window: int = 200) -> Dict[str, object]:
    recent = metrics.tail(limit=window)
    ux_events = [
        entry
        for entry in recent
        if isinstance(entry, dict) and str(entry.get("event", "")).startswith("aponi_ux_")
    ]
    per_type = {event_type: 0 for event_type in sorted(UX_EVENT_TYPES)}
    sessions: set[str] = set()
    features: set[str] = set()
    for entry in ux_events:
        payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
        event_type = str(payload.get("event_type", "")).strip().lower()
        if event_type in per_type:
            per_type[event_type] += 1
        session_id = str(payload.get("session_id", "")).strip()
        feature = str(payload.get("feature", "")).strip().lower()
        if session_id:
            sessions.add(session_id)
        if feature:
            features.add(feature)
    return {
        "window": window,
        "event_count": len(ux_events),
        "unique_sessions": len(sessions),
        "features_seen": sorted(features),
        "counts": per_type,
    }


def _control_policy_summary() -> Dict[str, object]:
    profiles = _load_skill_profiles()
    sources = _load_free_capability_sources()
    matrix = _skill_capability_matrix()
    return {
        "max_capabilities_per_intent": CONTROL_CAPABILITIES_MAX,
        "max_text_field_length": CONTROL_TEXT_FIELD_MAX,
        "governance_profiles": sorted(CONTROL_GOVERNANCE_PROFILES),
        "skill_profiles": sorted(profiles.keys()),
        "capability_sources": sorted(sources.keys()),
        "matrix_profile_count": len(matrix),
    }


def _control_intent_templates() -> Dict[str, Dict[str, object]]:
    matrix = _skill_capability_matrix()
    templates: Dict[str, Dict[str, object]] = {}
    for profile_name in sorted(matrix.keys()):
        profile = matrix.get(profile_name) or {}
        domains = profile.get("knowledge_domains") if isinstance(profile.get("knowledge_domains"), list) else []
        abilities = profile.get("abilities") if isinstance(profile.get("abilities"), list) else []
        capabilities = profile.get("capabilities") if isinstance(profile.get("capabilities"), list) else []
        first_domain = domains[0] if domains else ""
        first_ability = abilities[0] if abilities else ""
        first_capability = capabilities[0] if capabilities else ""
        templates[profile_name] = {
            "create_agent": {
                "type": "create_agent",
                "governance_profile": "strict",
                "agent_id": "example_agent",
                "skill_profile": profile_name,
                "knowledge_domain": first_domain,
                "capabilities": [first_capability] if first_capability else [],
                "purpose": "Describe the governed role of this agent",
            },
            "run_task": {
                "type": "run_task",
                "governance_profile": "strict",
                "agent_id": "example_agent",
                "skill_profile": profile_name,
                "knowledge_domain": first_domain,
                "capabilities": [first_capability] if first_capability else [],
                "ability": first_ability,
                "task": "Describe deterministic governed task",
            },
        }
    return templates


def _queue_entry_digest(entry: Dict[str, object]) -> str:
    canonical = json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"sha256:{sha256(canonical.encode('utf-8')).hexdigest()}"


def _verify_control_queue(entries: List[Dict[str, object]]) -> Dict[str, object]:
    issues: List[str] = []
    expected_index = 1
    previous_digest = ""
    for entry in entries:
        if not isinstance(entry, dict):
            issues.append("invalid_entry_type")
            expected_index += 1
            continue
        queue_index = entry.get("queue_index")
        if queue_index != expected_index:
            issues.append(f"unexpected_queue_index:{queue_index}:expected:{expected_index}")
        payload_raw = entry.get("payload")
        if not isinstance(payload_raw, dict):
            issues.append("invalid_payload_type")
            payload: Dict[str, object] = {}
        else:
            payload = payload_raw
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        expected_command_id = f"cmd-{expected_index:06d}-{sha256(canonical.encode('utf-8')).hexdigest()[:12]}"
        if entry.get("command_id") != expected_command_id:
            issues.append(f"unexpected_command_id:{entry.get('command_id')}:expected:{expected_command_id}")
        declared_previous = str(entry.get("previous_digest", "")).strip()
        if declared_previous != previous_digest:
            issues.append("previous_digest_mismatch")
        previous_digest = _queue_entry_digest(entry)
        expected_index += 1
    return {
        "ok": len(issues) == 0,
        "entries": len(entries),
        "issues": issues,
        "latest_digest": previous_digest,
    }


def _environment_health_snapshot() -> Dict[str, object]:
    queue_parent = CONTROL_QUEUE_PATH.parent
    queue_path_exists = CONTROL_QUEUE_PATH.exists()
    sources = _load_free_capability_sources()
    profiles = _load_skill_profiles()
    policy_ok = _load_governance_policy_cached() is not None
    return {
        "policy_loaded": policy_ok,
        "policy_error": GOVERNANCE_POLICY_ERROR or "",
        "command_surface_enabled": os.getenv("APONI_COMMAND_SURFACE", "0").strip() == "1",
        "queue_path": str(CONTROL_QUEUE_PATH),
        "queue_parent_exists": queue_parent.exists(),
        "queue_parent_writable": os.access(queue_parent, os.W_OK) if queue_parent.exists() else False,
        "queue_file_exists": queue_path_exists,
        "free_sources_count": len(sources),
        "skill_profiles_count": len(profiles),
        "required_files": {
            "free_sources": _schema_version_status(FREE_CAPABILITY_SOURCES_PATH),
            "skill_profiles": _schema_version_status(SKILL_PROFILES_PATH),
        },
    }


def _read_control_queue() -> List[Dict[str, object]]:
    if not CONTROL_QUEUE_PATH.exists():
        return []
    entries: List[Dict[str, object]] = []
    try:
        for line in CONTROL_QUEUE_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                entries.append(parsed)
    except (OSError, json.JSONDecodeError):
        return []
    return entries




def _find_control_queue_entry(command_id: str) -> Dict[str, object] | None:
    if not command_id:
        return None
    entries = _read_control_queue()
    for entry in reversed(entries):
        if isinstance(entry, dict) and str(entry.get("command_id", "")).strip() == command_id:
            return entry
    return None

def _queue_control_command(payload: Dict[str, object]) -> Dict[str, object]:
    return _append_control_queue_entry({"payload": payload, "status": "queued"})


def _append_control_queue_entry(fields: Dict[str, object]) -> Dict[str, object]:
    existing = _read_control_queue()
    payload_for_digest = fields.get("payload") if isinstance(fields.get("payload"), dict) else fields
    canonical = json.dumps(payload_for_digest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    command_id = f"cmd-{len(existing) + 1:06d}-{sha256(canonical.encode('utf-8')).hexdigest()[:12]}"
    previous_digest = _queue_entry_digest(existing[-1]) if existing else ""
    entry: Dict[str, object] = {
        "command_id": command_id,
        "queue_index": len(existing) + 1,
        "previous_digest": previous_digest,
    }
    entry.update(fields)
    CONTROL_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONTROL_QUEUE_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")
    return entry


def _cancel_control_command(command_id: str) -> Dict[str, object]:
    entries = _read_control_queue()
    if not entries:
        return {"ok": False, "error": "queue_empty"}
    target = next((entry for entry in entries if entry.get("command_id") == command_id), None)
    if target is None:
        return {"ok": False, "error": "command_not_found", "backend_supported": True}
    if target.get("status") == "canceled":
        return {"ok": True, "backend_supported": True, "already_canceled": True, "command_id": command_id}
    cancellation_entry = _append_control_queue_entry(
        {
            "status": "canceled",
            "payload": {
                "type": "cancel_intent",
                "target_command_id": command_id,
            },
        }
    )
    return {
        "ok": True,
        "backend_supported": True,
        "command_id": command_id,
        "cancellation_entry": cancellation_entry,
    }


class AponiDashboard:
    """
    Lightweight dashboard exposing orchestrator state and logs.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 8080, *, serve_mcp: bool = False, jwt_secret: str = "") -> None:
        self.host = host
        self.port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._state: Dict[str, str] = {}
        self.serve_mcp = bool(serve_mcp)
        self.jwt_secret = jwt_secret
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=max(4, (os.cpu_count() or 2)))

    def start(self, orchestrator_state: Dict[str, str]) -> None:
        self._state = orchestrator_state
        handler = self._build_handler()
        self._server = ThreadingHTTPServer((self.host, self.port), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        metrics.log(event_type="aponi_dashboard_started", payload={"host": self.host, "port": self.port}, level="INFO", element_id=ELEMENT_ID)

    def _build_handler(self):
        state_ref = self._state
        serve_mcp = self.serve_mcp
        jwt_secret = self.jwt_secret
        lineage_dir = APP_ROOT / "agents" / "lineage"
        staging_dir = lineage_dir / "_staging"
        capabilities_path = APP_ROOT.parent / "data" / "capabilities.json"
        lineage_v2 = LineageLedgerV2()
        replay = ReplayEngine(lineage_v2)
        bundle_builder = EvidenceBundleBuilder(ledger=lineage_v2, replay_engine=replay)
        seen_control_nonces: Dict[str, float] = {}
        executor = self._executor

        class Handler(SimpleHTTPRequestHandler):
            _replay_engine = replay
            _bundle_builder = bundle_builder
            _trace_id: str = ""

            def handle_one_request(self) -> None:
                self._trace_id = self.headers.get("X-Trace-Id", "").strip() if hasattr(self, "headers") and self.headers else ""
                if not self._trace_id:
                    self._trace_id = sha256(f"{time.time_ns()}:{id(self)}".encode("utf-8")).hexdigest()[:16]
                started = time.perf_counter()
                try:
                    super().handle_one_request()
                finally:
                    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
                    metrics.log(
                        event_type="aponi_http_request",
                        payload={"path": getattr(self, "path", ""), "method": getattr(self, "command", ""), "duration_ms": elapsed_ms, "trace_id": self._trace_id},
                        level="INFO",
                        element_id=ELEMENT_ID,
                    )
            def _send_json(self, payload, *, status_code: int = 200) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Trace-Id", self._trace_id)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)



            def _run_background(self, fn, *args, **kwargs):
                future = executor.submit(fn, *args, **kwargs)
                return future.result(timeout=CONTROL_BACKGROUND_TIMEOUT_SECONDS)
            @staticmethod
            def _b64url(data: bytes) -> str:
                import base64

                return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")

            @staticmethod
            def _b64url_decode(data: str) -> bytes:
                import base64

                pad = "=" * (-len(data) % 4)
                return base64.urlsafe_b64decode((data + pad).encode("utf-8"))

            def _issue_control_jwt(self, *, ttl_seconds: int = CONTROL_JWT_TTL_SECONDS) -> str:
                import hashlib
                import hmac

                if not jwt_secret:
                    raise ValueError("jwt_secret_missing")
                now = int(time.time())
                role = os.environ.get("APONI_CONTROL_DEFAULT_ROLE", "operator").strip().lower() or "operator"
                if role not in CONTROL_ALLOWED_ROLES:
                    role = "operator"
                header = self._b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode("utf-8"))
                payload = self._b64url(
                    json.dumps(
                        {
                            "aud": "aponi-control",
                            "sub": os.environ.get("APONI_CONTROL_DEFAULT_SUBJECT", "aponi-operator"),
                            "role": role,
                            "iat": now,
                            "exp": now + int(ttl_seconds),
                        },
                        separators=(",", ":"),
                    ).encode("utf-8")
                )
                message = f"{header}.{payload}".encode("utf-8")
                sig = self._b64url(hmac.new(jwt_secret.encode("utf-8"), message, hashlib.sha256).digest())
                return f"{header}.{payload}.{sig}"

            def _decode_jwt_payload(self, token: str) -> Dict[str, Any]:
                import hashlib
                import hmac

                header_b64, payload_b64, sig_b64 = token.split(".")
                message = f"{header_b64}.{payload_b64}".encode("utf-8")
                expected = self._b64url(hmac.new(jwt_secret.encode("utf-8"), message, hashlib.sha256).digest())
                if not hmac.compare_digest(expected, sig_b64):
                    raise ValueError("invalid_jwt")
                return json.loads(self._b64url_decode(payload_b64))

            def _audit_log(self, event: str, payload: Dict[str, object]) -> None:
                record = {
                    "event": event,
                    "client_ip": self.client_address[0] if self.client_address else "",
                    "path": self.path,
                    **payload,
                }
                logging.warning("CONTROL_AUDIT %s", json.dumps(record, sort_keys=True))
                try:
                    journal.append_tx("aponi_control_audit", record)
                except Exception:
                    logging.exception("CONTROL_AUDIT_LEDGER_WRITE_FAILED")

            @staticmethod
            def _claim_role(claims: Dict[str, Any]) -> str:
                role = str(claims.get("role", "")).strip().lower()
                if role in CONTROL_ALLOWED_ROLES:
                    return role
                return ""

            def _reject(self, status_code: int, reason: str, *, subject: str = "") -> None:
                self._audit_log(
                    "control_auth_reject",
                    {
                        "status": status_code,
                        "reason": reason,
                        "subject": subject,
                    },
                )
                self._send_json({"ok": False, "error": reason}, status_code=status_code)

            def _require_jwt(self) -> Dict[str, Any] | None:
                jwt_required = serve_mcp or os.environ.get("APONI_CONTROL_REQUIRE_JWT", "1").strip() == "1"
                if not jwt_required:
                    return {}
                auth = self.headers.get("Authorization", "")
                if not auth.startswith("Bearer "):
                    self._reject(401, "missing_jwt")
                    return None
                if not jwt_secret:
                    self._send_json({"ok": False, "error": "jwt_misconfigured"}, status_code=503)
                    return None
                token = auth.split(" ", 1)[1].strip()
                try:
                    payload = self._decode_jwt_payload(token)
                    if payload.get("aud") != "aponi-control":
                        self._reject(401, "invalid_jwt_audience", subject=str(payload.get("sub", "")))
                        return None
                    if int(payload.get("exp", 0) or 0) < int(time.time()):
                        self._reject(401, "expired_jwt", subject=str(payload.get("sub", "")))
                        return None
                except Exception:
                    self._reject(401, "invalid_jwt")
                    return None
                return payload

            def _require_control_origin(self) -> bool:
                allowed = _allowed_control_origins(self.headers.get("Host", ""))
                origin = _origin_from_header(self.headers.get("Origin", ""))
                referer_origin = _origin_from_header(self.headers.get("Referer", ""))
                if not origin and not referer_origin:
                    return True
                if origin and origin in allowed:
                    return True
                if referer_origin and referer_origin in allowed:
                    return True
                self._reject(403, "invalid_origin")
                return False

            def _require_control_write_auth(self) -> Dict[str, Any] | None:
                claims = self._require_jwt()
                if claims is None:
                    return None
                if self._claim_role(claims) not in CONTROL_WRITE_ROLES:
                    self._reject(403, "insufficient_role", subject=str(claims.get("sub", "")))
                    return None
                if not self._require_control_origin():
                    return None
                if not self._require_control_nonce():
                    return None
                return claims

            def _require_multi_party_signoff(self, claims: Dict[str, Any], *, action: str) -> bool:
                if not CONTROL_REQUIRE_SIGNOFF or action not in CONTROL_HIGH_IMPACT_ACTIONS:
                    return True
                signoff = self.headers.get("X-APONI-Signoff-Token", "").strip()
                if not signoff:
                    self._reject(403, "missing_signoff_token", subject=str(claims.get("sub", "")))
                    return False
                try:
                    signoff_claims = self._decode_jwt_payload(signoff)
                except Exception:
                    self._reject(403, "invalid_signoff_token", subject=str(claims.get("sub", "")))
                    return False
                if int(signoff_claims.get("exp", 0) or 0) < int(time.time()):
                    self._reject(403, "expired_signoff_token", subject=str(signoff_claims.get("sub", "")))
                    return False
                if self._claim_role(signoff_claims) not in CONTROL_SIGNOFF_ROLES:
                    self._reject(403, "insufficient_signoff_role", subject=str(signoff_claims.get("sub", "")))
                    return False
                if str(signoff_claims.get("sub", "")) == str(claims.get("sub", "")):
                    self._reject(403, "signoff_subject_conflict", subject=str(signoff_claims.get("sub", "")))
                    return False
                self._audit_log("control_signoff_accepted", {"subject": str(claims.get("sub", "")), "signoff_subject": str(signoff_claims.get("sub", "")), "action": action})
                return True

            def _require_control_nonce(self) -> bool:
                nonce = self.headers.get("X-APONI-Nonce", "").strip()
                if not nonce:
                    self._reject(401, "missing_nonce")
                    return False
                now = time.time()
                stale_cutoff = now - CONTROL_NONCE_TTL_SECONDS
                for key, ts in list(seen_control_nonces.items()):
                    if ts < stale_cutoff:
                        seen_control_nonces.pop(key, None)
                if nonce in seen_control_nonces:
                    self._audit_log("control_auth_reject", {"status": 409, "reason": "replayed_nonce", "subject": ""})
                    self._send_json({"ok": False, "error": "replayed_nonce"}, status_code=409)
                    return False
                seen_control_nonces[nonce] = now
                if len(seen_control_nonces) > CONTROL_NONCE_CACHE_LIMIT:
                    oldest = sorted(seen_control_nonces.items(), key=lambda item: item[1])[: max(1, len(seen_control_nonces) - CONTROL_NONCE_CACHE_LIMIT)]
                    for key, _ in oldest:
                        seen_control_nonces.pop(key, None)
                return True

            def _send_schema_violation(self, endpoint: str, violations: List[str]) -> None:
                self._send_json(
                    {
                        "ok": False,
                        "governance_error": "response_schema_violation",
                        "endpoint": endpoint,
                        "violations": violations,
                    },
                    status_code=500,
                )

            def _send_governance_error(self, endpoint: str, code: str, detail: str) -> None:
                self._send_json(
                    {
                        "ok": False,
                        "governance_error": code,
                        "endpoint": endpoint,
                        "detail": detail,
                    },
                    status_code=500,
                )

            def _send_validated_response(self, endpoint: str, schema_filename: str, payload: Dict | List[Dict]) -> None:
                violations = validate_response(schema_filename, payload)
                if violations:
                    self._send_schema_violation(endpoint, violations)
                    return
                self._send_json(payload)

            def _send_js(self, script: str) -> None:
                body = script.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _send_html(self, html: str) -> None:
                body = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; require-trusted-types-for 'script'; trusted-types default")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # noqa: N802 - required by base class
                parsed = urlparse(self.path)
                path = parsed.path
                query = parse_qs(parsed.query)

                # ── Cryovant gate ──────────────────────────────────────────
                # SPA paths always open; API data paths blocked when gate locked.
                _GATE_SPA_PATHS = {"/", "/index.html", "/version"}
                _DASHBOARD_GATE_PROTECTED_PREFIXES = (
                    "/state", "/metrics", "/fitness", "/system/",
                    "/risk/", "/replay/", "/policy/", "/simulation/",
                    "/alerts/", "/capabilities", "/lineage", "/evolution/",
                    "/projection/", "/mutations", "/staging", "/control/",
                    "/ux/", "/governance/",
                )
                if path not in _GATE_SPA_PATHS and any(
                    path.startswith(pfx) for pfx in _DASHBOARD_GATE_PROTECTED_PREFIXES
                ):
                    _gate = _read_gate_state()
                    if _gate["locked"]:
                        self._send_json(
                            {
                                "ok": False,
                                "error": "cryovant_gate_locked",
                                "reason": _gate["reason"] or "Cryovant gate LOCKED",
                                "protocol": _gate["protocol"],
                            },
                            status_code=423,
                        )
                        return


                if path in {"/", "/index.html"}:
                    self._send_html(self._user_console())
                    return
                if path == "/ui/aponi.js":
                    self._send_js(self._user_console_js())
                    return
                if path == "/ui/aponi/replay_inspector.js":
                    try:
                        self._send_js(REPLAY_INSPECTOR_JS_PATH.read_text(encoding="utf-8"))
                    except OSError:
                        self._send_json({"ok": False, "error": "replay_inspector_unavailable"}, status_code=503)
                    return
                if path.startswith("/version"):
                    self._send_json(_load_live_version())
                    return
                if path.startswith("/state"):
                    state_payload = self._run_background(dict, state_ref)
                    # Always surface live version fields — never let stale boot state obscure them
                    _live = _load_live_version()
                    state_payload["adaad_version"] = _live["adaad_version"]
                    state_payload["constitution_version"] = _live["constitution_version"]
                    state_payload["last_sync_sha"] = _live["last_sync_sha"]
                    state_payload["mutation_rate_limit"] = self._run_background(self._mutation_rate_state)
                    state_payload["determinism_panel"] = self._run_background(self._determinism_panel)
                    state_payload["reviewer_panel"] = self._run_background(self._reviewer_reputation_panel)
                    self._send_json(state_payload)
                    return
                if path.startswith("/metrics/review-quality"):
                    limit_raw = (query.get("limit") or ["500"])[0]
                    sla_raw = (query.get("sla_seconds") or ["86400"])[0]
                    try:
                        limit = max(1, min(2000, int(limit_raw)))
                    except (TypeError, ValueError):
                        limit = 500
                    try:
                        sla_seconds = max(1, int(sla_raw))
                    except (TypeError, ValueError):
                        sla_seconds = 86_400
                    events = [
                        entry
                        for entry in metrics.tail(limit=limit)
                        if isinstance(entry, dict) and str(entry.get("event", "")) == "governance_review_quality"
                    ]
                    payload = compute_review_quality_payload(events, sla_seconds=sla_seconds, window_limit=limit)
                    self._send_validated_response("/metrics/review-quality", "review_quality.schema.json", payload)
                    return
                if path.startswith("/metrics"):
                    self._send_json(
                        {
                            "entries": self._run_background(metrics.tail, 50),
                            "determinism": self._run_background(self._rolling_determinism_score, window=200),
                        }
                    )
                    return
                if path.startswith("/fitness"):
                    self._send_json(self._fitness_events())
                    return
                if path.startswith("/system/intelligence"):
                    self._send_validated_response("/system/intelligence", "system_intelligence.schema.json", self._run_background(self._intelligence_snapshot))
                    return
                if path.startswith("/risk/summary"):
                    self._send_validated_response("/risk/summary", "risk_summary.schema.json", self._run_background(self._risk_summary))
                    return
                if path.startswith("/risk/instability"):
                    try:
                        payload = self._run_background(self._risk_instability)
                    except GovernancePolicyError as exc:
                        self._send_governance_error("/risk/instability", "instability_policy_unavailable", str(exc))
                        return
                    self._send_validated_response("/risk/instability", "risk_instability.schema.json", payload)
                    return
                if path.startswith("/replay/divergence"):
                    self._send_validated_response("/replay/divergence", "replay_divergence.schema.json", self._replay_divergence())
                    return
                if path.startswith("/policy/simulate"):
                    if self.command != "GET":
                        self._send_json({"ok": False, "error": "method_not_allowed", "detail": "policy/simulate is GET only"}, status_code=405)
                        return
                    self._send_validated_response("/policy/simulate", "policy_simulate.schema.json", self._policy_simulation(query))
                    return
                if path.startswith("/simulation/context"):
                    self._send_json(
                        {
                            "ok": True,
                            "constitution_context": _active_constitution_context(),
                            "default_constraints": _default_simulation_constraints(),
                            "max_epoch_range": _simulation_max_epoch_range(),
                        }
                    )
                    return
                if path.startswith("/simulation/results/"):
                    run_id = path.rsplit("/", 1)[-1].strip()
                    if not run_id:
                        self._send_json({"ok": False, "error": "missing_run_id"}, status_code=400)
                        return
                    result = _simulation_api_request("GET", f"/simulation/results/{run_id}")
                    result.setdefault("run_id", run_id)
                    if result.get("ok") is False:
                        self._send_json(result, status_code=502 if str(result.get("error", "")).startswith("simulation_upstream") else 400)
                        return
                    result["ok"] = True
                    result["provenance"] = {
                        **(result.get("provenance") if isinstance(result.get("provenance"), dict) else {}),
                        **_active_constitution_context(),
                        "source_endpoint": "/simulation/results/{run_id}",
                        "max_epoch_range": _simulation_max_epoch_range(),
                    }
                    self._send_json(result)
                    return
                if path.startswith("/alerts/evaluate"):
                    try:
                        payload = self._run_background(self._alerts_evaluate)
                    except GovernancePolicyError as exc:
                        self._send_governance_error("/alerts/evaluate", "instability_policy_unavailable", str(exc))
                        return
                    self._send_validated_response("/alerts/evaluate", "alerts_evaluate.schema.json", payload)
                    return
                if path.startswith("/dork/session-brief"):
                    payload = self._run_background(self._dork_session_brief)
                    self._send_json(payload)
                    return
                if path.startswith("/replay/diff"):
                    epoch_id = query.get("epoch_id", [""])[0].strip()
                    if not epoch_id:
                        self._send_json({"ok": False, "error": "missing_epoch_id"})
                        return
                    self._send_validated_response("/replay/diff", "replay_diff.schema.json", self._replay_diff_export(epoch_id))
                    return
                if path.startswith("/capabilities"):
                    self._send_json(self._capabilities())
                    return
                if path.startswith("/lineage"):
                    self._send_json(journal.read_entries(limit=50))
                    return
                if path.startswith("/evolution/epoch"):
                    epoch_id = query.get("epoch_id", [""])[0].strip()
                    if not epoch_id:
                        self._send_json({"ok": False, "error": "missing_epoch_id"})
                        return
                    self._send_json(self._epoch_export(epoch_id))
                    return
                if path.startswith("/evolution/live"):
                    self._send_json(lineage_v2.read_all()[-50:])
                    return
                if path.startswith("/evolution/active"):
                    if CURRENT_EPOCH_PATH.exists():
                        self._send_json(json.loads(CURRENT_EPOCH_PATH.read_text(encoding="utf-8")))
                    else:
                        self._send_json({})
                    return
                if path.startswith("/evolution/timeline"):
                    self._send_validated_response("/evolution/timeline", "evolution_timeline.schema.json", self._evolution_timeline())
                    return
                if path.startswith("/evolution/evidence-graph"):
                    epoch_id = query.get("epoch_id", [""])[0].strip()
                    limit_raw = (query.get("limit") or ["100"])[0]
                    try:
                        limit = max(1, min(500, int(limit_raw)))
                    except (TypeError, ValueError):
                        limit = 100
                    payload = self._evidence_graph_projection(epoch_id=epoch_id, limit=limit)
                    self._send_validated_response("/evolution/evidence-graph", "evidence_graph.schema.json", payload)
                    return
                if path.startswith("/projection/mutation-roi"):
                    self._send_json(self._mutation_roi_projection())
                    return
                if path.startswith("/projection/lineage-trajectory"):
                    self._send_json(self._lineage_trajectory_projection())
                    return
                if path.startswith("/projection/confidence-bands"):
                    self._send_json(self._projection_confidence_bands())
                    return
                if path.startswith("/mutations"):
                    self._send_json(self._collect_mutations(lineage_dir))
                    return
                if path.startswith("/staging"):
                    self._send_json(self._collect_mutations(staging_dir))
                    return
                if path.startswith("/control/free-sources"):
                    self._send_json({"sources": _load_free_capability_sources()})
                    return
                if path.startswith("/control/skill-profiles"):
                    self._send_json({"profiles": _load_skill_profiles()})
                    return
                if path.startswith("/control/capability-matrix"):
                    self._send_json({"matrix": _skill_capability_matrix()})
                    return
                if path.startswith("/control/policy-summary"):
                    self._send_json(_control_policy_summary())
                    return
                if path.startswith("/control/templates"):
                    self._send_json({"templates": _control_intent_templates()})
                    return
                if path.startswith("/control/queue/verify"):
                    entries = _read_control_queue()
                    self._send_json(_verify_control_queue(entries))
                    return
                if path.startswith("/control/auth-token"):
                    if not self._command_surface_enabled():
                        self._send_json({"ok": False, "error": "command_surface_disabled"})
                        return
                    if not jwt_secret:
                        self._send_json({"ok": False, "error": "jwt_misconfigured"}, status_code=503)
                        return
                    self._send_json({"ok": True, "token": self._issue_control_jwt(), "expires_in_seconds": CONTROL_JWT_TTL_SECONDS})
                    return
                if path.startswith("/ux/summary"):
                    self._send_json(_ux_summary())
                    return
                if path.startswith("/control/queue"):
                    entries = _read_control_queue()
                    verification = _verify_control_queue(entries)
                    self._send_json({"enabled": self._command_surface_enabled(), "entries": entries[-50:], "latest_digest": verification.get("latest_digest", "")})
                    return
                # ── Whale.Dic API routes (DEBT-001 through DEBT-010) ──────────────
                if path.startswith("/api/governance/status"):
                    gate_snapshot = _read_gate_state()
                    intel = self._run_background(self._intelligence_snapshot)
                    self._send_json({
                        "ok": True,
                        "locked": gate_snapshot.get("locked", False),
                        "reason": gate_snapshot.get("reason", ""),
                        "constitution_version": intel.get("constitution_version", ""),
                        "mutation_enabled": not gate_snapshot.get("locked", False),
                        "replay_mode": intel.get("replay_mode", "audit"),
                        "gate_checks": intel.get("gate_checks", []),
                        "tier": intel.get("recovery_tier", "NOMINAL"),
                    })
                    return
                if path.startswith("/api/mutations/recent"):
                    limit_raw = (query.get("limit") or ["20"])[0]
                    try:
                        limit = max(1, min(100, int(limit_raw)))
                    except (TypeError, ValueError):
                        limit = 20
                    recent_entries = [
                        e for e in metrics.tail(limit=500)
                        if isinstance(e, dict) and str(e.get("event", "")).startswith("mutation_")
                    ]
                    self._send_json({"ok": True, "mutations": recent_entries[-limit:], "total": len(recent_entries)})
                    return
                if path.startswith("/api/replay/score"):
                    try:
                        from runtime.metrics_analysis import rolling_determinism_score
                        det = rolling_determinism_score(window=200)
                        score = det.get("rolling_score", 1.0)
                        divergence = det.get("failed", 0)
                    except Exception:
                        score = 1.0
                        divergence = 0
                    self._send_json({"ok": True, "score": score, "divergence": divergence, "mode": "audit"})
                    return
                if path.startswith("/api/epoch/current"):
                    intel = self._run_background(self._intelligence_snapshot)
                    self._send_json({"ok": True, "epoch": intel.get("epoch", 0), "phase": intel.get("phase", "unknown")})
                    return
                if path.startswith("/api/agents/health"):
                    intel = self._run_background(self._intelligence_snapshot)
                    agents_payload = intel.get("agents", {})
                    self._send_json({"ok": True, "agents": agents_payload})
                    return
                if path.startswith("/api/ledger/entries"):
                    limit_raw = (query.get("limit") or ["50"])[0]
                    try:
                        limit = max(1, min(200, int(limit_raw)))
                    except (TypeError, ValueError):
                        limit = 50
                    from runtime.api.app_layer import MutationLedger
                    try:
                        ledger = MutationLedger()
                        entries = list(ledger.tail(limit=limit))
                    except Exception:
                        entries = []
                    self._send_json({"ok": True, "entries": entries, "count": len(entries)})
                    return
                if path.startswith("/api/webhooks/stream"):
                    # SSE stream — emit recent webhook events then keep-alive
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "keep-alive")
                    self.end_headers()
                    recent_wh = [
                        e for e in metrics.tail(limit=200)
                        if isinstance(e, dict) and str(e.get("event", "")).startswith("github_webhook_")
                    ]
                    for evt in recent_wh[-10:]:
                        import json as _json
                        data_line = _json.dumps(evt)
                        self.wfile.write(f"data: {data_line}\n\n".encode())
                    self.wfile.write(b"data: {\"type\":\"connected\"}\n\n")
                    self.wfile.flush()
                    return
                if path.startswith("/api/webhooks/recent"):
                    limit_raw = (query.get("limit") or ["20"])[0]
                    try:
                        limit = max(1, min(100, int(limit_raw)))
                    except (TypeError, ValueError):
                        limit = 20
                    wh_events = [
                        e for e in metrics.tail(limit=500)
                        if isinstance(e, dict) and str(e.get("event", "")).startswith("github_webhook_")
                    ]
                    self._send_json({"ok": True, "events": wh_events[-limit:], "total": len(wh_events)})
                    return
                if path.startswith("/api/release/readiness"):
                    intel = self._run_background(self._intelligence_snapshot)
                    try:
                        from runtime.metrics_analysis import rolling_determinism_score
                        det = rolling_determinism_score(window=200)
                        replay_score = det.get("rolling_score", 1.0)
                    except Exception:
                        replay_score = 1.0
                    gate = _read_gate_state()
                    gate_ok = not gate.get("locked", False)
                    score = round((replay_score * 0.5) + (0.5 if gate_ok else 0.0), 3)
                    self._send_json({
                        "ok": True,
                        "readiness_score": score,
                        "gate_ok": gate_ok,
                        "replay_score": replay_score,
                        "blockers": [] if score >= 0.8 else ["governance_gate_locked" if not gate_ok else "replay_divergence"],
                    })
                    return
                if path.startswith("/api/ledger/log"):
                    limit_raw = (query.get("limit") or ["100"])[0]
                    try:
                        limit = max(1, min(500, int(limit_raw)))
                    except (TypeError, ValueError):
                        limit = 100
                    entries = [
                        e for e in metrics.tail(limit=limit * 3)
                        if isinstance(e, dict) and e.get("event")
                    ]
                    self._send_json({"ok": True, "log": entries[-limit:], "count": len(entries)})
                    return
                if path.startswith("/ui/developer/ADAADdev/whaledic.html"):
                    _whaledic = APP_ROOT.parent / "ui" / "developer" / "ADAADdev" / "whaledic.html"
                    if _whaledic.exists():
                        self._send_html(_whaledic.read_text(encoding="utf-8"))
                    else:
                        self.send_response(404)
                        self.end_headers()
                    return
                # SPA fallback — serve ui/aponi/index.html for browser deep-links
                _aponi_index = APP_ROOT.parent / "ui" / "aponi" / "index.html"
                if _aponi_index.exists():
                    self._send_html(_aponi_index.read_text(encoding="utf-8"))
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):  # noqa: N802 - required by base class
                parsed = urlparse(self.path)
                if serve_mcp and parsed.path in MCP_MUTATION_ENDPOINTS and self._require_jwt() is None:
                    return
                if parsed.path.startswith("/policy/simulate"):
                    self._send_json({"ok": False, "error": "method_not_allowed", "detail": "policy/simulate is GET only"}, status_code=405)
                    return
                if parsed.path.startswith("/simulation/run"):
                    content_length = int(self.headers.get("Content-Length", "0") or "0")
                    if content_length <= 0:
                        self._send_json({"ok": False, "error": "empty_body"}, status_code=400)
                        return
                    try:
                        payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
                    except json.JSONDecodeError:
                        self._send_json({"ok": False, "error": "invalid_json"}, status_code=400)
                        return
                    if not isinstance(payload, dict):
                        self._send_json({"ok": False, "error": "invalid_payload"}, status_code=400)
                        return
                    epoch_range = payload.get("epoch_range") if isinstance(payload.get("epoch_range"), dict) else {}
                    start_raw = epoch_range.get("start", 0)
                    end_raw = epoch_range.get("end", 0)
                    try:
                        start = int(start_raw)
                        end = int(end_raw)
                    except (TypeError, ValueError):
                        self._send_json({"ok": False, "error": "invalid_epoch_range"}, status_code=400)
                        return
                    if end < start:
                        self._send_json({"ok": False, "error": "invalid_epoch_range", "detail": "end_before_start"}, status_code=400)
                        return
                    max_range = _simulation_max_epoch_range()
                    if (end - start + 1) > max_range:
                        self._send_json(
                            {
                                "ok": False,
                                "error": "epoch_range_exceeds_platform_limit",
                                "max_epoch_range": max_range,
                                "requested_span": end - start + 1,
                            },
                            status_code=400,
                        )
                        return
                    constraints = payload.get("constraints")
                    normalized_constraints = constraints if isinstance(constraints, list) and constraints else _default_simulation_constraints()
                    forwarded_payload = {
                        "dsl_text": str(payload.get("dsl_text") or "").strip(),
                        "constraints": normalized_constraints,
                        "epoch_range": {"start": start, "end": end},
                        "constitution_context": _active_constitution_context(),
                    }
                    upstream = _simulation_api_request("POST", "/simulation/run", forwarded_payload)
                    if upstream.get("ok") is False:
                        self._send_json(upstream, status_code=502 if str(upstream.get("error", "")).startswith("simulation_upstream") else 400)
                        return
                    run_id = str(upstream.get("run_id") or "").strip()
                    result_payload = {
                        "ok": True,
                        "run_id": run_id,
                        "comparative_outcomes": upstream.get("comparative_outcomes", {}),
                        "result": upstream.get("result", upstream),
                        "provenance": {
                            **_active_constitution_context(),
                            "max_epoch_range": max_range,
                            "source_endpoint": "/simulation/run",
                            "request_digest": sha256(json.dumps(forwarded_payload, sort_keys=True).encode("utf-8")).hexdigest(),
                        },
                    }
                    self._send_json(result_payload)
                    return
                if parsed.path.startswith("/simulation/operator-forecast"):
                    content_length = int(self.headers.get("Content-Length", "0") or "0")
                    if content_length <= 0:
                        self._send_json({"ok": False, "error": "empty_body"}, status_code=400)
                        return
                    try:
                        payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
                    except json.JSONDecodeError:
                        self._send_json({"ok": False, "error": "invalid_json"}, status_code=400)
                        return
                    if not isinstance(payload, dict):
                        self._send_json({"ok": False, "error": "invalid_payload"}, status_code=400)
                        return
                    actions = payload.get("actions")
                    if not isinstance(actions, list) or not actions:
                        self._send_json({"ok": False, "error": "invalid_actions", "detail": "actions must be a non-empty list"}, status_code=400)
                        return
                    if not _AGENT_STATE_PATH.exists():
                        self._send_json({"ok": False, "error": "state_unavailable", "detail": str(_AGENT_STATE_PATH)}, status_code=503)
                        return
                    try:
                        state = json.loads(_AGENT_STATE_PATH.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        self._send_json({"ok": False, "error": "state_invalid_json", "detail": str(_AGENT_STATE_PATH)}, status_code=503)
                        return
                    if not isinstance(state, dict):
                        self._send_json({"ok": False, "error": "state_invalid_shape"}, status_code=503)
                        return
                    scenario_name = str(payload.get("scenario_name") or "").strip()
                    forecast = run_operator_simulation(state=state, actions=actions, scenario_name=scenario_name)
                    self._send_json(forecast)
                    return
                # Route priority: /ux/events and /control/telemetry are handled before generic
                # /control/queue validation so observability stays available even when command surface is off.
                if not (parsed.path.startswith("/simulation/run") or parsed.path.startswith("/simulation/operator-forecast") or parsed.path.startswith("/control/queue") or parsed.path.startswith("/control/telemetry") or parsed.path.startswith("/ux/events") or parsed.path.startswith("/control/cockpit/plan") or parsed.path.startswith("/control/execution")):
                    self.send_response(404)
                    self.end_headers()
                    return
                # Observability endpoints remain available even when the command surface is disabled.
                if (parsed.path.startswith("/control/queue") or parsed.path.startswith("/control/cockpit/plan") or parsed.path.startswith("/control/execution")) and not self._command_surface_enabled():
                    self._send_json({"ok": False, "error": "command_surface_disabled"})
                    return
                if parsed.path.startswith("/control/queue") or parsed.path.startswith("/control/cockpit/plan") or parsed.path.startswith("/control/execution"):
                    claims = self._require_control_write_auth()
                    if claims is None:
                        return
                content_length = int(self.headers.get("Content-Length", "0") or "0")
                if content_length <= 0:
                    self._send_json({"ok": False, "error": "empty_body"})
                    return
                try:
                    payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
                except json.JSONDecodeError:
                    self._send_json({"ok": False, "error": "invalid_json"})
                    return

                if parsed.path.startswith("/ux/events"):
                    validated = _validate_ux_event(payload)
                    if not validated.get("ok"):
                        self._send_json(validated)
                        return
                    event = validated["event"]
                    metrics.log(event_type="aponi_ux_event", payload=event, level="INFO", element_id=ELEMENT_ID)
                    self._send_json({"ok": True, "event": event})
                    return

                if parsed.path.startswith("/control/telemetry"):
                    event_type = _normalized_field(payload, "event_type")
                    if not event_type:
                        self._send_json({"ok": False, "error": "invalid_event_type"})
                        return
                    event_payload = payload.get("payload")
                    if not isinstance(event_payload, dict):
                        event_payload = {}
                    metrics.log(event_type=event_type, payload=event_payload, level="INFO", element_id=ELEMENT_ID)
                    self._send_json({"ok": True})
                    return

                if parsed.path.startswith("/control/cockpit/plan"):
                    prompt = _normalized_field(payload, "prompt")
                    if not prompt:
                        self._send_json({"ok": False, "error": "missing_prompt"})
                        return
                    skill_profiles = _load_skill_profiles()
                    plan = _plan_control_prompt(prompt, skill_profiles)
                    self._send_json({"ok": True, "plan": plan})
                    return

                if parsed.path.startswith("/control/queue/cancel"):
                    if not self._require_multi_party_signoff(claims, action="cancel"):
                        return
                    command_id = _normalized_field(payload, "command_id")
                    if not command_id:
                        self._send_json({"ok": False, "error": "missing_command_id"})
                        return
                    result = _cancel_control_command(command_id)
                    metrics.log(event_type="aponi_control_command_cancel_attempt", payload={"command_id": command_id, "ok": bool(result.get("ok"))}, level="INFO", element_id=ELEMENT_ID)
                    self._send_json(result)
                    return

                if parsed.path.startswith("/control/execution"):
                    validated_execution = self._validate_execution_control_command(payload)
                    if not validated_execution.get("ok"):
                        self._send_json(validated_execution)
                        return
                    if not self._require_multi_party_signoff(claims, action=str(validated_execution["command"].get("action", ""))):
                        return
                    entry = _queue_control_command(validated_execution["command"])
                    metrics.log(
                        event_type="aponi_execution_control_queued",
                        payload={
                            "command_id": entry["command_id"],
                            "action": validated_execution["command"].get("action", ""),
                            "target_command_id": validated_execution["command"].get("target_command_id", ""),
                        },
                        level="INFO",
                        element_id=ELEMENT_ID,
                    )
                    self._send_json({"ok": True, "entry": entry})
                    return

                validated = self._validate_control_command(payload)
                if not validated.get("ok"):
                    self._send_json(validated)
                    return
                entry = _queue_control_command(validated["command"])
                metrics.log(event_type="aponi_control_command_queued", payload={"command_id": entry["command_id"], "type": validated["command"]["type"], "mode": validated["command"].get("mode", "")}, level="INFO", element_id=ELEMENT_ID)
                self._send_json({"ok": True, "entry": entry})

            def log_message(self, format, *args):  # pragma: no cover
                return

            @staticmethod
            def _command_surface_enabled() -> bool:
                return os.getenv("APONI_COMMAND_SURFACE", "0").strip() == "1"

            @staticmethod
            def _execution_control_surface_enabled() -> bool:
                return os.getenv("APONI_EXECUTION_CONTROL_SURFACE", "0").strip() == "1"

            @staticmethod
            def _validate_control_command(raw_payload) -> Dict[str, object]:
                if not isinstance(raw_payload, dict):
                    return {"ok": False, "error": "invalid_payload"}
                command_type = _normalized_field(raw_payload, "type")
                if command_type not in {"create_agent", "run_task"}:
                    return {"ok": False, "error": "unsupported_type"}
                governance_profile = _normalized_field(raw_payload, "governance_profile", lower=True)
                if governance_profile not in CONTROL_GOVERNANCE_PROFILES:
                    return {"ok": False, "error": "invalid_governance_profile", "allowed": sorted(CONTROL_GOVERNANCE_PROFILES)}
                mode = _normalized_field(raw_payload, "mode", lower=True)
                metadata_raw = raw_payload.get("metadata")
                metadata_mode = ""
                if isinstance(metadata_raw, dict):
                    metadata_mode = _normalized_field(metadata_raw, "mode", lower=True)
                resolved_mode = metadata_mode or mode
                if resolved_mode not in CONTROL_MODES:
                    return {"ok": False, "error": "invalid_mode", "allowed": sorted(CONTROL_MODES)}
                agent_id = _normalized_field(raw_payload, "agent_id", lower=True)
                if not CONTROL_AGENT_ID_RE.match(agent_id):
                    return {"ok": False, "error": "invalid_agent_id"}
                free_sources = _load_free_capability_sources()
                skill_profiles = _load_skill_profiles()
                skill_profile = _normalized_field(raw_payload, "skill_profile")
                if skill_profile not in skill_profiles:
                    return {"ok": False, "error": "invalid_skill_profile", "allowed": sorted(skill_profiles.keys())}

                raw_capabilities = raw_payload.get("capabilities") or []
                if not isinstance(raw_capabilities, list):
                    return {"ok": False, "error": "invalid_capabilities", "allowed": sorted(free_sources.keys())}
                capabilities = sorted({_normalized_field({"v": item}, "v") for item in raw_capabilities if isinstance(item, str) and _normalized_field({"v": item}, "v")})
                if len(capabilities) > CONTROL_CAPABILITIES_MAX:
                    return {"ok": False, "error": "capabilities_limit_exceeded", "max": CONTROL_CAPABILITIES_MAX}
                if not all(item in free_sources for item in capabilities):
                    return {"ok": False, "error": "invalid_capabilities", "allowed": sorted(free_sources.keys())}

                profile_caps = skill_profiles.get(skill_profile, {}).get("allowed_capabilities")
                if not isinstance(profile_caps, list):
                    return {"ok": False, "error": "invalid_skill_profile_capabilities"}
                profile_caps_set = {str(item) for item in profile_caps if isinstance(item, str)}
                if any(item not in profile_caps_set for item in capabilities):
                    return {"ok": False, "error": "capability_not_allowed_for_skill", "allowed": sorted(profile_caps_set)}

                knowledge_domain = _normalized_field(raw_payload, "knowledge_domain")
                allowed_domains = skill_profiles.get(skill_profile, {}).get("knowledge_domains")
                if not isinstance(allowed_domains, list) or knowledge_domain not in allowed_domains:
                    return {"ok": False, "error": "invalid_knowledge_domain", "allowed": sorted(allowed_domains or [])}

                if command_type == "run_task":
                    task = _normalized_field(raw_payload, "task")
                    if not task:
                        return {"ok": False, "error": "missing_task"}
                    ability = _normalized_field(raw_payload, "ability")
                    allowed_abilities = skill_profiles.get(skill_profile, {}).get("abilities")
                    if not isinstance(allowed_abilities, list) or ability not in allowed_abilities:
                        return {"ok": False, "error": "invalid_ability", "allowed": sorted(allowed_abilities or [])}

                if command_type == "create_agent":
                    purpose = _normalized_field(raw_payload, "purpose")
                    if not purpose:
                        return {"ok": False, "error": "missing_purpose"}

                command = {
                    "type": command_type,
                    "agent_id": agent_id,
                    "governance_profile": governance_profile,
                    "skill_profile": skill_profile,
                    "mode": resolved_mode,
                    "knowledge_domain": knowledge_domain,
                    "capabilities": capabilities,
                    "metadata": {"mode": resolved_mode},
                }
                if command_type == "run_task":
                    command["task"] = task
                    command["ability"] = ability
                if command_type == "create_agent":
                    command["purpose"] = purpose
                return {"ok": True, "command": command}

            @staticmethod
            def _validate_execution_control_command(raw_payload) -> Dict[str, object]:
                if not isinstance(raw_payload, dict):
                    return {"ok": False, "error": "invalid_payload", "detail": "payload must be a JSON object"}
                command_type = _normalized_field(raw_payload, "type")
                if command_type != "execution_control":
                    return {
                        "ok": False,
                        "error": "unsupported_type",
                        "detail": "execution control endpoint requires type=execution_control",
                    }
                action = _normalized_field(raw_payload, "action", lower=True)
                if action not in CONTROL_EXECUTION_ACTIONS:
                    return {
                        "ok": False,
                        "error": "unsupported_action",
                        "detail": "action must be cancel or fork",
                    }
                target_command_id = _normalized_field(raw_payload, "target_command_id")
                if not CONTROL_COMMAND_ID_RE.match(target_command_id):
                    return {
                        "ok": False,
                        "error": "invalid_target_command_id",
                        "detail": "target_command_id must be a prior command id",
                    }
                command: Dict[str, object] = {
                    "type": command_type,
                    "action": action,
                    "target_command_id": target_command_id,
                }
                reason = _normalized_field(raw_payload, "reason")
                if reason:
                    command["reason"] = reason
                return {"ok": True, "command": command}

            @staticmethod
            def _collect_mutations(lineage_root: Path) -> List[str]:
                if not lineage_root.exists():
                    return []
                children = [item for item in lineage_root.iterdir() if item.is_dir()]
                children.sort(key=lambda entry: entry.stat().st_mtime, reverse=True)
                return [child.name for child in children]

            @staticmethod
            def _fitness_events() -> List[Dict]:
                entries = metrics.tail(limit=200)
                fitness_events = [
                    entry
                    for entry in entries
                    if entry.get("event") in {"fitness_scored", "beast_fitness_scored"}
                ]
                return fitness_events[-50:]

            @staticmethod
            def _capabilities() -> Dict:
                if not capabilities_path.exists():
                    return {}
                try:
                    return json.loads(capabilities_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    return {}

            @staticmethod
            def _rolling_determinism_score(window: int) -> Dict:
                from runtime.metrics_analysis import rolling_determinism_score

                return rolling_determinism_score(window=window)

            @classmethod
            def _determinism_panel(cls) -> Dict:
                summary = cls._rolling_determinism_score(window=200)
                return {
                    "title": "Determinism Score (rolling)",
                    "rolling_score": summary.get("rolling_score", 1.0),
                    "sample_size": summary.get("sample_size", 0),
                    "passed": summary.get("passed", 0),
                    "failed": summary.get("failed", 0),
                    "cause_buckets": summary.get("cause_buckets", {}),
                }

            @staticmethod
            def _mutation_rate_state() -> Dict:
                from runtime.metrics_analysis import mutation_rate_snapshot

                max_rate_env = os.getenv("ADAAD_MAX_MUTATIONS_PER_HOUR", "60").strip()
                window_env = os.getenv("ADAAD_MUTATION_RATE_WINDOW_SEC", str(_require_governance_policy().mutation_rate_window_sec)).strip()
                try:
                    max_rate = float(max_rate_env)
                except ValueError:
                    return {"ok": False, "reason": "invalid_max_rate", "value": max_rate_env}
                try:
                    window_sec = int(window_env)
                except ValueError:
                    return {"ok": False, "reason": "invalid_window_sec", "value": window_env}
                if max_rate <= 0:
                    return {
                        "ok": True,
                        "reason": "rate_limit_disabled",
                        "max_mutations_per_hour": max_rate,
                        "window_sec": window_sec,
                    }
                snapshot = mutation_rate_snapshot(window_sec)
                return {
                    "ok": snapshot["rate_per_hour"] <= max_rate,
                    "max_mutations_per_hour": max_rate,
                    "window_sec": window_sec,
                    "count": snapshot["count"],
                    "rate_per_hour": snapshot["rate_per_hour"],
                    "window_start_ts": snapshot["window_start_ts"],
                    "window_end_ts": snapshot["window_end_ts"],
                }

            @classmethod
            def _intelligence_snapshot(cls) -> Dict:
                determinism_window = _require_governance_policy().determinism_window
                determinism = cls._rolling_determinism_score(window=determinism_window)
                mutation_rate = cls._mutation_rate_state()
                recent = metrics.tail(limit=100)
                constitution_escalations = cls._constitution_escalations(recent)
                entropy_values: List[float] = []
                for entry in recent:
                    payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
                    entropy = payload.get("entropy")
                    if isinstance(entropy, (int, float)):
                        entropy_values.append(float(entropy))
                if len(entropy_values) >= 2:
                    entropy_trend_slope = (entropy_values[-1] - entropy_values[0]) / max(len(entropy_values) - 1, 1)
                else:
                    entropy_trend_slope = 0.0
                max_rate = float(mutation_rate.get("max_mutations_per_hour", 60.0) or 60.0)
                if max_rate <= 0:
                    mutation_aggression_index = 0.0
                else:
                    mutation_aggression_index = min(1.0, max(0.0, float(mutation_rate.get("rate_per_hour", 0.0)) / max_rate))
                rolling_score = float(determinism.get("rolling_score", 1.0))
                policy = _require_governance_policy()
                threshold_pass = policy.thresholds.determinism_pass
                threshold_warn = policy.thresholds.determinism_warn
                if rolling_score >= threshold_pass and mutation_rate.get("ok", True):
                    governance_health = "PASS"
                elif rolling_score >= threshold_warn:
                    governance_health = "WARN"
                else:
                    governance_health = "BLOCK"
                return {
                    "governance_health": governance_health,
                    "model_version": policy.model.version,
                    "policy_fingerprint": policy.fingerprint,
                    "model_inputs": {
                        "determinism_window": determinism_window,
                        "threshold_pass": threshold_pass,
                        "threshold_warn": threshold_warn,
                        "rate_limiter_ok": bool(mutation_rate.get("ok", True)),
                    },
                    "determinism_score": rolling_score,
                    "mutation_aggression_index": mutation_aggression_index,
                    "entropy_trend_slope": entropy_trend_slope,
                    "replay_mode": state_ref.get("replay_mode", os.getenv("ADAAD_REPLAY_MODE", "audit")),
                    "constitution_escalations_last_100": constitution_escalations,
                }

            @staticmethod
            def _constitution_escalations(entries: List[Dict]) -> int:
                count = 0
                for entry in entries:
                    event_type = normalize_event_type(entry)
                    if event_type == EVENT_TYPE_CONSTITUTION_ESCALATION:
                        count += 1
                        continue
                    event_name = str(entry.get("event", "")).lower()
                    if "constitution" in event_name and "escalat" in event_name:
                        count += 1
                return count

            @classmethod
            def _risk_summary(cls) -> Dict:
                intelligence = cls._intelligence_snapshot()
                recent = metrics.tail(limit=200)
                escalation_frequency = intelligence["constitution_escalations_last_100"] / 100.0
                override_frequency = sum(1 for entry in recent if normalize_event_type(entry) == EVENT_TYPE_OPERATOR_OVERRIDE) / 200.0
                replay_failure_rate = sum(1 for entry in recent if normalize_event_type(entry) == EVENT_TYPE_REPLAY_FAILURE) / 200.0
                aggression_trend_variance = intelligence["mutation_aggression_index"] * (1.0 - intelligence["mutation_aggression_index"])
                determinism_drift_index = max(0.0, 1.0 - intelligence["determinism_score"])
                return {
                    "escalation_frequency": escalation_frequency,
                    "override_frequency": override_frequency,
                    "replay_failure_rate": replay_failure_rate,
                    "aggression_trend_variance": aggression_trend_variance,
                    "determinism_drift_index": determinism_drift_index,
                }

            @staticmethod
            def _semantic_drift_density(entries: List[Dict]) -> float:
                if not entries:
                    return 0.0
                return sum(
                    1
                    for entry in entries
                    if str(entry.get("risk_tier", "")).lower() in {"high", "critical", "unknown"}
                ) / len(entries)

            @staticmethod
            def _risk_instability_confidence_interval(successes: int, total: int) -> Dict:
                if total <= 0:
                    return {"low": 0.0, "high": 0.0, "confidence": 0.95, "sample_size": 0}
                p_hat = successes / total
                instability_policy = _require_instability_policy()
                z_value = instability_policy.wilson_z_95
                z2 = z_value ** 2
                denom = 1.0 + z2 / total
                center = (p_hat + z2 / (2.0 * total)) / denom
                margin = (z_value / denom) * ((p_hat * (1.0 - p_hat) / total + z2 / (4.0 * total * total)) ** 0.5)
                low = max(0.0, center - margin)
                high = min(1.0, center + margin)
                return {
                    "low": round(low, 6),
                    "high": round(high, 6),
                    "confidence": 0.95,
                    "sample_size": total,
                }

            @classmethod
            def _semantic_drift_weighted_density(cls, timeline: List[Dict], window: int = 10) -> Dict:
                entries = timeline[-window:]
                if not entries:
                    return {"density": 0.0, "window": 0, "considered": 0}
                weighted_sum = 0.0
                considered = 0
                instability_policy = _require_instability_policy()
                max_weight = max(instability_policy.drift_class_weights.values())
                for entry in entries:
                    epoch_id = str(entry.get("epoch") or "").strip()
                    if not epoch_id:
                        continue
                    epoch = cls._replay_engine.reconstruct_epoch(epoch_id)
                    initial_state = epoch.get("initial_state") or {}
                    final_state = epoch.get("final_state") or {}
                    if not initial_state and not final_state:
                        continue
                    initial_keys = set(initial_state.keys())
                    final_keys = set(final_state.keys())
                    changed_keys = sorted(k for k in initial_keys & final_keys if initial_state.get(k) != final_state.get(k))
                    added_keys = sorted(final_keys - initial_keys)
                    removed_keys = sorted(initial_keys - final_keys)
                    semantic = cls._semantic_drift(changed_keys=changed_keys, added_keys=added_keys, removed_keys=removed_keys)
                    counts = semantic.get("class_counts", {})
                    total = sum(int(v) for v in counts.values())
                    if total <= 0:
                        continue
                    score = sum(instability_policy.drift_class_weights.get(name, 1.0) * int(counts.get(name, 0)) for name in SEMANTIC_DRIFT_CLASSES) / (total * max_weight)
                    weighted_sum += score
                    considered += 1
                if considered == 0:
                    return {"density": 0.0, "window": len(entries), "considered": 0}
                return {"density": round(weighted_sum / considered, 6), "window": len(entries), "considered": considered}

            @classmethod
            def _epoch_chain_anchors(cls, timeline: List[Dict], window: int = 50) -> Dict[str, Dict[str, str]]:
                anchors: Dict[str, Dict[str, str]] = {}
                previous_anchor = "sha256:" + ("0" * 64)
                for entry in timeline[-window:]:
                    epoch_id = str(entry.get("epoch") or "").strip()
                    if not epoch_id:
                        continue
                    payload = {
                        "epoch": epoch_id,
                        "mutation_id": str(entry.get("mutation_id") or ""),
                        "timestamp": str(entry.get("timestamp") or ""),
                        "risk_tier": str(entry.get("risk_tier") or ""),
                        "fitness_score": entry.get("fitness_score", 0.0),
                        "previous_anchor": previous_anchor,
                    }
                    anchor = cls._state_fingerprint(payload)
                    anchors[epoch_id] = {"anchor": anchor, "previous_anchor": previous_anchor}
                    previous_anchor = anchor
                return anchors

            @classmethod
            def _policy_simulation(cls, query: Dict[str, List[str]]) -> Dict:
                guard_flags = ("apply", "write", "mutate", "commit")
                for flag in guard_flags:
                    if query.get(flag, [""])[0].strip().lower() in {"1", "true", "yes"}:
                        return {"ok": False, "error": "read_only_endpoint", "blocked_flag": flag}

                policy_name = query.get("policy", ["governance_policy_v1.json"])[0].strip() or "governance_policy_v1.json"
                policy_path = Path("governance") / Path(policy_name).name
                try:
                    candidate = load_governance_policy(policy_path)
                except GovernancePolicyError as exc:
                    return {"ok": False, "error": "policy_load_failed", "detail": str(exc), "policy": policy_name}

                score_raw = query.get("determinism_score", [""])[0].strip()
                limiter_raw = query.get("rate_limiter_ok", [""])[0].strip().lower()
                if score_raw:
                    try:
                        score = float(score_raw)
                    except ValueError:
                        return {"ok": False, "error": "invalid_determinism_score", "value": score_raw}
                else:
                    score = float(cls._intelligence_snapshot().get("determinism_score", 1.0))
                if limiter_raw in {"true", "1", "yes"}:
                    rate_limiter_ok = True
                elif limiter_raw in {"false", "0", "no"}:
                    rate_limiter_ok = False
                else:
                    rate_limiter_ok = bool(cls._mutation_rate_state().get("ok", True))

                def _health(policy_obj):
                    if score >= policy_obj.thresholds.determinism_pass and rate_limiter_ok:
                        return "PASS"
                    if score >= policy_obj.thresholds.determinism_warn:
                        return "WARN"
                    return "BLOCK"

                current_policy = _require_governance_policy()
                current_health = _health(current_policy)
                simulated_health = _health(candidate)
                return {
                    "ok": True,
                    "inputs": {
                        "determinism_score": score,
                        "rate_limiter_ok": rate_limiter_ok,
                    },
                    "current_policy": {
                        "path": str(Path("governance") / "governance_policy_v1.json"),
                        "fingerprint": current_policy.fingerprint,
                        "health": current_health,
                    },
                    "simulated_policy": {
                        "path": str(policy_path),
                        "fingerprint": candidate.fingerprint,
                        "health": simulated_health,
                    },
                }

            @classmethod
            def _risk_instability(cls) -> Dict:
                risk = cls._risk_summary()
                timeline = cls._evolution_timeline()
                recent = timeline[-20:]
                weighted_drift = cls._semantic_drift_weighted_density(timeline, window=10)
                drift_density = float(weighted_drift.get("density", 0.0))

                momentum_window = 20
                momentum_span = timeline[-(momentum_window * 3):]
                density_windows = [
                    cls._semantic_drift_density(momentum_span[idx:idx + momentum_window])
                    for idx in range(0, len(momentum_span), momentum_window)
                    if len(momentum_span[idx:idx + momentum_window]) == momentum_window
                ]
                if len(density_windows) >= 2:
                    instability_velocity = round(density_windows[-1] - density_windows[-2], 6)
                else:
                    instability_velocity = 0.0
                if len(density_windows) >= 3:
                    instability_acceleration = round(density_windows[-1] - 2 * density_windows[-2] + density_windows[-3], 6)
                else:
                    instability_acceleration = 0.0

                drift_successes = sum(1 for entry in recent if str(entry.get("risk_tier", "")).lower() in {"high", "critical", "unknown"})
                confidence_interval = cls._risk_instability_confidence_interval(drift_successes, len(recent))

                instability_policy = _require_instability_policy()
                instability_weights = instability_policy.instability_weights
                instability = (
                    instability_weights["semantic_drift"] * drift_density
                    + instability_weights["replay_failure"] * float(risk.get("replay_failure_rate", 0.0))
                    + instability_weights["escalation"] * float(risk.get("escalation_frequency", 0.0))
                    + instability_weights["determinism_drift"] * float(risk.get("determinism_drift_index", 0.0))
                )
                instability_index = min(1.0, max(0.0, round(instability, 6)))
                velocity_spike = abs(instability_velocity) >= instability_policy.velocity_spike_threshold
                return {
                    "instability_index": instability_index,
                    "instability_velocity": instability_velocity,
                    "instability_acceleration": instability_acceleration,
                    "velocity_spike_anomaly": velocity_spike,
                    "velocity_anomaly_mode": "absolute_delta",
                    "confidence_interval": confidence_interval,
                    "weights": dict(instability_weights),
                    "drift_class_weights": dict(instability_policy.drift_class_weights),
                    "inputs": {
                        "semantic_drift_density": drift_density,
                        "replay_failure_rate": float(risk.get("replay_failure_rate", 0.0)),
                        "escalation_frequency": float(risk.get("escalation_frequency", 0.0)),
                        "determinism_drift_index": float(risk.get("determinism_drift_index", 0.0)),
                        "timeline_window": len(recent),
                        "momentum_window": momentum_window,
                        "drift_window": int(weighted_drift.get("window", 0)),
                        "drift_considered_epochs": int(weighted_drift.get("considered", 0)),
                    },
                }

            @classmethod
            def _alerts_evaluate(cls) -> Dict:
                instability = cls._risk_instability()
                risk = cls._risk_summary()
                critical: List[Dict] = []
                warning: List[Dict] = []
                info: List[Dict] = []

                instability_index = float(instability.get("instability_index", 0.0))
                replay_failure_rate = float(risk.get("replay_failure_rate", 0.0))
                velocity_spike = bool(instability.get("velocity_spike_anomaly", False))

                alert_thresholds = _require_instability_policy().alert_thresholds

                if instability_index >= float(alert_thresholds["instability_critical"]):
                    critical.append({"code": "instability_critical", "value": instability_index})
                elif instability_index >= float(alert_thresholds["instability_warning"]):
                    warning.append({"code": "instability_warning", "value": instability_index})

                if replay_failure_rate >= float(alert_thresholds["replay_failure_warning"]):
                    warning.append({"code": "replay_failure_warning", "value": replay_failure_rate})

                if bool(alert_thresholds["velocity_spike"]) and velocity_spike:
                    info.append(
                        {
                            "code": "instability_velocity_spike",
                            "value": float(instability.get("instability_velocity", 0.0)),
                            "mode": str(instability.get("velocity_anomaly_mode", "absolute_delta")),
                        }
                    )

                return {
                    "critical": critical,
                    "warning": warning,
                    "info": info,
                    "thresholds": dict(alert_thresholds),
                    "inputs": {
                        "instability_index": instability_index,
                        "replay_failure_rate": replay_failure_rate,
                        "velocity_spike_anomaly": velocity_spike,
                    },
                }

            @classmethod
            def _dork_session_brief(cls) -> Dict:
                state_payload = dict(state_ref)
                gate = _read_gate_state()
                state_payload["locked"] = bool(gate.get("locked", False))
                state_payload["reason"] = str(gate.get("reason", ""))
                return _build_session_brief_payload(
                    state=state_payload,
                    intelligence=cls._intelligence_snapshot(),
                    risk=cls._risk_summary(),
                    replay=cls._replay_divergence(),
                )

            @staticmethod
            def _state_fingerprint(value) -> str:
                return state_fingerprint(value, json)

            @classmethod
            def _epoch_export(cls, epoch_id: str) -> Dict:
                epoch = cls._replay_engine.reconstruct_epoch(epoch_id)
                if not epoch.get("bundles") and not epoch.get("initial_state") and not epoch.get("final_state"):
                    return {"ok": False, "error": "epoch_not_found", "epoch_id": epoch_id}
                try:
                    bundle = cls._bundle_builder.build_bundle(epoch_start=epoch_id, persist=True)
                except _evidence_bundle_error_type() as exc:
                    return {"ok": False, "error": "bundle_export_failed", "epoch_id": epoch_id, "detail": str(exc)}
                return {
                    "ok": True,
                    "epoch_id": epoch_id,
                    "bundle_id": bundle.get("bundle_id", ""),
                    "export_metadata": bundle.get("export_metadata", {}),
                    "epoch": epoch,
                }

            @classmethod
            def _replay_diff_export(cls, epoch_id: str) -> Dict:
                return replay_diff_export(epoch_id=epoch_id, replay_diff=cls._replay_diff, bundle_builder=cls._bundle_builder)

            @classmethod
            def _replay_diff(cls, epoch_id: str) -> Dict:
                epoch = cls._replay_engine.reconstruct_epoch(epoch_id)
                if not epoch.get("bundles") and not epoch.get("initial_state") and not epoch.get("final_state"):
                    return {"ok": False, "error": "epoch_not_found", "epoch_id": epoch_id}
                initial_state = epoch.get("initial_state") or {}
                final_state = epoch.get("final_state") or {}
                initial_keys = set(initial_state.keys())
                final_keys = set(final_state.keys())
                changed_keys = sorted(k for k in initial_keys & final_keys if initial_state.get(k) != final_state.get(k))
                added_keys = sorted(final_keys - initial_keys)
                removed_keys = sorted(initial_keys - final_keys)
                return {
                    "ok": True,
                    "epoch_id": epoch_id,
                    "initial_fingerprint": cls._state_fingerprint(initial_state),
                    "final_fingerprint": cls._state_fingerprint(final_state),
                    "changed_keys": changed_keys,
                    "added_keys": added_keys,
                    "removed_keys": removed_keys,
                    "semantic_drift": cls._semantic_drift(changed_keys=changed_keys, added_keys=added_keys, removed_keys=removed_keys),
                    "epoch_chain_anchor": cls._epoch_chain_anchors(cls._evolution_timeline()).get(epoch_id, {}),
                    "bundle_count": len(epoch.get("bundles") or []),
                    "replay_proof": cls._replay_proof_status(epoch_id),
                    "lineage_chain": cls._lineage_chain_for_epoch(epoch_id),
                }

            @classmethod
            def _lineage_chain_for_epoch(cls, epoch_id: str) -> Dict[str, object]:
                epoch_events = cls._replay_engine.ledger.read_epoch(epoch_id)
                all_entries = cls._replay_engine.ledger.read_all()
                by_mutation_id: Dict[str, Dict[str, object]] = {}
                for entry in all_entries:
                    if not isinstance(entry, dict):
                        continue
                    payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
                    certificate = payload.get("certificate") if isinstance(payload.get("certificate"), dict) else {}
                    mutation_id = str(payload.get("mutation_id") or payload.get("bundle_id") or certificate.get("mutation_id") or certificate.get("bundle_id") or "").strip()
                    if mutation_id:
                        by_mutation_id[mutation_id] = entry

                mutations: List[Dict[str, object]] = []
                seen: set[str] = set()
                for entry in epoch_events:
                    if not isinstance(entry, dict) or entry.get("type") != "MutationBundleEvent":
                        continue
                    resolved = resolve_certified_ancestor_path(entry)
                    mutation_id = str(resolved.get("mutation_id") or "").strip()
                    if not mutation_id or mutation_id in seen:
                        continue
                    seen.add(mutation_id)
                    ancestor_chain = [str(item) for item in resolved.get("ancestor_chain", []) if str(item)]
                    parent_mutation_id = str(resolved.get("parent_mutation_id") or "").strip()
                    if not ancestor_chain and parent_mutation_id:
                        inferred: List[str] = []
                        cursor = parent_mutation_id
                        guard = 0
                        while cursor and guard < 64 and cursor not in inferred:
                            inferred.insert(0, cursor)
                            parent_entry = by_mutation_id.get(cursor)
                            if not parent_entry:
                                break
                            parent_payload = parent_entry.get("payload") if isinstance(parent_entry.get("payload"), dict) else {}
                            parent_certificate = parent_payload.get("certificate") if isinstance(parent_payload.get("certificate"), dict) else {}
                            cursor = str(parent_payload.get("parent_mutation_id") or parent_payload.get("parent_bundle_id") or parent_certificate.get("parent_mutation_id") or parent_certificate.get("parent_bundle_id") or "").strip()
                            guard += 1
                        ancestor_chain = inferred
                    mutations.append(
                        {
                            "mutation_id": mutation_id,
                            "parent_mutation_id": parent_mutation_id,
                            "ancestor_chain": ancestor_chain,
                            "certified_signature": str(resolved.get("certified_signature") or ""),
                        }
                    )
                return {"epoch_id": epoch_id, "mutations": mutations}

            @staticmethod
            def _replay_proof_status(epoch_id: str) -> Dict:
                proof_path = _replay_proofs_dir() / f"{epoch_id}.replay_attestation.v1.json"
                if not proof_path.exists():
                    return {
                        "reference": str(proof_path),
                        "exists": False,
                        "verification": {"ok": False, "error": "proof_not_found"},
                    }
                try:
                    bundle = load_replay_proof(proof_path)
                except (OSError, json.JSONDecodeError):
                    return {
                        "reference": str(proof_path),
                        "exists": True,
                        "verification": {"ok": False, "error": "invalid_proof_bundle"},
                    }
                return {
                    "reference": str(proof_path),
                    "exists": True,
                    "verification": verify_replay_proof_bundle(bundle),
                }

            @staticmethod
            def _semantic_drift_class_for_key(key: str) -> str:
                normalized = key.strip().lower()
                governance_prefixes = ("constitution", "policy", "governance", "founders_law", "founderslaw")
                trait_prefixes = ("trait", "traits")
                runtime_artifact_prefixes = (
                    "runtime",
                    "artifact",
                    "artifacts",
                    "checkpoint",
                    "checkpoints",
                    "metric",
                    "metrics",
                    "telemetry",
                )
                config_prefixes = ("config", "settings", "env", "feature_flags")

                if normalized.startswith(governance_prefixes) or "constitution" in normalized or "policy" in normalized:
                    return "governance_drift"
                if normalized.startswith(trait_prefixes):
                    return "trait_drift"
                if normalized.startswith(runtime_artifact_prefixes):
                    return "runtime_artifact_drift"
                if normalized.startswith(config_prefixes):
                    return "config_drift"
                return "uncategorized_drift"

            @classmethod
            def _semantic_drift(cls, *, changed_keys: List[str], added_keys: List[str], removed_keys: List[str]) -> Dict:
                all_keys = sorted(set(changed_keys) | set(added_keys) | set(removed_keys))
                assignments: Dict[str, str] = {}
                class_counts = {drift_class: 0 for drift_class in SEMANTIC_DRIFT_CLASSES}
                for key in all_keys:
                    drift_class = cls._semantic_drift_class_for_key(key)
                    assignments[key] = drift_class
                    class_counts[drift_class] += 1
                return {"class_counts": class_counts, "per_key": assignments}

            @classmethod
            def _replay_divergence(cls) -> Dict:
                return replay_divergence(
                    metrics_module=metrics,
                    normalize_event_type=normalize_event_type,
                    replay_divergence_event=EVENT_TYPE_REPLAY_DIVERGENCE,
                    replay_failure_event=EVENT_TYPE_REPLAY_FAILURE,
                    lineage_v2=lineage_v2,
                    replay_proof_status=cls._replay_proof_status,
                )

            @staticmethod
            def _evolution_timeline() -> List[Dict]:
                return evolution_timeline(lineage_v2)

            @staticmethod
            def _evidence_graph_projection(*, epoch_id: str, limit: int) -> Dict[str, Any]:
                return build_evidence_graph_projection(lineage_v2, epoch_id=epoch_id, limit=limit)

            @staticmethod
            def _series_confidence_band(values: List[float]) -> Dict[str, float]:
                if not values:
                    return {"low": 0.0, "high": 0.0, "mean": 0.0, "sample_size": 0}
                mean = sum(values) / len(values)
                spread = (sum((value - mean) ** 2 for value in values) / len(values)) ** 0.5
                return {
                    "low": round(mean - (1.96 * spread), 6),
                    "high": round(mean + (1.96 * spread), 6),
                    "mean": round(mean, 6),
                    "sample_size": len(values),
                }

            @classmethod
            def _mutation_roi_projection(cls) -> Dict[str, object]:
                timeline = cls._evolution_timeline()
                recent = timeline[-24:]
                gains = [float(item.get("fitness_score", 0.0)) for item in recent]
                if len(gains) >= 2:
                    slope = (gains[-1] - gains[0]) / max(1, len(gains) - 1)
                else:
                    slope = 0.0
                projected = round((gains[-1] if gains else 0.0) + (slope * 6), 6)
                return {
                    "window": len(recent),
                    "trend_slope": round(slope, 6),
                    "forecast_horizon": 6,
                    "forecast_roi": projected,
                    "confidence_band": cls._series_confidence_band(gains),
                }

            @classmethod
            def _lineage_trajectory_projection(cls) -> Dict[str, object]:
                timeline = cls._evolution_timeline()
                recent = timeline[-24:]
                applied_rate = 0.0
                if recent:
                    applied_rate = sum(1 for item in recent if bool(item.get("applied", False))) / len(recent)
                risk_counts: Dict[str, int] = {}
                for item in recent:
                    risk_tier = str(item.get("risk_tier", "unknown")).lower()
                    risk_counts[risk_tier] = risk_counts.get(risk_tier, 0) + 1
                dominant_risk_tier = max(risk_counts, key=risk_counts.get) if risk_counts else "unknown"
                return {
                    "window": len(recent),
                    "applied_rate": round(applied_rate, 6),
                    "dominant_risk_tier": dominant_risk_tier,
                    "risk_distribution": dict(sorted(risk_counts.items())),
                    "trajectory": "stabilizing" if applied_rate >= 0.75 else "volatile",
                }

            @classmethod
            def _projection_confidence_bands(cls) -> Dict[str, object]:
                timeline = cls._evolution_timeline()
                recent = timeline[-24:]
                roi_series = [float(item.get("fitness_score", 0.0)) for item in recent]
                applied_series = [1.0 if bool(item.get("applied", False)) else 0.0 for item in recent]
                risk_series = [
                    1.0
                    for item in recent
                    if str(item.get("risk_tier", "unknown")).lower() in {"high", "critical", "unknown"}
                ]
                return {
                    "window": len(recent),
                    "bands": {
                        "roi": cls._series_confidence_band(roi_series),
                        "applied_rate": cls._series_confidence_band(applied_series),
                        "risk_instability": cls._series_confidence_band(risk_series),
                    },
                }
            @staticmethod
            def _user_console() -> str:
                return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{HUMAN_DASHBOARD_TITLE}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 0; background: #0e1624; color: #e8eef6; min-height: 100vh; }}
    header {{ background: #17243a; padding: 1rem 1.25rem; }}
    main {{ padding: 1rem 1.25rem 6.25rem; display: grid; gap: 1rem; }}
    section {{ border: 1px solid #273751; border-radius: 8px; padding: 0.9rem; background: #121d30; }}
    h1, h2, h3 {{ margin: 0 0 0.75rem; }}
    h1 {{ font-size: 1.3rem; }}
    h2 {{ font-size: 1rem; color: #9ac0ff; }}
    h3 {{ font-size: 0.9rem; color: #bcd4ff; margin-top: 0.9rem; }}
    pre {{ overflow-x: auto; white-space: pre-wrap; margin: 0; }}
    .meta {{ color: #a8b8cc; font-size: 0.9rem; margin-top: 0.3rem; }}
    .meta-row {{ display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem 0.8rem; margin-top: 0.45rem; }}
    .meta-select {{ background: #0a1422; color: #e8eef6; border: 1px solid #2f4768; border-radius: 6px; padding: 0.25rem 0.45rem; }}
    .floating-panel {{ position: fixed; right: 1rem; bottom: 1rem; width: min(420px, calc(100vw - 2rem)); z-index: 20; border: 1px solid #2f4768; border-radius: 10px; background: #0f1d30; box-shadow: 0 12px 30px rgba(0,0,0,0.45); }}
    .floating-header {{ cursor: move; display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; background: #18314d; padding: 0.55rem 0.7rem; border-bottom: 1px solid #2f4768; border-top-left-radius: 10px; border-top-right-radius: 10px; }}
    .floating-body {{ padding: 0.7rem; display: grid; gap: 0.6rem; }}
    .floating-panel.collapsed .floating-body {{ display: none; }}
    .floating-label {{ font-size: 0.82rem; color: #b8cae1; }}
    .floating-input, .floating-select, .floating-textarea {{ width: 100%; background: #0a1422; color: #e8eef6; border: 1px solid #2f4768; border-radius: 6px; padding: 0.45rem; box-sizing: border-box; }}
    .floating-textarea {{ min-height: 70px; resize: vertical; }}
    .floating-actions {{ display: flex; gap: 0.5rem; }}
    .floating-btn {{ border: 1px solid #3f5f89; color: #e6f0ff; background: #1f3555; padding: 0.45rem 0.7rem; border-radius: 6px; cursor: pointer; }}
    .floating-status {{ font-size: 0.8rem; color: #9cc0f5; white-space: pre-wrap; }}
    .view-nav {{ display: flex; gap: 0.5rem; margin-top: 0.75rem; flex-wrap: wrap; }}
    .view-btn {{ border: 1px solid #345077; background: #14243a; color: #dbe9ff; padding: 0.4rem 0.65rem; border-radius: 6px; cursor: pointer; }}
    .view-btn.active {{ background: #28508a; border-color: #3e6db2; }}
    .view {{ display: none; gap: 1rem; }}
    .view.active {{ display: grid; }}
    .context-strip {{ display: flex; gap: 0.5rem; flex-wrap: wrap; }}
    .context-pill {{ border: 1px solid #2f4768; border-radius: 999px; padding: 0.25rem 0.55rem; font-size: 0.82rem; color: #c4d8f5; background: #101d31; }}
    .primary-card {{ border: 1px solid #3d5f90; background: linear-gradient(135deg, #10223b 0%, #172f4c 100%); }}
    .primary-headline {{ font-size: 1.1rem; font-weight: 700; margin-bottom: 0.4rem; }}
    .primary-reason {{ color: #bbd3f3; margin-bottom: 0.6rem; }}
    .primary-cta {{ border: 1px solid #4876b9; background: #24528f; color: #f2f7ff; border-radius: 6px; padding: 0.45rem 0.8rem; cursor: pointer; }}
    .quick-actions {{ display: flex; gap: 0.5rem; flex-wrap: wrap; }}
    .quick-action {{ border: 1px solid #3f5f89; background: #18304d; color: #dbe9ff; border-radius: 8px; padding: 0.42rem 0.75rem; cursor: pointer; transition: transform 120ms ease, box-shadow 120ms ease; }}
    .quick-action:hover {{ transform: translateY(-1px); box-shadow: 0 6px 14px rgba(17,35,58,0.45); }}
    .brief-grid {{ display: grid; gap: 0.5rem; }}
    .brief-summary {{ font-size: 0.84rem; color: #c7d8f0; }}
    .brief-alert-list {{ display: grid; gap: 0.45rem; }}
    .brief-alert {{ border: 1px solid #38577d; border-radius: 8px; padding: 0.5rem; background: #0f2034; }}
    .brief-alert.critical {{ border-color: #9c3f3f; background: #2a1717; }}
    .brief-alert.warning {{ border-color: #8a6a31; background: #2b2314; }}
    .brief-alert-title {{ font-size: 0.82rem; font-weight: 700; }}
    .brief-chip-row {{ margin-top: 0.35rem; display: flex; gap: 0.35rem; flex-wrap: wrap; }}
    .brief-chip {{ border: 1px solid #3f5f89; border-radius: 999px; background: #173251; color: #dbe9ff; padding: 0.2rem 0.5rem; font-size: 0.74rem; cursor: pointer; }}
    .brief-controls {{ display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: center; }}
    .action-grid {{ display: grid; gap: 0.7rem; }}
    .action-card {{ border: 1px solid #2e4464; background: #0d192a; border-radius: 8px; padding: 0.65rem; display: grid; gap: 0.55rem; }}
    .action-card h3 {{ margin: 0; font-size: 0.95rem; }}
    .action-desc {{ margin: 0; color: #b7c9e2; font-size: 0.86rem; }}
    .action-estimate {{ font-size: 0.8rem; color: #8db2e8; }}
    .action-inputs {{ border: 1px solid #2e4464; border-radius: 6px; padding: 0.4rem 0.5rem; }}
    .action-inputs summary {{ cursor: pointer; color: #9ac0ff; font-size: 0.82rem; }}
    .action-input-list {{ margin-top: 0.45rem; display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 0.4rem; }}
    .action-field {{ display: grid; gap: 0.2rem; }}
    .action-field span {{ font-size: 0.72rem; color: #a8bddc; }}
    .action-field input, .action-field textarea {{ width: 100%; box-sizing: border-box; background: #0a1422; color: #e8eef6; border: 1px solid #2f4768; border-radius: 6px; padding: 0.4rem; }}
    .action-field textarea {{ min-height: 58px; resize: vertical; }}
    .action-footer {{ display: flex; justify-content: space-between; align-items: center; gap: 0.55rem; }}
    .action-status {{ font-size: 0.78rem; color: #9cc0f5; white-space: pre-wrap; }}
    .action-run {{ border: 1px solid #3f5f89; color: #e6f0ff; background: #1f3555; padding: 0.38rem 0.62rem; border-radius: 6px; cursor: pointer; }}
    .action-card.executing {{ border-color: #557fb9; background: #10233d; }}
    .action-card.executing .action-inputs {{ opacity: 0.5; pointer-events: none; }}
    .action-card.done {{ border-color: #2c6f4f; }}
    .execution-panel {{ border: 1px solid #355179; border-radius: 8px; padding: 0.55rem; background: #0c1829; display: grid; gap: 0.5rem; }}
    .execution-panel.hidden {{ display: none; }}
    .execution-summary {{ font-size: 0.85rem; color: #d8e7ff; }}
    .execution-progress {{ width: 100%; }}
    details.execution-raw summary {{ cursor: pointer; color: #9ac0ff; font-size: 0.8rem; }}
    .execution-actions {{ display: flex; gap: 0.5rem; }}
    .history-toolbar {{ display: flex; flex-wrap: wrap; gap: 0.6rem; align-items: end; margin-bottom: 0.8rem; }}
    .history-toolbar label {{ font-size: 0.78rem; color: #b8cae1; display: grid; gap: 0.25rem; min-width: 150px; }}
    .history-toolbar input, .history-toolbar select {{ background: #0a1422; color: #e8eef6; border: 1px solid #2f4768; border-radius: 6px; padding: 0.4rem; }}
    .history-items {{ display: grid; gap: 0.6rem; }}
    .history-item {{ border: 1px solid #2d4260; border-radius: 8px; background: #0c1728; padding: 0.65rem; }}
    .history-item-header {{ display: flex; justify-content: space-between; gap: 0.5rem; align-items: center; }}
    .history-item-title {{ font-weight: 600; color: #d7e8ff; }}
    .history-item-meta {{ font-size: 0.78rem; color: #9fb4d0; margin-top: 0.2rem; }}
    .history-item-actions {{ display: flex; gap: 0.4rem; flex-wrap: wrap; }}
    .history-item-actions button {{ border: 1px solid #3f5f89; color: #dbe9ff; background: #18304f; padding: 0.3rem 0.55rem; border-radius: 6px; cursor: pointer; font-size: 0.76rem; }}
    .history-item details {{ margin-top: 0.45rem; }}
    .insight-card {{ border: 1px solid #2e4464; background: #0d192a; border-radius: 8px; padding: 0.65rem; margin-bottom: 0.6rem; }}
    .insight-card h3 {{ margin: 0 0 0.3rem 0; font-size: 0.92rem; }}
    .insight-card p {{ margin: 0; color: #b7c9e2; font-size: 0.82rem; }}
    .insight-card details {{ margin-top: 0.4rem; }}

    .replay-inspector {{ border-top: 1px solid #2a3d57; margin-top: 0.6rem; padding-top: 0.6rem; }}
    .replay-status {{ font-size: 0.78rem; margin-bottom: 0.5rem; color: #9fb4d0; }}
    .replay-status.loading {{ color: #f7cb78; }}
    .replay-status.error {{ color: #ff8a8a; }}
    .replay-status.ok {{ color: #8ef0a1; }}
    .replay-chip-row {{ display: flex; flex-wrap: wrap; gap: 0.35rem; margin-bottom: 0.5rem; }}
    .replay-chip {{ border-radius: 999px; border: 1px solid #38577d; padding: 0.22rem 0.5rem; font-size: 0.72rem; background: #0f2034; color: #dbe9ff; }}
    .replay-chip-link {{ cursor: pointer; }}
    .replay-chip-selected {{ border-color: #8ef0a1; box-shadow: 0 0 0 1px #8ef0a1 inset; }}
    .replay-chip-alert {{ border-color: #ff9b77; color: #ffd7c7; }}
    .replay-note {{ font-size: 0.76rem; color: #b7c9e2; margin-bottom: 0.45rem; }}
    .replay-detail {{ max-height: 220px; overflow: auto; font-size: 0.74rem; }}
  
    /* ── GitHub Feed Panel (Phase 78) ─────────────────────────────── */
    .github-feed-toolbar {{ display:flex; align-items:center; gap:0.75rem; margin-bottom:0.75rem; }}
    .github-feed-status  {{ font-size:0.8rem; color:#7090a0; }}
    .feed-refresh-btn    {{ font-size:0.75rem; padding:0.25rem 0.6rem; border:1px solid #2a4060;
                           border-radius:4px; background:#0d1f30; color:#a0c8e8; cursor:pointer; }}
    .feed-refresh-btn:hover {{ background:#1a3050; }}
    .github-feed-list    {{ display:flex; flex-direction:column; gap:0.4rem; max-height:540px;
                           overflow-y:auto; }}
    .feed-empty          {{ color:#506070; font-size:0.85rem; padding:1rem 0; }}
    .feed-event-card     {{ border:1px solid #1e3048; border-radius:6px; padding:0.5rem 0.75rem;
                           background:#0b1a28; display:grid;
                           grid-template-columns:auto 1fr auto; gap:0 0.6rem; align-items:start; }}
    .feed-event-icon     {{ font-size:1rem; line-height:1.4; }}
    .feed-event-body     {{ min-width:0; }}
    .feed-event-type     {{ font-size:0.72rem; font-weight:700; text-transform:uppercase;
                           letter-spacing:0.04em; color:#4a90c0; }}
    .feed-event-detail   {{ font-size:0.82rem; color:#c0d8e8; white-space:nowrap;
                           overflow:hidden; text-overflow:ellipsis; }}
    .feed-event-meta     {{ font-size:0.7rem; color:#506070; white-space:nowrap; }}
    .feed-event-card.push      {{ border-left:3px solid #00d4ff; }}
    .feed-event-card.pr        {{ border-left:3px solid #00ff88; }}
    .feed-event-card.ci        {{ border-left:3px solid #f97316; }}
    .feed-event-card.slash     {{ border-left:3px solid #a855f7; }}
    .feed-event-card.install   {{ border-left:3px solid #f5c842; }}
    .feed-event-card.rejected  {{ border-left:3px solid #ff4466; }}
    </style>
</head>
<body>
  <header>
    <h1>{HUMAN_DASHBOARD_TITLE}</h1>
    <div class="meta">Read-only governance intelligence view plus strict-gated command intent initiator.</div>
    <div class="meta-row" id="contextStrip">
      <label for="modeSwitcher">Profile / Settings mode</label>
      <select id="modeSwitcher" class="meta-select" aria-label="Profile mode selector">
        <option value="builder">Builder</option>
        <option value="automation">Automation</option>
        <option value="analysis">Analysis</option>
        <option value="growth">Growth</option>
      </select>
      <span id="modeSummary" class="meta"></span>
    </div>
    <div class="view-nav" role="tablist" aria-label="Dashboard views">
      <button class="view-btn active" data-view="home" type="button">Home</button>
      <button class="view-btn" data-view="insights" type="button">Insights</button>
      <button class="view-btn" data-view="history" type="button">History</button>
      <button class="view-btn" data-view="github" type="button">⬡ GitHub</button>
    </div>
  </header>


  <div style="display:none">
    <span id="controlStageLabel"></span>
    <progress id="controlStageProgress"></progress>
    <select id="modeSwitcher"></select>
    <div id="view-insights" class="view"></div>
    <div id="tasksActions"></div>
    <div id="insightsActions"></div>
    <div id="insights"></div>
    <div id="executionPanel"></div>
    <div id="executionSummary"></div>
    <pre id="executionRaw"></pre>
    <pre id="uxSummary"></pre>
    <select id="historyTypeFilter"></select>
    <input id="historyDateFrom" />
    <input id="historyDateTo" />
    <template id="actionCardTemplate"></template>
    <span>Cancel action</span><span>Fork action</span><span>Raw execution event payload</span><span>History</span>
  </div>
  <main>
    <div id="view-home" class="view active" role="tabpanel">
      <section class="primary-card">
        <h2>Primary action</h2>
        <div id="homePrimaryHeadline" class="primary-headline">Analyzing current conditions…</div>
        <div id="homePrimaryReason" class="primary-reason">Loading recommendation inputs from live governance endpoints.</div>
        <button id="homePrimaryCta" type="button" class="primary-cta">Open control panel</button>
      </section>
      <section>
        <h2>Context</h2>
        <div class="context-strip">
          <span class="context-pill" id="homeProject">Project: --</span>
          <span class="context-pill" id="homeAgent">Active agent: --</span>
          <span class="context-pill" id="homeMode">Mode: --</span>
          <span class="context-pill" id="homeVersion" title="Live ADAAD + Constitution version">ADAAD v— · Constitution v—</span>
        </div>
      </section>
      <section>
        <h2>Quick actions</h2>
        <div id="homeQuickActions" class="quick-actions"></div>
      </section>
      <section>
        <h2>Daily / Session Brief</h2>
        <div class="brief-controls">
          <label>Frequency
            <select id="briefFrequency" class="meta-select">
              <option value="high">High</option>
              <option value="normal">Normal</option>
              <option value="low">Low</option>
            </select>
          </label>
          <label>Mute scope
            <select id="briefMuteScope" class="meta-select">
              <option value="none">None</option>
              <option value="info">Info only</option>
              <option value="warning">Info + warning</option>
              <option value="all">All</option>
            </select>
          </label>
        </div>
        <div id="sessionBriefCard" class="brief-grid">
          <div id="sessionBriefSummary" class="brief-summary">Loading session brief…</div>
          <div id="sessionBriefAlerts" class="brief-alert-list"></div>
        </div>
      </section>
    </div>
    <div id="view-insights" class="view" role="tabpanel" aria-hidden="true">
      <section id="card-state" data-card-key="state"><h2>System state</h2><pre id="state">Loading...</pre></section>
      <section id="card-intelligence" data-card-key="intelligence"><h2>Intelligence snapshot</h2><pre id="intelligence">Loading...</pre></section>
      <section id="card-risk" data-card-key="risk"><h2>Risk summary</h2><pre id="risk">Loading...</pre></section>
      <section id="card-instability" data-card-key="instability"><h2>Risk instability</h2><pre id="instability">Loading...</pre></section>
      <section id="card-uxSummary" data-card-key="uxSummary"><h2>UX summary</h2><pre id="uxSummary">Loading...</pre></section>
    </div>
    <div id="view-history" class="view" role="tabpanel" aria-hidden="true">
      <section id="card-replay" data-card-key="replay"><h2>Replay divergence</h2><pre id="replay">Loading...</pre>
        <div id="replayInspector" class="replay-inspector">
          <div class="replay-status loading" data-replay-status>Loading replay inspector...</div>
          <div class="replay-chip-row" data-replay-nav></div>
          <div data-replay-body class="replay-body"></div>
        </div>
      </section>
      <section id="card-timeline" data-card-key="timeline">
        <h2>History</h2>
        <div class="history-toolbar">
          <label>Type
            <select id="historyTypeFilter"><option value="all">All event types</option></select>
          </label>
          <label>From
            <input id="historyDateFrom" type="datetime-local" />
          </label>
          <label>To
            <input id="historyDateTo" type="datetime-local" />
          </label>
        </div>
        <div id="historyList" class="history-items">Loading...</div>
      </section>
    </div>
    <section>
      <h2>Tasks</h2>
      <div id="tasksActions" class="action-grid">Loading...</div>
    </section>
    <section>
      <h2>Insights</h2>
      <div id="insights"></div>
      <div id="insightsActions" class="action-grid">Loading...</div>
    </section>
    <div id="view-github" class="view" role="tabpanel" aria-hidden="true">
      <section id="card-github-feed" data-card-key="githubFeed">
        <h2>&#9451; GitHub Feed</h2>
        <div class="github-feed-toolbar">
          <span class="github-feed-status" id="githubFeedStatus">Loading events&hellip;</span>
          <button type="button" id="githubFeedRefresh" class="feed-refresh-btn">&#8635; Refresh</button>
        </div>
        <div id="githubFeedList" class="github-feed-list" role="list" aria-live="polite">
          <div class="feed-empty">No GitHub events recorded yet. Push a commit or open a PR to see events here.</div>
        </div>
      </section>
    </div>
  </main>
  <template id="actionCardTemplate">
    <article class="action-card" data-source="" data-kind="" data-payload="">
      <h3 class="action-title"></h3>
      <p class="action-desc"></p>
      <details class="action-inputs">
        <summary>Inline inputs</summary>
        <div class="action-input-list"></div>
      </details>
      <div class="action-estimate"></div>
      <div class="action-footer">
        <button type="button" class="action-run">Run</button>
        <div class="action-status">Ready.</div>
      </div>
    </article>
  </template>
  <aside id="controlPanel" class="floating-panel" aria-label="Aponi command initiator">
    <div id="controlPanelHeader" class="floating-header">
      <strong>Aponi Guided Assistant</strong>
      <button id="controlToggle" type="button" class="floating-btn">Collapse</button>
    </div>
    <div class="floating-body">
      <div class="floating-label">Command queue status</div>
      <pre id="queueSummary">Loading...</pre>
      <div id="executionPanel" class="execution-panel hidden" aria-live="polite">
        <div id="executionSummary" class="execution-summary">No active execution.</div>
        <details class="execution-raw">
          <summary>Raw execution event payload</summary>
          <pre id="executionRaw">{{}}</pre>
        </details>
        <progress id="executionProgress" class="execution-progress" max="100" value="0"></progress>
        <div id="executionProgressLabel" class="floating-label">0% queued</div>
        <div class="execution-actions">
          <button id="executionCancel" type="button" class="floating-btn">Cancel action</button>
          <button id="executionFork" type="button" class="floating-btn">Fork action</button>
        </div>
      </div>
      <h3>Create a new action</h3>
      <div class="floating-helper">Choose from guided options below. Advanced safeguards are applied automatically.</div>
      <div id="controlGuidance" class="guidance-pills"></div>
      <label class="floating-label" for="controlType">What do you want to do?</label>
      <select id="controlType" class="floating-select">
        <option value="create_agent">create_agent</option>
        <option value="run_task">run_task</option>
      </select>
      <label class="floating-label" for="controlAgentId">Agent name</label>
      <input id="controlAgentId" class="floating-input" value="triage_agent" />
      <label class="floating-label" for="controlGovernance">Safety level</label>
      <select id="controlGovernance" class="floating-select">
        <option value="strict">Strict</option>
        <option value="high-assurance">High Assurance</option>
      </select>
      <label class="floating-label" for="controlSkillProfile">Skill set</label>
      <select id="controlSkillProfile" class="floating-select"></select>
      <label class="floating-label" for="controlKnowledgeDomain">Knowledge area</label>
      <select id="controlKnowledgeDomain" class="floating-select"></select>
      <label class="floating-label" for="controlCapabilities">Capabilities to use (select one or more)</label>
      <select id="controlCapabilities" class="floating-select" multiple></select>
      <label class="floating-label" for="controlAbility">Ability to apply</label>
      <select id="controlAbility" class="floating-select"></select>
      <label class="floating-label" for="controlTask">Suggested task / purpose</label>
      <select id="controlTask" class="floating-select"></select>
      <label class="floating-label" for="controlGeneralPrompt">General cockpit prompt</label>
      <textarea id="controlGeneralPrompt" class="floating-input" rows="4" placeholder="Describe your intent in natural language. The planner will map it to governed command fields."></textarea>
      <div id="proposalSimulationPanel" class="simulation-panel" aria-live="polite">
        <div class="floating-label">Inline proposal simulation</div>
        <div class="simulation-grid">
          <label class="floating-label" for="simulationEpochStart">Epoch start<input id="simulationEpochStart" class="floating-input" type="number" min="0" value="1" /></label>
          <label class="floating-label" for="simulationEpochEnd">Epoch end<input id="simulationEpochEnd" class="floating-input" type="number" min="0" value="5" /></label>
        </div>
        <label class="floating-label" for="simulationConstraints">Simulation constraints (JSON array)</label>
        <textarea id="simulationConstraints" class="floating-textarea" rows="4"></textarea>
        <div class="floating-actions">
          <button id="simulationRun" type="button" class="floating-btn">Run simulation</button>
          <button id="simulationRefresh" type="button" class="floating-btn">Refresh result</button>
        </div>
        <div id="simulationStatus" class="floating-status">Simulation idle.</div>
        <pre id="simulationResults">No simulation run yet.</pre>
        <div id="simulationProvenance" class="simulation-provenance"></div>
      </div>
      <div class="floating-actions">
        <button id="controlPromptRun" type="button" class="floating-btn">Analyze prompt</button>
        <button id="queueSubmit" type="button" class="floating-btn">Submit action</button>
        <button id="queueRefresh" type="button" class="floating-btn">Refresh status</button>
      </div>
      <div class="floating-label">Command lifecycle</div>
      <div id="controlStageLabel" class="floating-status">Stage: select</div>
      <progress id="controlStageProgress" max="4" value="0" style="width:100%;"></progress>
      <div id="controlStatus" class="floating-status">Awaiting command input.</div>
    </div>
  </aside>
  <script src="/ui/aponi/replay_inspector.js"></script>
  <script src="/ui/aponi.js"></script>
</body>
</html>
"""

            @staticmethod
            def _user_console_js() -> str:
                return """const STORAGE_KEY = 'aponi.control.panel.v1';
const DRAFT_STORAGE_KEY = 'aponi.control.draft.v1';
const MODE_STORAGE_KEY = 'aponi.user.mode.v1';
const UX_SESSION_KEY = 'aponi.ux.session.v1';
const BRIEF_SETTINGS_KEY = 'aponi.brief.settings.v1';
let uxFirstSuccessMarked = false;
const DEFAULT_MODE = 'builder';
const QUICK_ACTION_LIMIT = 3;
const EXECUTION_POLL_MS = 1500;
const REFRESH_TIMEOUT_MS = 7000;
const QUEUE_REFRESH_TIMEOUT_MS = 7000;
const REFRESH_BASE_DELAY_MS = 5000;
const QUEUE_BASE_DELAY_MS = EXECUTION_POLL_MS || 4000;
const REFRESH_MAX_BACKOFF_MULTIPLIER = 6;
const UNDO_TOAST_MS = 5000;
const CONTROL_AGENT_ID_RE = /^[a-z0-9_-]{3,64}$/;
const ALLOWED_GOVERNANCE_PROFILES = ['strict', 'high-assurance'];
const CONTROL_CAPABILITIES_MAX = 8;
const CONTROL_MODES_LIST = ['builder', 'automation', 'analysis', 'growth'];
const MODE_CONFIG = {
  builder: { summary: 'Design-first view for creating governed agents.', defaultType: 'create_agent', showQueueComposer: true, cardOrder: ['state','timeline','intelligence','risk','instability','replay'] },
  automation: { summary: 'Execution-first view for task dispatch and queue monitoring.', defaultType: 'run_task', showQueueComposer: true, cardOrder: ['state','intelligence','risk','timeline','instability','replay'] },
  analysis: { summary: 'Investigation-first view focused on risk and replay analysis.', defaultType: 'run_task', showQueueComposer: false, cardOrder: ['risk','instability','replay','intelligence','timeline','state'] },
  growth: { summary: 'Trajectory-first view focused on evolution and capability growth.', defaultType: 'create_agent', showQueueComposer: true, cardOrder: ['timeline','state','intelligence','risk','instability','replay'] },
};

const executionState = {
  activeEntry: null,
  lastFingerprint: '',
};

const controlAuthState = { token: '', expiresAtMs: 0 };

const undoManager = { stack: [], toastTimer: null };

let isRefreshing = false;
let isQueueRefreshing = false;
let refreshRequestId = 0;
let queueRequestId = 0;
let refreshTimer = null;
let queueTimer = null;
let refreshFailureCount = 0;
let queueFailureCount = 0;
let replayInspector = null;
let previousBriefSignals = null;

// === Safe DOM Rendering Utilities ===
// SECURITY: Do not use innerHTML for any API-derived content.
// All dynamic DOM updates must use el() or textContent.
const SAFE_ATTRS = Object.freeze(new Set(['id', 'class', 'value', 'type', 'role', 'name', 'for', 'title']));
const SAFE_TAGS = Object.freeze(new Set(['div', 'span', 'button', 'article', 'details', 'summary', 'pre', 'h3', 'p', 'select', 'option', 'label', 'input', 'textarea']));

function isSafeAttrName(name) {
  if (typeof name !== 'string' || !name) return false;
  return SAFE_ATTRS.has(name) || name.startsWith('data-') || name.startsWith('aria-');
}

function safeArray(value) {
  return Array.isArray(value) ? value : [];
}

function safeText(value) {
  if (value === null || value === undefined) return '';
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value);
    } catch (_) {
      return '[unserializable object]';
    }
  }
  return String(value);
}

function el(tag, options = {}) {
  if (typeof tag !== 'string') throw new Error('Invalid tag type');
  const normalizedTag = tag.toLowerCase();
  if (!SAFE_TAGS.has(normalizedTag)) throw new Error(`Unsafe tag type: ${normalizedTag}`);
  const element = document.createElement(normalizedTag);
  if (options.className) element.className = options.className;
  if (options.id) element.id = options.id;
  if (options.text !== undefined) element.textContent = safeText(options.text);
  if (options.attrs && typeof options.attrs === 'object' && !Array.isArray(options.attrs)) {
    for (const [k, v] of Object.entries(options.attrs)) {
      if (!isSafeAttrName(k)) continue;
      element.setAttribute(k, safeText(v));
    }
  }
  if (Array.isArray(options.children)) {
    for (const child of options.children) {
      if (child instanceof Node) element.appendChild(child);
    }
  }
  return element;
}

function clearNode(node) {
  if (!node) return;
  while (node.firstChild) node.removeChild(node.firstChild);
}

window.trustedTypes?.createPolicy('default', {
  createHTML: () => {
    throw new Error('Dynamic HTML creation blocked.');
  },
});

async function ensureControlAuthToken() {
  const now = Date.now();
  if (controlAuthState.token && controlAuthState.expiresAtMs > now + 5000) return controlAuthState.token;
  const response = await fetch('/control/auth-token', { cache: 'no-store' });
  const payload = await response.json();
  if (!response.ok || !payload.ok || !payload.token) throw new Error('control_auth_unavailable');
  controlAuthState.token = String(payload.token);
  controlAuthState.expiresAtMs = now + (Number(payload.expires_in_seconds || 0) * 1000);
  return controlAuthState.token;
}

async function controlAuthHeaders(extraHeaders = {}) {
  const token = await ensureControlAuthToken();
  const nonce = `nonce-${Date.now()}-${Math.random().toString(16).slice(2, 12)}`;
  return { ...extraHeaders, Authorization: `Bearer ${token}`, 'X-APONI-Nonce': nonce };
}

async function postTelemetry(eventType, payload) {
  try {
    await fetch('/control/telemetry', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_type: eventType, payload: payload || {} }),
    });
  } catch (_) {
    return;
  }
}

function ensureUndoToast() {
  let toastNode = document.getElementById('undoToast');
  if (toastNode) return toastNode;
  toastNode = el('div', { attrs: { id: 'undoToast' } });
  toastNode.style.position = 'fixed';
  toastNode.style.left = '20px';
  toastNode.style.bottom = '20px';
  toastNode.style.background = 'rgba(20, 25, 40, 0.95)';
  toastNode.style.border = '1px solid #406db3';
  toastNode.style.borderRadius = '8px';
  toastNode.style.padding = '10px 12px';
  toastNode.style.color = '#d6e7ff';
  toastNode.style.zIndex = '1000';
  toastNode.style.display = 'none';
  const label = el('span', { attrs: { id: 'undoToastLabel' } });
  const undoBtn = el('button', { className: 'floating-btn', text: 'Undo', attrs: { type: 'button' } });
  undoBtn.style.marginLeft = '10px';
  undoBtn.addEventListener('click', () => undoLatestAction('toast'));
  toastNode.appendChild(label);
  toastNode.appendChild(undoBtn);
  document.body.appendChild(toastNode);
  return toastNode;
}

function showUndoToast(action) {
  const toast = ensureUndoToast();
  const label = document.getElementById('undoToastLabel');
  if (label) label.textContent = action.label;
  toast.style.display = 'block';
  if (undoManager.toastTimer) clearTimeout(undoManager.toastTimer);
  undoManager.toastTimer = setTimeout(() => {
    toast.style.display = 'none';
    postTelemetry('aponi_control_undo_toast_expired', { undo_id: action.id, action_type: action.type });
  }, UNDO_TOAST_MS);
}

function registerUndoAction(action) {
  const stamp = Date.now();
  const undoAction = { id: `undo-${stamp}-${Math.random().toString(16).slice(2, 8)}`, created_at: stamp, ...action };
  undoManager.stack.push(undoAction);
  showUndoToast(undoAction);
  postTelemetry('aponi_control_undo_registered', { undo_id: undoAction.id, action_type: undoAction.type });
}

async function undoLatestAction(source) {
  const action = undoManager.stack.pop();
  const toast = document.getElementById('undoToast');
  if (!action) { if (toast) toast.style.display = 'none'; return; }
  try {
    await action.undo();
    postTelemetry('aponi_control_undo_executed', { undo_id: action.id, action_type: action.type, source: source || 'unknown' });
  } catch (err) {
    postTelemetry('aponi_control_undo_failed', { undo_id: action.id, action_type: action.type, error: String(err) });
  }
  if (toast) toast.style.display = 'none';
}

function currentMode() {
  const raw = localStorage.getItem(MODE_STORAGE_KEY) || DEFAULT_MODE;
  return Object.prototype.hasOwnProperty.call(MODE_CONFIG, raw) ? raw : DEFAULT_MODE;
}

function modeConfig(mode) { return MODE_CONFIG[mode] || MODE_CONFIG[DEFAULT_MODE]; }

function reorderHomeCards(mode) {
  const host = document.querySelector('main');
  if (!host) return;
  const config = modeConfig(mode);
  const allCards = Array.from(host.querySelectorAll('[data-card-key]'));
  const byKey = new Map(allCards.map((card) => [card.getAttribute('data-card-key'), card]));
  const ordered = [];
  for (const key of config.cardOrder || []) {
    const node = byKey.get(key);
    if (node) ordered.push(node);
  }
  for (const card of allCards) if (!ordered.includes(card)) ordered.push(card);
  for (const card of ordered) host.appendChild(card);
}

function applyMode(mode) {
  const config = modeConfig(mode);
  localStorage.setItem(MODE_STORAGE_KEY, mode);
  const switcher = document.getElementById('modeSwitcher');
  if (switcher && switcher.value !== mode) switcher.value = mode;
  const summary = document.getElementById('modeSummary');
  if (summary) summary.textContent = config.summary;
  const typeInput = document.getElementById('controlType');
  if (typeInput && config.defaultType) typeInput.value = config.defaultType;
  const composerHeading = document.querySelector('.floating-body h3');
  const hideComposer = !config.showQueueComposer;
  const composerIds = ['controlType','controlAgentId','controlGovernance','controlSkillProfile','controlKnowledgeDomain','controlCapabilities','controlAbility','controlTask','queueSubmit'];
  if (composerHeading) composerHeading.style.display = hideComposer ? 'none' : '';
  for (const id of composerIds) {
    const node = document.getElementById(id);
    if (!node) continue;
    const label = document.querySelector(`label[for="${id}"]`);
    node.style.display = hideComposer ? 'none' : '';
    if (label) label.style.display = hideComposer ? 'none' : '';
  }
  reorderHomeCards(mode);
  renderControlGuidance();
}

function setupModeSwitcher() {
  const switcher = document.getElementById('modeSwitcher');
  if (!switcher) return;
  switcher.value = currentMode();
  switcher.addEventListener('change', (event) => {
    const selectedMode = String((event.target || {}).value || DEFAULT_MODE);
    applyMode(selectedMode);
  });
  applyMode(currentMode());
}


function renderControlGuidance(extra = {}) {
  const host = document.getElementById('controlGuidance');
  if (!host) return;
  const type = ((document.getElementById('controlType') || {}).value || 'run_task').replace('_', ' ');
  const profile = (document.getElementById('controlSkillProfile') || {}).value || 'not selected';
  const mode = currentMode();
  const safety = (document.getElementById('controlGovernance') || {}).value || 'strict';
  const pills = [
    `Mode: ${mode}`,
    `Action: ${type}`,
    `Skill set: ${profile}`,
    `Safety: ${safety}`,
  ];
  if (typeof extra.capabilityCount === 'number') pills.push(`Capabilities: ${extra.capabilityCount}`);
  clearNode(host);
  pills.forEach((text) => host.appendChild(el('span', { className: 'guidance-pill', text })));
}

function replaceSelectOptions(selectNode, values, { selectedValues = null, emptyLabel = '' } = {}) {
  if (!selectNode) return;
  clearNode(selectNode);
  const selectedSet = selectedValues instanceof Set ? selectedValues : null;
  (Array.isArray(values) ? values : []).forEach((value) => {
    const normalized = safeText(value);
    const option = el('option', { text: normalized, attrs: { value: normalized } });
    if (selectedSet && selectedSet.has(normalized)) option.selected = true;
    selectNode.appendChild(option);
  });
  if (!selectNode.options.length && emptyLabel) {
    selectNode.appendChild(el('option', { text: emptyLabel, attrs: { value: '' } }));
  }
}

function bindComposerPersistence() {
  const ids = ['controlType','controlAgentId','controlGovernance','controlSkillProfile','controlKnowledgeDomain','controlCapabilities','controlAbility','controlTask'];
  ids.forEach((id) => {
    const node = document.getElementById(id);
    if (!node) return;
    node.addEventListener('change', () => {
      persistDraft(readCommandPayload());
      renderControlGuidance();
    });
  });
}


function ensureSelectOption(selectEl, value) {
  if (!selectEl) return;
  const normalized = String(value || '').trim();
  if (!normalized) return;
  const exists = Array.from(selectEl.options || []).some((opt) => opt.value === normalized);
  if (!exists) {
    selectEl.appendChild(el('option', { text: normalized, attrs: { value: normalized } }));
  }
  selectEl.value = normalized;
}

function paintDraft(payload) {
  const type = document.getElementById('controlType');
  const agentId = document.getElementById('controlAgentId');
  const governance = document.getElementById('controlGovernance');
  const skill = document.getElementById('controlSkillProfile');
  const domain = document.getElementById('controlKnowledgeDomain');
  const caps = document.getElementById('controlCapabilities');
  const ability = document.getElementById('controlAbility');
  const task = document.getElementById('controlTask');
  if (type && payload.type) type.value = payload.type;
  if (agentId && payload.agent_id) agentId.value = payload.agent_id;
  if (governance && payload.governance_profile) governance.value = payload.governance_profile;
  if (skill && payload.skill_profile) skill.value = payload.skill_profile;
  if (domain && payload.knowledge_domain) domain.value = payload.knowledge_domain;
  if (caps && Array.isArray(payload.capabilities)) {
    const selected = new Set(payload.capabilities.map((item) => String(item)));
    Array.from(caps.options || []).forEach((opt) => { opt.selected = selected.has(opt.value); });
  }
  if (ability && payload.ability) ensureSelectOption(ability, payload.ability);
  if (task) ensureSelectOption(task, payload.task || payload.purpose || '');
}

function persistDraft(payload) { localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(payload)); }
function restoreDraft() {
  try {
    const raw = localStorage.getItem(DRAFT_STORAGE_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === 'object') paintDraft(parsed);
  } catch (_) { return; }
}

function activateView(viewName) {
  document.querySelectorAll('[data-view]').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.view === viewName);
  });
  document.querySelectorAll('.view').forEach((viewEl) => {
    const isActive = viewEl.id === `view-${viewName}`;
    viewEl.classList.toggle('active', isActive);
    viewEl.setAttribute('aria-hidden', String(!isActive));
  });
}

function setupViews() {
  document.querySelectorAll('[data-view]').forEach((btn) => {
    btn.addEventListener('click', () => activateView(btn.dataset.view || 'home'));
  });
}

function ensureReplayInspector() {
  if (replayInspector) return replayInspector;
  if (!window.AponiReplayInspector || typeof window.AponiReplayInspector.createInspector !== 'function') return null;
  replayInspector = window.AponiReplayInspector.createInspector('replayInspector');
  return replayInspector;
}

function openControlPanel() {
  const panel = document.getElementById('controlPanel');
  if (!panel) return;
  panel.classList.remove('collapsed');
  const toggle = document.getElementById('controlToggle');
  if (toggle) toggle.textContent = 'Collapse';
  panel.scrollIntoView({ behavior: 'smooth' });
  persistPanelState();
}

async function paint(id, endpoint) {
  const el = document.getElementById(id);
  if (!el) return null;
  try {
    const response = await fetch(endpoint, { cache: 'no-store' });
    if (!response.ok) throw new Error(`endpoint returned HTTP ${response.status}`);
    const payload = await response.json();
    el.textContent = JSON.stringify(payload, null, 2);
    return payload;
  } catch (err) {
    // Sanitize: never surface raw internal error codes (e.g. invalid_json_response) in the UI
    const raw = (err && err.message) ? err.message : String(err);
    const safe = raw
      .replace(/invalid_json_response[^)]*[))]*/gi, 'server_response_error')
      .replace(/unparsabl[a-z]*/gi, 'parse_error')
      .replace(/json_response_must_be_object/gi, 'response_format_error')
      .replace(/provider_request_failed[^.]*[.]?/gi, 'provider_unavailable. ');
    el.textContent = 'Unavailable: ' + endpoint + ' (' + safe.trim() + ')';
    return null;
  }
}

function reorderHomeCards(mode) {
  const host = document.getElementById('view-insights');
  if (!host) return;

  const cards = Array.from(host.querySelectorAll('[data-card-key]'));
  if (!cards.length) return;

  const sortByMode = {
    alpha: (left, right) => {
      const leftKey = left.dataset.cardKey || '';
      const rightKey = right.dataset.cardKey || '';
      return leftKey.localeCompare(rightKey);
    },
    reverse: (left, right) => {
      const leftKey = left.dataset.cardKey || '';
      const rightKey = right.dataset.cardKey || '';
      return rightKey.localeCompare(leftKey);
    },
  };

  const comparator = sortByMode[mode];
  if (!comparator) return;

  cards.sort(comparator);
  cards.forEach((card) => host.appendChild(card));
}

function restorePanelState() {
  const panel = document.getElementById('controlPanel');
  if (!panel) return;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    if (parsed && parsed.collapsed) panel.classList.add('collapsed');
    if (parsed && typeof parsed.right === 'number') panel.style.right = parsed.right + 'px';
    if (parsed && typeof parsed.bottom === 'number') panel.style.bottom = parsed.bottom + 'px';
  } catch (_) {
    return;
  }
}

function persistPanelState() {
  const panel = document.getElementById('controlPanel');
  if (!panel) return;
  const payload = {
    collapsed: panel.classList.contains('collapsed'),
    right: parseInt(panel.style.right || '16', 10),
    bottom: parseInt(panel.style.bottom || '16', 10),
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
}

function setupFloatingPanel() {
  const panel = document.getElementById('controlPanel');
  const header = document.getElementById('controlPanelHeader');
  const toggle = document.getElementById('controlToggle');
  if (!panel || !header || !toggle) return;
  restorePanelState();
  toggle.textContent = panel.classList.contains('collapsed') ? 'Expand' : 'Collapse';
  toggle.addEventListener('click', () => {
    const wasCollapsed = panel.classList.contains('collapsed');
    panel.classList.toggle('collapsed');
    toggle.textContent = panel.classList.contains('collapsed') ? 'Expand' : 'Collapse';
    persistPanelState();
    markInteraction('panel_toggle');
    registerUndoAction({
      type: 'quick_toggle',
      label: `Panel ${panel.classList.contains('collapsed') ? 'collapsed' : 'expanded'}.`,
      undo: async () => {
        markUndo('panel_toggle', { collapsed: wasCollapsed });
        panel.classList.toggle('collapsed', wasCollapsed);
        toggle.textContent = panel.classList.contains('collapsed') ? 'Expand' : 'Collapse';
        persistPanelState();
      },
    });
  });

  let dragging = false;
  let startX = 0;
  let startY = 0;
  let startRight = 16;
  let startBottom = 16;

  header.addEventListener('mousedown', (event) => {
    dragging = true;
    startX = event.clientX;
    startY = event.clientY;
    startRight = parseInt(panel.style.right || '16', 10);
    startBottom = parseInt(panel.style.bottom || '16', 10);
  });
  window.addEventListener('mousemove', (event) => {
    if (!dragging) return;
    const dx = event.clientX - startX;
    const dy = event.clientY - startY;
    panel.style.right = Math.max(10, startRight - dx) + 'px';
    panel.style.bottom = Math.max(10, startBottom - dy) + 'px';
  });
  window.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    persistPanelState();
  });
}

async function refreshSkillProfiles() {
  const profileSelect = document.getElementById('controlSkillProfile');
  const domainSelect = document.getElementById('controlKnowledgeDomain');
  const capabilityInput = document.getElementById('controlCapabilities');
  const abilityInput = document.getElementById('controlAbility');
  const typeSelect = document.getElementById('controlType');
  const taskSelect = document.getElementById('controlTask');
  const status = document.getElementById('controlStatus');
  if (!profileSelect || !domainSelect || !capabilityInput || !abilityInput || !taskSelect) return;
  try {
    const [matrixResponse, templatesResponse] = await Promise.all([
      fetch('/control/capability-matrix', { cache: 'no-store' }),
      fetch('/control/templates', { cache: 'no-store' }),
    ]);
    if (!matrixResponse.ok) throw new Error(`capability-matrix returned HTTP ${matrixResponse.status}`);
    const payload = await matrixResponse.json();
    const templatePayload = templatesResponse.ok ? await templatesResponse.json() : { templates: {} };
    const templates = templatePayload && templatePayload.templates ? templatePayload.templates : {};
    const matrix = payload && payload.matrix ? payload.matrix : {};
    const keys = Object.keys(matrix).sort();
    if (!keys.length) {
      if (status) status.textContent = 'No governed skill profiles were returned by /control/capability-matrix.';
      return;
    }
    replaceSelectOptions(profileSelect, keys);

    const applyProfile = () => {
      const selected = profileSelect.value;
      const selectedType = (typeSelect && typeSelect.value) || 'run_task';
      const profile = matrix[selected] || {};
      const domains = safeArray(profile.knowledge_domains);
      const abilities = safeArray(profile.abilities);
      const capabilities = safeArray(profile.capabilities);
      const template = (templates[selected] && templates[selected][selectedType]) || {};
      const taskOptions = [];
      if (typeof template.task === 'string' && template.task.trim()) taskOptions.push(template.task.trim());
      if (typeof template.purpose === 'string' && template.purpose.trim()) taskOptions.push(template.purpose.trim());
      if (!taskOptions.length && abilities.length && domains.length) taskOptions.push(`${abilities[0]} ${domains[0]} updates`);

      replaceSelectOptions(domainSelect, domains);
      replaceSelectOptions(abilityInput, abilities);
      replaceSelectOptions(capabilityInput, capabilities, { selectedValues: new Set(capabilities.map((item) => safeText(item))) });
      replaceSelectOptions(taskSelect, taskOptions, { emptyLabel: 'No task presets available' });
      renderControlGuidance({ capabilityCount: capabilities.length });
    };

    profileSelect.onchange = applyProfile;
    if (typeSelect) {
      typeSelect.onchange = applyProfile;
      typeSelect.addEventListener('change', () => renderControlGuidance({ capabilityCount: Array.isArray((matrix[profileSelect.value] || {}).capabilities) ? (matrix[profileSelect.value] || {}).capabilities.length : 0 }));
    }
    applyProfile();
    restoreDraft();
  } catch (err) {
    if (status) status.textContent = 'Failed to load skill profiles: ' + err;
  }
}

function executionFingerprint(entry) {
  if (!entry || typeof entry !== 'object') return '';
  return `${entry.command_id || ''}:${entry.status || ''}:${entry.digest || ''}`;
}

function summarizeExecution(entry) {
  if (!entry || typeof entry !== 'object') return 'No active execution.';
  const payload = entry.payload || {};
  const parts = [payload.type || 'action', payload.agent_id ? `agent=${payload.agent_id}` : '', payload.ability ? `ability=${payload.ability}` : ''].filter(Boolean);
  return `${parts.join(' · ') || 'Queued action'} · status=${entry.status || 'queued'} · command=${entry.command_id || 'unknown'}`;
}

function setExecutionPanelVisibility(visible) {
  const panel = document.getElementById('executionPanel');
  if (!panel) return;
  panel.classList.toggle('hidden', !visible);
}

function renderExecution(entry) {
  const summaryEl = document.getElementById('executionSummary');
  const rawEl = document.getElementById('executionRaw');
  const progressEl = document.getElementById('executionProgress');
  const progressLabel = document.getElementById('executionProgressLabel');
  if (!summaryEl || !rawEl || !progressEl || !progressLabel) return;
  if (!entry) { setExecutionPanelVisibility(false); return; }
  setExecutionPanelVisibility(true);
  summaryEl.textContent = summarizeExecution(entry);
  rawEl.textContent = JSON.stringify(entry, null, 2);
  const status = String(entry.status || 'queued').toLowerCase();
  const progressMap = { queued: 10, pending: 20, running: 60, completed: 100, complete: 100, done: 100, failed: 100, error: 100, canceled: 100, cancelled: 100 };
  const progressValue = Number.isFinite(entry.progress_percent) ? Math.max(0, Math.min(100, Number(entry.progress_percent))) : (progressMap[status] || 15);
  progressEl.value = progressValue;
  progressLabel.textContent = `${progressValue}% ${status}`;
}

function hydrateForkDraft(entry) {
  if (!entry || typeof entry !== 'object') return;
  const payload = entry.payload || {};
  const typeEl = document.getElementById('controlType');
  const agentEl = document.getElementById('controlAgentId');
  const governanceEl = document.getElementById('controlGovernance');
  const profileEl = document.getElementById('controlSkillProfile');
  const domainEl = document.getElementById('controlKnowledgeDomain');
  const capsEl = document.getElementById('controlCapabilities');
  const abilityEl = document.getElementById('controlAbility');
  const taskEl = document.getElementById('controlTask');
  if (typeEl && payload.type) typeEl.value = payload.type;
  if (agentEl && payload.agent_id) agentEl.value = payload.agent_id;
  if (governanceEl && payload.governance_profile) governanceEl.value = payload.governance_profile;
  if (profileEl && payload.skill_profile) profileEl.value = payload.skill_profile;
  if (domainEl && payload.knowledge_domain) domainEl.value = payload.knowledge_domain;
  if (capsEl && Array.isArray(payload.capabilities)) {
    const selected = new Set(payload.capabilities.map((item) => String(item)));
    Array.from(capsEl.options || []).forEach((opt) => { opt.selected = selected.has(opt.value); });
  }
  if (abilityEl) ensureSelectOption(abilityEl, payload.ability || '');
  if (taskEl) ensureSelectOption(taskEl, payload.task || payload.purpose || '');
}

async function queueExecutionControl(type, activeEntry) {
  const status = document.getElementById('controlStatus');
  if (!activeEntry || !activeEntry.command_id) {
    if (status) status.textContent = `No active command to ${type}.`;
    return;
  }
  const payload = {
    type: 'run_task',
    agent_id: (activeEntry.payload && activeEntry.payload.agent_id) || 'triage_agent',
    governance_profile: (activeEntry.payload && activeEntry.payload.governance_profile) || 'strict',
    skill_profile: (activeEntry.payload && activeEntry.payload.skill_profile) || ((document.getElementById('controlSkillProfile') || {}).value || ''),
    knowledge_domain: (activeEntry.payload && activeEntry.payload.knowledge_domain) || ((document.getElementById('controlKnowledgeDomain') || {}).value || ''),
    capabilities: Array.isArray(activeEntry.payload && activeEntry.payload.capabilities) ? activeEntry.payload.capabilities : [],
    ability: type === 'cancel' ? 'cancel_execution' : 'fork_execution',
    task: `${type} execution for ${activeEntry.command_id}`,
    execution_ref: activeEntry.command_id,
    execution_backend: 'queue_bridge',
  };
  try {
    const response = await fetch('/control/queue', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const result = await response.json();
    const statusLabel = response.ok ? '' : `[HTTP ${response.status}] `;
    if (status) status.textContent = statusLabel + JSON.stringify(result, null, 2);
    await refreshControlQueue();
  } catch (err) {
    if (status) status.textContent = `Failed to ${type} execution: ` + err;
  }
}

function wireExecutionActions() {
  document.getElementById('executionCancel')?.addEventListener('click', async () => {
    await queueExecutionControl('cancel', executionState.activeEntry);
  });
  document.getElementById('executionFork')?.addEventListener('click', () => {
    hydrateForkDraft(executionState.activeEntry);
    const status = document.getElementById('controlStatus');
    if (status) status.textContent = 'Fork draft loaded from active execution. Update details and queue intent.';
  });
}

const HISTORY_WINDOW_MS = 10 * 60 * 1000;
const HISTORY_LABELS = {
  built_agent_pipeline: 'Built agent pipeline',
  ran_scan: 'Ran scan',
  queued_governed_intent: 'Queued governed intent',
  replay_health_update: 'Evaluated replay health',
  evolution_activity: 'Tracked evolution activity',
  governance_signal: 'Observed governance signal',
  operational_event: 'Recorded operational event',
};

function eventTypeOf(entry) {
  if (!entry || typeof entry !== 'object') return '';
  if (typeof entry.event_type === 'string' && entry.event_type) return entry.event_type;
  if (typeof entry.event === 'string' && entry.event) return entry.event;
  return '';
}

function eventTimestamp(entry) {
  const raw = (entry && (entry.timestamp || entry.ts || entry.time)) || '';
  if (!raw) return null;
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed;
}

function semanticGroupFor(entry) {
  const eventType = eventTypeOf(entry);
  if (eventType === 'aponi_control_command_queued' || eventType.includes('queue')) return 'queued_governed_intent';
  if (eventType.includes('scan') || eventType.includes('replay') || eventType.includes('diff')) return 'ran_scan';
  if (eventType.includes('agent') || eventType.includes('mutation') || eventType.includes('evolution')) return 'built_agent_pipeline';
  if (eventType.includes('override') || eventType.includes('constitution') || eventType.includes('policy')) return 'governance_signal';
  return 'operational_event';
}

function groupHistoryEvents(entries) {
  const grouped = new Map();
  const normalized = safeArray(entries).filter((entry) => entry && typeof entry === 'object').map((entry) => {
    const ts = eventTimestamp(entry);
    const tsMs = ts ? ts.getTime() : 0;
    return { entry, eventType: eventTypeOf(entry) || 'unknown', tsMs, semanticType: semanticGroupFor(entry) };
  }).sort((a,b)=>b.tsMs-a.tsMs);

  for (const item of normalized) {
    const bucket = item.tsMs ? Math.floor(item.tsMs / HISTORY_WINDOW_MS) : 0;
    const key = `${item.semanticType}:${bucket}`;
    if (!grouped.has(key)) grouped.set(key, { id:key, semanticType:item.semanticType, label:HISTORY_LABELS[item.semanticType] || item.semanticType, eventTypes:new Set(), count:0, items:[], latestTsMs:item.tsMs });
    const cur = grouped.get(key);
    cur.count += 1; cur.items.push(item.entry); cur.eventTypes.add(item.eventType);
    if (item.tsMs > cur.latestTsMs) cur.latestTsMs = item.tsMs;
  }

  return Array.from(grouped.values()).map((g)=>({ ...g, eventTypes:Array.from(g.eventTypes).sort(), latestIso:g.latestTsMs ? new Date(g.latestTsMs).toISOString() : ''})).sort((a,b)=>b.latestTsMs-a.latestTsMs);
}

function withinDateFilter(group, fromDate, toDate) {
  if (!group.latestTsMs) return true;
  if (fromDate && group.latestTsMs < fromDate.getTime()) return false;
  if (toDate && group.latestTsMs > toDate.getTime()) return false;
  return true;
}

function rerunHistoryItem(group) {
  const task = `rerun history item ${group.label.toLowerCase()} (${group.eventTypes.join(', ')})`;
  const taskInput = document.getElementById('controlTask');
  const typeInput = document.getElementById('controlType');
  if (taskInput) ensureSelectOption(taskInput, task);
  if (typeInput) typeInput.value = 'run_task';
  queueIntent();
}

function forkHistoryItem(group) {
  const task = `fork from history item ${group.label.toLowerCase()} (${group.eventTypes.join(', ')})`;
  const taskInput = document.getElementById('controlTask');
  const typeInput = document.getElementById('controlType');
  if (taskInput) ensureSelectOption(taskInput, task);
  if (typeInput) typeInput.value = 'create_agent';
  queueIntent();
}

function renderHistory(groups) {
  const list = document.getElementById('historyList');
  const typeFilter = document.getElementById('historyTypeFilter');
  const fromInput = document.getElementById('historyDateFrom');
  const toInput = document.getElementById('historyDateTo');
  if (!list || !typeFilter || !fromInput || !toInput) return;

  const allEventTypes = new Set();
  for (const group of groups) for (const eventType of group.eventTypes) allEventTypes.add(eventType);
  const existingValue = typeFilter.value || 'all';
  const sortedTypes = Array.from(allEventTypes).sort();
  const nextValue = existingValue && sortedTypes.includes(existingValue) ? existingValue : 'all';
  replaceSelectOptions(typeFilter, ['all', ...sortedTypes]);
  typeFilter.value = nextValue;

  const selectedType = typeFilter.value;
  const fromDate = fromInput.value ? new Date(fromInput.value) : null;
  const toDate = toInput.value ? new Date(toInput.value) : null;
  const filtered = groups.filter((group) => (selectedType === 'all' || group.eventTypes.includes(selectedType)) && withinDateFilter(group, fromDate, toDate));

  clearNode(list);
  if (!filtered.length) {
    list.appendChild(el('div', { className: 'history-item', text: 'No matching history items.' }));
    return;
  }

  filtered.forEach((group) => {
    const summary = `${group.count} event${group.count === 1 ? '' : 's'} · ${group.latestIso || 'unknown time'}`;
    const article = el('article', { className: 'history-item', attrs: { 'data-history-id': group.id } });
    const header = el('div', { className: 'history-item-header' });
    const textBlock = el('div');
    textBlock.appendChild(el('div', { className: 'history-item-title', text: group.label }));
    textBlock.appendChild(el('div', { className: 'history-item-meta', text: summary }));
    textBlock.appendChild(el('div', { className: 'history-item-meta', text: `Types: ${group.eventTypes.join(', ') || 'unknown'}` }));

    const actions = el('div', { className: 'history-item-actions' });
    // data-action="rerun" and data-action="fork" are intentionally preserved for compatibility tests.
    const rerunBtn = el('button', { text: 'Rerun', attrs: { type: 'button', 'data-action': 'rerun' } });
    rerunBtn.addEventListener('click', () => rerunHistoryItem(group));
    const forkBtn = el('button', { text: 'Fork', attrs: { type: 'button', 'data-action': 'fork' } });
    forkBtn.addEventListener('click', () => forkHistoryItem(group));
    actions.appendChild(rerunBtn);
    actions.appendChild(forkBtn);

    header.appendChild(textBlock);
    header.appendChild(actions);
    article.appendChild(header);

    const details = el('details');
    details.appendChild(el('summary', { text: 'Show raw JSON' }));
    details.appendChild(el('pre', { text: JSON.stringify(group.items, null, 2) }));
    article.appendChild(details);
    list.appendChild(article);
  });
}

async function refreshHistory() {
  try {
    const [lineageResponse, metricsResponse] = await Promise.all([
      fetch('/lineage', { cache: 'no-store' }),
      fetch('/metrics', { cache: 'no-store' }),
    ]);
    const lineagePayload = lineageResponse.ok ? await lineageResponse.json() : [];
    const metricsPayload = metricsResponse.ok ? await metricsResponse.json() : {};
    const lineageEntries = Array.isArray(lineagePayload) ? lineagePayload : [];
    const metricEntries = Array.isArray(metricsPayload.entries) ? metricsPayload.entries : [];
    const groups = groupHistoryEvents([...lineageEntries, ...metricEntries]);
    renderHistory(groups);
  } catch (err) {
    const list = document.getElementById('historyList');
    if (list) list.textContent = 'Failed to load history: ' + err;
  }
}

function emitUXEvent(eventType, payload = {}) {
  postTelemetry(eventType, payload);
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 7000) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    return response;
  } finally {
    clearTimeout(timeoutId);
  }
}

function computeAdaptiveDelay(baseDelayMs, elapsedMs, failureCount) {
  const safeElapsed = Number.isFinite(elapsedMs) ? Math.max(0, elapsedMs) : 0;
  const safeFailures = Number.isFinite(failureCount) ? Math.max(0, failureCount) : 0;
  const baseDelay = Math.max(500, Number(baseDelayMs) || 500);
  const backoffMultiplier = Math.min(REFRESH_MAX_BACKOFF_MULTIPLIER, Math.pow(2, safeFailures));
  const targetDelay = (baseDelay * backoffMultiplier) - safeElapsed;
  return Math.max(500, Math.round(targetDelay));
}

function scheduleNextRefresh(startTime = performance.now()) {
  if (refreshTimer) clearTimeout(refreshTimer);
  const elapsed = performance.now() - startTime;
  const settings = getBriefSettings();
  const frequencyMultiplier = settings.frequency === 'high' ? 0.7 : (settings.frequency === 'low' ? 1.8 : 1.0);
  const delay = computeAdaptiveDelay(Math.round(REFRESH_BASE_DELAY_MS * frequencyMultiplier), elapsed, refreshFailureCount);
  refreshTimer = setTimeout(refresh, delay);
}

function scheduleNextQueueRefresh(startTime = performance.now()) {
  if (queueTimer) clearTimeout(queueTimer);
  const elapsed = performance.now() - startTime;
  const delay = computeAdaptiveDelay(QUEUE_BASE_DELAY_MS, elapsed, queueFailureCount);
  queueTimer = setTimeout(refreshControlQueue, delay);
}

async function refreshControlQueue() {
  const el = document.getElementById('queueSummary');
  if (!el) {
    scheduleNextQueueRefresh();
    return;
  }
  if (isQueueRefreshing) {
    emitUXEvent('refresh_skipped_inflight', { loop: 'queue' });
    scheduleNextQueueRefresh();
    return;
  }

  isQueueRefreshing = true;
  const requestId = ++queueRequestId;
  const startTime = performance.now();

  try {
    const [queueResponse, verifyResponse] = await Promise.all([
      fetchWithTimeout('/control/queue', { cache: 'no-store' }, QUEUE_REFRESH_TIMEOUT_MS),
      fetchWithTimeout('/control/queue/verify', { cache: 'no-store' }, QUEUE_REFRESH_TIMEOUT_MS),
    ]);
    const [queueResult, verifyResult] = await Promise.allSettled([
      queueResponse.json(),
      verifyResponse.json(),
    ]);
    if (requestId !== queueRequestId) return;
    const payload = queueResult.status === 'fulfilled' ? queueResult.value : {};
    const verify = verifyResult.status === 'fulfilled' ? verifyResult.value : {};
    const entries = Array.isArray(payload.entries) ? payload.entries : [];
    const latestEntry = entries.length ? entries[entries.length - 1] : null;
    const fingerprint = executionFingerprint(latestEntry);
    executionState.activeEntry = latestEntry;
    if (fingerprint !== executionState.lastFingerprint) {
      executionState.lastFingerprint = fingerprint;
      renderExecution(latestEntry);
    } else {
      renderExecution(latestEntry);
    }
    const summary = {
      enabled: !!payload.enabled,
      latest_digest: payload.latest_digest || '',
      queue_parse_error: queueResult.status === 'rejected' ? String(queueResult.reason) : null,
      verify_ok: !!verify.ok,
      verify_issue_count: Array.isArray(verify.issues) ? verify.issues.length : 0,
      verify_parse_error: verifyResult.status === 'rejected' ? String(verifyResult.reason) : null,
      execution_bridge: {
        backend: 'control/queue polling bridge',
        poll_ms: QUEUE_BASE_DELAY_MS,
        endpoint_todo: '/control/execution (pending)',
      },
      latest_entries: entries.slice(-3),
    };
    const summaryText = JSON.stringify(summary, null, 2);
    el.textContent = summaryText;
    const profileSummary = document.getElementById('queueSummaryProfile');
    if (profileSummary) profileSummary.textContent = summaryText;
    queueFailureCount = 0;
    emitUXEvent('refresh_metrics', { loop: 'queue', status: 'success', duration_ms: Math.round(performance.now() - startTime), failure_count: queueFailureCount });
  } catch (err) {
    if (requestId !== queueRequestId) return;
    queueFailureCount += 1;
    if (err && err.name === 'AbortError') {
      emitUXEvent('refresh_timeout', { loop: 'queue', failure_count: queueFailureCount });
      el.textContent = 'Queue refresh timed out; retrying automatically.';
      emitUXEvent('refresh_metrics', { loop: 'queue', status: 'timeout', duration_ms: Math.round(performance.now() - startTime), failure_count: queueFailureCount });
    } else {
      emitUXEvent('refresh_error', { loop: 'queue', failure_count: queueFailureCount, message: String(err) });
      el.textContent = 'Failed to load queue surfaces: ' + err;
      emitUXEvent('refresh_metrics', { loop: 'queue', status: 'error', duration_ms: Math.round(performance.now() - startTime), failure_count: queueFailureCount });
    }
  } finally {
    if (requestId === queueRequestId) isQueueRefreshing = false;
    scheduleNextQueueRefresh(startTime);
  }
}

function readCommandPayload() {
  const selectedMode = currentMode();
  const type = (document.getElementById('controlType') || {}).value || modeConfig(selectedMode).defaultType || 'create_agent';
  const agentId = (document.getElementById('controlAgentId') || {}).value || '';
  const governanceProfile = (document.getElementById('controlGovernance') || {}).value || 'strict';
  const skillProfile = (document.getElementById('controlSkillProfile') || {}).value || '';
  const capabilitiesElement = document.getElementById('controlCapabilities');
  const ability = (document.getElementById('controlAbility') || {}).value || '';
  const taskOrPurpose = (document.getElementById('controlTask') || {}).value || '';
  const payload = {
    type: type,
    agent_id: agentId,
    governance_profile: governanceProfile,
    skill_profile: skillProfile,
    mode: selectedMode,
    metadata: { mode: selectedMode },
    knowledge_domain: ((document.getElementById('controlKnowledgeDomain') || {}).value || ""),
    capabilities: Array.from((capabilitiesElement && capabilitiesElement.selectedOptions) || []).map((opt) => String(opt.value || '').trim()).filter(Boolean),
  };
  if (type === 'run_task') {
    payload.task = taskOrPurpose;
    payload.ability = ability;
  } else {
    payload.purpose = taskOrPurpose;
  }
  return payload;
}

const CONTROL_STATES = {
  select: 0,
  configure: 1,
  execute: 2,
  complete: 3,
  failed: 4,
};

function createControlStateMachine() {
  let current = 'select';
  const stateLabel = document.getElementById('controlStageLabel');
  const stateProgress = document.getElementById('controlStageProgress');
  const status = document.getElementById('controlStatus');
  const submit = document.getElementById('queueSubmit');
  const transitions = {
    select: ['configure'],
    configure: ['execute', 'failed'],
    execute: ['complete', 'failed'],
    complete: ['select'],
    failed: ['select', 'configure'],
  };

  const updateUi = (message) => {
    if (stateLabel) stateLabel.textContent = `Stage: ${current}`;
    if (stateProgress) stateProgress.value = CONTROL_STATES[current] || 0;
    if (status && message) status.textContent = `[${current}] ${message}`;
    if (submit) submit.textContent = current === 'execute' ? 'Submitting...' : 'Submit action';
    if (submit) submit.disabled = current === 'execute';
  };

  const transition = (next, message) => {
    if (!transitions[current] || !transitions[current].includes(next)) {
      updateUi(`Invalid transition blocked: ${current} → ${next}`);
      return false;
    }
    current = next;
    updateUi(message || `Transitioned to ${next}`);
    return true;
  };

  const reset = (message) => {
    current = 'select';
    updateUi(message || 'Ready for next command intent.');
  };

  updateUi('Select command type and start configuration.');

  return {
    getState: () => current,
    transition,
    reset,
  };
}

function validateConfiguration(payload) {
  if (!payload.type || !['create_agent', 'run_task'].includes(payload.type)) {
    return 'Unsupported action type. Please choose create_agent or run_task.';
  }
  if (!ALLOWED_GOVERNANCE_PROFILES.includes(payload.governance_profile)) {
    return 'Safety level must be strict or high-assurance.';
  }
  const resolvedMode = (payload.metadata && payload.metadata.mode) || payload.mode || '';
  if (!CONTROL_MODES_LIST.includes(resolvedMode)) {
    return 'Mode must be builder, automation, analysis, or growth.';
  }
  if (!payload.agent_id) return 'Agent ID is required before queue submission.';
  if (!CONTROL_AGENT_ID_RE.test(payload.agent_id)) return 'Agent ID must be 3-64 chars using lowercase letters, numbers, _ or -.';
  if (!payload.skill_profile) return 'Skill profile is required before queue submission.';
  if (!payload.knowledge_domain) return 'Knowledge domain is required before queue submission.';
  if (!Array.isArray(payload.capabilities) || !payload.capabilities.length) {
    return 'At least one capability is required before queue submission.';
  }
  if (payload.capabilities.length > CONTROL_CAPABILITIES_MAX) {
    return `A maximum of ${CONTROL_CAPABILITIES_MAX} capabilities is supported per action.`;
  }
  if (payload.type === 'run_task') {
    if (!payload.task) return 'Task is required for run_task.';
    if (!payload.ability) return 'Ability is required for run_task.';
  }
  if (payload.type === 'create_agent' && !payload.purpose) return 'Purpose is required for create_agent.';
  return '';
}



function toCardModelFromTemplate(profileName, kind, templatePayload) {
  const payload = templatePayload && typeof templatePayload === 'object' ? templatePayload : {};
  return {
    source: 'task-template',
    kind: kind,
    title: `${profileName} · ${kind}`,
    description: kind === 'run_task' ? 'Execute a deterministic governed task.' : 'Prepare a governed agent role scaffold.',
    estimate: kind === 'run_task' ? 'Estimated output: queue entry + run-task command digest.' : 'Estimated output: queue entry + create-agent command digest.',
    inlineInputs: [
      { key: 'agent_id', label: 'Agent ID', type: 'text', value: payload.agent_id || '' },
      { key: 'task', label: 'Task', type: 'textarea', value: payload.task || payload.purpose || '' },
    ],
    payload: payload,
  };
}

function toCardModelFromInsightRecommendation(index, recommendation) {
  const text = String(recommendation || '').trim();
  const fallbackAgent = 'insight_agent';
  return {
    source: 'insight-recommendation',
    kind: 'run_task',
    title: `Insight recommendation #${index + 1}`,
    description: text || 'Review latest governance intelligence recommendation.',
    estimate: 'Estimated output: queue entry for recommendation follow-through.',
    inlineInputs: [
      { key: 'agent_id', label: 'Agent ID', type: 'text', value: fallbackAgent },
      { key: 'task', label: 'Task', type: 'textarea', value: text || 'Summarize current governance intelligence.' },
    ],
    payload: {
      type: 'run_task',
      governance_profile: 'strict',
      agent_id: fallbackAgent,
      skill_profile: '',
      knowledge_domain: '',
      capabilities: [],
      ability: 'summarize',
      task: text || 'Summarize current governance intelligence.',
    },
  };
}

function toCardModelFromHistoryRerun(entry) {
  const payload = entry && entry.payload && typeof entry.payload === 'object' ? entry.payload : {};
  const commandId = entry && entry.command_id ? String(entry.command_id) : 'history-command';
  return {
    source: 'history-rerun',
    kind: String(payload.type || 'run_task'),
    title: `Rerun ${commandId}`,
    description: 'Replay a previously queued command with optional edits.',
    estimate: 'Estimated output: queue entry cloned from prior command.',
    inlineInputs: [
      { key: 'agent_id', label: 'Agent ID', type: 'text', value: payload.agent_id || '' },
      { key: 'task', label: 'Task/Purpose', type: 'textarea', value: payload.task || payload.purpose || '' },
    ],
    payload: payload,
  };
}

function createActionCard(card) {
  const tpl = document.getElementById('actionCardTemplate');
  if (!tpl || !tpl.content) return el('div');
  const node = tpl.content.firstElementChild.cloneNode(true);
  node.dataset.source = card.source || '';
  node.dataset.kind = card.kind || '';
  node.dataset.payload = JSON.stringify(card.payload || {});
  node.querySelector('.action-title').textContent = card.title || 'Action';
  node.querySelector('.action-desc').textContent = card.description || '';
  node.querySelector('.action-estimate').textContent = card.estimate || 'Estimated output: queued command.';
  const inputList = node.querySelector('.action-input-list');
  (card.inlineInputs || []).forEach((input) => {
    const wrap = el('label', { className: 'action-field' });
    const label = el('span', { text: input.label || input.key || 'Input' });
    wrap.appendChild(label);
    const inputNode = input.type === 'textarea' ? el('textarea') : el('input', { attrs: { type: 'text' } });
    inputNode.value = input.value || '';
    inputNode.dataset.key = input.key || '';
    wrap.appendChild(inputNode);
    inputList.appendChild(wrap);
  });
  return node;
}

async function runActionCard(cardElement) {
  const cardStatus = cardElement.querySelector('.action-status');
  const runButton = cardElement.querySelector('.action-run');
  let payload = {};
  try {
    payload = JSON.parse(cardElement.dataset.payload || '{}');
  } catch (_) {
    payload = {};
  }
  cardElement.querySelectorAll('[data-key]').forEach((el) => {
    const key = el.dataset.key;
    if (!key) return;
    const value = (el.value || '').trim();
    if (key === 'task') {
      if (payload.type === 'create_agent') payload.purpose = value;
      else payload.task = value;
      return;
    }
    payload[key] = value;
  });
  cardElement.classList.add('executing');
  if (runButton) runButton.disabled = true;
  if (cardStatus) cardStatus.textContent = 'Submitting action...';
  const status = document.getElementById('controlStatus');
  try {
    const response = await fetch('/control/queue', {
      method: 'POST',
      headers: await controlAuthHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(`[HTTP ${response.status}] ${JSON.stringify(result)}`);
    cardElement.classList.remove('executing');
    cardElement.classList.add('done');
    if (cardStatus) cardStatus.textContent = 'Done: ' + (result.entry && result.entry.command_id ? result.entry.command_id : 'queued');
    if (status) status.textContent = 'Action submitted successfully.';
    if (runButton) runButton.textContent = 'Run again';
    await refreshControlQueue();
  } catch (err) {
    cardElement.classList.remove('executing');
    if (runButton) runButton.disabled = false;
    if (cardStatus) cardStatus.textContent = 'Failed: ' + err;
    if (status) status.textContent = 'Action could not be submitted. Please review required fields.';
  }
}

function bindActionCards(container) {
  container.querySelectorAll('.action-run').forEach((button) => {
    button.addEventListener('click', async () => {
      const card = button.closest('.action-card');
      if (!card) return;
      await runActionCard(card);
    });
  });
}

async function refreshActionCards() {
  const tasksEl = document.getElementById('tasksActions');
  const insightsEl = document.getElementById('insightsActions');
  if (!tasksEl || !insightsEl) return;
  try {
    const [templatesRes, intelligenceRes, queueRes] = await Promise.all([
      fetch('/control/templates', { cache: 'no-store' }),
      fetch('/system/intelligence', { cache: 'no-store' }),
      fetch('/control/queue', { cache: 'no-store' }),
    ]);
    const templatesPayload = templatesRes.ok ? await templatesRes.json() : { templates: {} };
    const intelligence = intelligenceRes.ok ? await intelligenceRes.json() : {};
    const queue = queueRes.ok ? await queueRes.json() : { entries: [] };
    const taskCards = [];
    Object.entries(templatesPayload.templates || {}).forEach(([profileName, templateMap]) => {
      if (!templateMap || typeof templateMap !== 'object') return;
      ['create_agent', 'run_task'].forEach((kind) => {
        if (templateMap[kind]) taskCards.push(toCardModelFromTemplate(profileName, kind, templateMap[kind]));
      });
    });
    const insightCards = [];
    const recommendations = [];
    if (typeof intelligence.governance_health === 'string' && intelligence.governance_health !== 'PASS') {
      recommendations.push(`Governance health is ${intelligence.governance_health}; investigate determinism and replay drift.`);
    }
    if (typeof intelligence.mutation_aggression_index === 'number' && intelligence.mutation_aggression_index > 0.3) {
      recommendations.push('Mutation aggression index is elevated; run mitigation summary task.');
    }
    recommendations.forEach((item, idx) => insightCards.push(toCardModelFromInsightRecommendation(idx, item)));
    (Array.isArray(queue.entries) ? queue.entries : [])
      .filter((entry) => entry && typeof entry === 'object' && entry.payload)
      .slice(-2)
      .forEach((entry) => insightCards.push(toCardModelFromHistoryRerun(entry)));

    clearNode(tasksEl);
    taskCards.forEach((card) => tasksEl.appendChild(createActionCard(card)));
    if (!taskCards.length) tasksEl.textContent = 'No task templates available.';
    bindActionCards(tasksEl);

    clearNode(insightsEl);
    insightCards.forEach((card) => insightsEl.appendChild(createActionCard(card)));
    if (!insightCards.length) insightsEl.textContent = 'No insight actions currently recommended.';
    bindActionCards(insightsEl);
  } catch (err) {
    tasksEl.textContent = 'Failed to load task actions: ' + err;
    insightsEl.textContent = 'Failed to load insight actions: ' + err;
  }
}


function getUxSessionId() {
  let sessionId = localStorage.getItem(UX_SESSION_KEY) || '';
  if (!sessionId) {
    sessionId = `ux-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
    localStorage.setItem(UX_SESSION_KEY, sessionId);
  }
  return sessionId;
}

async function postUxEvent(eventType, feature, metadata = {}) {
  try {
    await fetch('/ux/events', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_type: eventType, session_id: getUxSessionId(), feature, metadata }),
    });
  } catch (_) {
    return;
  }
}

function markFeatureEntry(feature, metadata = {}) { postUxEvent('feature_entry', feature, metadata); }
function markFeatureCompletion(feature, metadata = {}) { postUxEvent('feature_completion', feature, metadata); }
function markInteraction(feature, metadata = {}) { postUxEvent('interaction', feature, metadata); }
function markUndo(feature, metadata = {}) { postUxEvent('undo', feature, metadata); }
function markFirstSuccess(feature, metadata = {}) {
  if (uxFirstSuccessMarked) return;
  uxFirstSuccessMarked = true;
  postUxEvent('first_success', feature, metadata);
}

window.addEventListener('beforeunload', () => {
  const payload = JSON.stringify({ event_type: 'abandoned_config', session_id: getUxSessionId(), feature: 'control_panel', metadata: { ts: Date.now() } });
  if (navigator.sendBeacon) navigator.sendBeacon('/ux/events', new Blob([payload], { type: 'application/json' }));
});

function normalizeInsights(payload) {
  if (!payload) return [];
  if (Array.isArray(payload.insights)) return payload.insights;
  if (Array.isArray(payload.recommendations)) return payload.recommendations.map((r) => ({ title: 'Recommendation', summary: String(r) }));
  return [];
}

function renderInsights(items) {
  const container = document.getElementById('insights');
  if (!container) return;
  clearNode(container);
  if (!Array.isArray(items) || !items.length) {
    container.textContent = 'No insight details available.';
    return;
  }
  items.forEach((item, idx) => {
    const card = el('article', { className: 'insight-card' });
    const title = el('h3', { text: item && item.title ? item.title : `Insight ${idx + 1}` });
    const summary = el('p', { text: (item && (item.summary || item.description)) || 'No summary provided.' });
    const details = el('details');
    const detailsSummary = el('summary', { text: 'Expand insight details' });
    const pre = el('pre', { text: JSON.stringify(item, null, 2) });
    details.appendChild(detailsSummary);
    details.appendChild(pre);
    card.appendChild(title);
    card.appendChild(summary);
    card.appendChild(details);
    container.appendChild(card);
  });
}

function setupModeTracking() {
  const typeSelect = document.getElementById('controlType');
  if (!typeSelect) return;
  let previous = typeSelect.value;
  typeSelect.addEventListener('change', () => {
    const current = typeSelect.value;
    markInteraction('mode_change', { to: current });
    registerUndoAction({
      type: 'mode_change',
      label: `Mode changed to ${current}.`,
      undo: async () => { typeSelect.value = previous; markUndo('mode_change', { to: previous }); },
    });
    previous = current;
  });
}

async function analyzeCockpitPrompt() {
  const promptInput = document.getElementById('controlGeneralPrompt');
  const status = document.getElementById('controlStatus');
  if (!promptInput) return;
  const prompt = String(promptInput.value || '').trim();
  if (!prompt) { if (status) status.textContent = 'Enter a prompt before analysis.'; return; }
  if (status) status.textContent = 'Analyzing prompt with cockpit planner...';
  try {
    const headers = await controlAuthHeaders({ 'Content-Type': 'application/json' });
    const response = await fetch('/control/cockpit/plan', { method: 'POST', headers, body: JSON.stringify({ prompt }) });
    const result = await response.json();
    if (!response.ok || !result.ok || !result.plan || typeof result.plan !== 'object') {
      if (status) status.textContent = 'Prompt planning failed: ' + JSON.stringify(result);
      return;
    }
    const command = result.plan.command && typeof result.plan.command === 'object' ? result.plan.command : {};
    paintDraft(command);
    renderControlGuidance({ capabilityCount: Array.isArray(command.capabilities) ? command.capabilities.length : 0 });
    persistDraft(readCommandPayload());
    if (status) status.textContent = `Prompt analyzed (${result.plan.provider || 'planner'}). Review fields and submit.`;
  } catch (err) {
    if (status) status.textContent = 'Failed to analyze prompt: ' + err;
  }
}

async function queueIntent() {
  const machine = window.aponiControlMachine;
  if (!machine) return;
  const currentState = machine.getState();
  if (currentState === 'execute') return;
  if (currentState === 'complete') {
    if (!machine.transition('select', 'Preparing a new command run...')) return;
  }

  if (!machine.transition('configure', 'Validating command configuration...')) {
    return;
  }

  await Promise.resolve();

  const commandPayload = readCommandPayload();
  const validationError = validateConfiguration(commandPayload);
  if (validationError) {
    machine.transition('failed', validationError);
    return;
  }

  if (!machine.transition('execute', 'Submitting command intent...')) return;

  const status = document.getElementById('controlStatus');
  try {
    const response = await fetch('/control/queue', {
      method: 'POST',
      headers: await controlAuthHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(commandPayload),
    });
    const payload = await response.json();
    const statusLabel = response.ok ? '' : `[HTTP ${response.status}] `;
    if (response.ok) {
      markFeatureCompletion('queue_intent');
      markFirstSuccess('queue_intent');
      machine.transition('complete', statusLabel + JSON.stringify(payload, null, 2));
      if (payload && payload.entry) {
        executionState.activeEntry = payload.entry;
        executionState.lastFingerprint = executionFingerprint(payload.entry);
        renderExecution(payload.entry);
      }
      const entry = payload && payload.entry ? payload.entry : null;
      if (entry && entry.command_id) {
        registerUndoAction({
          type: 'queued_intent',
          label: 'Intent queued. Undo available.',
          undo: async () => {
            const cancelResponse = await fetch('/control/queue/cancel', {
              method: 'POST',
              headers: await controlAuthHeaders({ 'Content-Type': 'application/json' }),
              body: JSON.stringify({ command_id: entry.command_id }),
            });
            const cancelPayload = await cancelResponse.json();
            if (cancelResponse.ok && cancelPayload.ok) {
              if (status) status.textContent = `Queued intent ${entry.command_id} canceled.`;
              await refreshControlQueue();
              return;
            }
            paintDraft(commandPayload);
            persistDraft(commandPayload);
            if (status) status.textContent = 'Backend cancellation unavailable; restored local draft only. Review queue manually.';
          },
        });
      }
    } else {
      machine.transition('failed', statusLabel + JSON.stringify(payload, null, 2));
    }
    await refreshControlQueue();
  } catch (err) {
    machine.transition('failed', 'Failed to submit intent: ' + err);
  }
}

function latestRunTaskEntry(queuePayload) {
  const entries = queuePayload && Array.isArray(queuePayload.entries) ? queuePayload.entries : [];
  for (let idx = entries.length - 1; idx >= 0; idx -= 1) {
    const entry = entries[idx];
    if (entry && entry.payload && entry.payload.type === 'run_task') {
      return entry;
    }
  }
  return null;
}

async function queueExecutionControl(type, activeEntry) {
  const status = document.getElementById('controlStatus');
  if (!activeEntry || !activeEntry.command_id) {
    if (status) status.textContent = 'No eligible run_task entry is available for execution control.';
    return;
  }
  const payload = {
    type: 'execution_control',
    action: type,
    target_command_id: activeEntry.command_id,
    execution_backend: 'queue_bridge',
  };
  if (status) status.textContent = 'Submitting execution control...';
  try {
    const response = await fetch('/control/execution', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    const statusLabel = response.ok ? '' : `[HTTP ${response.status}] `;
    if (result && result.error === 'not_supported_yet') {
      if (status) status.textContent = statusLabel + 'Execution controls are not supported yet on this backend: ' + JSON.stringify(result, null, 2);
    } else if (!response.ok && result && result.error === 'validation_failed') {
      if (status) status.textContent = statusLabel + 'Execution control validation failed: ' + JSON.stringify(result, null, 2);
    } else if (!response.ok && result && (result.error === 'target_not_found' || result.error === 'target_not_executable')) {
      if (status) status.textContent = statusLabel + 'Execution control target rejected: ' + JSON.stringify(result, null, 2);
    } else if (status) {
      status.textContent = statusLabel + JSON.stringify(result, null, 2);
    }
    await refreshControlQueue();
  } catch (err) {
    if (status) status.textContent = 'Failed to submit execution control: ' + err;
  }
}


function createControlStateMachine() {
  let current = 'select';
  const transitions = {
    select: ['configure'],
    configure: ['execute', 'failed'],
    execute: ['complete', 'failed'],
    complete: ['select'],
    failed: ['select', 'configure'],
  };
  return {
    getState: () => current,
    transition: (next) => {
      if (!transitions[current] || !transitions[current].includes(next)) return false;
      current = next;
      const label = document.getElementById('controlStageLabel');
      const progress = document.getElementById('controlStageProgress');
      if (label) label.textContent = `Stage: ${current}`;
      if (progress) progress.value = CONTROL_STATES[current] || 0;
      return true;
    },
    reset: () => { current = 'select'; },
  };
}

function validateConfiguration(payload) {
  if (!payload.agent_id) return 'Agent ID is required before queue submission.';
  if (!payload.skill_profile) return 'Skill profile is required before queue submission.';
  if (!payload.knowledge_domain) return 'Knowledge domain is required before queue submission.';
  if (!Array.isArray(payload.capabilities) || !payload.capabilities.length) return 'At least one capability is required before queue submission.';
  return '';
}

function toCardModelFromTemplate(profileName, kind, templatePayload) { return { source: 'task-template', kind, payload: templatePayload || {}, title: `${profileName} · ${kind}` }; }
function toCardModelFromInsightRecommendation(index, recommendation) { return { source: 'insight-recommendation', kind: 'run_task', payload: {}, title: `Insight recommendation #${index + 1}`, summary: recommendation }; }
function toCardModelFromHistoryRerun(entry) { return { source: 'history-rerun', kind: 'run_task', payload: (entry && entry.payload) || {}, title: 'Rerun' }; }

function wireExecutionActions() {
  document.getElementById('execCancel')?.addEventListener('click', async () => {
    await queueExecutionControl('cancel', executionState.activeEntry);
  });
  document.getElementById('execFork')?.addEventListener('click', () => {
    hydrateForkDraft(executionState.activeEntry);
  });
}
function refreshActionCards() { return Promise.resolve(); }
function refreshHistory() { return Promise.resolve(); }
function routeFromHash() {
  const raw = (window.location.hash || '').replace(/^#/, '').trim().toLowerCase();
  return APP_ROUTES.includes(raw) ? raw : 'home';
}

function applyRoute(route, opts = {}) {
  const destination = APP_ROUTES.includes(route) ? route : 'home';
  const views = document.querySelectorAll('.app-view[data-route]');
  views.forEach((view) => {
    const active = view.dataset.route === destination;
    view.classList.toggle('is-active', active);
    if (active) {
      view.removeAttribute('hidden');
    } else {
      view.setAttribute('hidden', 'hidden');
    }
  });

  document.querySelectorAll('.command-btn[data-route-target]').forEach((button) => {
    const active = button.dataset.routeTarget === destination;
    if (active) {
      button.setAttribute('aria-current', 'page');
    } else {
      button.removeAttribute('aria-current');
    }
  });

  if (!opts.skipHashSync) {
    const targetHash = '#' + destination;
    if (window.location.hash !== targetHash) {
      window.location.hash = targetHash;
    }
  }

  if (opts.focusMain !== false) {
    const activeView = document.querySelector('.app-view.is-active');
    if (activeView) activeView.focus();
  }
}

function setupViews() {
  document.querySelectorAll('.command-btn[data-route-target]').forEach((button) => {
    button.addEventListener('click', () => applyRoute(button.dataset.routeTarget || 'home'));
    button.addEventListener('keydown', (event) => {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      const buttons = Array.from(document.querySelectorAll('.command-btn[data-route-target]'));
      const index = buttons.indexOf(button);
      if (index < 0) return;
      const direction = event.key === 'ArrowRight' ? 1 : -1;
      const next = buttons[(index + direction + buttons.length) % buttons.length];
      if (next) next.focus();
      event.preventDefault();
    });
  });

  window.addEventListener('hashchange', () => applyRoute(routeFromHash(), { skipHashSync: true }));
  applyRoute(routeFromHash(), { skipHashSync: true, focusMain: false });
}

function setupModeSwitcher() { reorderHomeCards('alpha'); }
function setupModeTracking() {}
function markFeatureEntry() {}
function markInteraction() {}
function registerUndoAction() {}
function hydrateForkDraft() {}

async function queueExecutionControlForLatest(type) {
  const status = document.getElementById('controlStatus');
  try {
    const response = await fetch('/control/queue', { cache: 'no-store' });
    if (!response.ok) throw new Error(`[HTTP ${response.status}] queue endpoint unavailable`);
    const queuePayload = await response.json();
    const activeEntry = latestRunTaskEntry(queuePayload);
    if (!activeEntry) {
      if (status) status.textContent = 'No run_task entry exists in the queue yet.';
      return;
    }
    await queueExecutionControl(type, activeEntry);
  } catch (err) {
    if (status) status.textContent = 'Failed to resolve active queue entry: ' + err;
  }
}

async function refresh() {
  if (isRefreshing) {
    emitUXEvent('refresh_skipped_inflight', { loop: 'main' });
    scheduleNextRefresh();
    return;
  }

  isRefreshing = true;
  const requestId = ++refreshRequestId;
  const startTime = performance.now();

  try {
    const endpoints = {
      state: '/state',
      intelligence: '/system/intelligence',
      risk: '/risk/summary',
      brief: '/dork/session-brief',
    };
    const [stateResponse, intelligenceResponse, riskResponse, briefResponse] = await Promise.allSettled([
      fetchWithTimeout(endpoints.state, { cache: 'no-store' }, REFRESH_TIMEOUT_MS),
      fetchWithTimeout(endpoints.intelligence, { cache: 'no-store' }, REFRESH_TIMEOUT_MS),
      fetchWithTimeout(endpoints.risk, { cache: 'no-store' }, REFRESH_TIMEOUT_MS),
      fetchWithTimeout(endpoints.brief, { cache: 'no-store' }, REFRESH_TIMEOUT_MS),
    ]);

    const parseResult = async (result) => {
      if (result.status !== 'fulfilled') return null;
      if (!result.value.ok) return null;
      try {
        return await result.value.json();
      } catch (_) {
        return null;
      }
    };

    const state = await parseResult(stateResponse);
    const intelligence = await parseResult(intelligenceResponse);
    const risk = await parseResult(riskResponse);
    const brief = await parseResult(briefResponse);

    if (requestId !== refreshRequestId) return;

    if (state) document.getElementById('state').textContent = JSON.stringify(state, null, 2);
    if (intelligence) document.getElementById('intelligence').textContent = JSON.stringify(intelligence, null, 2);
    if (risk) document.getElementById('risk').textContent = JSON.stringify(risk, null, 2);

    renderHome(state || {}, intelligence || {}, risk || {});
    renderSessionBrief(brief || {});

    const divergencePayload = await paint('replay', '/replay/divergence');
    const replayInspectorRef = ensureReplayInspector();
    await Promise.all([
      paint('instability', '/risk/instability'),
      paint('uxSummary', '/ux/summary'),
      refreshHistory(),
      refreshActionCards(),
      replayInspectorRef && typeof replayInspectorRef.refresh === 'function' ? replayInspectorRef.refresh(divergencePayload || undefined) : Promise.resolve(),
    ]);
    renderInsights(normalizeInsights(intelligence || {}));
    refreshFailureCount = 0;
    emitUXEvent('refresh_metrics', { loop: 'main', status: 'success', duration_ms: Math.round(performance.now() - startTime), failure_count: refreshFailureCount });
  } catch (err) {
    if (requestId !== refreshRequestId) return;
    refreshFailureCount += 1;
    if (err && err.name === 'AbortError') {
      emitUXEvent('refresh_timeout', { loop: 'main', failure_count: refreshFailureCount });
      emitUXEvent('refresh_metrics', { loop: 'main', status: 'timeout', duration_ms: Math.round(performance.now() - startTime), failure_count: refreshFailureCount });
    } else {
      emitUXEvent('refresh_error', { loop: 'main', failure_count: refreshFailureCount, message: String(err) });
      emitUXEvent('refresh_metrics', { loop: 'main', status: 'error', duration_ms: Math.round(performance.now() - startTime), failure_count: refreshFailureCount });
    }
  } finally {
    if (requestId === refreshRequestId) isRefreshing = false;
    scheduleNextRefresh(startTime);
  }
}

function rankRecommendedAction(state, intelligence, risk) {
  const health = String(intelligence.governance_health || '').toUpperCase();
  const riskDrift = Number(risk.determinism_drift_index || 0);
  const replayRate = Number(risk.replay_failure_rate || 0);
  const escalations = Number(intelligence.constitution_escalations_last_100 || 0);
  const mode = String(intelligence.replay_mode || state.replay_mode || 'audit').toLowerCase();

  const actions = [
    {
      key: 'stabilize-determinism',
      headline: 'Stabilize determinism before new mutations',
      reason: `Determinism drift is ${riskDrift.toFixed(2)} with governance health ${health || 'UNKNOWN'}.`,
      cta: 'Inspect Insights',
      score: (riskDrift * 0.6) + (health === 'BLOCK' ? 0.3 : 0),
      onClick: () => activateView('insights'),
    },
    {
      key: 'review-replay',
      headline: 'Review replay divergence before promoting',
      reason: `Replay failure rate is ${replayRate.toFixed(2)} and replay mode is ${mode}.`,
      cta: 'Open History',
      score: (replayRate * 0.7) + (mode !== 'audit' ? 0.2 : 0),
      onClick: () => activateView('history'),
    },
    {
      key: 'triage-escalations',
      headline: 'Triage constitution escalations',
      reason: `Detected ${escalations} escalations in the last 100 governance events.`,
      cta: 'Open control panel',
      score: Math.min(1, escalations / 10),
      onClick: () => openControlPanel(),
    },
  ].sort((a, b) => (b.score - a.score) || a.key.localeCompare(b.key));

  return actions[0] || {
    key: 'no-recommendation',
    headline: 'No recommended action',
    reason: 'No actionable governance signals are currently available.',
    cta: 'Refresh',
    onClick: () => refresh(),
  };
}

function _sanitizeBannerText(text) {
  // Prevent raw internal error codes from reaching visible UI surfaces
  return String(text || '')
    .replace(/invalid_json_response[^)]*[))]*/gi, 'service_unavailable')
    .replace(/unparsabl[a-z]*/gi, 'parse_error')
    .replace(/json_response_must_be_object/gi, 'response_format_error')
    .replace(/provider_request_failed[^.]*[.]?/gi, 'provider_unavailable. ')
    .replace(/missing_api_key[^.]*[.]?/gi, 'provider_unconfigured. ')
    .replace(/provider_unavailable[^.]*[.]?/gi, 'provider_unavailable. ')
    .trim();
}

function getBriefSettings() {
  const fallback = { frequency: 'normal', mute_scope: 'none' };
  try {
    const parsed = JSON.parse(localStorage.getItem(BRIEF_SETTINGS_KEY) || '{}');
    const frequency = ['high', 'normal', 'low'].includes(parsed.frequency) ? parsed.frequency : fallback.frequency;
    const mute_scope = ['none', 'info', 'warning', 'all'].includes(parsed.mute_scope) ? parsed.mute_scope : fallback.mute_scope;
    return { frequency, mute_scope };
  } catch (_) {
    return fallback;
  }
}

function persistBriefSettings() {
  const frequencyEl = document.getElementById('briefFrequency');
  const muteEl = document.getElementById('briefMuteScope');
  const settings = {
    frequency: String(frequencyEl?.value || 'normal'),
    mute_scope: String(muteEl?.value || 'none'),
  };
  localStorage.setItem(BRIEF_SETTINGS_KEY, JSON.stringify(settings));
  return settings;
}

function isSeverityMuted(severity, muteScope) {
  if (muteScope === 'all') return true;
  if (muteScope === 'warning') return severity === 'info' || severity === 'warning';
  if (muteScope === 'info') return severity === 'info';
  return false;
}

function buildBriefNudges(briefPayload) {
  const alerts = safeArray(briefPayload?.alerts);
  const currentSignals = {
    gate_locked: alerts.some((item) => item && item.code === 'gate_locked'),
    replay_divergence_spike: alerts.some((item) => item && item.code === 'replay_divergence_spike'),
    evidence_incomplete: alerts.some((item) => item && item.code === 'evidence_incomplete'),
  };
  const nudges = [];
  if (previousBriefSignals) {
    if (!previousBriefSignals.gate_locked && currentSignals.gate_locked) nudges.push('Gate flipped to locked. Show blockers.');
    if (!previousBriefSignals.replay_divergence_spike && currentSignals.replay_divergence_spike) nudges.push('Replay divergence increased. Explain replay divergence.');
    if (!previousBriefSignals.evidence_incomplete && currentSignals.evidence_incomplete) nudges.push('Evidence became incomplete. What to fix first.');
  }
  previousBriefSignals = currentSignals;
  return nudges;
}

function runBriefCta(label) {
  const normalized = String(label || '').toLowerCase();
  if (normalized.includes('blocker')) return activateView('insights');
  if (normalized.includes('replay')) return activateView('history');
  if (normalized.includes('fix first')) return openControlPanel();
  return refresh();
}

function renderSessionBrief(briefPayload) {
  const summaryEl = document.getElementById('sessionBriefSummary');
  const alertsEl = document.getElementById('sessionBriefAlerts');
  if (!summaryEl || !alertsEl) return;
  clearNode(alertsEl);
  const summary = briefPayload?.summary || {};
  summaryEl.textContent = `Gate: ${summary.gate_status || 'unknown'} · Replay divergence: ${Number(summary.replay_divergence_count || 0)} · Blockers: ${Number(summary.blocker_count || 0)} · Findings: ${Number(summary.open_findings_count || 0)}.`;
  const settings = getBriefSettings();
  const nudges = buildBriefNudges(briefPayload);
  nudges.forEach((text) => alertsEl.appendChild(el('div', { className: 'brief-summary', text: `Nudge: ${text}` })));
  safeArray(briefPayload?.alerts).forEach((alert) => {
    const severity = String(alert?.severity || 'info');
    if (isSeverityMuted(severity, settings.mute_scope)) return;
    const card = el('article', { className: `brief-alert ${severity}` });
    card.appendChild(el('div', { className: 'brief-alert-title', text: `${String(alert?.title || 'Alert')} (${severity.toUpperCase()})` }));
    card.appendChild(el('div', { className: 'brief-summary', text: String(alert?.summary || '') }));
    const chips = el('div', { className: 'brief-chip-row' });
    safeArray(alert?.cta).forEach((chipLabel) => {
      const chip = el('button', { className: 'brief-chip', text: chipLabel, attrs: { type: 'button' } });
      chip.addEventListener('click', () => runBriefCta(chipLabel));
      chips.appendChild(chip);
    });
    card.appendChild(chips);
    alertsEl.appendChild(card);
  });
}

function renderHome(state, intelligence, risk) {
  const recommendation = rankRecommendedAction(state, intelligence, risk);
  document.getElementById('homePrimaryHeadline').textContent =
    _sanitizeBannerText(recommendation.headline);
  document.getElementById('homePrimaryReason').textContent =
    _sanitizeBannerText(recommendation.reason);
  const ctaBtn = document.getElementById('homePrimaryCta');
  ctaBtn.textContent = recommendation.cta;
  ctaBtn.dataset.actionKey = recommendation.key || 'unknown';
  ctaBtn.onclick = recommendation.onClick;

  const project = String(state.project || state.system || 'ADAAD').trim() || 'ADAAD';
  const activeAgent = String(state.active_agent || state.agent_id || 'triage_agent').trim() || 'triage_agent';
  const mode = String(intelligence.replay_mode || state.replay_mode || 'audit').trim() || 'audit';
  const adaadVer = String(state.adaad_version || '—').trim();
  const constVer = String(state.constitution_version || '—').trim();
  document.getElementById('homeProject').textContent = `Project: ${project}`;
  document.getElementById('homeAgent').textContent = `Active agent: ${activeAgent}`;
  document.getElementById('homeMode').textContent = `Mode: ${mode}`;
  const homeVer = document.getElementById('homeVersion');
  if (homeVer) homeVer.textContent = `ADAAD v${adaadVer}  ·  Constitution v${constVer}`;

  const quickActions = [
    {
      headline: 'Refresh status verification',
      cta: 'Refresh status',
      onClick: () => refreshControlQueue(),
    },
    {
      headline: 'Open command initiator',
      cta: 'Command panel',
      onClick: () => openControlPanel(),
    },
  ].slice(0, QUICK_ACTION_LIMIT);

  const container = document.getElementById('homeQuickActions');
  if (!container) return;
  clearNode(container);
  quickActions.forEach((action) => {
    const button = el('button', { className: 'quick-action', text: action.cta, attrs: { type: 'button', title: action.headline } });
    button.addEventListener('click', action.onClick);
    container.appendChild(button);
  });
}


async function loadSimulationContext() {
  const status = document.getElementById('simulationStatus');
  const constraintsInput = document.getElementById('simulationConstraints');
  const provenance = document.getElementById('simulationProvenance');
  if (!constraintsInput) return;
  try {
    const response = await fetch('/simulation/context', { cache: 'no-store' });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      if (status) status.textContent = 'Simulation context unavailable: ' + JSON.stringify(payload);
      return;
    }
    const constraints = Array.isArray(payload.default_constraints) ? payload.default_constraints : [];
    constraintsInput.value = JSON.stringify(constraints, null, 2);
    const maxRange = Number(payload.max_epoch_range || 0);
    const epochStart = document.getElementById('simulationEpochStart');
    const epochEnd = document.getElementById('simulationEpochEnd');
    if (epochStart && epochEnd && maxRange > 0) {
      const start = Number(epochStart.value || 1);
      epochEnd.value = String(start + Math.max(0, maxRange - 1));
    }
    if (provenance) provenance.textContent = 'Constitution context: ' + JSON.stringify(payload.constitution_context || {});
  } catch (err) {
    if (status) status.textContent = 'Failed to load simulation context: ' + err;
  }
}

async function renderSimulationResult(resultPayload) {
  const resultNode = document.getElementById('simulationResults');
  const provenance = document.getElementById('simulationProvenance');
  if (resultNode) resultNode.textContent = JSON.stringify({
    comparative_outcomes: resultPayload.comparative_outcomes || {},
    result: resultPayload.result || {},
  }, null, 2);
  if (provenance) provenance.textContent = 'Deterministic provenance: ' + JSON.stringify(resultPayload.provenance || {}, null, 2);
}

async function runProposalSimulation() {
  const status = document.getElementById('simulationStatus');
  const prompt = document.getElementById('controlGeneralPrompt');
  const constraintsInput = document.getElementById('simulationConstraints');
  const start = Number(document.getElementById('simulationEpochStart')?.value || 0);
  const end = Number(document.getElementById('simulationEpochEnd')?.value || 0);
  let constraints = [];
  if (constraintsInput && String(constraintsInput.value || '').trim()) {
    try {
      constraints = JSON.parse(constraintsInput.value);
    } catch (err) {
      if (status) status.textContent = 'Constraint JSON is invalid: ' + err;
      return;
    }
  }
  if (status) status.textContent = 'Submitting simulation request...';
  try {
    const response = await fetch('/simulation/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        dsl_text: String(prompt?.value || '').trim(),
        constraints,
        epoch_range: { start, end },
      }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      if (status) status.textContent = 'Simulation failed: ' + JSON.stringify(payload);
      return;
    }
    window.aponiLastSimulationRunId = payload.run_id || '';
    if (status) status.textContent = 'Simulation completed inline.';
    await renderSimulationResult(payload);
  } catch (err) {
    if (status) status.textContent = 'Simulation request failed: ' + err;
  }
}

async function refreshProposalSimulationResult() {
  const status = document.getElementById('simulationStatus');
  const runId = String(window.aponiLastSimulationRunId || '').trim();
  if (!runId) {
    if (status) status.textContent = 'No previous simulation run id available.';
    return;
  }
  if (status) status.textContent = 'Refreshing simulation result...';
  try {
    const response = await fetch(`/simulation/results/${encodeURIComponent(runId)}`, { cache: 'no-store' });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      if (status) status.textContent = 'Result retrieval failed: ' + JSON.stringify(payload);
      return;
    }
    if (status) status.textContent = 'Simulation result refreshed.';
    await renderSimulationResult(payload);
  } catch (err) {
    if (status) status.textContent = 'Simulation result refresh failed: ' + err;
  }
}


// ── GitHub Feed Panel (Phase 78) ────────────────────────────────────────────
const GITHUB_FEED_EVENT_ICONS = {
  'push': '⬆', 'pr': '⎇', 'pr.merged': '⎇', 'pr.updated': '⎇',
  'ci.failure': '✗', 'ci': '◎', 'slash_command': '/', 'slash': '/',
  'installation': '⚙', 'gate.preflight_blocked': '⛔', 'rejected': '⛔',
};

function classifyFeedEvent(eventName) {
  if (!eventName) return 'generic';
  if (eventName.startsWith('push')) return 'push';
  if (eventName.startsWith('pr')) return 'pr';
  if (eventName.startsWith('ci')) return 'ci';
  if (eventName.startsWith('slash')) return 'slash';
  if (eventName.startsWith('install')) return 'install';
  if (eventName.includes('reject') || eventName.includes('block')) return 'rejected';
  return 'generic';
}

function renderGithubFeedCard(event) {
  const cls = classifyFeedEvent(event.event || event.event_name || '');
  const icon = GITHUB_FEED_EVENT_ICONS[cls] || '◈';
  const evtName = (event.event || event.event_name || 'unknown').replace('github_app.', '');
  const repo = (event.data && event.data.repo) || (event.data && event.data.repository) || '';
  const actor = (event.data && (event.data.pusher || event.data.merged_by || event.data.actor || event.data.sender)) || '';
  const detail = [repo, actor].filter(Boolean).join(' · ') || JSON.stringify(event.data || {}).slice(0, 80);
  const ts = (event.ts || event.timestamp || '').slice(0, 19).replace('T', ' ');
  const card = el('div', { className: `feed-event-card ${cls}`, attrs: { role: 'listitem' } });
  card.appendChild(el('span', { className: 'feed-event-icon', text: icon }));
  const body = el('div', { className: 'feed-event-body' });
  body.appendChild(el('div', { className: 'feed-event-type', text: evtName }));
  body.appendChild(el('div', { className: 'feed-event-detail', text: detail, attrs: { title: detail } }));
  card.appendChild(body);
  card.appendChild(el('span', { className: 'feed-event-meta', text: ts }));
  return card;
}

async function loadGithubFeed() {
  const list   = document.getElementById('githubFeedList');
  const status = document.getElementById('githubFeedStatus');
  if (!list) return;
  try {
    status && (status.textContent = 'Loading…');
    const res = await fetch('/api/github/feed?limit=50');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const events = await res.json();
    if (!Array.isArray(events) || events.length === 0) {
      clearNode(list);
      list.appendChild(el('div', { className: 'feed-empty', text: 'No GitHub events recorded yet.' }));
      status && (status.textContent = 'No events');
      return;
    }
    clearNode(list);
    events.forEach((event) => list.appendChild(renderGithubFeedCard(event)));
    status && (status.textContent = `${events.length} event${events.length !== 1 ? 's' : ''}`);
  } catch (err) {
    // Fallback: try to read from JSONL audit log via governance endpoint
    try {
      const r2 = await fetch('/api/governance/external-events?limit=50');
      if (r2.ok) {
        const data = await r2.json();
        const evts = data.events || data || [];
        if (evts.length > 0) {
          clearNode(list);
          evts.forEach((event) => list.appendChild(renderGithubFeedCard(event)));
          status && (status.textContent = `${evts.length} events (governance bridge)`);
          return;
        }
      }
    } catch (_) {}
    clearNode(list);
    list.appendChild(el('div', { className: 'feed-empty', text: 'GitHub feed unavailable — governance API not reachable.' }));
    status && (status.textContent = 'Unavailable');
  }
}

function setupGithubFeedPanel() {
  const refreshBtn = document.getElementById('githubFeedRefresh');
  if (refreshBtn) refreshBtn.addEventListener('click', loadGithubFeed);
  // Auto-load when panel becomes active
  document.querySelectorAll('[data-view]').forEach(btn => {
    if (btn.dataset.view === 'github') {
      btn.addEventListener('click', loadGithubFeed);
    }
  });
}

setupViews();
markFeatureEntry('dashboard_loaded');
const briefSettings = getBriefSettings();
const briefFrequencyEl = document.getElementById('briefFrequency');
const briefMuteScopeEl = document.getElementById('briefMuteScope');
if (briefFrequencyEl) briefFrequencyEl.value = briefSettings.frequency;
if (briefMuteScopeEl) briefMuteScopeEl.value = briefSettings.mute_scope;
briefFrequencyEl?.addEventListener('change', () => { persistBriefSettings(); refresh(); });
briefMuteScopeEl?.addEventListener('change', () => { persistBriefSettings(); refresh(); });
setupGithubFeedPanel();
setupFloatingPanel();
setupModeTracking();
setupModeSwitcher();
refreshSkillProfiles();
bindComposerPersistence();
wireExecutionActions();
window.aponiControlMachine = createControlStateMachine();
document.getElementById('queueSubmit')?.addEventListener('click', () => { markInteraction('queue_submit_click'); queueIntent(); });
document.getElementById('queueRefresh')?.addEventListener('click', () => { markInteraction('queue_refresh_click'); refreshControlQueue(); });
document.getElementById('controlPromptRun')?.addEventListener('click', () => { markInteraction('prompt_plan_click'); analyzeCockpitPrompt(); });
document.getElementById('simulationRun')?.addEventListener('click', runProposalSimulation);
document.getElementById('simulationRefresh')?.addEventListener('click', refreshProposalSimulationResult);
loadSimulationContext();
document.getElementById('historyTypeFilter')?.addEventListener('change', refreshHistory);
document.getElementById('historyDateFrom')?.addEventListener('change', refreshHistory);
document.getElementById('historyDateTo')?.addEventListener('change', refreshHistory);
scheduleNextRefresh();
scheduleNextQueueRefresh();
"""



        return Handler

    @classmethod
    def _reviewer_reputation_panel(cls) -> dict:
        """Compute reviewer reputation panel data for Aponi dashboard."""
        from runtime.governance.reviewer_reputation import (
            compute_epoch_reputation_batch,
            DEFAULT_EPOCH_WEIGHTS,
            SCORING_ALGORITHM_VERSION,
        )
        from runtime.governance.review_pressure import compute_panel_calibration, DEFAULT_TIER_CONFIG
        from security.ledger.journal import JOURNAL_PATH, ensure_journal
        import json as _json

        ensure_journal()
        events: list = []
        try:
            for line in JOURNAL_PATH.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = _json.loads(line)
                    payload = entry.get("payload") or {}
                    if (
                        entry.get("type") == "reviewer_action_outcome"
                        or payload.get("event_type") == "reviewer_action_outcome"
                    ):
                        events.append({"event_type": "reviewer_action_outcome", "payload": payload})
                except (ValueError, KeyError):
                    continue
        except OSError:
            events = []

        # Collect unique epoch IDs from events
        epoch_ids = list({str(ev["payload"].get("epoch_id") or "") for ev in events if ev["payload"].get("epoch_id")})
        latest_epoch = epoch_ids[-1] if epoch_ids else "unknown"

        ids = list({
            str(ev["payload"].get("reviewer_id") or "")
            for ev in events
            if ev["payload"].get("epoch_id") == latest_epoch and ev["payload"].get("reviewer_id")
        })

        reputation_scores = compute_epoch_reputation_batch(ids, events, epoch_id=latest_epoch)

        tier_scores: dict = {}
        for rec in reputation_scores.values():
            for tier in DEFAULT_TIER_CONFIG:
                tier_scores[tier] = rec["composite_score"]
            break
        calibration = compute_panel_calibration(tier_scores) if tier_scores else {}

        return {
            "epoch_id": latest_epoch,
            "scoring_algorithm_version": SCORING_ALGORITHM_VERSION,
            "reviewer_count": len(ids),
            "reputation_scores": {
                rid: {
                    "composite_score": rec["composite_score"],
                    "dimension_scores": rec["dimension_scores"],
                    "event_count": rec["event_count"],
                }
                for rid, rec in reputation_scores.items()
            },
            "tier_calibration": {
                tier: {
                    "adjusted_count": cal["adjusted_count"],
                    "base_count": cal["base_count"],
                    "constitutional_floor_enforced": cal["constitutional_floor_enforced"],
                }
                for tier, cal in calibration.items()
            },
        }


    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
        if self._thread:
            self._thread.join(timeout=1)
        self._executor.shutdown(wait=False, cancel_futures=True)


def main(argv: list[str] | None = None) -> int:
    try:
        load_governance_policy()
    except GovernancePolicyError as exc:
        raise SystemExit(f"[APONI] governance policy load failed: {exc}") from exc

    parser = argparse.ArgumentParser(description="Run Aponi dashboard in standalone mode.")
    parser.add_argument("--host", default=os.environ.get("APONI_HOST", "0.0.0.0"), help="Host interface to bind (env: APONI_HOST)")
    parser.add_argument("--port", type=int, default=_resolve_aponi_port(), help="Port to bind (env: APONI_PORT)")
    parser.add_argument("--serve-mcp", action="store_true", help="Enable MCP mutation utility endpoints with JWT enforcement.")
    args = parser.parse_args(argv)

    dashboard = AponiDashboard(host=args.host, port=args.port, serve_mcp=args.serve_mcp, jwt_secret=os.environ.get("ADAAD_MCP_JWT_SECRET", ""))
    dashboard.start({"status": "dashboard_only"})
    print(f"[APONI] dashboard running on http://{dashboard.host}:{dashboard.port}")
    print(
        "[APONI] endpoints: / /state /metrics /fitness /system/intelligence /risk/summary /risk/instability /policy/simulate /simulation/context /simulation/run /simulation/results/{run_id} /alerts/evaluate /replay/divergence /replay/diff?epoch_id=... "
        "/capabilities /lineage /mutations /staging /evolution/epoch?epoch_id=... /evolution/live /evolution/active /evolution/timeline /projection/mutation-roi /projection/lineage-trajectory /projection/confidence-bands /control/free-sources /control/skill-profiles /control/capability-matrix /control/policy-summary /control/templates /control/environment-health /control/queue /control/queue/verify /ux/summary /ux/events"
    )
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:  # pragma: no cover - manual shutdown path
        dashboard.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
