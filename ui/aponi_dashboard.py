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
from runtime.evolution import LineageLedgerV2, ReplayEngine
from runtime.evolution.epoch import CURRENT_EPOCH_PATH
from security.ledger import journal

ELEMENT_ID = "Metal"
HUMAN_DASHBOARD_TITLE = "Aponi Governance Nerve Center"
GOVERNANCE_HEALTH_MODEL_VERSION = "v1.0.0"
CONSTITUTION_ESCALATION_EVENT_TYPES = {"constitution_escalation", "constitution_escalated"}


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
                if path.startswith("/replay/divergence"):
                    self._send_json(self._replay_divergence())
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
                window_env = os.getenv("ADAAD_MUTATION_RATE_WINDOW_SEC", "3600").strip()
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
                determinism = cls._rolling_determinism_score(window=200)
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
                threshold_pass = 0.98
                threshold_warn = 0.90
                if rolling_score >= threshold_pass and mutation_rate.get("ok", True):
                    governance_health = "PASS"
                elif rolling_score >= threshold_warn:
                    governance_health = "WARN"
                else:
                    governance_health = "BLOCK"
                return {
                    "governance_health": governance_health,
                    "model_version": GOVERNANCE_HEALTH_MODEL_VERSION,
                    "model_inputs": {
                        "determinism_window": 200,
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
                    event_name = str(entry.get("event", "")).lower()
                    event_type = str(entry.get("event_type", "")).lower()
                    if event_name in CONSTITUTION_ESCALATION_EVENT_TYPES or event_type in CONSTITUTION_ESCALATION_EVENT_TYPES:
                        count += 1
                        continue
                    if "constitution" in event_name and "escalat" in event_name:
                        count += 1
                return count

            @classmethod
            def _risk_summary(cls) -> Dict:
                intelligence = cls._intelligence_snapshot()
                recent = metrics.tail(limit=200)
                escalation_frequency = intelligence["constitution_escalations_last_100"] / 100.0
                override_frequency = sum(1 for entry in recent if "override" in str(entry.get("event", "")).lower()) / 200.0
                replay_failure_rate = sum(1 for entry in recent if "replay" in str(entry.get("event", "")).lower() and "fail" in str(entry.get("event", "")).lower()) / 200.0
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
            def _state_fingerprint(value) -> str:
                canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                return f"sha256:{sha256(canonical.encode('utf-8')).hexdigest()}"

            @classmethod
            def _replay_diff(cls, epoch_id: str) -> Dict:
                epoch = replay.reconstruct_epoch(epoch_id)
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
                    "bundle_count": len(epoch.get("bundles") or []),
                }

            @staticmethod
            def _replay_divergence() -> Dict:
                recent = metrics.tail(limit=200)
                divergence_events = [
                    entry
                    for entry in recent
                    if "replay" in str(entry.get("event", "")).lower()
                    and (
                        "diverg" in str(entry.get("event", "")).lower()
                        or "fail" in str(entry.get("event", "")).lower()
                    )
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
    parser = argparse.ArgumentParser(description="Run Aponi dashboard in standalone mode.")
    parser.add_argument("--host", default=os.environ.get("APONI_HOST", "0.0.0.0"), help="Host interface to bind (env: APONI_HOST)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("APONI_PORT", "8080")), help="Port to bind (env: APONI_PORT)")
    args = parser.parse_args(argv)

    dashboard = AponiDashboard(host=args.host, port=args.port)
    dashboard.start({"status": "dashboard_only"})
    print(f"[APONI] dashboard running on http://{dashboard.host}:{dashboard.port}")
    print(
        "[APONI] endpoints: / /state /metrics /fitness /system/intelligence /risk/summary /replay/divergence /replay/diff?epoch_id=... "
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
