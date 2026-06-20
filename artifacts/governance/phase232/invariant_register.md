# Invariant Register — Phase 232 · INNOV-137 · CACG

| ID | Class | Description |
|---|---|---|
| CACG-CHAIN-0 | Hard | CycleGovernanceLedger HMAC-SHA-256 chained; verified before every append |
| CACG-APPEND-0 | Hard | CycleGovernanceLedger append-only; sealed records cannot be removed or mutated |
| CACG-STAGES-0 | Hard | Exactly 8 ACI pipeline stages governed (CASL/CADE/CAPE/CAVE/CAOE/CALI/CACP/CAMS); unrecognised stage raises StageError |
| CACG-TIMEOUT-0 | Hard | Every stage carries a positive timeout; completion after deadline raises TimeoutViolation; zero/negative raises ConfigError at registration |
| CACG-STALL-0 | Hard | Cycle with any missing stage classified STALLED; STALLED cycle blocks promotion |
| CACG-HUMAN0-0 | Hard | Every STALLED or VIOLATED cycle requires non-empty HUMAN-0 escalation identity |
| CACG-IMMUT-0 | Hard | Sealed CycleGovernanceRecords raise ImmutabilityViolation on any write attempt after sealing |
| CACG-DETERM-0 | Hard | Cycle outcome classification deterministic given stage receipts and timeout thresholds; no RNG |
| CACG-AUDIT-0 | Hard | Every CACG operation sealed into parallel HMAC-chained audit log |
| CACG-PROOF-0 | Hard | Every sealed CycleGovernanceRecord carries HMAC-SHA-256 proof binding all stage receipts |

**Total new Hard-class invariants: 10**
**Cumulative Hard-class invariants: 944**
