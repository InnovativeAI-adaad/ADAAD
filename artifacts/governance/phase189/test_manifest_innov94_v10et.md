# Test Manifest — INNOV-94 · V10ET
**Phase 189 · v9.122.0 · 30/30 tests passing**

| Test ID | Name | Category | Invariant Exercised |
|---------|------|----------|---------------------|
| T189-V10ET-01 | test_01_engine_instantiates | Epoch Input Validation | — |
| T189-V10ET-02 | test_02_reads_agent_state | Epoch Input Validation | V10ET-SCOPE-0 |
| T189-V10ET-03 | test_03_reads_gtc_ledger | Epoch Input Validation | V10ET-SCOPE-0 |
| T189-V10ET-04 | test_04_empty_gtc_ledger_returns_none | Epoch Input Validation | V10ET-SCOPE-0 |
| T189-V10ET-05 | test_05_missing_gtc_ledger_returns_advisory_only | Epoch Input Validation | V10ET-HUMAN0-0 |
| T189-V10ET-06 | test_06_missing_agent_state_uses_defaults | Epoch Input Validation | V10ET-SCOPE-0 |
| T189-V10ET-07 | test_07_merkle_root_recomputed_correctly | Merkle Re-validation | V10ET-VERIFY-0 |
| T189-V10ET-08 | test_08_tampered_merkle_root_raises_verify_error | Merkle Re-validation | V10ET-VERIFY-0 |
| T189-V10ET-09 | test_09_empty_digest_list_raises_verify_error | Merkle Re-validation | V10ET-VERIFY-0 |
| T189-V10ET-10 | test_10_merkle_is_deterministic | Merkle Re-validation | V10ET-VERIFY-0 |
| T189-V10ET-11 | test_11_merkle_changes_with_different_innovations | Merkle Re-validation | V10ET-VERIFY-0 |
| T189-V10ET-12 | test_12_seal_includes_merkle_root_in_record | Merkle Re-validation | V10ET-VERIFY-0 |
| T189-V10ET-13 | test_13_sealed_entry_has_valid_hmac | HMAC Chain | V10ET-CHAIN-0 |
| T189-V10ET-14 | test_14_verify_chain_returns_true_on_valid_ledger | HMAC Chain | V10ET-CHAIN-0 |
| T189-V10ET-15 | test_15_tampered_hmac_raises_chain_error_on_load | HMAC Chain | V10ET-CHAIN-0 |
| T189-V10ET-16 | test_16_prev_digest_is_genesis_for_first_entry | HMAC Chain | V10ET-CHAIN-0 |
| T189-V10ET-17 | test_17_hmac_compare_digest_used_not_string_equality | HMAC Chain | AUTH-CT-0 |
| T189-V10ET-18 | test_18_advisory_emitted_before_seal | HUMAN-0 Runbook | V10ET-HUMAN0-0 |
| T189-V10ET-19 | test_19_runbook_contains_10_steps | HUMAN-0 Runbook | V10ET-HUMAN0-0 |
| T189-V10ET-20 | test_20_runbook_non_delegable_note_present | HUMAN-0 Runbook | V10ET-HUMAN0-0 |
| T189-V10ET-21 | test_21_latest_advisory_returns_after_seal | HUMAN-0 Runbook | V10ET-HUMAN0-0 |
| T189-V10ET-22 | test_22_seal_creates_epoch_ledger_file | Epoch Immutability | V10ET-EPOCH-0 |
| T189-V10ET-23 | test_23_double_seal_raises_epoch_error | Epoch Immutability | V10ET-EPOCH-0 |
| T189-V10ET-24 | test_24_sealed_record_contains_governor | Epoch Immutability | — |
| T189-V10ET-25 | test_25_sealed_record_epoch_transition_fields | Epoch Immutability | V10ET-EPOCH-0 |
| T189-V10ET-26 | test_26_fixed_timestamp_provider_is_deterministic | Determinism | AUTH-DETERM-0 |
| T189-V10ET-27 | test_27_same_inputs_produce_same_hmac | Determinism | AUTH-CT-0 |
| T189-V10ET-28 | test_28_epoch_seal_record_id_is_deterministic_with_fixed_ts | Determinism | AUTH-DETERM-0 |
| T189-V10ET-29 | test_29_router_has_required_routes | REST Coverage | — |
| T189-V10ET-30 | test_30_seal_endpoint_dry_run_returns_advisory_only | REST Coverage | V10ET-SCOPE-0 |

**Result: 30/30 PASS**
