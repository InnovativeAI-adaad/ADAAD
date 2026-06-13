# Prior Art Notes

## Public Verification Endpoint — Phase 221 CGML

The public CGML verification surface is implemented by `app/api/cgml.py`. The router exposes `GET /cgml/chain/verify` as the chain-integrity verification endpoint for the Constitutional Governance Meta-Ledger, returning `CHAIN-VALID` when the HMAC-SHA-256 meta-ledger chain verifies successfully.

Repository-local verification coverage is documented in `tests/test_phase221_cgml.py`, including the Phase 221 route round trip that appends a CGML event and then calls `GET /cgml/chain/verify`. The Phase 221 governance artifact `artifacts/governance/phase221/ILA-221-2026-06-13-001.json` records `app/api/cgml.py`, `GET /cgml/chain/verify`, and `tests/test_phase221_cgml.py` as the shipped router, endpoint, and test suite for INNOV-126 / CGML.

Documentation-only verification command for build sessions:

```bash
PYTHONPATH=. pytest tests/test_phase221_cgml.py -q
```

Do not treat this note as an instruction to execute tests during documentation-only edits; run the command only inside an active build or verification session.
