# DORK Intelligence Module
# Strategic LLM interaction layer for ADAAD

import os
import json
import urllib.request
import subprocess
import re
from datetime import datetime
from pathlib import Path

# External Context and State Modules
try:
    import dorkllm.context as context
    import dorkllm.state as state
    import dorkllm.retriever as retriever
except ImportError:
    context = None
    state = None
    retriever = None

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "dork")
TRACE_LOG_PATH = "logs/dork_llm_trace.jsonl"

def log_trace(event_type, payload):
    """Logs LLM interaction events for drift detection and causal analysis."""
    os.makedirs("logs", exist_ok=True)
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "type": event_type,
        "payload": payload
    }
    with open(TRACE_LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")

def get_system_prompt(current_state=None, query=""):
    """Builds a strategically enhanced system prompt with dynamic knowledge retrieval."""
    prompt = """You are DORK (Dynamic Operative Resource Knowledge), the best AI assistant ever by far. 
You are the primary Strategic Orchestrator for ADAAD (Autonomous Development & Adaptation Architecture).

### MISSION
Provide constitutional intelligence, causal forensics, and architectural orchestration. 

### COGNITIVE ARCHITECTURE
- ALIGNMENT: Cross-reference actions against the ADAAD Constitution. 
- STRATEGY: Start complex tasks with a 'STRATEGIC PLAN'.
- OPTIMAL MAGNITUDES: Most efficient, high-impact solution only.

### CAPABILITIES
- You can execute shell commands using <execute>command</execute>.
"""
    # 1. Integrate Live System State
    if state:
        prompt += f"\n{state.get_state_summary()}"
    elif current_state:
         prompt += f"\n### LIVE SYSTEM STATE\n{json.dumps(current_state, indent=2)}"
    
    # 2. Strategic Context Synthesis (Dynamic Knowledge Retrieval)
    if context:
        q_lower = query.lower()
        strategic_parts = []
        
        # Base Codebase Summary
        if any(kw in q_lower for kw in ["structure", "where", "list", "files", "find"]):
            strategic_parts.append(context.get_codebase_summary())
            
        # Innovations Context (for feature-related queries)
        if any(kw in q_lower for kw in ["innovation", "feature", "new", "change", "add", "implementation"]):
            strategic_parts.append(context.get_innovations_context())
            
        # Constitutional/Governance Context (for safety/governance queries)
        if any(kw in q_lower for kw in ["governance", "gate", "constitutional", "constitution", "rule", "policy", "safe", "invariant"]):
            strategic_parts.append(context.get_constitution_context())
            
        # App Logic Structure (for code-related queries)
        if any(kw in q_lower for kw in ["refactor", "optimize", "logic", "code", "app", "core", "function"]):
            strategic_parts.append(context.get_app_structure())

        if strategic_parts:
            prompt += f"\n\n### STRATEGIC CONTEXT SYNTHESIS\n" + "\n".join(strategic_parts)
            log_trace("context_synthesis", {"query": query, "modules": len(strategic_parts)})
    
    return prompt

def check_ollama():
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=1.0) as response:
            if response.status == 200:
                tags = json.loads(response.read().decode())
                models = [m['name'] for m in tags.get('models', [])]
                return True, models
    except:
        pass
    return False, []

