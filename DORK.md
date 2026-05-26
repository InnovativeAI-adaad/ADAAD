# DORK — Developer Operator Runtime Kernel

<div align="center">

**Governance Intelligence for ADAAD**

*Ask why a mutation was blocked. Ask which invariants are under pressure. Ask DORK anything about your constitutional history — it answers from the ledger, not from training data.*

[![ADAAD](https://img.shields.io/badge/ADAAD-v10.7.0-00d9ff?style=flat-square&labelColor=0b0c0f)](https://github.com/InnovativeAI-adaad/adaad)
[![Live](https://img.shields.io/badge/Live-aponi.adaad.pro-22c55e?style=flat-square&labelColor=0b0c0f)](https://aponi.adaad.pro)
[![PyPI](https://img.shields.io/badge/PyPI-adaad-f97316?style=flat-square&labelColor=0b0c0f)](https://pypi.org/project/adaad/)

</div>

---

## What DORK is

DORK is not a chatbot bolted on top of a system. It is the **institutional memory** of ADAAD — the constitutional archivist and the operator's primary interface to the entire mutation history of a running instance.

Three purpose-built subsystems power every response:

| Component | Full Name | Function |
|:----------|:----------|:---------|
| **DQR** | DORK Query Router (INNOV-52) | Constitutional priority-dispatch with HUMAN-0 override gate |
| **RAGS** | Retrieval-Augmented Governance Synthesis (INNOV-50) | Responses grounded in constitutional precedent with cosine-scored citation chains |
| **DPM** | DORK Persistent Memory (INNOV-51) | Session-agnostic, HMAC-chained, confidence-gated memory across restarts |

Every response is grounded in evidence retrieved from the cryptographic ledger. DORK does not hallucinate governance history.

---

## Capabilities

| Capability | Description |
|:-----------|:------------|
| **Constitutional Q&A** | Natural-language queries over the full constitutional corpus |
| **Ledger archaeology** | Retrieves and explains any past governance decision by phase, mutation, or invariant |
| **Invariant pressure analysis** | Surfaces which Hard-class invariants are seeing the most stress |
| **Mutation lineage tracing** | Traces any current capability back to its originating mutation and phase |
| **V10 readiness assessment** | Real-time Convergence Score across eight V10 criteria (CCA — INNOV-90) |
| **GIP proposals** | Governance Improvement Proposals submitted through DORK directly |
| **Agent status** | Live Architect / Dream / Beast agent status via Living Fleet bridge (INNOV-42) |
| **CEL loop reporting** | Constitutional Evolution Loop status, gate results, and phase lineage |

---

## Interface

### Aponi Dashboard (Recommended)

DORK lives natively inside **Aponi** as a first-class tab — streaming chat, live governance context bar, preset chips.

```bash
python server.py             # API server on :8000
python ui/aponi_dashboard.py # Dashboard on :8080
```

Open `http://localhost:8080` → click the **◉ DORK** tab (or press `8`).

### Standalone

```
python server.py
open http://localhost:8000/dork
```

### API

```bash
# Primary governance chat (streaming)
curl -X POST http://localhost:8000/api/dork/console/route \
  -H "Content-Type: application/json" \
  -d '{"query": "Which invariants have the highest violation rate?"}'

# Typed intent routing
curl -X POST http://localhost:8000/api/dork/intents/route \
  -H "Content-Type: application/json" \
  -d '{"query": "Explain Phase 138 governance decision"}'

# Submit a GIP
curl -X POST http://localhost:8000/api/dork/gip/propose \
  -H "Content-Type: application/json" \
  -d '{"proposal": "Add invariant for ledger compaction frequency"}'
```

### PyPI

```bash
pip install adaad
```

DQR, RAGS, and DPM are available as part of the `adaad` package.

---

## Quick-start prompts

```
"Why was the mutation in Phase 132 blocked?"
"Which invariants have the highest violation rate this month?"
"Explain INNOV-50 RAGS in plain English."
"What changed between v9.74.0 and v9.75.0 from a governance perspective?"
"What is my current V10 readiness score?"
"Is the HUMAN-0 gate active on this instance?"
"Trace the CEL loop status."
"What are the open findings right now?"
"Give me the constitutional pressure index reading."
```

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   DORK Intelligence                  │
│                                                     │
│  ┌────────────┐   ┌─────────────┐   ┌────────────┐ │
│  │    DQR     │──▶│    RAGS     │──▶│    DPM     │ │
│  │Query Router│   │  Synthesis  │   │  Memory    │ │
│  └────────────┘   └─────────────┘   └────────────┘ │
│         │                │                  │       │
│         ▼                ▼                  ▼       │
│  ┌─────────────────────────────────────────────┐   │
│  │     Constitutional Ledger (HMAC-chained)     │   │
│  │   Hash-anchored evidence · Cosine retrieval  │   │
│  └─────────────────────────────────────────────┘   │
│                                                     │
│  POST /api/dork/console/route   ← primary chat      │
│  POST /api/dork/intents/route   ← typed intents     │
│  POST /api/dork/gip/propose     ← GIP submission    │
│  GET  /api/fleet/status         ← agent status      │
└─────────────────────────────────────────────────────┘
```

---

## Configuration

| Variable | Default | Description |
|:---------|:--------|:------------|
| `ANTHROPIC_API_KEY` | — | Required for LLM responses |
| `ADAAD_ENV` | `prod` | Set `dev` for dev-token fallback |
| `DORK_MODEL` | `claude-sonnet-4-6` | Model used for responses |

---

## Source layout

```
dorkllm/
├── query_router.py                       # DQR — INNOV-52
├── retriever.py                          # RAGS retrieval
├── grounded_responder.py                 # RAGS synthesis
├── memory_engine.py                      # DPM — INNOV-51
├── intelligence.py                       # Orchestration layer
├── intent_schema.py                      # INNOV-53 Intent Expression Schema
├── convergence_certification_auditor.py  # INNOV-90 CCA V10 gate
└── ...  (40+ governance modules)

app/api/ui.py                # REST endpoints
ui/dork.html                 # Standalone UI
ui/aponi/dork_panel.js       # Native Aponi panel (Phase 186)
```

---

## Live infrastructure

| Surface | URL |
|:--------|:----|
| Dashboard | [aponi.adaad.pro](https://aponi.adaad.pro) |
| API | [api.adaad.pro](https://api.adaad.pro) |
| Docs | [docs.adaad.pro](https://docs.adaad.pro) |
| Hub | [adaad.pro](https://adaad.pro) |

---

**Governor:** Dustin L. Reid (HUMAN-0) · InnovativeAI LLC  
**License:** Apache 2.0 with proprietary governance IP

*See [README.md](README.md) for the full ADAAD system overview.*
