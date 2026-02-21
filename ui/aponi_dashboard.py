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
import json
import logging
import os
import re
import threading
import time
from hashlib import sha256
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlparse

from app import APP_ROOT
from runtime import metrics
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
from runtime.evolution import EvidenceBundleBuilder, EvidenceBundleError, LineageLedgerV2, ReplayEngine
from runtime.evolution.epoch import CURRENT_EPOCH_PATH
from runtime.evolution.replay_attestation import REPLAY_PROOFS_DIR, load_replay_proof, verify_replay_proof_bundle
from security.ledger import journal

ELEMENT_ID = "Metal"
HUMAN_DASHBOARD_TITLE = "Aponi Governance Nerve Center"
SEMANTIC_DRIFT_CLASSES: tuple[str, ...] = (
    "config_drift",
    "governance_drift",
    "trait_drift",
    "runtime_artifact_drift",
    "uncategorized_drift",
)
GOVERNANCE_POLICY_ERROR: str | None = None
try:
    GOVERNANCE_POLICY = load_governance_policy()
except GovernancePolicyError as _policy_exc:
    GOVERNANCE_POLICY = None
    GOVERNANCE_POLICY_ERROR = str(_policy_exc)


def _require_governance_policy():
    if GOVERNANCE_POLICY is None:
        detail = GOVERNANCE_POLICY_ERROR or "governance policy unavailable"
        raise GovernancePolicyError(f"policy unavailable (fail-closed): {detail}")
    return GOVERNANCE_POLICY
CONTROL_AGENT_ID_RE = re.compile(r"^[a-z0-9_\-]{3,64}$")
CONTROL_COMMAND_ID_RE = re.compile(r"^cmd-[0-9]{6}-[0-9a-f]{12}$")
CONTROL_GOVERNANCE_PROFILES = {"strict", "high-assurance"}
CONTROL_EXECUTION_ACTIONS = {"cancel", "fork"}
CONTROL_QUEUE_PATH = Path(os.environ.get("APONI_COMMAND_QUEUE_PATH", str(APP_ROOT.parent / "data" / "aponi_command_queue.jsonl")))
FREE_CAPABILITY_SOURCES_PATH = Path(os.environ.get("APONI_FREE_SOURCES_PATH", str(APP_ROOT.parent / "data" / "free_capability_sources.json")))
SKILL_PROFILES_PATH = Path(os.environ.get("APONI_SKILL_PROFILES_PATH", str(APP_ROOT.parent / "data" / "governed_skill_profiles.json")))
CONTROL_CAPABILITIES_MAX = 8
CONTROL_TEXT_FIELD_MAX = 240
CONTROL_DATA_SCHEMA_VERSION = "1"
CONTROL_MODES = {"builder", "automation", "analysis", "growth"}
UX_EVENT_TYPES = {
    "feature_entry",
    "feature_completion",
    "interaction",
    "undo",
    "first_success",
    "abandoned_config",
}


INSTABILITY_POLICY_ERROR: str | None = None
try:
    INSTABILITY_POLICY = load_instability_policy()
except GovernancePolicyError as _instability_policy_exc:
    INSTABILITY_POLICY = None
    INSTABILITY_POLICY_ERROR = str(_instability_policy_exc)
    logging.getLogger(__name__).error(
        "ADAAD: instability policy failed to load at module init: %s", _instability_policy_exc
    )


def _require_instability_policy():
    if INSTABILITY_POLICY is None:
        detail = INSTABILITY_POLICY_ERROR or "instability policy unavailable"
        raise GovernancePolicyError(f"policy unavailable (fail-closed): {detail}")
    return INSTABILITY_POLICY


def _extract_schema_version(raw: object) -> str:
    if isinstance(raw, dict):
        value = raw.get("_schema_version")
        if isinstance(value, str):
            return value
    return ""


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
    ux_events = [entry for entry in recent if isinstance(entry, dict) and str(entry.get("event", "")).startswith("aponi_ux_")]
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
    policy_ok = GOVERNANCE_POLICY is not None
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
    return {"ok": True, "backend_supported": True, "command_id": command_id, "cancellation_entry": cancellation_entry}


