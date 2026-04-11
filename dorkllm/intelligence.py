# DORK Intelligence Module — Phase 132 Enhancement
# OPT-001 → OPT-006 optimization passes + DORK-OUTPUT-0 invariant
# Constitutional invariants: DORK-OUTPUT-0, DORK-TRACE-0

import os
import json
import urllib.request
import subprocess
import re
import shlex
from datetime import datetime
from pathlib import Path

try:
    import dorkllm.context as context_mod
    import dorkllm.state as state_mod
    import dorkllm.retriever as retriever
except ImportError:
    context_mod = None
    state_mod = None
    retriever = None

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "dork")
TRACE_LOG_PATH = "logs/dork_llm_trace.jsonl"
RUN_TAG_ENV = "ADAAD_DORK_ALLOW_RUN_TAGS"
RUN_ALLOWLIST_ENV = "ADAAD_DORK_RUN_ALLOWLIST"
RUN_ALLOW_PREFIX_ENV = "ADAAD_DORK_RUN_ALLOW_PREFIXES"
RUN_TIMEOUT_SEC = int(os.getenv("ADAAD_DORK_RUN_TIMEOUT_SEC", "10"))
RUN_OUTPUT_MAX_CHARS = int(os.getenv("ADAAD_DORK_RUN_OUTPUT_MAX_CHARS", "2000"))
POLICY_BLOCKED_RUN_RESPONSE = (
    "Policy blocked: `<run>` tool execution is disabled. "
    "Set ADAAD_DORK_ALLOW_RUN_TAGS=1 to allow policy-gated execution."
)

# ── DORK-OUTPUT-0 ─────────────────────────────────────────────────────────────
# Hard invariant: All LLM responses MUST be post-processed through the
# output_sanitizer pipeline (OPT-005) before delivery to the caller.
# Responses containing hallucinated hash references (hex strings > 16 chars
# not present in source context) MUST be flagged and stripped.
# ─────────────────────────────────────────────────────────────────────────────

# ── DORK-TRACE-0 ─────────────────────────────────────────────────────────────
# Hard invariant: Every LLM invocation MUST emit a structured trace entry
# to TRACE_LOG_PATH before returning. Silent failures are constitutionally
# prohibited — errors must be logged, not swallowed.
# ─────────────────────────────────────────────────────────────────────────────


# ── OPT-001: Context Deduplication ───────────────────────────────────────────
def opt_001_dedup_context(messages: list[dict]) -> list[dict]:
    """Remove exact-duplicate consecutive assistant messages."""
    if len(messages) < 2:
        return messages
    deduped = [messages[0]]
    for msg in messages[1:]:
        if not (msg["role"] == "assistant" and deduped[-1]["role"] == "assistant"
                and msg["content"] == deduped[-1]["content"]):
            deduped.append(msg)
    return deduped


# ── OPT-002: Prompt Compression ──────────────────────────────────────────────
def opt_002_compress_prompt(system_prompt: str, max_chars: int = 3000) -> str:
    """Truncate system prompt at sentence boundary to stay within token budget."""
    if len(system_prompt) <= max_chars:
        return system_prompt
    truncated = system_prompt[:max_chars]
    last_period = truncated.rfind(". ")
    if last_period > max_chars // 2:
        truncated = truncated[:last_period + 1]
    return truncated + "\n[context truncated by OPT-002]"


# ── OPT-003: Turn Budget Enforcement ─────────────────────────────────────────
MAX_TURNS = int(os.getenv("DORK_MAX_TURNS", "8"))

def opt_003_enforce_turn_budget(turn: int) -> bool:
    """Return True if we are within the allowed turn budget."""
    return turn < MAX_TURNS


# ── OPT-004: Intent Preflight ────────────────────────────────────────────────
def opt_004_intent_preflight(query: str) -> dict:
    """
    Classify the query before LLM invocation to select the right system prompt.
    Returns {'category': str, 'confidence': float}.
    """
    if context_mod and hasattr(context_mod, "classify_query"):
        cat, conf = context_mod.classify_query(query)
        return {"category": cat, "confidence": conf}
    return {"category": "governance", "confidence": 0.0}


