# Invariant Register — Phase 231 · INNOV-136 · CAMS

**Cumulative total after Phase 231: 934**

## New Invariants (Phase 231)

| Invariant ID | Class | Enforcement | hmac.compare_digest |
|---|---|---|---|
| CAMS-CHAIN-0 | Hard | MonitoringLedger.verify_chain() | ✅ |
| CAMS-APPEND-0 | Hard | MonitoringLedger.append() — no delete/mutate API | ✅ |
| CAMS-SAMPLE-0 | Hard | CHIMonitor.ingest() range + non-empty guard | n/a |
| CAMS-CLASS-0 | Hard | Module-load RuntimeError + TrendDetector.classify() | n/a |
| CAMS-DETERM-0 | Hard | TrendDetector.classify() — fixed thresholds, no RNG | n/a |
| CAMS-WINDOW-0 | Hard | TrendDetector.__init__() + classify() window guard | n/a |
| CAMS-ALERT-0 | Hard | AlertEngine.raise_alert() CRITICAL-only guard | n/a |
| CAMS-HUMAN0-0 | Hard | AlertEngine.acknowledge() empty-string guard | n/a |
| CAMS-IMMUT-0 | Hard | AlertEngine.acknowledge() state guard (OPEN only) | n/a |
| CAMS-AUDIT-0 | Hard | CAMSAuditor.record() raises AuditFailure on write error | n/a |
