# SPDX-License-Identifier: Apache-2.0
# Security Policy — ADAAD

## Supported Versions

| Version Series | Supported |
|:---|:---:|
| v9.x.x (current) | ✅ Active |
| v8.x.x and below | ❌ End of life |

ADAAD uses a phase-correlated version scheme. Only the latest release on `main` receives security patches. Each phase ships as a minor version increment (`v9.N.0`).

---

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

### Preferred channel — GitHub Security Advisories

1. Go to [Security → Report a vulnerability](https://github.com/InnovativeAI-adaad/adaad/security/advisories/new)
2. Include: affected version(s), reproduction steps, impact assessment, and any suggested remediation
3. Acknowledgement within **72 hours**

### Alternative — Direct contact

Email: **security@innovativeai.dev**  
Subject: `[ADAAD SECURITY] <brief description>`

Include: affected component and version, reproduction steps, assessed severity (CVSS if available), preferred attribution or anonymity request.

---

## Response Timeline

| Stage | Target |
|:---|:---|
| Acknowledgement | 72 hours |
| Initial triage and severity assessment | 5 business days |
| Patch development (Critical / High) | 14 days from confirmation |
| Patch development (Medium / Low) | Next scheduled phase |
| CVE registration (if applicable) | At patch release |
| Public disclosure | Coordinated with reporter after patch ships |

---

## Scope

**In scope:**
- `server.py` — FastAPI application, CORS, auth, LLM proxy endpoints
- `runtime/` — Constitutional Evolution Loop, governance gates, ledger operations
- `adaad_core/` — Governance kernel public API
- `security/` — Key management, signature verification, HMAC chains
- CI/CD workflows with supply chain impact
- Dependencies with a realistic exploit path

**Out of scope:**
- Issues requiring physical access to the ADAADell governance host
- Social engineering against HUMAN-0
- Theoretical vulnerabilities with no realistic exploit path
- Development-only tooling (`scripts/`, `tools/`) with no production impact

---

## Governance-Specific Security Properties

The following are **architecturally enforced** — not policy-based:

| Property | Mechanism | Invariant |
|:---|:---|:---:|
| Critical mutations require GPG sign-off | `GovernanceGateV2` hard stop — not configurable | `HUMAN-0` |
| Ledger is tamper-evident | SHA-256 hash chain — altering any entry breaks all subsequent hashes | `CEL-EVIDENCE-0` |
| Ed25519 only in production | Fail-closed — no silent HMAC downgrade | `REPLAY-ALGO-0` |
| HMAC keys from environment | Never hardcoded in source | `GRRP-KEY-0` |
| GPG fingerprint binding | Approval tied to key fingerprint, not just presence | `HAPG-IDENTITY-0` |
| Approvals expire after 7 days | Prevents replay of stale approvals | `HAPG-EXPIRY-0` |

Findings that claim to bypass these invariants are treated as **Critical** and triaged immediately.

---

## Disclosure Policy

ADAAD follows **coordinated disclosure**:

1. Reporter submits finding privately
2. Patch developed as a governed phase (with governance artifacts and ledger entry)
3. Security advisory published simultaneously with patch release
4. Reporter credited unless anonymity requested

ADAAD will not take legal action against researchers acting in good faith under this policy.

---

## Known Open Findings

| Finding | Status | Reference |
|:---|:---|:---|
| LLM proxy endpoints lack JWT/API key auth | Open — planned Phase 143 | Audit C-4 |
| `server.py` monolithic architecture | Open — phased refactor planned | Audit H-1 |
| No dependency lock file | Open — `pip-compile` rollout planned | Audit H-7 |
| `x-adaad-plan` header trust | Open — server-side entitlements planned | Audit H-4 |

---

*ADAAD · Innovative AI LLC · Governor: Dustin L. Reid · Blackwell, Oklahoma*  
*Last updated: 2026-04-12 · v9.75.0 · Phase 142*
