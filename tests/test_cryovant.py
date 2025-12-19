import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from security.cryovant import Cryovant, CryovantError, LEDGER_PATH, LEDGER_SCHEMA_VERSION
from security.schema_versions import LINEAGE_SCHEMA_VERSION


class CryovantTests(unittest.TestCase):
    def setUp(self) -> None:
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)

    def tearDown(self) -> None:
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def _read_events(self) -> list[dict]:
        ledger = LEDGER_PATH
        if not ledger.exists():
            return []
        return [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_ledger_write_and_path(self) -> None:
        c = Cryovant()
        ledger_path = c.touch_ledger()
        c.append_event(
            {
                "action": "doctor_probe",
                "actor": "test",
                "outcome": "ok",
                "agent_id": "n/a",
                "lineage_hash": "n/a",
                "signature_id": "n/a",
                "schema_version": LEDGER_SCHEMA_VERSION,
                "detail": {},
            }
        )
        self.assertEqual(ledger_path, LEDGER_PATH)
        self.assertTrue(ledger_path.exists())
        events = self._read_events()
        self.assertEqual(events[0]["action"], "doctor_probe")
        self.assertEqual(events[0]["schema_version"], LEDGER_SCHEMA_VERSION)

    def test_gate_cycle_records_rejection_on_missing(self) -> None:
        agent_dir = Path("app/agents/example")
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "meta.json").write_text("{}", encoding="utf-8")

        c = Cryovant()
        with self.assertRaises(CryovantError):
            c.gate_cycle([agent_dir])

        events = self._read_events()
        missing_files = ["dna.json", "certificate.json"]
        rejection_payload = {
            "reason": "metadata_invalid",
            "missing": missing_files,
            "schema_violations": [],
            "path": str(agent_dir),
        }
        seed = json.dumps({"agent_id": "example", "reason": "metadata_invalid", "detail": rejection_payload}, sort_keys=True)
        expected_hash = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        self.assertEqual(events[0]["action"], "gate_cycle")
        self.assertEqual(events[0]["outcome"], "rejected")
        self.assertEqual(events[0]["agent_id"], "example")
        self.assertEqual(events[0]["lineage_hash"], expected_hash)
        self.assertEqual(events[0]["signature_id"], f"example-{expected_hash[:12]}")
        self.assertIn("missing", events[0]["detail"])
        self.assertIn("path", events[0]["detail"])
        self.assertEqual(events[0]["schema_version"], LEDGER_SCHEMA_VERSION)

    def test_gate_cycle_accepts_with_required_metadata(self) -> None:
        agent_dir = Path("app/agents/example")
        agent_dir.mkdir(parents=True, exist_ok=True)
        for name in ("meta.json", "dna.json", "certificate.json"):
            (agent_dir / name).write_text(json.dumps({"schema_version": LINEAGE_SCHEMA_VERSION}), encoding="utf-8")

        c = Cryovant()
        c.gate_cycle([agent_dir])

        events = self._read_events()
        self.assertEqual(events[0]["outcome"], "accepted")
        self.assertEqual(events[0]["agent_id"], "example")
        self.assertTrue(events[0]["lineage_hash"])
        self.assertEqual(events[0]["signature_id"], f"example-{events[0]['lineage_hash']}")
        self.assertEqual(events[0]["schema_version"], LEDGER_SCHEMA_VERSION)

    def test_gate_cycle_rejects_on_schema_version_mismatch(self) -> None:
        agent_dir = Path("app/agents/example")
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "meta.json").write_text(json.dumps({"schema_version": "0.9"}), encoding="utf-8")
        (agent_dir / "dna.json").write_text(json.dumps({"schema_version": LINEAGE_SCHEMA_VERSION}), encoding="utf-8")
        (agent_dir / "certificate.json").write_text(
            json.dumps({"schema_version": LINEAGE_SCHEMA_VERSION}), encoding="utf-8"
        )

        c = Cryovant()
        with self.assertRaises(CryovantError):
            c.gate_cycle([agent_dir])

        events = self._read_events()
        self.assertEqual(events[0]["outcome"], "rejected")
        self.assertIn("schema_violations", events[0]["detail"])
        self.assertEqual(events[0]["schema_version"], LEDGER_SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