# ── OPT-005: Output Sanitizer ────────────────────────────────────────────────
_HEX_PATTERN = re.compile(r"\b[0-9a-f]{32,}\b", re.IGNORECASE)

def opt_005_sanitize_output(text: str, source_context: str = "") -> tuple[str, list[str]]:
    """
    Strip hallucinated hex hashes not present in source context.
    Returns (sanitized_text, list_of_stripped_hashes).
    """
    stripped = []
    def replacer(m):
        h = m.group(0)
        if h not in source_context:
            stripped.append(h)
            return "[hash-redacted]"
        return h
    sanitized = _HEX_PATTERN.sub(replacer, text)
    return sanitized, stripped


# ── OPT-006: Response Length Guard ───────────────────────────────────────────
MAX_RESPONSE_CHARS = int(os.getenv("DORK_MAX_RESPONSE_CHARS", "4000"))

def opt_006_length_guard(text: str) -> str:
    """Truncate overlong responses with a governance note."""
    if len(text) <= MAX_RESPONSE_CHARS:
        return text
    return text[:MAX_RESPONSE_CHARS] + "\n\n[OPT-006: Response truncated at governance limit]"


# ── Trace Logger ─────────────────────────────────────────────────────────────
def log_trace(event_type: str, payload: dict) -> None:
    """DORK-TRACE-0: emit structured trace entry before returning."""
    os.makedirs("logs", exist_ok=True)
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "event": event_type,
        **payload,
    }
    try:
        with open(TRACE_LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as exc:
        # Last-resort: stderr — never swallow silently
        import sys
        print(f"[DORK-TRACE-0 VIOLATION] log_trace failed: {exc}", file=sys.stderr)


# ── System Prompt Builder ─────────────────────────────────────────────────────
def build_system_prompt(query: str = "") -> str:
    preflight = opt_004_intent_preflight(query)
    context_block = (
        context_mod.get_relevant_context(query)
        if context_mod and hasattr(context_mod, "get_relevant_context")
        else "### CONTEXT UNAVAILABLE"
    )
    state_block = (
        state_mod.get_state_summary()
        if state_mod and hasattr(state_mod, "get_state_summary")
        else "STATE BUS: UNAVAILABLE"
    )
    base = f"""You are DORK, the AI assistant for the ADAAD autonomous governance engine.
You are embedded in the Whale.Dic developer console of Innovative AI LLC.
Governor: HUMAN-0 (Dustin L. Reid). You speak with precision, dry wit, and zero tolerance for hallucination.

Query intent: {preflight['category']} (confidence={preflight['confidence']:.3f})

{opt_002_compress_prompt(context_block)}

{state_block}

Constitutional mandate: Never fabricate ledger hashes, governance decisions, or invariant numbers.
If you do not know, say so. Cite sources when you can."""
    return base


def _env_flag_enabled(name: str) -> bool:
    value = os.getenv(name, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _split_csv_env(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _is_run_command_allowed(argv: list[str]) -> tuple[bool, str]:
    if not argv:
        return False, "empty_command"
    allowlisted_commands = set(_split_csv_env(RUN_ALLOWLIST_ENV))
    allowlisted_prefixes = _split_csv_env(RUN_ALLOW_PREFIX_ENV)
    command = argv[0]
    if command in allowlisted_commands:
        return True, "allowlist_command"
    command_line = " ".join(argv)
    if any(command_line.startswith(prefix) for prefix in allowlisted_prefixes):
        return True, "allowlist_prefix"
    return False, "command_not_allowlisted"


# ── Core Ask Function ─────────────────────────────────────────────────────────
def ask(query: str, messages: list[dict] | None = None) -> tuple[str, list[dict]]:
    """
    Submit a query to the DORK LLM with the full OPT-001→006 pipeline applied.
    Returns (response_text, updated_messages).
    """
    system_prompt = build_system_prompt(query)
    messages = messages or []
    messages = opt_001_dedup_context(messages)

    source_context = system_prompt  # used by OPT-005

    for turn in range(MAX_TURNS):
        if not opt_003_enforce_turn_budget(turn):
            log_trace("turn_budget_exceeded", {"turn": turn, "query": query[:200]})
            return "Error: DORK turn budget exceeded (OPT-003).", messages

        current_messages = messages + [{"role": "user", "content": query}]

        try:
            payload = json.dumps({
                "model": OLLAMA_MODEL,
                "messages": [{"role": "system", "content": system_prompt}] + current_messages,
                "stream": False,
            }).encode()

            req = urllib.request.Request(
                f"{OLLAMA_URL}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())

            raw_text = data.get("message", {}).get("content", "")

            # OPT-005: sanitize
            text, stripped = opt_005_sanitize_output(raw_text, source_context)
            if stripped:
                log_trace("hash_sanitized", {"stripped": stripped, "turn": turn})

            # OPT-006: length guard
            text = opt_006_length_guard(text)

            # Check for tool/command invocation pattern
            cmd_match = re.search(r"<run>(.*?)</run>", text, re.DOTALL)
            if cmd_match:
                cmd = cmd_match.group(1).strip()
                if not _env_flag_enabled(RUN_TAG_ENV):
                    log_trace(
                        "tool_invocation_blocked",
                        {
                            "tool": "run",
                            "policy": "run_tags_disabled",
                            "command": cmd,
                            "turn": turn,
                            "gate_env": RUN_TAG_ENV,
                        },
                    )
                    messages.append({"role": "assistant", "content": POLICY_BLOCKED_RUN_RESPONSE})
                    return POLICY_BLOCKED_RUN_RESPONSE, messages

                try:
                    argv = shlex.split(cmd)
                except ValueError as exc:
                    log_trace(
                        "tool_invocation_blocked",
                        {
                            "tool": "run",
                            "policy": "invalid_command_parse",
                            "command": cmd,
                            "turn": turn,
                            "error": str(exc),
                        },
                    )
                    blocked_response = f"Policy blocked: malformed `<run>` command ({exc})."
                    messages.append({"role": "assistant", "content": blocked_response})
                    return blocked_response, messages

                allowed, allow_reason = _is_run_command_allowed(argv)
                if not allowed:
                    log_trace(
                        "tool_invocation_blocked",
                        {
                            "tool": "run",
                            "policy": allow_reason,
                            "command": cmd,
                            "turn": turn,
                            "allowlist_env": RUN_ALLOWLIST_ENV,
                            "allow_prefix_env": RUN_ALLOW_PREFIX_ENV,
                        },
                    )
                    blocked_response = (
                        f"Policy blocked: `<run>` command not allowlisted ({allow_reason})."
                    )
                    messages.append({"role": "assistant", "content": blocked_response})
                    return blocked_response, messages

                log_trace(
                    "tool_invocation_allowed",
                    {
                        "tool": "run",
                        "policy": allow_reason,
                        "command": cmd,
                        "turn": turn,
                    },
                )
                try:
                    result = subprocess.run(
                        argv,
                        shell=False,
                        capture_output=True,
                        text=True,
                        timeout=RUN_TIMEOUT_SEC,
                    )
                    output = result.stdout + result.stderr
                    if len(output) > RUN_OUTPUT_MAX_CHARS:
                        output = output[:RUN_OUTPUT_MAX_CHARS] + "... (truncated)"
                    messages.append({"role": "assistant", "content": text})
                    messages.append({"role": "user", "content": f"Command output:\n{output}"})
                    continue
                except subprocess.TimeoutExpired:
                    log_trace(
                        "tool_invocation_timeout",
                        {"tool": "run", "command": cmd, "turn": turn, "timeout": RUN_TIMEOUT_SEC},
                    )
                    messages.append({"role": "user", "content": "Command timed out."})
                    continue
            else:
                log_trace("interaction_complete", {"turn": turn, "response_len": len(text)})
                messages.append({"role": "assistant", "content": text})
                return text, messages

        except Exception as exc:
            log_trace("error", {"error": str(exc), "turn": turn})
            return f"Error: Dork Intelligence Error: {exc}", messages

    log_trace("max_turns_reached", {"query": query[:200]})
    return "Error: Max turns reached without final response.", messages


def call_llm(query: str, state=None, messages: list | None = None) -> tuple:
    """Backwards compatibility for call_llm."""
    return ask(query, messages)
