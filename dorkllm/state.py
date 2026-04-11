# DORK State Bus Interface Module
# Handles synthesis of the live ADAAD state bus for LLM context

import http.client
import json
import os

PORT = int(os.getenv("ADAAD_PORT", "8000"))

def fetch_adaad_state():
    """
    Fetches the full system state from the live ADAAD server.
    """
    state = {}
    try:
        conn = http.client.HTTPConnection("localhost", PORT, timeout=1.0)
        
        # 1. Base Health (version, uptime, etc)
        conn.request("GET", "/api/health")
        resp = conn.getresponse()
        if resp.status == 200:
            state["health"] = json.loads(resp.read().decode())
        
        # 2. Governance (gate, policy, entropy)
        conn.request("GET", "/api/governance/health")
        resp = conn.getresponse()
        if resp.status == 200:
            state["governance"] = json.loads(resp.read().decode())
        
        # 3. Readiness (metrics, convergence)
        conn.request("GET", "/api/readiness")
        resp = conn.getresponse()
        if resp.status == 200:
            state["readiness"] = json.loads(resp.read().decode())
            
        conn.close()
    except:
        pass
    return state

def get_state_summary():
    """
    Returns a condensed string summary of the system state for the LLM.
    """
    state = fetch_adaad_state()
    if not state:
        return "STATE BUS: UNAVAILABLE (Local Server Down)"
        
    summary = ["### LIVE STATE BUS SUMMARY"]
    
    # Extract key metrics
    health = state.get("health", {})
    gov = state.get("governance", {})
    readiness = state.get("readiness", {})
    
    summary.append(f"- Gate Status: {'🔴 LOCKED' if gov.get('gate', {}).get('locked') else '🟢 PASS'}")
    summary.append(f"- Epoch/Phase: {health.get('epoch', '—')} / {health.get('phase', '—')}")
    summary.append(f"- Readiness: {readiness.get('readiness_score', 0.0):.2f}")
    
    return "\n".join(summary)
