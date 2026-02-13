# SPDX-License-Identifier: Apache-2.0

from runtime.recovery.tier_manager import RecoveryPolicy, RecoveryTierLevel, TierManager


def test_tier_manager_escalates_on_ledger_error() -> None:
    manager = TierManager()
    tier = manager.evaluate_escalation(
        governance_violations=0,
        ledger_errors=1,
        mutation_failures=0,
        metric_anomalies=0,
    )
    assert tier == RecoveryTierLevel.CRITICAL
    policy = RecoveryPolicy.for_tier(tier)
    assert policy.fail_close


def test_tier_manager_conservative_on_mutation_failures() -> None:
    manager = TierManager()
    tier = manager.evaluate_escalation(
        governance_violations=0,
        ledger_errors=0,
        mutation_failures=5,
        metric_anomalies=0,
    )
    assert tier == RecoveryTierLevel.CONSERVATIVE


def test_recovery_tier_supports_ordering() -> None:
    assert RecoveryTierLevel.NONE < RecoveryTierLevel.ADVISORY
    assert RecoveryTierLevel.GOVERNANCE > RecoveryTierLevel.CONSERVATIVE


def test_recovery_policy_exposes_network_toggles() -> None:
    policy = RecoveryPolicy.for_tier(RecoveryTierLevel.CRITICAL)
    assert not policy.allow_web_fetch
    assert not policy.allow_llm_calls
