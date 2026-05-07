# Gravatar Integration Plan — InnovativeAI LLC
# adaad.pro · Dork Dashboard · InnovativeArtsInc · docs.adaad.pro
# Authored: 2026-05-07 · HUMAN-0: Dustin L. Reid · Status: RATIFIED

---

## Overview

This document is the canonical integration plan for Gravatar API v3.0.0 across
all InnovativeAI LLC digital surfaces. adaad.pro is the Gravatar-powered
canonical identity hub. This plan extends that foundation into the Dork
dashboard, documentation surfaces, and the InnovativeArtsInc creative universe.

**Gravatar API version:** v3.0.0 (breaking changes from all prior versions)
**Base URL:** `https://api.gravatar.com/v3`
**OpenAPI spec:** `https://api.gravatar.com/v3/openapi`
**Email hashing:** SHA256 only — MD5 is the legacy algorithm and is incorrect for v3.0.0

---

## Constitutional Constraints

- `GRAVATAR_API_KEY` must be stored as an environment variable — never hardcoded
- All error paths raise typed exceptions — silent failure is a constitutional violation
- Any credential that appears in conversation context is considered compromised
  and must be rotated before the next production operation
- Phase 1 requires no API key — begin immediately
- Phases 2–4 are gated on a freshly generated API key from gravatar.com/developers

---

## Identity Binding

| ADAAD Entity          | Gravatar Role             | Notes                                |
|-----------------------|---------------------------|--------------------------------------|
| HUMAN-0 (Dustin Reid) | Registered account owner  | Primary email drives all lookups     |
| adaad.pro             | Gravatar-powered hub      | Central profile link aggregator      |
| architect@adaad.ai    | ArchitectAgent git email  | NOT a Gravatar-registered email      |
| dustin@adaad.pro      | Primary contact email     | Primary Gravatar lookup email        |

---

## Phase 1 — Foundation (No API Key Required)

**Target:** Immediate. Zero blockers.

### 1.1 Hash Utility Module

**File:** `runtime/integrations/gravatar_hash.py`

```python
import hashlib
from typing import Final

GRAVATAR_HASH_ALGORITHM: Final[str] = "sha256"  # NEVER "md5"

class GravatarHashError(RuntimeError):
    """Raised when email hashing preconditions are violated."""

def compute_gravatar_hash(email: str) -> str:
    """
    Compute the Gravatar SHA256 identifier for a given email address.

    Constitutional invariant GRAV-HASH-0:
    - Input must be stripped and lowercased before hashing.
    - Algorithm must be sha256. Any other algorithm is a constitutional violation.
    - Empty email raises GravatarHashError (fail-closed).

    Returns: 64-character lowercase hex SHA256 digest.
    """
    if not email or not email.strip():
        raise GravatarHashError("GRAV-HASH-0: Email must be non-empty.")
    normalized = email.strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
```

### 1.2 Avatar URL Builder

No API call required. URL constructed directly from hash.

```python
def build_avatar_url(
    email: str,
    size: int = 200,
    default: str = "mp",
    rating: str = "g",
) -> str:
    """
    Build a Gravatar avatar URL from an email address.

    Args:
        size:    Pixel dimensions (1-2048). Default 200px.
        default: Fallback image code. 'mp' (mystery person) for ADAAD surfaces.
        rating:  Content rating filter. 'g' for all ADAAD surfaces.
    """
    hash_ = compute_gravatar_hash(email)
    return (
        f"https://0.gravatar.com/avatar/{hash_}"
        f"?s={size}&d={default}&r={rating}"
    )
```

### 1.3 Dork Dashboard Avatar

**Target file:** `ui/dork.html`
**Change:** 32–40px avatar circle in dashboard header using `build_avatar_url()`.
**Note:** Hash of `dustin@adaad.pro` can be pre-computed and hardcoded — no
dynamic lookup required for HUMAN-0 identity display.

---

## Phase 2 — Profile API (API Key Required)

**Gate:** Fresh `GRAVATAR_API_KEY` generated and stored in env before any
Phase 2 work begins. Rotate previous key if it appeared in conversation context.

### 2.1 Environment Variable Contract

```python
import os

def get_gravatar_api_key() -> str:
    key = os.environ.get("GRAVATAR_API_KEY", "")
    if not key:
        raise RuntimeError(
            "GRAV-AUTH-0: GRAVATAR_API_KEY environment variable is not set. "
            "Constitutional violation: credential must not be hardcoded."
        )
    return key
```

### 2.2 Profile Fetch Module

**Endpoint:** `GET https://api.gravatar.com/v3/profiles/{profileIdentifier}`

