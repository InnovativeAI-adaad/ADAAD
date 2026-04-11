"""
tests/test_dork_v2_makeover.py
DORK v2 Makeover Acceptance Tests — 30 assertions
Validates: knowledge base expansion, capability registry extension,
           runtime extension, Claude provider wiring, UI enrichments.
"""
from pathlib import Path

WHALEDIC  = Path("ui/developer/ADAADdev/whaledic.html")
REGISTRY  = Path("ui/developer/ADAADdev/dork_capability_registry.js")
RUNTIME   = Path("ui/developer/ADAADdev/dork_runtime.js")
KB        = Path("ui/developer/ADAADdev/dork_knowledge_base.js")


# ── Knowledge Base ─────────────────────────────────────────────────────────

def test_kb_file_exists():
    assert KB.exists(), "dork_knowledge_base.js must exist"

def test_kb_has_lookup_function():
    src = KB.read_text(encoding="utf-8")
    assert "function lookup(" in src

def test_kb_has_list_all():
    src = KB.read_text(encoding="utf-8")
    assert "function listAll(" in src

def test_kb_has_list_by_tag():
    src = KB.read_text(encoding="utf-8")
    assert "function listByTag(" in src

def test_kb_exposes_dork_kb_global():
    src = KB.read_text(encoding="utf-8")
    assert "global.DORK_KB" in src

def test_kb_backward_compat_shim():
    src = KB.read_text(encoding="utf-8")
    assert "DORK_KNOWLEDGE_BASE" in src

def test_kb_covers_dork_identity():
    src = KB.read_text(encoding="utf-8")
    assert "what is dork" in src

def test_kb_covers_human_zero():
    src = KB.read_text(encoding="utf-8")
    assert "human-0" in src

def test_kb_covers_signing_ceremony():
    src = KB.read_text(encoding="utf-8")
    assert "signing ceremony" in src

def test_kb_covers_market_fitness():
    src = KB.read_text(encoding="utf-8")
    assert "market fitness" in src or "innov-22" in src.lower()

def test_kb_covers_providers():
    src = KB.read_text(encoding="utf-8")
    assert "providers" in src and "anthropic" in src.lower()

def test_kb_token_overlap_fields():
    src = KB.read_text(encoding="utf-8")
    assert "function tokenise(" in src
    assert "function overlap(" in src


# ── Capability Registry Extension ─────────────────────────────────────────

def test_registry_extension_exists():
    src = REGISTRY.read_text(encoding="utf-8")
    assert "extendDorkCapabilityRegistry" in src

def test_registry_mutation_pipeline_inspector():
    src = REGISTRY.read_text(encoding="utf-8")
    assert "mutation_pipeline_inspector" in src

def test_registry_ledger_forensics():
    src = REGISTRY.read_text(encoding="utf-8")
    assert "ledger_forensics" in src

def test_registry_constitution_diff():
    src = REGISTRY.read_text(encoding="utf-8")
    assert "constitution_diff" in src

def test_registry_phase_progress_tracker():
    src = REGISTRY.read_text(encoding="utf-8")
    assert "phase_progress_tracker" in src

def test_registry_sandbox_preflight_checker():
    src = REGISTRY.read_text(encoding="utf-8")
    assert "sandbox_preflight_checker" in src

def test_registry_agent_proposal_ranker():
    src = REGISTRY.read_text(encoding="utf-8")
    assert "agent_proposal_ranker" in src

def test_registry_signing_ceremony_status():
    src = REGISTRY.read_text(encoding="utf-8")
    assert "signing_ceremony_status" in src

def test_registry_market_fitness_readiness():
    src = REGISTRY.read_text(encoding="utf-8")
    assert "market_fitness_readiness" in src

def test_registry_v2_merge_exposes_global():
    src = REGISTRY.read_text(encoding="utf-8")
    assert "DORK_CAPABILITY_REGISTRY_V2" in src

def test_registry_extension_fan_out_merge():
    src = REGISTRY.read_text(encoding="utf-8")
    assert "mergeIntoRegistry" in src


# ── Runtime Extension ──────────────────────────────────────────────────────

def test_runtime_extension_exists():
    src = RUNTIME.read_text(encoding="utf-8")
    assert "extendDorkRuntime" in src

