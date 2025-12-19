import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.tools.gatekeeper import process_review_tickets


class GatekeeperTests(unittest.TestCase):
    def setUp(self) -> None:
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        self._setup_base_fs()

    def tearDown(self) -> None:
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def _setup_base_fs(self) -> None:
        Path("security/ledger").mkdir(parents=True, exist_ok=True)
        Path("security/keys").mkdir(parents=True, exist_ok=True)
        Path("app/agents/active").mkdir(parents=True, exist_ok=True)
        Path("data/work/02_review").mkdir(parents=True, exist_ok=True)
        Path("data/work/00_inbox").mkdir(parents=True, exist_ok=True)
        Path("data/work/03_done").mkdir(parents=True, exist_ok=True)

    def _read_events(self) -> list[dict]:
        ledger_path = Path("security/ledger/events.jsonl")
        if not ledger_path.exists():
            return []
        return [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_rejection_on_ticket_parse_failure(self) -> None:
        review_ticket = Path("data/work/02_review/bad.json")
        review_ticket.write_text("{invalid", encoding="utf-8")

        process_review_tickets(review_dir=Path("data/work/02_review"))

        events = self._read_events()
        self.assertEqual(events[0]["action"], "promotion")
        self.assertEqual(events[0]["outcome"], "rejected")
        self.assertEqual(events[0]["detail"]["rejection_reason"], "ticket_parse_failed")
        self.assertEqual(events[0]["agent_id"], "unknown")
        self.assertIn("test_summary_hash", events[0]["detail"])

    @patch("runtime.tools.gatekeeper._run_tests", return_value=(True, "hash-ok"))
    def test_rejection_on_agent_validation_failure(self, _: object) -> None:
        review_ticket = Path("data/work/02_review/one.json")
        review_ticket.write_text(json.dumps({"id": "one", "title": "demo"}), encoding="utf-8")

        agent_dir = Path("app/agents/active/demo")
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "meta.json").write_text("{}", encoding="utf-8")

        process_review_tickets(review_dir=Path("data/work/02_review"))

        events = self._read_events()
        self.assertEqual(events[0]["action"], "promotion")
        self.assertEqual(events[0]["outcome"], "rejected")
        self.assertEqual(events[0]["detail"]["rejection_reason"], "agent_validation_failed")
        self.assertEqual(events[0]["detail"]["ticket_id"], "one")
        self.assertIn("test_summary_hash", events[0]["detail"])


if __name__ == "__main__":
    unittest.main()