- Unauthenticated: limited profile subset
- Authenticated (Bearer token): full profile object — always use in production
- Rate limit: 1,000 req/hr with API key
- Cache responses: 1 hour TTL — Redis key: `gravatar:profile:{hash}`

```python
import httpx
from runtime.integrations.gravatar_hash import compute_gravatar_hash

GRAVATAR_API_BASE: Final[str] = "https://api.gravatar.com/v3"

class GravatarProfileNotFoundError(RuntimeError):
    """GRAV-404-0: No Gravatar profile found for identifier."""

class GravatarRateLimitError(RuntimeError):
    """GRAV-429-0: API rate limit exceeded. Implement exponential backoff."""

class GravatarAuthError(RuntimeError):
    """GRAV-AUTH-0: Authentication failed. Check GRAVATAR_API_KEY."""

async def fetch_gravatar_profile(email: str, api_key: str) -> dict:
    """
    Fetch full Gravatar profile for an email address.
    Fail-closed: raises on any non-200 response.
    """
    hash_ = compute_gravatar_hash(email)
    url = f"{GRAVATAR_API_BASE}/profiles/{hash_}"
    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=10.0,
        )
    if response.status_code == 404:
        raise GravatarProfileNotFoundError(f"No profile for hash {hash_}")
    if response.status_code == 429:
        raise GravatarRateLimitError("Rate limit exceeded. Implement backoff.")
    if response.status_code == 401:
        raise GravatarAuthError("Authentication failed. Check GRAVATAR_API_KEY.")
    response.raise_for_status()
    return response.json()
```

### 2.3 adaad.pro Dynamic Profile Card

Replaces the static Gravatar profile page with a dynamic card consuming
the profile API. Displays: avatar, display_name, bio (description),
job_title, verified_accounts as platform badges, links, interests as tag cloud.

**Key note:** Secondary emails on the account will 404 on profile API but may
still return an avatar. Always use the primary registered email for profile lookups.

### 2.4 docs.adaad.pro Author Attribution

Uses the public `.json` format URL — no API key required:
```
https://gravatar.com/{sha256_hash}.json
```

Parse `display_name` and `avatar_url` for documentation bylines.
Also available: `.xml`, `.vcf`, `.php`, `.md` format extensions.

---

## Phase 3 — Interactive Components

### 3.1 Quick Editor

Allows HUMAN-0 to update Gravatar profile without leaving adaad.pro.

```bash
npm install @gravatar-com/quick-editor
```

```javascript
import { GravatarQuickEditorCore } from '@gravatar-com/quick-editor';

const initGravatarEditor = (email, onUpdated) => {
  const editor = new GravatarQuickEditorCore({
    email,
    scope: ['avatars', 'about', 'links'],
    onProfileUpdated: (type) => {
      console.log(`[ADAAD] Gravatar profile updated: ${type}`);
      onUpdated(type);  // Trigger Dork dashboard avatar cache invalidation
    },
    onOpened: () => {
      console.log('[ADAAD] Gravatar Quick Editor opened');
    },
  });
  return editor;
};
```

**Configuration options:**

| Option               | Type   | Description                                      |
|----------------------|--------|--------------------------------------------------|
| email                | string | dustin@adaad.pro                                 |
| editorTriggerSelector| string | CSS selector for element that opens editor       |
| avatarSelector       | string | CSS selector for avatar img elements to refresh  |
| scope                | array  | ['avatars', 'about', 'links', 'interests']       |
| locale               | string | Interface language                               |
| avatarRefreshDelay   | number | ms delay before refreshing avatar after update   |

### 3.2 Hovercards

Profile popup on hover over any Gravatar-linked image. No auth required.

```bash
npm install @gravatar-com/hovercards
```

```javascript
import { GravatarHovercards } from '@gravatar-com/hovercards';

new GravatarHovercards({
  selector: '.gravatar-image',
  position: 'top',
  theme: 'dark',  // Matches ADAAD Void Black / Midnight Slate aesthetic
});
```

CDN alternative (no npm):
```html
<script src="https://secure.gravatar.com/js/gprofiles.js"></script>
<img src="https://www.gravatar.com/avatar/{hash}" class="hovercard" alt="..." />
```

### 3.3 QR Code

No authentication required. Returns PNG.

```
GET https://api.gravatar.com/v3/qr-code/{sha256_hash}?size=300&version=3&type=user
```

```python
def build_qr_code_url(email: str, size: int = 300) -> str:
    hash_ = compute_gravatar_hash(email)
    return (
        f"https://api.gravatar.com/v3/qr-code/{hash_}"
        f"?size={size}&version=3&type=user"
    )
```

