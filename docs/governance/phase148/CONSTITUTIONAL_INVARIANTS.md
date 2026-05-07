# SPDX-License-Identifier: Apache-2.0
# Phase 148 — Constitutional Invariants Declaration
# Live Execution Feed (Innovation 54) · v9.81.0

## Invariant Registry

### CEL-FEED-0
**Rule:** Subscribing to the LEF engine MUST NEVER influence the CEL execution path.
**Enforcement:** Structural — `emit()` never awaits subscriber acknowledgement. Fan-out
occurs after chain state is committed. Removing a subscriber has zero effect on the chain
or any other subscriber.
**Test coverage:** T148-E13, T148-E14, T148-S03
**Violation consequence:** Any implementation that gates `emit()` on subscriber readiness
is a CEL-FEED-0 violation and must be rejected by ArchitectAgent.

### CEL-FEED-COMPLETE-0
**Rule:** Every CEL cycle MUST emit a COMPLETE or BLOCKED step before the generator returns.
Silent exits are a constitutional violation.
**Enforcement:** `lef_context()` emits `EPOCH_COMPLETE` on clean exit and `EPOCH_BLOCKED`
on any exception in the epoch body. `step()` context manager emits COMPLETE or ERROR.
**Test coverage:** T148-L06, T148-L07, T148-L02, T148-L03
**Violation consequence:** Silent epoch exits lose auditability of the CEL pipeline.

### LEF-CHAIN-0
**Rule:** The HMAC-SHA256 chain is integrity-critical. Any `prev_hash` mismatch raises
`CELChainIntegrityError` immediately. No partial-chain emission occurs.
**Enforcement:** `CELFeedEngine.emit()` verifies `event.prev_hash == self._prev_hash`
inside `_chain_lock` before signing. `verify_chain()` replays the full in-memory log.
**Test coverage:** T148-E04, T148-E05, T148-E10, T148-E11
**Violation consequence:** Chain break = audit evidence is untrustworthy. Fail-closed.

### LEF-DETERM-0
**Rule:** `CELStepEvent` serialisation is deterministic for identical inputs.
**Enforcement:** `canonical_bytes()` uses `json.dumps(sort_keys=True, separators=(",", ":"))`.
No random salt, no wall-clock variation in the HMAC input. Timestamp is supplied by caller.
**Test coverage:** T148-E06, T148-E18, T148-E07
**Violation consequence:** Non-determinism breaks replay proof.

### LEF-NOWRITE-0
**Rule:** SSE subscription produces zero lineage ledger writes. The engine stores events
in memory only; it never touches the evidence ledger, lineage ledger, or GovernanceGate.
**Enforcement:** AST import scan in CI (T148-S03, S04, S05). In-memory `_event_log` list
only. No filesystem writes in `emit()`, `subscribe()`, or `_fanout()`.
**Test coverage:** T148-S03, T148-S04, T148-S05, T148-E12
**Violation consequence:** Observer path must never contaminate governed evidence surface.

## Authority Note
These invariants are advisory additions to the ADAAD constitutional layer.
They do not modify GovernanceGate rules or require a constitution version bump.
GovernanceGate retains sole mutation-approval authority.

## Sign-off
Phase: 148
Innovation: INNOV-54
Authority level: governor-review
Human gate token required: HUMAN-0 (INNOV-54)
Date: 2026-05-01