def ask(query, messages=None):
    """
    Main entry point for Dork Intelligence.
    Handles KB retrieval, LLM interaction, and tool-use loop.
    """
    # 1. Deterministic KB Lookup (First Priority)
    if retriever:
        kb_hit = retriever.get_kb_matches(query)
        if kb_hit:
            log_trace("kb_hit", {"query": query, "hit": kb_hit})
            return f"(Aligned KB Hit - Score {kb_hit['score']:.2f}):\n{kb_hit['answer']}", None

    # 2. LLM Interaction
    api_key = os.getenv("ADAAD_ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
    groq_key = os.getenv("GROQ_API_KEY")
    ngrok_gateway_url = os.getenv("NGROK_AI_GATEWAY_URL")
    ngrok_api_key = os.getenv("NGROK_AI_GATEWAY_API_KEY")
    
    sys_prompt = get_system_prompt(None, query)
    if messages is None:
        messages = [{"role": "user", "content": query}]
    else:
        messages.append({"role": "user", "content": query})

    ollama_ok, ollama_models = check_ollama()
    
    log_trace("interaction_start", {"query": query, "provider_status": {"ollama": ollama_ok, "groq": bool(groq_key)}})

    # Multi-turn execution loop
    for turn in range(5):
        try:
            # 1. Groq
            if groq_key:
                req = urllib.request.Request(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {groq_key}", "content-type": "application/json"},
                    data=json.dumps({
                        "model": "llama3-8b-8192",
                        "messages": [{"role": "system", "content": sys_prompt}] + messages
                    }).encode("utf-8")
                )
            # 2. Ollama
            elif ollama_ok:
                model = "dork"
                if model not in ollama_models and f"{model}:latest" not in ollama_models:
                    model = OLLAMA_MODEL
                if model not in ollama_models and f"{model}:latest" not in ollama_models:
                    model = "llama3.2" if "llama3.2" in ollama_models else (ollama_models[0] if ollama_models else "llama3.2")
                
                req = urllib.request.Request(
                    f"{OLLAMA_URL}/api/chat",
                    headers={"content-type": "application/json"},
                    data=json.dumps({
                        "model": model,
                        "messages": [{"role": "system", "content": sys_prompt}] + messages,
                        "stream": False
                    }).encode("utf-8")
                )
            # 3. ngrok AI Gateway
            elif ngrok_gateway_url and ngrok_api_key:
                 req = urllib.request.Request(
                    f"{ngrok_gateway_url.rstrip('/')}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {ngrok_api_key}", "content-type": "application/json"},
                    data=json.dumps({
                        "model": "gpt-4o",
                        "messages": [{"role": "system", "content": sys_prompt}] + messages
                    }).encode("utf-8")
                )
            # 4. Anthropic
            elif api_key:
                model = os.getenv("ADAAD_ANTHROPIC_MODEL", "claude-3-opus-20240229")
                req = urllib.request.Request(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                    data=json.dumps({
                        "model": model,
                        "max_tokens": 4096,
                        "system": sys_prompt,
                        "messages": messages
                    }).encode("utf-8")
                )
            else:
                return "Error: No LLM provider found. Start Ollama or set API keys.", messages

            with urllib.request.urlopen(req) as response:
                res = json.loads(response.read().decode("utf-8"))
                if groq_key or (ngrok_gateway_url and ngrok_api_key):
                    text = res.get("choices", [{}])[0].get("message", {}).get("content", "No response.")
                elif ollama_ok:
                    text = res.get("message", {}).get("content", "No response.")
                else: # Anthropic
                    text = res.get("content", [{}])[0].get("text", "No response.")

                # Action Parser
                match = re.search(r'<execute>(.*?)</execute>', text, re.DOTALL)
                if match:
                    cmd = match.group(1).strip()
                    text_before = text[:match.start()].strip()
                    if text_before:
                        print(f"\ndork:\n{text_before}")
                    
                    print(f"\n[dork strategic execution]: {cmd}")
                    log_trace("tool_execution", {"command": cmd, "turn": turn})
                    
                    try:
                        output = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT, text=True, timeout=60)
                    except subprocess.CalledProcessError as e:
                        output = f"Exit code {e.returncode}\n{e.output}"
                    except Exception as e:
                        output = str(e)
                    
                    if len(output) > 2000:
                        output = output[:2000] + "... (truncated)"
                    
                    messages.append({"role": "assistant", "content": text})
                    messages.append({"role": "user", "content": f"Command output:\n{output}"})
                    continue
                else:
                    log_trace("interaction_complete", {"turn": turn})
                    return text, messages

        except Exception as e:
            log_trace("error", {"error": str(e), "turn": turn})
            return f"Error: Dork Intelligence Error: {str(e)}", messages

    return "Error: Max turns reached without final response.", messages

def call_llm(query, state=None, messages=None):
    """Backwards compatibility for call_llm."""
    return ask(query, messages)
