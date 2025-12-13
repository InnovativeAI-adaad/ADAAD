# tests

Tests enforce Founder’s Law.
They must keep the system bootable and governed.

## Required coverage

1) Import sanity
  - app/main.py imports without sys.path hacks
  - canonical import roots only

2) Cryovant integrity
  - ledger directory is writable via Cryovant only
  - keys directory permission lock attempted

3) Policy exists and denies when uncertified
  - policy.evaluate() callable
  - write action denied when cert_ok is False

## Android/Termux constraints

Avoid heavy test dependencies.
Prefer stdlib and small unit tests.

## Recommended commands

python -m compileall app runtime security ui tests
pytest -q
