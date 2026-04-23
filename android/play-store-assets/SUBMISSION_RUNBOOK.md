# ADAAD Android — Play Store Submission Runbook
# InnovativeAI LLC · Dustin L. Reid
# Version: 3.0.0 · March 2026

## Prerequisites

### 1. Google Play Developer Account
- Register at: https://play.google.com/console/signup
- One-time $25 registration fee
- Account name: **InnovativeAI LLC**
- Email: use the InnovativeAI business email (not personal)
- D-U-N-S number required for organization accounts → register at dnb.com if not yet obtained

### 2. Play Service Account for CI/CD
Create a service account so GitHub Actions can publish automatically:

1. Go to Play Console → Setup → API access
2. Link to a Google Cloud project (create if needed)
3. Create service account: play-store-publisher@<project>.iam.gserviceaccount.com
4. Grant role: **Release Manager** (minimum for AAB upload)
5. Download JSON key → add as GitHub secret `PLAY_SERVICE_ACCOUNT_JSON`

---

## Keystore Setup

### Store credentials in GitHub Secrets (Settings → Secrets → Actions):
```
ADAAD_KEYSTORE_BASE64   = base64 -w0 keystore/innovativeai-release.jks
ADAAD_STORE_PASSWORD    = <your storepass>
ADAAD_KEY_ALIAS         = adaad-release
ADAAD_KEY_PASSWORD      = <your keypass>  (same as storepass for PKCS12)
PLAY_SERVICE_ACCOUNT_JSON = <contents of service account JSON>
```

### Enrol in Play App Signing (STRONGLY RECOMMENDED)
Protects against keystore loss — Google holds the distribution key, you hold the upload key.
1. Play Console → Your app → Setup → App signing
2. Select "Use a key you upload (recommended for existing apps)" — or for first upload: "Use Google-managed key"
3. Export upload certificate:
   ```bash
   keytool -export -rfc \
     -keystore keystore/innovativeai-release.jks \
     -alias adaad-release \
     -storepass YOUR_STOREPASS \
     -file adaad-upload-cert.pem
   ```
4. Upload `adaad-upload-cert.pem` in Play Console

---

## Play Console App Setup

### Step 1: Create App
- Play Console → All apps → Create app
- App name: **ADAAD — Constitutional Governance**
- Default language: English (United States)
- App or Game: **App**
- Free or Paid: **Free** (for Community tier)
- Declarations: accept developer policies

### Step 2: App Content
Complete all required sections in Play Console → App content:

| Section | Content |
|---------|---------|
| Privacy policy URL | https://innovativeai.dev/adaad/privacy |
| App access | All functionality available without special access |
| Ads | No ads |
| Content rating | Complete questionnaire → expected: Everyone (governance/business tool) |
| Target audience | 18+ (developer/professional audience) |
| News apps | No |
| COVID-19 contact tracing | No |
| Data safety | See Data Safety section below |

### Step 3: Data Safety Disclosure
Required since Android 12. ADAAD's honest disclosure:

| Data type | Collected | Shared | Required | Can opt out |
|-----------|-----------|--------|----------|-------------|
| App interactions (governance events) | Yes | No | Yes (governance audit) | No |
| Crash logs | Yes | No | No | Yes |
| App info / performance | Yes | No | No | Yes |
| Authentication info | No | — | — | — |
| Personal info (name, email) | No | — | — | — |
| Financial info | No | — | — | — |
| Location | No | — | — | — |
| Device identifiers | No | — | — | — |

Encryption in transit: Yes (TLS 1.2+)
Deletion request: Yes (contact support@innovativeai.dev)

### Step 4: Store Listing Assets