**Parameters:**
- `size` — pixels (default 80, recommend 300 for adaad.pro share card)
- `version` — 1 (standard) or 3 (modern dots — matches ADAAD node graph aesthetic)
- `type` — center icon: `user`, `gravatar`, or `none`

**Use cases:** adaad.pro share card, printed merch, Epoch Milestone social posts.

---

## Phase 4 — Creative Universe

### 4.1 JRT Collaborator Attribution

**Dependency:** Joshua Robert Thompson registers a Gravatar account.

When available: InnovativeArtsInc credit block displays JRT avatar,
display_name, and verified accounts via hovercard on any JRT attribution.
Fallback: static attribution text if no Gravatar registered.

### 4.2 InnovativeArtsInc Corpus Ingestion

Profile `.json` format ingested into creative corpus:
- `interests` array → recommendation engine seed data
- `verified_accounts` → provenance chain for IP attribution
- Profile fetch event → HMAC-chained ledger entry via ILA sign-off

### 4.3 Shame Tapestry Voice Profile Cards

Nine voices presented as Gravatar-style profile cards in the Testimony
aesthetic (Parchment / Archive Ink / Reckoning Red palette from Brand v2.0).
These are UI components, not real Gravatar API calls — no API dependency.
Ships with Shame Tapestry Season 1 content.

---

## Full Profile Data Model (v3.0.0)

```typescript
interface GravatarProfile {
  hash: string;                    // SHA256 of primary email
  display_name: string;
  profile_url: string;             // https://gravatar.com/{slug}
  avatar_url: string;              // https://0.gravatar.com/avatar/{hash}
  avatar_alt_text: string;
  first_name: string;
  last_name: string;
  pronouns: string;
  pronunciation: string;
  location: string;
  timezone: string;
  languages: string[];
  description: string;             // Bio / about
  job_title: string;
  company: string;
  header_image: string;
  hide_default_header_image: boolean;
  background_color: string;        // Hex
  verified_accounts: VerifiedAccount[];
  number_verified_accounts: number;
  links: ProfileLink[];
  interests: Interest[];
  payments: PaymentInfo;
  contact_info: ContactInfo;
  gallery: GalleryImage[];
  last_profile_edit: string;       // ISO 8601
  registration_date: string;       // ISO 8601
  is_organization: boolean;
}
```

---

## Error Handling Reference

| HTTP | Code               | Cause                         | Resolution                        |
|------|--------------------|-------------------------------|-----------------------------------|
| 400  | uncropped_image    | Avatar not 1:1 ratio          | Crop to square before upload      |
| 400  | unsupported_image  | Wrong format                  | Use JPG, PNG, or GIF              |
| 401  | —                  | Bad API key                   | Verify GRAVATAR_API_KEY env var   |
| 403  | insufficient_scope | Token lacks permissions       | Request correct OAuth scopes      |
| 404  | disabled           | Profile disabled by user      | Handle gracefully — no resolution |
| 429  | rate_limit_exceeded| Too many requests             | Exponential backoff + caching     |
| 500  | —                  | Server error                  | Retry with exponential backoff    |

**Troubleshooting:**
- Avatar not loading → verify SHA256 (not MD5) hash; add `?d=mp` fallback
- Profile 404 on secondary email → use PRIMARY registered email only
- Rate limit → cache profile responses 1 hour; apply for increased limits at
  gravatar.com/developers if burst traffic is anticipated

---

## Constitutional Compliance Checklist

Before any Gravatar-touching module ships:

- [ ] SHA256 hashing confirmed — MD5 not present anywhere in the module
- [ ] GRAVATAR_API_KEY loaded from env var — never hardcoded
- [ ] All error paths raise typed `GravatarXxxError` subclasses
- [ ] No silent returns on API failure — `return None` on error is forbidden
- [ ] Profile responses cached with 1-hour TTL
- [ ] Avatar URLs constructed locally from hash — no API call for avatar URL
- [ ] Rate limit headers logged for governance visibility
- [ ] Secondary email → primary email resolution documented in module docstring
- [ ] Quick Editor `onProfileUpdated` callback wired to avatar cache invalidation
- [ ] Missing API key raises at module init time, not at first request

---

## Reference

- OpenAPI Specification: https://api.gravatar.com/v3/openapi
- Developer Dashboard:   https://gravatar.com/developers
- API Console:           https://gravatar.com/developers/console
- Android SDK:           https://github.com/Automattic/Gravatar-SDK-Android
- iOS SDK:               https://github.com/Automattic/Gravatar-SDK-iOS
- GitHub Org:            https://github.com/Automattic/gravatar
- Status Page:           https://automatticstatus.com

---

*Sealed: 2026-05-07 · HUMAN-0: Dustin L. Reid · InnovativeAI LLC*
