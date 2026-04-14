# DORK — Developer Operator Runtime Kernel

**DORK is the governance intelligence of ADAAD.** It is not a chatbot bolted on top of a system. It is the institutional memory, the constitutional archivist, and the operator's primary interface to the entire mutation history of a running ADAAD instance.

Ask it why a mutation was blocked six weeks ago. Ask it which constitutional invariants are under the most pressure right now. Ask it to explain the CEPD proof chain for Phase 138 in plain English. It answers with citations from the hash-chained ledger.

---

## What DORK does

| Capability | Description |
|:-----------|:------------|
| **Constitutional Q&A** | Natural-language queries over the full constitutional corpus |
| **Ledger archaeology** | Retrieves and explains any past governance decision by phase, mutation, or invariant |
| **Invariant pressure analysis** | Surfaces which Hard-class invariants are seeing the most stress |
| **Mutation lineage tracing** | Traces any current capability back to its originating mutation and phase |
| **Grounded synthesis (RAGS)** | Every response is grounded in retrieved constitutional precedent — not hallucinated |
| **Real-time agent state** | Exposes live Architect / Dream / Beast agent status via the Living Fleet bridge |

---

## Interface

**Production:** [aponi.adaad.pro](https://aponi.adaad.pro)  
**Local:** `python server.py` → open `ui/dork.html`  
**Streaming endpoint:** `POST /api/dork/stream`  
**Default model:** `claude-sonnet-4-6`

---

## Quick-start prompts

```
"Why was the mutation in Phase 132 blocked?"
"Which invariants have the highest violation rate this month?"
"Explain INNOV-50 RAGS in plain English."
"What changed between v9.74.0 and v9.75.0 from a governance perspective?"
"Show me the blast radius model output for INNOV-43."
"Is the HUMAN-0 gate active on this instance?"
```

---

## The DORK Intelligence Trilogy

DORK is built on three layered innovations shipped in Phases 142–144:

| Innovation | Module | What it delivers |
|:-----------|:-------|:-----------------|
| **INNOV-48 · CSS** | `embedder.py` | Vector-space semantic search over the entire constitutional corpus |
| **INNOV-49 · CMU** | `model_validator.py` | Governed LLM backend rotation with constitutional benchmark gate |
| **INNOV-50 · RAGS** | `grounded_responder.py` | Retrieval-Augmented Governance Synthesis — responses grounded in constitutional precedent |

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  DORK Interface                      │
│              ui/dork.html  (browser)                 │
└────────────────────────┬────────────────────────────┘
                         │  POST /api/dork/stream
┌────────────────────────▼────────────────────────────┐
│                  server.py (proxy)                   │
│           Model: claude-sonnet-4-6                   │
└────────────────────────┬────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────┐
│                  RAGS (INNOV-50)                     │
│         grounded_responder.py                        │
│   Retrieves constitutional precedent before          │
│   generating any governance response                 │
└────────────────────────┬────────────────────────────┘
                         │
        ┌────────────────┴──────────────────┐
        │                                   │
┌───────▼──────┐                  ┌─────────▼──────┐
│  CSS (48)    │                  │  Evolution     │
│  Semantic    │                  │  Ledger        │
│  Embedder    │                  │  .jsonl        │
└──────────────┘                  └────────────────┘
```

---

## Constitutional invariants governing DORK

| Invariant | Requirement |
|:----------|:------------|
| `DFLEET-0` | Living Fleet agents must maintain constitutional lifecycle compliance |
| `DFSB-0` | Fleet-server bridge must expose real-time state without mutation side effects |
| `LKSE-SYNC-0` | Knowledge corpus sync must be deterministic and hash-verified |
| `CSS-DETERM-0` | Semantic search results must be deterministic given identical queries |
| `CMU-HUMAN0-0` | LLM backend changes require HUMAN-0 ratification |
| `RAGS-GROUND-0` | Every synthesis response must cite its retrieved constitutional sources |
| `RAGS-DETERM-0` | RAGS output is deterministic for identical context and query |

---

## Documentation

- **Strategic Plan & Thesis:** [`docs/governance/DORK_STRATEGIC_PLAN.md`](docs/governance/DORK_STRATEGIC_PLAN.md)
- **Evolutionary Roadmap:** [`docs/governance/DORK_EVOLUTIONARY_ROADMAP.md`](docs/governance/DORK_EVOLUTIONARY_ROADMAP.md)
- **RAGS Implementation:** `runtime/evolution/grounded_responder.py`
- **Fleet Bridge:** `runtime/evolution/dork_fleet_server_bridge.py`

---

*DORK: How a constitutional system knows itself.*