#### Required graphics to create before first submission:
| Asset | Size | Notes |
|-------|------|-------|
| App icon | 512×512 PNG | High-res version — use ADAAD logo on navy (#0F2B4A) background |
| Feature graphic | 1024×500 PNG | Hero banner — constitution/governance theme |
| Screenshots (phone) | 2–8 required | 1080×1920 or 1080×2400 recommended |
| Screenshots (tablet) | Optional | 1200×1920 recommended |

#### Copy to paste into Play Console:
- **Title:** `ADAAD — Constitutional Governance`
- **Short description:** `Govern autonomous code evolution with constitutional rules and cryptographic proof.`
- **Full description:** See `fastlane/metadata/android/en-US/full_description.txt`

#### Category: **Tools** (primary), **Business** (secondary)

---

## First Upload — Manual (v3.0.0 internal track)

For the very first upload, do this manually (CI takes over after):

1. Build the AAB locally:
   ```bash
   export ADAAD_KEYSTORE_PATH=keystore/innovativeai-release.jks
   export ADAAD_STORE_PASSWORD=<your storepass>
   export ADAAD_KEY_ALIAS=adaad-release
   export ADAAD_KEY_PASSWORD=<same as storepass>
   ./gradlew bundleCommunityRelease
   ```
   Output: `app/build/outputs/bundle/communityRelease/app-community-release.aab`

2. Play Console → Testing → Internal testing → Create new release
3. Upload the `.aab` file
4. Release name: `3.0.0 (30000)`
5. Release notes: paste from `fastlane/metadata/android/en-US/changelogs/30000.txt`
6. Save and review → Start rollout to Internal testing

---

## Subsequent Releases — Automated via GitHub Actions

After the first manual upload, all subsequent releases are automated:

```bash
# Tag a release (triggers android-release.yml workflow)
git tag android-v3.0.1
git push origin android-v3.0.1
```

Or trigger manually from GitHub Actions → Android Release → Run workflow
- Select track: internal / alpha / beta / production
- Select flavor: community / developer / enterprise

### Track promotion strategy:
1. **Internal** → test with InnovativeAI team (up to 100 testers)
2. **Closed testing (alpha)** → Developer Preview cohort (S1 participants)
3. **Open testing (beta)** → Public Beta (S2 launch)
4. **Production** → GA launch (S3) — use staged rollout: 10% → 50% → 100%

---

## Pre-Launch Checklist

- [ ] Google Play Developer account created and verified — **Blocked:** requires Play Console
      org owner action and identity/billing verification. **Owner:** InnovativeAI Org Owner.
      **Target date:** 2026-05-01.
- [ ] Service account JSON created and added to GitHub secrets — **Blocked:** depends on Play
      account + GCP project/API linkage. **Owner:** DevOps. **Target date:** 2026-05-02.
- [ ] Keystore base64 and passwords added to GitHub secrets — **Blocked:** requires repository
      admin privileges and controlled secret handling workflow. **Owner:** Security + DevOps.
      **Target date:** 2026-05-02.
- [ ] Play App Signing enrolled — **Blocked:** can only be completed inside Play Console after
      app setup. **Owner:** Android Release Engineer. **Target date:** 2026-05-03.
- [ ] Privacy policy published at innovativeai.dev/adaad/privacy — **Blocked:** external site
      publication + legal approval required. **Owner:** Legal/Comms. **Target date:** 2026-05-01.
- [ ] App icon (512×512) created — **Blocked:** design asset not tracked in repository runbook
      evidence set. **Owner:** Design. **Target date:** 2026-04-30.
- [ ] Feature graphic (1024×500) created — **Blocked:** design deliverable pending. **Owner:** Design.
      **Target date:** 2026-04-30.
- [ ] Minimum 2 phone screenshots created — **Blocked:** requires device capture from current
      app build. **Owner:** Android QA. **Target date:** 2026-05-02.
- [ ] Data safety form completed in Play Console — **Blocked:** Play Console gated; requires final
      legal/product disclosures. **Owner:** Product + Legal. **Target date:** 2026-05-03.
- [ ] Content rating questionnaire completed — **Blocked:** Play Console gated and must be completed
      after listing content freeze. **Owner:** Product. **Target date:** 2026-05-03.
- [ ] First AAB uploaded manually to internal track — **Blocked:** depends on all prior Play
      setup gates. **Owner:** Android Release Engineer. **Target date:** 2026-05-04.
- [ ] Internal test build passes on physical Android device — **Blocked:** requires device QA run
      against uploaded internal-track build. **Owner:** Android QA. **Target date:** 2026-05-05.
- [ ] CI workflow tested with internal track before promoting to alpha — **Blocked:** follows successful
      internal-track upload and service-account automation setup. **Owner:** DevOps + Android Release Engineer.
      **Target date:** 2026-05-06.

---

## Post-Launch Monitoring

- **Crash rate:** Play Console → Android vitals → Crashes & ANRs — target < 0.1%
- **Reviews:** Respond to all 1-3 star reviews within 48 hours
- **Rating target:** ≥ 4.0 stars by end of Developer Preview
- **Version adoption:** target ≥ 80% of active installs on latest version within 30 days

## Support

- In-app feedback: governance@innovativeai.dev
- Play Store replies: use the same email
- Bug reports: github.com/InnovativeAI-adaad/ADAAD/issues (label: android)