def test_runtime_intent_classifier():
    src = RUNTIME.read_text(encoding="utf-8")
    assert "function classifyIntent(" in src

def test_runtime_session_fingerprint():
    src = RUNTIME.read_text(encoding="utf-8")
    assert "function sessionFingerprint(" in src

def test_runtime_call_claude():
    src = RUNTIME.read_text(encoding="utf-8")
    assert "async function callClaude(" in src
    assert "anthropic-version" in src

def test_runtime_forensic_bundle():
    src = RUNTIME.read_text(encoding="utf-8")
    assert "function buildForensicBundle(" in src

def test_runtime_fan_out_capabilities():
    src = RUNTIME.read_text(encoding="utf-8")
    assert "function fanOutCapabilities(" in src

def test_runtime_kb_enricher():
    src = RUNTIME.read_text(encoding="utf-8")
    assert "function enrichWithKB(" in src

def test_runtime_patches_instance_send_message_not_only_global():
    src = RUNTIME.read_text(encoding="utf-8")
    assert "function patchRuntimeInstance(runtime)" in src
    assert "runtime.sendMessage = async function sendMessageV2" in src
    assert "global.initDorkRuntime = function patchedInitDorkRuntime" in src

def test_runtime_enrichment_metadata_return_contract():
    src = RUNTIME.read_text(encoding="utf-8")
    assert "fanOutCount: fanOut.length" in src
    assert "kbHit: kbHit || null" in src
    assert "intent" in src

def test_runtime_has_internal_event_bridge_without_event_target_dependency():
    src = RUNTIME.read_text(encoding="utf-8")
    assert "const eventBridge = (typeof global.EventTarget === \"function\") ? new global.EventTarget() : null;" in src
    assert "eventBridge.dispatchEvent(new global.CustomEvent(type, { detail: evt }))" in src
    assert "_eventTarget" not in src


# ── Whaledic UI Wiring ────────────────────────────────────────────────────

def test_whaledic_loads_kb_script():
    html = WHALEDIC.read_text(encoding="utf-8")
    assert 'script src="./dork_knowledge_base.js"' in html

def test_whaledic_loads_runtime_script():
    html = WHALEDIC.read_text(encoding="utf-8")
    assert 'script src="./dork_runtime.js"' in html

def test_whaledic_claude_provider_ui():
    html = WHALEDIC.read_text(encoding="utf-8")
    assert 'id="cp-claude"' in html
    assert 'id="inp-claude"' in html
    assert 'id="row-claude"' in html

def test_whaledic_call_claude_in_send_loop():
    html = WHALEDIC.read_text(encoding="utf-8")
    assert "callClaude(" in html
    assert "prov==='claude'" in html

def test_whaledic_call_claude_function():
    html = WHALEDIC.read_text(encoding="utf-8")
    assert "async function callClaude(" in html
    assert "anthropic-version" in html

def test_whaledic_forensic_export_button():
    html = WHALEDIC.read_text(encoding="utf-8")
    assert "exportForensicBundle" in html

def test_whaledic_intent_label_element():
    html = WHALEDIC.read_text(encoding="utf-8")
    assert 'id="dork-intent-lbl"' in html

def test_whaledic_last_query_tracking():
    html = WHALEDIC.read_text(encoding="utf-8")
    assert "lastQuery=" in html or "lastQuery =" in html

def test_whaledic_dork_v2_identity_in_buildsp():
    html = WHALEDIC.read_text(encoding="utf-8")
    assert "DORK v2" in html

def test_whaledic_kb_context_in_buildsp():
    html = WHALEDIC.read_text(encoding="utf-8")
    assert "KB CONTEXT" in html

def test_whaledic_claude_key_in_save_cfg():
    html = WHALEDIC.read_text(encoding="utf-8")
    assert "claudeKey" in html
    assert "inp-claude" in html

def test_whaledic_dork_v2_label():
    html = WHALEDIC.read_text(encoding="utf-8")
    assert "dork-title" in html and "v2" in html

def test_whaledic_runtime_send_message_bridge_exists():
    html = WHALEDIC.read_text(encoding="utf-8")
    assert "async function sendThroughDorkRuntime(msg, options)" in html
    assert "return dorkRuntime.sendMessage(msg, options||{});" in html
