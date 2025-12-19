import unittest

from security.policy import evaluate


class PolicyFidelityTests(unittest.TestCase):
    def test_policy_denies_ledger_write_when_uncertified_for_system_subject(self) -> None:
        decision = evaluate(
            {"type": "write", "path": "security/ledger/events.jsonl"},
            subject="system",
            resource="security/ledger/events.jsonl",
            context={"cert_ok": False},
        )
        self.assertFalse(decision["allow"])

    def test_policy_allows_ledger_write_for_cryovant_even_when_uncertified(self) -> None:
        decision = evaluate(
            {"type": "write", "path": "security/ledger/events.jsonl"},
            subject="cryovant",
            resource="security/ledger/events.jsonl",
            context={"cert_ok": False},
        )
        self.assertTrue(decision["allow"])

    def test_policy_denies_keys_write_even_for_cryovant(self) -> None:
        decision = evaluate(
            {"type": "write", "path": "security/keys/secret.key"},
            subject="cryovant",
            resource="security/keys/secret.key",
            context={"cert_ok": True},
        )
        self.assertFalse(decision["allow"])


if __name__ == "__main__":
    unittest.main()
