# SPDX-License-Identifier: Apache-2.0
import base64
import hashlib
import hmac
import json
import os
import tempfile
import unittest
from pathlib import Path

from runtime import metrics
from security import cryovant
from security.ledger import journal


class CryovantSignatureValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        self._orig_metrics_path = metrics.METRICS_PATH
        metrics.METRICS_PATH = Path(self.tmp.name) / "metrics.jsonl"
        self.addCleanup(setattr, metrics, "METRICS_PATH", self._orig_metrics_path)

        self._orig_ledger_root = journal.LEDGER_ROOT
        self._orig_ledger_file = journal.LEDGER_FILE
        journal.LEDGER_ROOT = Path(self.tmp.name) / "ledger"
        journal.LEDGER_FILE = journal.LEDGER_ROOT / "lineage.jsonl"
        self.addCleanup(setattr, journal, "LEDGER_ROOT", self._orig_ledger_root)
        self.addCleanup(setattr, journal, "LEDGER_FILE", self._orig_ledger_file)

        self._orig_hmac_key_b64 = os.environ.get("CRYOVANT_HMAC_KEY_B64")
        secret = b"test-secret"
        os.environ["CRYOVANT_HMAC_KEY_B64"] = base64.b64encode(secret).decode("utf-8")

        def _restore_hmac_key() -> None:
            if self._orig_hmac_key_b64 is None:
                os.environ.pop("CRYOVANT_HMAC_KEY_B64", None)
            else:
                os.environ["CRYOVANT_HMAC_KEY_B64"] = self._orig_hmac_key_b64

        self.addCleanup(_restore_hmac_key)

    def _build_agent(self, agents_root: Path, name: str, certificate: dict) -> Path:
        agent_dir = agents_root / name
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "meta.json").write_text(json.dumps({"name": name}), encoding="utf-8")
        (agent_dir / "dna.json").write_text(json.dumps({"seq": "abc"}), encoding="utf-8")
        (agent_dir / "certificate.json").write_text(json.dumps(certificate), encoding="utf-8")
        return agent_dir

    def test_certify_rejects_invalid_prefix(self) -> None:
        agents_root = Path(self.tmp.name) / "agents"
        agent_dir = self._build_agent(agents_root, "agentA", {"signature": "placeholder"})
        valid = cryovant.evolve_certificate("agentA", agent_dir, Path(self.tmp.name) / "mutation", {"capability": "ok"})
        valid["signature"] = "bad-prefix"
        (agent_dir / "certificate.json").write_text(json.dumps(valid), encoding="utf-8")

        certified, errors = cryovant.certify_agents(agents_root)

        self.assertFalse(certified)
        self.assertIn("agentA:invalid_signature", errors)

    def test_certify_rejects_wrong_hmac_signature(self) -> None:
        agents_root = Path(self.tmp.name) / "agents"
        agent_dir = self._build_agent(agents_root, "agentB", {"signature": "placeholder"})
        valid_cert = cryovant.evolve_certificate("agentB", agent_dir, Path(self.tmp.name) / "mutation-b", {"capability": "ok"})
        payload = cryovant._signature_payload(  # type: ignore[attr-defined]
            agent_id="agentB",
            issued_at=valid_cert["issued_at"],
            issued_from=valid_cert["issued_from"],
            capabilities_snapshot=valid_cert["capabilities_snapshot"],
            meta=json.loads((agent_dir / "meta.json").read_text()),
            dna=json.loads((agent_dir / "dna.json").read_text()),
            issuer=valid_cert["issuer"],
            key_id=valid_cert["key_id"],
        )
        canonical = cryovant._canonical_json(payload)  # type: ignore[attr-defined]
        bad_sig = hmac.new(b"wrong-key", canonical.encode("utf-8"), hashlib.sha256).hexdigest()
        valid_cert["signature"] = f"hmac256:{bad_sig}"
        (agent_dir / "certificate.json").write_text(json.dumps(valid_cert), encoding="utf-8")

        certified, errors = cryovant.certify_agents(agents_root)

        self.assertFalse(certified)
        self.assertIn("agentB:invalid_signature", errors)

    def test_evolve_certificate_generates_valid_signature(self) -> None:
        agents_root = Path(self.tmp.name) / "agents"
        agent_dir = self._build_agent(agents_root, "agentC", {"signature": "cryovant-dev-temp"})
        mutation_dir = Path(self.tmp.name) / "lineage" / "mutation-1"
        mutation_dir.mkdir(parents=True, exist_ok=True)

        certificate = cryovant.evolve_certificate("agentC", agent_dir, mutation_dir, {"capability": "ok"})

        meta = json.loads((agent_dir / "meta.json").read_text())
        dna = json.loads((agent_dir / "dna.json").read_text())
        self.assertTrue(cryovant.verify_certificate("agentC", meta, dna, certificate))
        certified, errors = cryovant.certify_agents(agents_root)
        self.assertTrue(certified)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
