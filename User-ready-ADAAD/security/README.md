# security

Element: WATER

Security is governance. It enforces ancestry, certification, and policy gating.
If security is wrong, the system is untrustworthy.

## Responsibilities

1) Cryovant gatekeeper
  - initializes ledger
  - validates ancestry and required agent structure
  - sets cert_ok state used across the system

2) Policy enforcement
  - evaluate(action, subject, resource, context) is the only policy entry point
  - default posture is deny-by-default on writes when uncertified

3) Ledger discipline
  - append-only writes
  - clear audit trail
  - no silent mutation of history

## Directory layout

security/
  cryovant.py
  policy.py
  ledger/
    events.jsonl
  keys/
    (private material, permissions locked)

## Key directory permissions

keys/ must be chmod 700.
If chmod fails, boot should fail closed for mutation engines.

## Mandatory rules

1) No module may write to ledger/ directly.
   All ledger writes go through Cryovant helper functions.

2) No module may write to keys/ directly.
   keys/ is provisioned and locked by Cryovant only.

3) No mutation engine may start unless Cryovant.gate_cycle() returns True.

4) All external side effects must call policy.evaluate().
   If policy denies, the action must not proceed.

## Policy interface

policy.evaluate(action, subject, resource, context) returns:
  { "allow": bool, "reason": str, "requires": [ ... ] }

Context MUST include:
  cert_ok: bool

Recommended extension fields:
  agent_id
  authority
  environment
  risk_level

## Ledger format

ledger/events.jsonl is JSONL.
Each line is one event object.
Events should be compact and machine-readable.

Do not store large blobs in the ledger.
Store references and hashes instead.