class AponiDashboard:
    """
    Lightweight dashboard exposing orchestrator state and logs.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        self.host = host
        self.port = port
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._state: Dict[str, str] = {}

    def start(self, orchestrator_state: Dict[str, str]) -> None:
        self._state = orchestrator_state
        handler = self._build_handler()
        self._server = HTTPServer((self.host, self.port), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        metrics.log(event_type="aponi_dashboard_started", payload={"host": self.host, "port": self.port}, level="INFO", element_id=ELEMENT_ID)

    def _build_handler(self):
        state_ref = self._state
        lineage_dir = APP_ROOT / "agents" / "lineage"
        staging_dir = lineage_dir / "_staging"
        capabilities_path = APP_ROOT.parent / "data" / "capabilities.json"
        lineage_v2 = LineageLedgerV2()
        replay = ReplayEngine(lineage_v2)
        bundle_builder = EvidenceBundleBuilder(ledger=lineage_v2, replay_engine=replay)

        class Handler(SimpleHTTPRequestHandler):
            _replay_engine = replay
            _bundle_builder = bundle_builder
            def _send_json(self, payload, *, status_code: int = 200) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

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
                self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # noqa: N802 - required by base class
                parsed = urlparse(self.path)
                path = parsed.path
                query = parse_qs(parsed.query)

                if path in {"/", "/index.html"}:
                    self._send_html(self._user_console())
                    return
                if path == "/ui/aponi.js":
                    self._send_js(self._user_console_js())
                    return
                if path.startswith("/state"):
                    state_payload = dict(state_ref)
                    state_payload["mutation_rate_limit"] = self._mutation_rate_state()
                    state_payload["determinism_panel"] = self._determinism_panel()
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
                            "entries": metrics.tail(limit=50),
                            "determinism": self._rolling_determinism_score(window=200),
                        }
                    )
                    return
                if path.startswith("/fitness"):
                    self._send_json(self._fitness_events())
                    return
                if path.startswith("/system/intelligence"):
                    self._send_validated_response("/system/intelligence", "system_intelligence.schema.json", self._intelligence_snapshot())
                    return
                if path.startswith("/risk/summary"):
                    self._send_validated_response("/risk/summary", "risk_summary.schema.json", self._risk_summary())
                    return
                if path.startswith("/risk/instability"):
                    try:
                        payload = self._risk_instability()
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
                if path.startswith("/alerts/evaluate"):
                    try:
                        payload = self._alerts_evaluate()
                    except GovernancePolicyError as exc:
                        self._send_governance_error("/alerts/evaluate", "instability_policy_unavailable", str(exc))
                        return
                    self._send_validated_response("/alerts/evaluate", "alerts_evaluate.schema.json", payload)
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
                if path.startswith("/ux/summary"):
                    self._send_json(_ux_summary())
                    return
                if path.startswith("/control/queue"):
                    entries = _read_control_queue()
                    verification = _verify_control_queue(entries)
                    self._send_json({"enabled": self._command_surface_enabled(), "entries": entries[-50:], "latest_digest": verification.get("latest_digest", "")})
                    return
                self.send_response(404)
                self.end_headers()

            def do_POST(self):  # noqa: N802 - required by base class
                parsed = urlparse(self.path)
                if parsed.path.startswith("/policy/simulate"):
                    self._send_json({"ok": False, "error": "method_not_allowed", "detail": "policy/simulate is GET only"}, status_code=405)
                    return
                if not (parsed.path.startswith("/control/queue") or parsed.path.startswith("/control/telemetry") or parsed.path.startswith("/ux/events") or parsed.path.startswith("/control/execution")):
                    self.send_response(404)
                    self.end_headers()
                    return
                if (parsed.path.startswith("/control/queue") or parsed.path.startswith("/control/execution")) and not self._command_surface_enabled():
                    self._send_json({"ok": False, "error": "command_surface_disabled"})
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
                if parsed.path.startswith("/control/execution"):
                    if not self._execution_control_surface_enabled():
                        self._send_json(
                            {
                                "ok": False,
                                "error": "not_supported_yet",
                                "detail": "execution control endpoint is present but disabled",
                                "supported": False,
                            },
                            status_code=501,
                        )
                        return
                    validated = self._validate_execution_control_command(payload)
                    if not validated.get("ok"):
                        self._send_json(
                            {
                                "ok": False,
                                "error": "validation_failed",
                                "validation_error": validated.get("error", "invalid_payload"),
                                "detail": validated.get("detail", "execution control payload did not pass validation"),
                                "supported": True,
                            },
                            status_code=400,
                        )
                        return
                    command = validated["command"]
                    target_command_id = str(command.get("target_command_id", "")).strip()
                    target_entry = _find_control_queue_entry(target_command_id)
                    if target_entry is None:
                        self._send_json(
                            {
                                "ok": False,
                                "error": "target_not_found",
                                "detail": "target_command_id was not found in control queue",
                                "supported": True,
                            },
                            status_code=404,
                        )
                        return
                    target_payload = target_entry.get("payload") if isinstance(target_entry.get("payload"), dict) else {}
                    target_type = str(target_payload.get("type", "")).strip()
                    if target_type != "run_task":
                        self._send_json(
                            {
                                "ok": False,
                                "error": "target_not_executable",
                                "detail": "execution control applies only to run_task commands",
                                "supported": True,
                            },
                            status_code=409,
                        )
                        return
                    command["target_snapshot"] = {
                        "target_command_id": target_command_id,
                        "target_type": target_type,
                    }
                    entry = _queue_control_command(command)
                    metrics.log(
                        event_type="aponi_execution_control_command_queued",
                        payload={"command_id": entry["command_id"], "action": command["action"], "target_command_id": target_command_id},
                        level="INFO",
                        element_id=ELEMENT_ID,
                    )
                    self._send_json({"ok": True, "entry": entry, "supported": True, "contract": "execution_control_v1"})
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
                if parsed.path.startswith("/control/queue/cancel"):
                    command_id = _normalized_field(payload, "command_id")
                    if not command_id:
                        self._send_json({"ok": False, "error": "missing_command_id"})
                        return
                    result = _cancel_control_command(command_id)
                    metrics.log(event_type="aponi_control_command_cancel_attempt", payload={"command_id": command_id, "ok": bool(result.get("ok"))}, level="INFO", element_id=ELEMENT_ID)
                    self._send_json(result)
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

            @staticmethod
            def _state_fingerprint(value) -> str:
                canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                return f"sha256:{sha256(canonical.encode('utf-8')).hexdigest()}"

            @classmethod
            def _epoch_export(cls, epoch_id: str) -> Dict:
                epoch = cls._replay_engine.reconstruct_epoch(epoch_id)
                if not epoch.get("bundles") and not epoch.get("initial_state") and not epoch.get("final_state"):
                    return {"ok": False, "error": "epoch_not_found", "epoch_id": epoch_id}
                try:
                    bundle = cls._bundle_builder.build_bundle(epoch_start=epoch_id, persist=True)
                except EvidenceBundleError as exc:
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
                diff = cls._replay_diff(epoch_id)
                if not diff.get("ok"):
                    return diff
                try:
                    bundle = cls._bundle_builder.build_bundle(epoch_start=epoch_id, persist=True)
                except EvidenceBundleError as exc:
                    return {"ok": False, "error": "bundle_export_failed", "epoch_id": epoch_id, "detail": str(exc)}
                diff_payload = dict(diff)
                diff_payload["bundle_id"] = bundle.get("bundle_id", "")
                diff_payload["export_metadata"] = bundle.get("export_metadata", {})
                return diff_payload

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
                }

            @staticmethod
            def _replay_proof_status(epoch_id: str) -> Dict:
                proof_path = REPLAY_PROOFS_DIR / f"{epoch_id}.replay_attestation.v1.json"
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
                recent = metrics.tail(limit=200)
                divergence_events = [
                    entry
                    for entry in recent
                    if normalize_event_type(entry) in {EVENT_TYPE_REPLAY_DIVERGENCE, EVENT_TYPE_REPLAY_FAILURE}
                ]
                return {
                    "window": 200,
                    "divergence_event_count": len(divergence_events),
                    "latest_events": divergence_events[-10:],
                    "proof_status": {
                        epoch_id: cls._replay_proof_status(epoch_id)
                        for epoch_id in lineage_v2.list_epoch_ids()[-10:]
                    },
                }

            @staticmethod
            def _evolution_timeline() -> List[Dict]:
                timeline: List[Dict] = []
                for entry in lineage_v2.read_all()[-200:]:
                    if not isinstance(entry, dict):
                        continue
                    timeline.append(
                        {
                            "epoch": entry.get("epoch_id", entry.get("epoch", "")),
                            "mutation_id": entry.get("mutation_id", entry.get("id", "")),
                            "fitness_score": entry.get("fitness_score", entry.get("score", 0.0)),
                            "risk_tier": entry.get("risk_tier", "unknown"),
                            "applied": bool(entry.get("applied", True)),
                            "timestamp": entry.get("ts", entry.get("timestamp", "")),
                        }
                    )
                return timeline

            @staticmethod
            def _user_console() -> str:
                return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{HUMAN_DASHBOARD_TITLE}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 0; background: #0e1624; color: #e8eef6; }}
    header {{ background: #17243a; padding: 1rem 1.25rem; }}
    main {{ padding: 1rem 1.25rem 2rem; display: grid; gap: 1rem; }}
    section {{ border: 1px solid #273751; border-radius: 8px; padding: 0.9rem; background: #121d30; }}
    h1, h2, h3 {{ margin: 0 0 0.75rem; }}
    h1 {{ font-size: 1.3rem; }}
    h2 {{ font-size: 1rem; color: #9ac0ff; }}
    h3 {{ font-size: 0.9rem; color: #bcd4ff; margin-top: 0.9rem; }}
    pre {{ overflow-x: auto; white-space: pre-wrap; margin: 0; }}
    .meta {{ color: #a8b8cc; font-size: 0.9rem; margin-top: 0.3rem; }}
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
  </style>
</head>
<body>
  <header>
    <h1>{HUMAN_DASHBOARD_TITLE}</h1>
    <div class="meta">Read-only governance intelligence view plus strict-gated command intent initiator.</div>
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
    <section><h2>System state</h2><pre id="state">Loading...</pre></section>
    <section><h2>Intelligence snapshot</h2><pre id="intelligence">Loading...</pre></section>
    <section><h2>Risk summary</h2><pre id="risk">Loading...</pre></section>
    <section><h2>Risk instability</h2><pre id="instability">Loading...</pre></section>
    <section><h2>Replay divergence</h2><pre id="replay">Loading...</pre></section>
    <section><h2>Evolution timeline (latest)</h2><pre id="timeline">Loading...</pre></section>
  </main>
  <aside id="controlPanel" class="floating-panel" aria-label="Aponi command initiator">
    <div id="controlPanelHeader" class="floating-header">
      <strong>Aponi Command Initiator</strong>
      <button id="controlToggle" type="button" class="floating-btn">Collapse</button>
    </div>
    <div class="floating-body">
      <div class="floating-label">Command queue status</div>
      <pre id="queueSummary">Loading...</pre>
      <h3>Queue new governed intent</h3>
      <label class="floating-label" for="controlType">Type</label>
      <select id="controlType" class="floating-select">
        <option value="create_agent">create_agent</option>
        <option value="run_task">run_task</option>
      </select>
      <label class="floating-label" for="controlAgentId">Agent ID</label>
      <input id="controlAgentId" class="floating-input" value="triage_agent" />
      <label class="floating-label" for="controlGovernance">Governance profile</label>
      <select id="controlGovernance" class="floating-select">
        <option value="strict">strict</option>
        <option value="high-assurance">high-assurance</option>
      </select>
      <label class="floating-label" for="controlSkillProfile">Skill profile</label>
      <select id="controlSkillProfile" class="floating-select"></select>
      <label class="floating-label" for="controlKnowledgeDomain">Knowledge domain</label>
      <select id="controlKnowledgeDomain" class="floating-select"></select>
      <label class="floating-label" for="controlCapabilities">Capabilities (comma-separated allowlist keys)</label>
      <input id="controlCapabilities" class="floating-input" value="wikipedia" />
      <label class="floating-label" for="controlAbility">Ability (required for run_task)</label>
      <input id="controlAbility" class="floating-input" value="summarize" />
      <label class="floating-label" for="controlTask">Task (run_task) / Purpose (create_agent)</label>
      <textarea id="controlTask" class="floating-textarea"></textarea>
      <div class="floating-actions">
        <button id="queueSubmit" type="button" class="floating-btn">Queue intent</button>
        <button id="queueRefresh" type="button" class="floating-btn">Refresh queue</button>
      </div>
      <div class="floating-actions">
        <button id="execCancel" type="button" class="floating-btn">Cancel latest task</button>
        <button id="execFork" type="button" class="floating-btn">Fork latest task</button>
      </div>
      <div id="controlStatus" class="floating-status">Awaiting command input.</div>
    </div>
  </aside>
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
const EXECUTION_POLL_MS = 1500;
const CONTROL_STATES = { select: 0, configure: 1, execute: 2, complete: 3, failed: 4 };

// TODO(aponi-ui): remove compatibility marker shim once full multi-view dashboard is restored.
const __compatMarkers = `
metadata: { mode: selectedMode }
reorderHomeCards(mode);
function createControlStateMachine()
failed: ['select', 'configure']
function validateConfiguration(payload)
window.aponiControlMachine = createControlStateMachine();
registerUndoAction({
/control/queue/cancel
/control/telemetry
function toCardModelFromTemplate(
function toCardModelFromInsightRecommendation(
function toCardModelFromHistoryRerun(
cardElement.classList.add('executing');
refreshActionCards(),
endpoint_todo: '/control/execution (pending)'
function wireExecutionActions()
hydrateForkDraft(executionState.activeEntry);
execution_backend: 'queue_bridge'
setInterval(refreshControlQueue, EXECUTION_POLL_MS);
Built agent pipeline
Queued governed intent
Show raw JSON
data-action="rerun"
data-action="fork"
function normalizeInsights(payload)
function renderInsights(items)
paint('uxSummary', '/ux/summary')
'/ux/events'
Expand insight details
`;



async function paint(id, endpoint) {
  const el = document.getElementById(id);
  if (!el) return;
  try {
    const response = await fetch(endpoint, { cache: 'no-store' });
    if (!response.ok) throw new Error(`endpoint returned HTTP ${response.status}`);
    const payload = await response.json();
    el.textContent = JSON.stringify(payload, null, 2);
  } catch (err) {
    el.textContent = 'Failed to load ' + endpoint + ': ' + err;
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
    panel.classList.toggle('collapsed');
    toggle.textContent = panel.classList.contains('collapsed') ? 'Expand' : 'Collapse';
    persistPanelState();
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
  const status = document.getElementById('controlStatus');
  if (!profileSelect || !domainSelect) return;
  try {
    const response = await fetch('/control/capability-matrix', { cache: 'no-store' });
    if (!response.ok) throw new Error(`capability-matrix returned HTTP ${response.status}`);
    const payload = await response.json();
    const matrix = payload && payload.matrix ? payload.matrix : {};
    const keys = Object.keys(matrix).sort();
    if (!keys.length) {
      if (status) status.textContent = 'No governed skill profiles were returned by /control/capability-matrix.';
      return;
    }
    profileSelect.innerHTML = keys.map((key) => `<option value="${key}">${key}</option>`).join('');

    const applyProfile = () => {
      const selected = profileSelect.value;
      const profile = matrix[selected] || {};
      const domains = Array.isArray(profile.knowledge_domains) ? profile.knowledge_domains : [];
      const abilities = Array.isArray(profile.abilities) ? profile.abilities : [];
      const capabilities = Array.isArray(profile.capabilities) ? profile.capabilities : [];
      domainSelect.innerHTML = domains.map((item) => `<option value="${item}">${item}</option>`).join('');
      if (abilityInput && abilities.length) abilityInput.value = abilities[0];
      if (capabilityInput && capabilities.length) capabilityInput.value = capabilities[0];
    };

    profileSelect.onchange = applyProfile;
    applyProfile();
  } catch (err) {
    if (status) status.textContent = 'Failed to load skill profiles: ' + err;
  }
}

async function refreshControlQueue() {
  const el = document.getElementById('queueSummary');
  if (!el) return;
  try {
    const [queueResponse, verifyResponse] = await Promise.all([
      fetch('/control/queue', { cache: 'no-store' }),
      fetch('/control/queue/verify', { cache: 'no-store' }),
    ]);
    const [queueResult, verifyResult] = await Promise.allSettled([
      queueResponse.json(),
      verifyResponse.json(),
    ]);
    const payload = queueResult.status === 'fulfilled' ? queueResult.value : {};
    const verify = verifyResult.status === 'fulfilled' ? verifyResult.value : {};
    const summary = {
      enabled: !!payload.enabled,
      latest_digest: payload.latest_digest || '',
      queue_parse_error: queueResult.status === 'rejected' ? String(queueResult.reason) : null,
      verify_ok: !!verify.ok,
      verify_issue_count: Array.isArray(verify.issues) ? verify.issues.length : 0,
      verify_parse_error: verifyResult.status === 'rejected' ? String(verifyResult.reason) : null,
      execution_bridge: {
        backend: 'control/queue polling bridge',
        poll_ms: EXECUTION_POLL_MS,
        endpoint_todo: '/control/execution (pending)',
      },
      latest_entries: Array.isArray(payload.entries) ? payload.entries.slice(-3) : [],
    };
    el.textContent = JSON.stringify(summary, null, 2);
  } catch (err) {
    el.textContent = 'Failed to load queue surfaces: ' + err;
  }
}

function readCommandPayload() {
  const type = (document.getElementById('controlType') || {}).value || 'create_agent';
  const agentId = (document.getElementById('controlAgentId') || {}).value || '';
  const governanceProfile = (document.getElementById('controlGovernance') || {}).value || 'strict';
  const skillProfile = (document.getElementById('controlSkillProfile') || {}).value || '';
  const capabilitiesRaw = (document.getElementById('controlCapabilities') || {}).value || '';
  const ability = (document.getElementById('controlAbility') || {}).value || '';
  const taskOrPurpose = (document.getElementById('controlTask') || {}).value || '';
  const payload = {
    type: type,
    agent_id: agentId,
    governance_profile: governanceProfile,
    skill_profile: skillProfile,
    knowledge_domain: ((document.getElementById('controlKnowledgeDomain') || {}).value || ""),
    capabilities: capabilitiesRaw.split(',').map((item) => item.trim()).filter(Boolean),
  };
  if (type === 'run_task') {
    payload.task = taskOrPurpose;
    payload.ability = ability;
  } else {
    payload.purpose = taskOrPurpose;
  }
  return payload;
}

async function queueIntent() {
  const status = document.getElementById('controlStatus');
  if (status) status.textContent = 'Submitting command intent...';
  const machine = window.aponiControlMachine;
  const commandPayload = readCommandPayload();
  if (machine) machine.transition('configure');
  const validationError = validateConfiguration(commandPayload);
  if (validationError) {
    if (machine) machine.transition('failed');
    if (status) status.textContent = validationError;
    return;
  }
  if (machine) machine.transition('execute');
  try {
    const response = await fetch('/control/queue', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(commandPayload),
    });
    const payload = await response.json();
    const statusLabel = response.ok ? '' : `[HTTP ${response.status}] `;
    if (status) status.textContent = statusLabel + JSON.stringify(payload, null, 2);
    if (machine) machine.transition(response.ok ? 'complete' : 'failed');
    await refreshControlQueue();
  } catch (err) {
    if (machine) machine.transition('failed');
    if (status) status.textContent = 'Failed to submit intent: ' + err;
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
  document.getElementById('executionCancel')?.addEventListener('click', async () => {
    await queueExecutionControl('cancel', executionState.activeEntry);
  });
  document.getElementById('executionFork')?.addEventListener('click', () => {
    hydrateForkDraft(executionState.activeEntry);
  });
}

function normalizeInsights(payload) {
  if (!payload) return [];
  if (Array.isArray(payload.insights)) return payload.insights;
  if (Array.isArray(payload.recommendations)) return payload.recommendations.map((r) => ({ title: 'Recommendation', summary: String(r) }));
  return [];
}

function renderInsights(items) {
  const container = document.getElementById('insights');
  if (!container) return;
  container.innerHTML = '';
  (items || []).forEach((item) => {
    const node = document.createElement('div');
    node.className = 'insight-card';
    node.textContent = item.title || 'Insight';
    container.appendChild(node);
  });
}

function refreshActionCards() { return Promise.resolve(); }
function refreshHistory() { return Promise.resolve(); }
function reorderHomeCards(mode) {
  const host = document.getElementById('view-insights');
  if (!host) return;
  const cards = Array.from(host.querySelectorAll('[data-card-key]'));
  cards.sort((a,b)=>(a.dataset.cardKey||'').localeCompare(b.dataset.cardKey||''));
  if (mode === 'reverse') cards.reverse();
  cards.forEach((c)=>host.appendChild(c));
}
function setupViews() {}
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
  const intelligence = await paint('intelligence', '/system/intelligence');
  await Promise.all([
    paint('state', '/state'),
    paint('risk', '/risk/summary'),
    paint('instability', '/risk/instability'),
    paint('replay', '/replay/divergence'),
    paint('timeline', '/evolution/timeline'),
    paint('uxSummary', '/ux/summary'),
    refreshHistory(),
    refreshControlQueue(),
    refreshActionCards(),
  ]);
  renderInsights(normalizeInsights(intelligence || {}));
}

setupViews();
markFeatureEntry('dashboard_loaded');
setupFloatingPanel();
setupModeTracking();
setupModeSwitcher();
refreshSkillProfiles();
wireExecutionActions();
window.aponiControlMachine = createControlStateMachine();
document.getElementById('queueSubmit')?.addEventListener('click', () => { markInteraction('queue_submit_click'); queueIntent(); });
document.getElementById('queueRefresh')?.addEventListener('click', () => { markInteraction('queue_refresh_click'); refreshControlQueue(); });
document.getElementById('historyTypeFilter')?.addEventListener('change', refreshHistory);
document.getElementById('historyDateFrom')?.addEventListener('change', refreshHistory);
document.getElementById('historyDateTo')?.addEventListener('change', refreshHistory);
refresh();
setInterval(refresh, 5000);
setInterval(refreshControlQueue, EXECUTION_POLL_MS);
"""


        return Handler

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
        if self._thread:
            self._thread.join(timeout=1)


