# DORK Intelligence Module (dorkllm)

The **DORK Intelligence Module** is the strategic brain of ADAAD. it provides a high-level, constitutionally-aligned interface for developer intelligence.

## Architecture

- **`intelligence.py`**: The core execution engine. It manages a hierarchy of LLM providers (Local Ollama, Groq, Anthropic) and handles multi-turn strategic tool execution.
- **`context.py`**: The context synthesis layer. It builds deep codebase awareness by scanning project structure, architectural documents, and git history.
- **`Modelfile`**: The personality definition for Ollama. It bakes the DORK persona, cognitive architecture, and constitutional constraints directly into the local model.
- **`trace.jsonl`**: Located in `logs/`, this provides a causal trace of all LLM interactions for drift detection and auditing.

## Providers

1. **Groq (Free Tier)**: Primary cloud provider for high-speed technical reasoning.
2. **Local Ollama (`dork` model)**: Secondary/Local provider for privacy and zero-cost operation.
3. **Anthropic (Claude)**: Tertiary provider for complex strategic reasoning.

## Strategic Mode

DORK automatically enters **Strategic Mode** when queries involve complex architectural tasks (e.g., "refactor", "optimize"). In this mode, it performs an extensive context synthesis of the codebase to provide more accurate and grounded responses.

## Setup

To build the local DORK model:
```bash
cd dorkllm
./build.sh
```
