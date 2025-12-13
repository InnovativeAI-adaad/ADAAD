# scripts

Scripts are operational helpers.
They must not bypass governance.

Allowed:
  - setup steps for Android/Termux
  - launch wrappers
  - basic validation commands

Forbidden:
  - scripts that write directly to security/ledger or security/keys
  - scripts that promote agents without Cryovant gate + policy allow

Keep scripts minimal and auditable.
