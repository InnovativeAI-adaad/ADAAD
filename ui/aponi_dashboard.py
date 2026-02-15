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
import os
import threading
import time
from hashlib import sha256
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Dict, List
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
from runtime.governance.policy_artifact import GovernancePolicyError, load_governance_policy
from runtime.evolution import LineageLedgerV2, ReplayEngine
from runtime.evolution.epoch import CURRENT_EPOCH_PATH
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
GOVERNANCE_POLICY = load_governance_policy()
INSTABILITY_WEIGHTS = {
    "semantic_drift": 0.35,
    "replay_failure": 0.25,
    "escalation": 0.20,
    "determinism_drift": 0.20,
}
DRIFT_CLASS_WEIGHTS = {
    "config_drift": 0.8,
    "governance_drift": 1.4,
    "trait_drift": 1.0,
    "runtime_artifact_drift": 1.1,
    "uncategorized_drift": 0.9,
}
VELOCITY_SPIKE_THRESHOLD = 0.2
WILSON_Z_95 = 1.96
ALERT_THRESHOLDS = {
    "instability_critical": 0.7,
    "instability_warning": 0.5,
    "replay_failure_warning": 0.05,
    "velocity_spike": True,
}


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

        class Handler(SimpleHTTPRequestHandler):
            _replay_engine = replay
            def _send_json(self, payload) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

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
                    self._send_json(self._intelligence_snapshot())
                    return
                if path.startswith("/risk/summary"):
                    self._send_json(self._risk_summary())
                    return
                if path.startswith("/risk/instability"):
                    self._send_json(self._risk_instability())
                    return
                if path.startswith("/replay/divergence"):
                    self._send_json(self._replay_divergence())
                    return
                if path.startswith("/policy/simulate"):
                    self._send_json(self._policy_simulation(query))
                    return
                if path.startswith("/alerts/evaluate"):
                    self._send_json(self._alerts_evaluate())
                    return
                if path.startswith("/replay/diff"):
                    epoch_id = query.get("epoch_id", [""])[0].strip()
                    if not epoch_id:
                        self._send_json({"ok": False, "error": "missing_epoch_id"})
                        return
                    self._send_json(self._replay_diff(epoch_id))
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
                    data = replay.reconstruct_epoch(epoch_id)
                    if not data.get("bundles") and not data.get("initial_state") and not data.get("final_state"):
                        self._send_json({"ok": False, "error": "epoch_not_found", "epoch_id": epoch_id})
                        return
                    self._send_json({"ok": True, "epoch": data})
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
                    self._send_json(self._evolution_timeline())
                    return
                if path.startswith("/mutations"):
                    self._send_json(self._collect_mutations(lineage_dir))
                    return
                if path.startswith("/staging"):
                    self._send_json(self._collect_mutations(staging_dir))
                    return
                self.send_response(404)
                self.end_headers()

            def log_message(self, format, *args):  # pragma: no cover
                return

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
                window_env = os.getenv("ADAAD_MUTATION_RATE_WINDOW_SEC", str(GOVERNANCE_POLICY.mutation_rate_window_sec)).strip()
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
                determinism_window = GOVERNANCE_POLICY.determinism_window
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
                threshold_pass = GOVERNANCE_POLICY.thresholds.determinism_pass
                threshold_warn = GOVERNANCE_POLICY.thresholds.determinism_warn
                if rolling_score >= threshold_pass and mutation_rate.get("ok", True):
                    governance_health = "PASS"
                elif rolling_score >= threshold_warn:
                    governance_health = "WARN"
                else:
                    governance_health = "BLOCK"
                return {
                    "governance_health": governance_health,
                    "model_version": GOVERNANCE_POLICY.model.version,
                    "policy_fingerprint": GOVERNANCE_POLICY.fingerprint,
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
                z2 = WILSON_Z_95 ** 2
                denom = 1.0 + z2 / total
                center = (p_hat + z2 / (2.0 * total)) / denom
                margin = (WILSON_Z_95 / denom) * ((p_hat * (1.0 - p_hat) / total + z2 / (4.0 * total * total)) ** 0.5)
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
                max_weight = max(DRIFT_CLASS_WEIGHTS.values())
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
                    score = sum(DRIFT_CLASS_WEIGHTS.get(name, 1.0) * int(counts.get(name, 0)) for name in SEMANTIC_DRIFT_CLASSES) / (total * max_weight)
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

                current_health = _health(GOVERNANCE_POLICY)
                simulated_health = _health(candidate)
                return {
                    "ok": True,
                    "inputs": {
                        "determinism_score": score,
                        "rate_limiter_ok": rate_limiter_ok,
                    },
                    "current_policy": {
                        "path": str(Path("governance") / "governance_policy_v1.json"),
                        "fingerprint": GOVERNANCE_POLICY.fingerprint,
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

                instability = (
                    INSTABILITY_WEIGHTS["semantic_drift"] * drift_density
                    + INSTABILITY_WEIGHTS["replay_failure"] * float(risk.get("replay_failure_rate", 0.0))
                    + INSTABILITY_WEIGHTS["escalation"] * float(risk.get("escalation_frequency", 0.0))
                    + INSTABILITY_WEIGHTS["determinism_drift"] * float(risk.get("determinism_drift_index", 0.0))
                )
                instability_index = min(1.0, max(0.0, round(instability, 6)))
                velocity_spike = abs(instability_velocity) >= VELOCITY_SPIKE_THRESHOLD
                return {
                    "instability_index": instability_index,
                    "instability_velocity": instability_velocity,
                    "instability_acceleration": instability_acceleration,
                    "velocity_spike_anomaly": velocity_spike,
                    "velocity_anomaly_mode": "absolute_delta",
                    "confidence_interval": confidence_interval,
                    "weights": dict(INSTABILITY_WEIGHTS),
                    "drift_class_weights": dict(DRIFT_CLASS_WEIGHTS),
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

                if instability_index >= ALERT_THRESHOLDS["instability_critical"]:
                    critical.append({"code": "instability_critical", "value": instability_index})
                elif instability_index >= ALERT_THRESHOLDS["instability_warning"]:
                    warning.append({"code": "instability_warning", "value": instability_index})

                if replay_failure_rate >= ALERT_THRESHOLDS["replay_failure_warning"]:
                    warning.append({"code": "replay_failure_warning", "value": replay_failure_rate})

                if ALERT_THRESHOLDS["velocity_spike"] and velocity_spike:
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
                    "thresholds": dict(ALERT_THRESHOLDS),
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

            @staticmethod
            def _replay_divergence() -> Dict:
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
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>{HUMAN_DASHBOARD_TITLE}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 0; background: #0e1624; color: #e8eef6; }}
    header {{ background: #17243a; padding: 1rem 1.25rem; }}
    main {{ padding: 1rem 1.25rem 2rem; display: grid; gap: 1rem; }}
    section {{ border: 1px solid #273751; border-radius: 8px; padding: 0.9rem; background: #121d30; }}
    h1, h2 {{ margin: 0 0 0.75rem; }}
    h1 {{ font-size: 1.3rem; }}
    h2 {{ font-size: 1rem; color: #9ac0ff; }}
    pre {{ overflow-x: auto; white-space: pre-wrap; margin: 0; }}
    .meta {{ color: #a8b8cc; font-size: 0.9rem; margin-top: 0.3rem; }}
  </style>
</head>
<body>
  <header>
    <h1>{HUMAN_DASHBOARD_TITLE}</h1>
    <div class=\"meta\">Read-only governance control plane view. No mutation execution is exposed by this UI.</div>
  </header>
  <main>
    <section><h2>System state</h2><pre id=\"state\">Loading...</pre></section>
    <section><h2>Intelligence snapshot</h2><pre id=\"intelligence\">Loading...</pre></section>
    <section><h2>Risk summary</h2><pre id=\"risk\">Loading...</pre></section>
    <section><h2>Risk instability</h2><pre id=\"instability\">Loading...</pre></section>
    <section><h2>Replay divergence</h2><pre id=\"replay\">Loading...</pre></section>
    <section><h2>Evolution timeline (latest)</h2><pre id=\"timeline\">Loading...</pre></section>
  </main>
  <script src=\"/ui/aponi.js\"></script>
</body>
</html>
"""

            @staticmethod
            def _user_console_js() -> str:
                return """async function paint(id, endpoint) {
  const el = document.getElementById(id);
  if (!el) return;
  try {
    const response = await fetch(endpoint, { cache: 'no-store' });
    const payload = await response.json();
    el.textContent = JSON.stringify(payload, null, 2);
  } catch (err) {
    el.textContent = 'Failed to load ' + endpoint + ': ' + err;
  }
}

async function refresh() {
  await Promise.all([
    paint('state', '/state'),
    paint('intelligence', '/system/intelligence'),
    paint('risk', '/risk/summary'),
    paint('instability', '/risk/instability'),
    paint('replay', '/replay/divergence'),
    paint('timeline', '/evolution/timeline'),
  ]);
}

refresh();
setInterval(refresh, 5000);
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
        "/capabilities /lineage /mutations /staging /evolution/epoch?epoch_id=... /evolution/live /evolution/active /evolution/timeline"
    )
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:  # pragma: no cover - manual shutdown path
        dashboard.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
