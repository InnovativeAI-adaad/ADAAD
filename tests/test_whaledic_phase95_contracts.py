# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from pathlib import Path


WHALEDIC_PATH = Path("ui/developer/ADAADdev/whaledic.html")


def _html() -> str:
    return WHALEDIC_PATH.read_text(encoding="utf-8")


def test_dork_seed_deep_link_autostart_contract() -> None:
    """Deep-link seed path auto-starts exactly once and dispatches sendDork()."""
    html = _html()

    assert "function parseDorkSeedFromQuery()" in html
    assert "const raw=params.get('dork_seed');" in html
    assert "function autostartDorkSeed(){" in html
    assert "if(dorkSeedAutoStarted)return;" in html
    assert "dorkSeedAutoStarted=true;" in html
    assert "bus('bridge','dork_seed autostart');" in html
    assert "sendDork();" in html
    assert "setTimeout(autostartDorkSeed,0);" in html


def test_provider_fallback_order_contract_groq_then_ollama_then_engine() -> None:
    """Provider routing preserves ordered fallback contract Groq → Ollama → DorkEngine."""
    html = _html()

    groq_branch = "if(prov==='groq'&&llmCfg.groqKey){await callGroq(apiMsgs,sys,onChunk);"
    ollama_branch = "else if(prov==='ollama'){await callOllama(apiMsgs,sys,onChunk);"
    engine_branch = "else{await callDorkEngine(apiMsgs,onChunk);"

    assert groq_branch in html
    assert ollama_branch in html
    assert engine_branch in html
    assert html.index(groq_branch) < html.index(ollama_branch) < html.index(engine_branch)

    assert "if(selected==='groq'&&!llmCfg.groqKey){" in html
    assert "selected='ollama';" in html
    assert "selected='engine';" in html


def test_event_bus_structured_logging_and_filter_contract() -> None:
    """Event bus persists normalized structured rows and filter semantics."""
    html = _html()

    assert "function bus(type,message,meta={},source='ui',severity='info'){" in html
    assert "const ev={ts:new Date().toISOString(),source,type,severity:normSev(severity||type),message:String(message||''),meta:(meta&&typeof meta==='object')?meta:{}};" in html
    assert "eventBus.unshift(ev);" in html
    assert "persistEventBus();" in html
    assert "renderEventBus();" in html

    assert "if(eventBusFilter==='all')return true;" in html
    assert "if(eventBusFilter==='errors')return ev.severity==='error';" in html
    assert "return detectFilterTag(ev)===eventBusFilter;" in html
    assert "if(src.includes('oracle')||typ.includes('oracle')||msg.includes('oracle'))return'oracle';" in html


def test_oracle_bridge_propagates_over_snapshot_channel_and_prompt_bridge() -> None:
    """Oracle context survives tabs/sessions and is bridged into dork prompts."""
    html = _html()

    assert "const ADAAD_STATE_BUS_CHANNEL='adaad_state_bus';" in html
    assert "const ADAAD_STATE_BUS_SNAPSHOT_KEY='adaad_state_bus_snapshot';" in html
    assert "stateBusChannel=new BroadcastChannel(ADAAD_STATE_BUS_CHANNEL);" in html
    assert "localStorage.setItem(ADAAD_STATE_BUS_SNAPSHOT_KEY,JSON.stringify(window.ADAAD_STATE_BUS));" in html
    assert "function hydrateStateBusFromSnapshot(){" in html
    assert "function subscribeStateBusChannel(){" in html
    assert "if(!payload||payload.type!=='state_bus_patch'||!payload.patch)return;" in html

    assert "function dorkBridgeOracle(){" in html
    assert "const sb=window.ADAAD_STATE_BUS||{};" in html
    assert "bus('oracle_bridge','Oracle context bridged'" in html
    assert "dorkPrompt('Interpret this Oracle result: query=\"'+sb.oracle_last_query+'\" type='+sb.oracle_last_query_type+' summary: '+sb.oracle_last_answer_summary);" in html


def test_intent_routing_and_deterministic_response_contract() -> None:
    """DorkEngine intent classifier and fallback response path remain deterministic."""
    html = _html()

    assert "classify(q){" in html
    assert "if(/gate|lock|constit|tier|govern/.test(s))return'gate';" in html
    assert "if(/oracle|history|innovat|seed|graduated/.test(s))return'oracle';" in html
    assert "return'health';" in html

    assert "respond(q){" in html
    assert "const intent=this.classify(q);" in html
    assert "switch(intent){" in html
    assert "case'gate':" in html
    assert "case'oracle':" in html
    assert "default:{" in html

    assert "async function callDorkEngine(msgs,onChunk){" in html
    assert "const answer=DE.respond(lastUser?lastUser.content:'');" in html
    assert "const words=answer.split(' ');" in html


def test_dork_trust_metadata_badge_and_event_envelope_contract() -> None:
    """Each Dork answer includes trust metadata, a trust badge, and structured envelope persistence."""
    html = _html()

    assert "function buildTrustMetadata({providerUsed,requestedProvider,fallbackUsed,errorMessage=''}) {" in html
    assert "data_sources_used:sources" in html
    assert "snapshot_freshness:stale?'stale':'fresh'" in html
    assert "mode," in html
    assert "trust_score:trustScore" in html
    assert "downgrade_reasons:downgradeReasons" in html

    assert "function renderTrustBadge(metadata){" in html
    assert "trust-badge" in html
    assert "if(msgEl){" in html
    assert "dt.insertAdjacentHTML('afterend',renderTrustBadge(trustMetadata));" in html

    assert "emitStructuredDorkEvent(trustMetadata);" in html
    assert "event_type:'dork_answer_generated'" in html
    assert "payload:{trust_metadata:meta||{}}" in html
