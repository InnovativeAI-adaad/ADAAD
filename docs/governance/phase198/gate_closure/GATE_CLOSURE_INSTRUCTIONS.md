# Phase 198 + Governance Drift — Gate Closure Package
**Purpose:** Enable full DEVADAAD (Track B) authority for Epoch A (Phases 199–206) by closing the two remaining constitutional gates.

**Gates to Close:**
1. Phase 198 Ratification (PENDING_GPG)
2. Four-Surface Version/Phase Drift

**Authority Note:**  
User has issued a formal DEVADAAD directive authorizing full Track B execution of Epoch A **once these gates are verifiably closed**.

---

## Step 1: Perform Real GPG Signature on ADAADell (Required)

This step **must** be executed on the physical ADAADell machine by HUMAN-0.

### 1.1 Copy Current Unsigned Files to ADAADell

From your main machine:

```powershell
# Example using SCP (adjust paths as needed)
scp "C:\Users\dl_rd\adaad\artifacts\governance\phase198\sign_off.json" adaadell:~/phase198-closure/
```

### 1.2 On ADAADell — Execute the Signature

```bash
cd ~/phase198-closure/

# Create the detached armored signature
gpg --armor --detach-sign \
    --output sign_off.json.asc \
    sign_off.json

# Verify the signature locally
gpg --verify sign_off.json.asc sign_off.json
```

You should see a "Good signature" message from your HUMAN-0 key.

### 1.3 Copy the Signature Back

```bash
scp sign_off.json.asc "C:\Users\dl_rd\adaad\artifacts\governance\phase198\"
```

---

## Step 2: Update the Canonical Artifacts (After Real GPG)

Once the real `.asc` file is in place, perform the following updates:

### 2.1 Update `sign_off.json`

Replace the content of:

`artifacts/governance/phase198/sign_off.json`

with the content of the prepared file in this package:

`gate_closure/sign_off.json.ratified`

Then manually fill in these fields with the actual values from your GPG operation:

- `gpg_key_id`: Your actual key ID (e.g. `0xABCDEF1234567890`)
- `gpg_signature_date`: The exact timestamp of the signature
- Update the `gpg_note` if desired

**Do not** commit this until the real signature has been verified.

### 2.2 Reconcile `governance/report_version.json`

Replace (or carefully merge) the content of:

`governance/report_version.json`

with the content of the prepared file in this package:

`gate_closure/report_version.json.reconciled`

This should clear the majority of the current drift violations.

---

## Step 3: Post-Closure Validation (Mandatory)

After updating both files, run the following from the repo root:

```bash
# 1. Verify the GPG signature
gpg --verify artifacts/governance/phase198/sign_off.json.asc artifacts/governance/phase198/sign_off.json

# 2. Run the official drift validator
python scripts/validate_governance_state_drift.py

# 3. (Optional but recommended) Run schema validation
python scripts/validate_governance_schemas.py
```

**Success Criteria:**
- `gpg --verify` reports a good signature from your HUMAN-0 key.
- `validate_governance_state_drift.py` exits with 0 violations (or only minor acceptable ones).
- `sign_off.json` shows `"gpg_signed": true` and `"status": "RATIFIED"`.

---

## Step 4: Commit & Announce

Once validation passes cleanly:

1. Commit the following together:
   - `artifacts/governance/phase198/sign_off.json`
   - `artifacts/governance/phase198/sign_off.json.asc`
   - `governance/report_version.json`
   - This Gate Closure Package (or a summary)

2. Create a short commit message referencing this package and the DEVADAAD directive.

3. Reply in this session with something like:
   > "Gates closed. Proceeding with full Epoch A under DEVADAAD authority."

At that point, I will switch to full Track B execution mode for Phases 199–206.

---

## Files Included in This Package

- `GATE_CLOSURE_INSTRUCTIONS.md` (this file)
- `sign_off.json.ratified` — Target content for `sign_off.json` after real GPG
- `report_version.json.reconciled` — Target content to resolve version/phase drift
- `ADAADell_GPG_Commands.md` — Copy of the exact signing commands (for convenience)

---

**This package was prepared under the conditional DEVADAAD authorization issued on 2026-05-27.**

Once you complete the real cryptographic step on ADAADell and the validations pass, Epoch A may proceed with full Track B authority.