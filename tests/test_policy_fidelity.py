from security.policy import evaluate


def test_policy_denies_ledger_write_when_uncertified_for_system_subject():
    decision = evaluate(
        {"type": "write", "path": "security/ledger/events.jsonl"},
        subject="system",
        resource="security/ledger/events.jsonl",
        context={"cert_ok": False},
    )
    assert decision["allow"] is False


def test_policy_allows_ledger_write_for_cryovant_even_when_uncertified():
    decision = evaluate(
        {"type": "write", "path": "security/ledger/events.jsonl"},
        subject="cryovant",
        resource="security/ledger/events.jsonl",
        context={"cert_ok": False},
    )
    assert decision["allow"] is True


def test_policy_denies_keys_write_even_for_cryovant():
    decision = evaluate(
        {"type": "write", "path": "security/keys/secret.key"},
        subject="cryovant",
        resource="security/keys/secret.key",
        context={"cert_ok": True},
    )
    assert decision["allow"] is False