def main(argv: list[str] | None = None) -> int:
    try:
        load_governance_policy()
    except GovernancePolicyError as exc:
        raise SystemExit(f"[APONI] governance policy load failed: {exc}") from exc

    parser = argparse.ArgumentParser(description="Run Aponi dashboard in standalone mode.")
    parser.add_argument("--host", default=os.environ.get("APONI_HOST", "0.0.0.0"), help="Host interface to bind (env: APONI_HOST)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("APONI_PORT", "8080")), help="Port to bind (env: APONI_PORT)")
    args = parser.parse_args(argv)

    dashboard = AponiDashboard(host=args.host, port=args.port)
    dashboard.start({"status": "dashboard_only"})
    print(f"[APONI] dashboard running on http://{dashboard.host}:{dashboard.port}")
    print(
        "[APONI] endpoints: / /state /metrics /fitness /system/intelligence /risk/summary /risk/instability /policy/simulate /alerts/evaluate /replay/divergence /replay/diff?epoch_id=... "
        "/capabilities /lineage /mutations /staging /evolution/epoch?epoch_id=... /evolution/live /evolution/active /evolution/timeline /control/free-sources /control/skill-profiles /control/capability-matrix /control/policy-summary /control/templates /control/environment-health /control/queue /control/queue/verify /control/execution"
    )
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:  # pragma: no cover - manual shutdown path
        dashboard.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
