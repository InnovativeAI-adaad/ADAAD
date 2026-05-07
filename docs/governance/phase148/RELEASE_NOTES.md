# SPDX-License-Identifier: Apache-2.0
# ADAAD v9.81.0 — Release Notes
# Phase 148 · Live Execution Feed · Innovation 54 · 2026-05-01

## What shipped

ADAAD's Constitutional Evolution Loop is now fully observable in real time.

Every step of every epoch — proposal generation, gate evaluation, sandbox execution,
fitness scoring, lineage updates — is now emitted as a signed, HMAC-chained event to
any connected subscriber. The observer path is constitutionally firewalled: it can
watch the pipeline but never alter it.

### New subsystem: `dorkllm` (Live Execution Feed engine)

The `dorkllm` package introduces `CELFeedEngine` — a HMAC-SHA256 chained event bus
built on five constitutional invariants. Events are signed, chained, and fan-out to
async subscribers without ever touching the governance ledger or GovernanceGate.

```python
from dorkllm.cel_feed import get_global_engine

engine = get_global_engine()
engine.emit_step("PROPOSAL", "STARTED", epoch_id="ep-001")
engine.emit_step("GATE_EVAL", "COMPLETE", epoch_id="ep-001")
assert engine.verify_chain()
```

### New adapter: `runtime.innovations30.live_execution_feed`

`LiveExecutionFeed` and `lef_context()` wrap EvolutionLoop epoch hooks:

```python
from runtime.innovations30.live_execution_feed import lef_context

with lef_context("ep-001") as lef:
    with lef.step("MUTATION_SCAN"):
        run_scanner()
    with lef.step("GATE_EVAL"):
        run_gate()
# EPOCH_COMPLETE emitted automatically on clean exit
# EPOCH_BLOCKED emitted automatically on any exception
```

### New MCP endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/events/cel-feed` | GET | SSE stream of real-time CEL step events |
| `/events/cel-feed/snapshot` | GET | In-memory chain snapshot + integrity verdict |

### New UI panel: `ui/whaledic.html`

Connect to any ADAAD server and watch the CEL pipeline execute in real time.
Epoch grouping, HMAC chain display per step, stats sidebar, invariant status
indicators, and a full event detail pane with cryptographic chain link inspection.

## Constitutional invariants (Phase 148)

| ID | Rule | Enforced by |
|---|---|---|
| CEL-FEED-0 | Subscribe never influences execution | Structure + T148-E13,E14 |
| CEL-FEED-COMPLETE-0 | COMPLETE or BLOCKED always emitted | `lef_context()` + T148-L06,L07 |
| LEF-CHAIN-0 | HMAC break is fatal | `emit()` fail-closed + T148-E05,E11 |
| LEF-DETERM-0 | Serialisation deterministic | `canonical_bytes()` + T148-E06,E18 |
| LEF-NOWRITE-0 | Zero ledger writes from observer | AST scan + T148-S03,S04,S05 |

## Test coverage
- 40 tests (T148-E01..E18, T148-L01..L09, T148-S01..S06, T148-X01..X07)
- 40/40 passing ✅

## Breaking changes
None. All new surfaces. Existing `runtime/mcp/server.py` routes unaffected.

## Upgrade
```bash
git pull origin main
# ui/whaledic.html is available immediately in your browser
# /events/cel-feed SSE endpoint live on server restart
```
