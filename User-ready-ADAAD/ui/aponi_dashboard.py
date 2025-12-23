"""
Minimal HTTP dashboard served with the standard library.
"""

import json
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Dict, List

from app import APP_ROOT
from runtime import metrics
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
                    self._send_json(state_ref)
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
                fitness_events = [entry for entry in entries if entry.get("event") == "fitness_scored"]
                return fitness_events[-50:]

            @staticmethod
            def _capabilities() -> Dict:
                if not capabilities_path.exists():
                    return {}
                try:
                    return json.loads(capabilities_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    return {}

        return Handler

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
        if self._thread:
            self._thread.join(timeout=1)
