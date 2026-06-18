# Invariant Register — Phase 230 · INNOV-135 · CAVE

**Cumulative total after Phase 230: 924**

## New Invariants (Phase 230)

| Invariant ID | Class | Enforcement | hmac.compare_digest |
|---|---|---|---|
| CAVE-CHAIN-0 | Hard | QuarantineLedger.verify_chain() | ✅ |
| CAVE-APPEND-0 | Hard | QuarantineLedger.append() — no delete/mutate API | ✅ |
| CAVE-IMMUT-0 | Hard | QuarantineEngine.seal() + release() state guard | ✅ |
| CAVE-SCOPE-0 | Hard | Module-load RuntimeError + VerdictRouter.route() | ✅ |
| CAVE-QUARANTINE-0 | Hard | CAVEEngine.execute() REJECT/DEFER path | ✅ |
| CAVE-REEVAL-0 | Hard | CAVEEngine.execute() HOLD path + CHIReEvaluator | ✅ |
| CAVE-HUMAN0-0 | Hard | QuarantineEngine.release() empty-string guard | ✅ |
| CAVE-DETERM-0 | Hard | VerdictRouter.route() — no RNG, pure logic | ✅ |
| CAVE-AUDIT-0 | Hard | CAVEAuditor.record() raises AuditFailure on write error | ✅ |
| CAVE-ORIGIN-0 | Hard | VerdictRouter.route() non-empty cade_record_id + mutation_ref | ✅ |
