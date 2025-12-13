def test_policy_exists():
    from security import policy  # noqa: WPS433
    assert callable(policy.evaluate)
