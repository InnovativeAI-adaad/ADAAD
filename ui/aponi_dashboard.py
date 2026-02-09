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
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Dict, List

from app import APP_ROOT
from runtime import metrics
from runtime.metrics_analysis import mutation_rate_snapshot
from security.ledger import journal

ELEMENT_ID = "Metal"


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

        class Handler(SimpleHTTPRequestHandler):
            def _send_json(self, payload) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # noqa: N802 - required by base class
                if self.path.startswith("/state"):
                    state_payload = dict(state_ref)
                    state_payload["mutation_rate_limit"] = self._mutation_rate_state()
                    self._send_json(state_payload)
                    return
                if self.path.startswith("/metrics"):
                    self._send_json(metrics.tail(limit=50))
                    return
                if self.path.startswith("/fitness"):
                    self._send_json(self._fitness_events())
                    return
                if self.path.startswith("/capabilities"):
                    self._send_json(self._capabilities())
                    return
                if self.path.startswith("/lineage"):
                    self._send_json(journal.read_entries(limit=50))
                    return
                if self.path.startswith("/mutations"):
                    self._send_json(self._collect_mutations(lineage_dir))
                    return
                if self.path.startswith("/staging"):
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
            def _mutation_rate_state() -> Dict:
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
    print("[APONI] endpoints: /state /metrics /fitness /capabilities /lineage /mutations /staging")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:  # pragma: no cover - manual shutdown path
        dashboard.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
