# ADAADell GPG Signing Instructions — Phase 198 (INNOV-103 CMCE)

**Purpose**: Perform the real HUMAN-0 GPG ratification for Track B (DEVADAAD) on the physical ADAADell machine.

**Do NOT** run these commands on your normal Windows machine unless your GPG private key lives there. ADAADell is the designated machine.

---

## Prerequisites on ADAADell

1. You are logged into the ADAADell machine (Ubuntu/WSL recommended).
2. Your GPG private key for `DUSTIN L REID (HUMAN-0)` is available.
3. `gpg` is installed and the key is trusted.

Verify your key:
```bash
gpg --list-secret-keys --keyid-format LONG "Dustin L. Reid" | head -5
```

---

## Step-by-Step Signing Procedure

### 1. Copy the current attestation file to ADAADell

From your Windows machine, copy the **current** (unsigned) file:

```powershell
# On Windows (PowerShell)
scp "C:\Users\dl_rd\adaad\artifacts\governance\phase198\sign_off.json" adaadell:~/adaad-phase198-signing/
```

Or use whatever transfer method you normally use (rsync, USB, etc.).

### 2. On ADAADell — Perform the Detached Signature

```bash
cd ~/adaad-phase198-signing/

# Recommended: armored detached signature (what the project uses)
gpg --armor --detach-sign \
    --output sign_off.json.asc \
    sign_off.json

# Verify the signature was created correctly
gpg --verify sign_off.json.asc sign_off.json
```

You should see output similar to:
```
gpg: Good signature from "Dustin L. Reid (HUMAN-0) <...>"
```

### 3. Copy the Signature Back

```bash
# From ADAADell
scp sign_off.json.asc adaad-windows:C:/Users/dl_rd/adaad/artifacts/governance/phase198/
```

Or copy it back manually.

### 4. Update the JSON on the main machine (after real signing)

Once the real `.asc` file is in place, replace the content of:

`artifacts/governance/phase198/sign_off.json`

with the content from:

`artifacts/governance/phase198/drafts/sign_off.json.signed`

Then manually edit the following fields in the real file:

- `"gpg_key_id"`: Fill with the actual key ID used (e.g. `0xABCDEF1234567890`)
- `"gpg_signature_date"`: Use the actual timestamp from the signature
- `"gpg_note"`: Update with the real key information

Example final `gpg_note`:
```json
"gpg_note": "Signed on ADAADell with key 0xABCDEF1234567890 on 2026-05-27T14:22:00Z. Detached signature: sign_off.json.asc"
```

---

## Alternative: One-Liner for WSL Users

If you are already inside WSL on the same Windows machine and have the key there:

```bash
cd /mnt/c/Users/dl_rd/adaad/artifacts/governance/phase198

gpg --armor --detach-sign \
    --output sign_off.json.asc \
    sign_off.json

gpg --verify sign_off.json.asc sign_off.json
```

Then proceed with updating the JSON.

---

## After Signing — Commit Checklist

- [ ] Real `sign_off.json.asc` is committed in `artifacts/governance/phase198/`
- [ ] `sign_off.json` has been updated with `gpg_signed: true` and `status: "RATIFIED"`
- [ ] `gpg_key_id` and `gpg_signature_date` are filled accurately
- [ ] `governance/report_version.json` has been advanced to Phase 198 / v10.9.0 (see sibling draft)
- [ ] A new `DEVADAAD` command can now be issued with proper authority

---

**Warning**: Never commit a `sign_off.json` with `gpg_signed: true` unless a real, verifiable detached signature exists in the same directory.

This draft was generated on 2026-05-27 by the agent at the user's request.
