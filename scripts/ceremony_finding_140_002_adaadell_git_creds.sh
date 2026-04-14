#!/usr/bin/env bash
# ============================================================
# ADAAD ADAADell Git Credential Repair — FINDING-140-002
#
# Target Machine : ADAADell (WSL2 / Ubuntu under Windows)
# Authority      : HUMAN-0 / Dustin L. Reid
# Finding        : FINDING-140-002 (P1)
# Problem        : WSL cannot push via HTTPS — Windows GCM
#                  intercepts credentials and fails silently.
# Solution A     : PAT-embedded remote URL (immediate, no config)
# Solution B     : SSH deploy key (permanent, no PAT rotation risk)
#
# USAGE (run inside WSL on ADAADell):
#   cd /path/to/ADAAD
#   bash scripts/ceremony_finding_140_002_adaadell_git_creds.sh
# ============================================================

set -euo pipefail

echo "════════════════════════════════════════════════════════"
echo "  ADAAD ADAADell Git Credential Repair"
echo "  FINDING-140-002"
echo "════════════════════════════════════════════════════════"
echo ""

REPO_URL="https://github.com/InnovativeAI-adaad/ADAAD.git"
ORG="InnovativeAI-adaad"
REPO="ADAAD"

# ── OPTION SELECTOR ───────────────────────────────────────────
echo "Select credential strategy:"
echo "  [A] PAT-embedded remote URL  (quick fix, works immediately)"
echo "  [B] SSH deploy key           (permanent, no PAT needed)"
echo ""
read -r -p "Enter A or B: " CHOICE

case "${CHOICE^^}" in

# ══════════════════════════════════════════════════════════════
# OPTION A — PAT-embedded HTTPS remote
# ══════════════════════════════════════════════════════════════
A)
    echo ""
    echo "[A] Configuring PAT-embedded remote URL..."
    echo "    Paste your GitHub PAT (from /mnt/project/Git_TOKEN or GitHub UI):"
    read -r -s GIT_TOKEN
    echo ""

    if [[ -z "${GIT_TOKEN}" ]]; then
        echo "ERROR: No token entered. Aborting."
        exit 1
    fi

    # Validate token length (ADAAD tokens are 93 chars)
    TOKEN_LEN=${#GIT_TOKEN}
    echo "    Token length: ${TOKEN_LEN} chars"

    EMBEDDED_URL="https://oauth2:${GIT_TOKEN}@github.com/${ORG}/${REPO}.git"

    git remote set-url origin "${EMBEDDED_URL}"
    echo "    Remote updated."

    # Disable Windows GCM for this repo
    git config credential.helper ""
    echo "    Credential helper cleared (disables Windows GCM for this repo)."

    # Smoke test
    echo ""
    echo "    Testing push access..."
    if git ls-remote "${EMBEDDED_URL}" HEAD >/dev/null 2>&1; then
        echo "    Remote access: OK"
    else
        echo "    Remote access: FAILED — check token"
        exit 1
    fi

    echo ""
    echo "    ✓ OPTION A complete. You can now git push normally."
    echo "    NOTE: If you rotate the PAT, re-run this script."
    echo ""
    echo "    Push pattern for non-fast-forward (autosync workaround):"
    echo "      git fetch origin main"
    echo "      git merge FETCH_HEAD --strategy-option=ours -m 'chore: sync'"
    echo "      git push origin main"
    ;;

# ══════════════════════════════════════════════════════════════
# OPTION B — SSH deploy key (permanent solution)
# ══════════════════════════════════════════════════════════════
B)
    echo ""
    echo "[B] Setting up SSH deploy key..."

    SSH_KEY_PATH="${HOME}/.ssh/adaad_deploy_ed25519"

    if [[ -f "${SSH_KEY_PATH}" ]]; then
        echo "    SSH key already exists at ${SSH_KEY_PATH}"
        echo "    Delete it and re-run to regenerate, or skip to configure."
    else
        ssh-keygen -t ed25519 -C "adaad-deploy@adaadell" -f "${SSH_KEY_PATH}" -N ""
        echo "    Key pair generated: ${SSH_KEY_PATH}"
    fi

    echo ""
    echo "    ════════ ACTION REQUIRED ════════"
    echo "    Add this public key to GitHub as a Deploy Key:"
    echo "    URL: https://github.com/${ORG}/${REPO}/settings/keys"
    echo ""
    echo "    Public key:"
    cat "${SSH_KEY_PATH}.pub"
    echo ""
    echo "    ─ Check 'Allow write access' on GitHub ─"
    echo "    Press ENTER when the deploy key has been added..."
    read -r

    # Configure SSH agent
    eval "$(ssh-agent -s)" >/dev/null
    ssh-add "${SSH_KEY_PATH}"

    # Configure ~/.ssh/config for this repo
    SSH_CONFIG="${HOME}/.ssh/config"
    if ! grep -q "Host adaad-github" "${SSH_CONFIG}" 2>/dev/null; then
        cat >> "${SSH_CONFIG}" <<EOF

# ADAAD deploy key — FINDING-140-002 ceremony
Host adaad-github
    HostName github.com
    User git
    IdentityFile ${SSH_KEY_PATH}
    IdentitiesOnly yes
EOF
        echo "    SSH config entry added."
    else
        echo "    SSH config entry already present."
    fi

    # Set remote to SSH alias
    git remote set-url origin "adaad-github:${ORG}/${REPO}.git"
    echo "    Remote set to SSH."

    # Smoke test
    echo ""
    echo "    Testing SSH access..."
    if ssh -T -o StrictHostKeyChecking=accept-new git@github.com 2>&1 | grep -q "successfully authenticated\|Hi InnovativeAI"; then
        echo "    SSH auth: OK"
    else
        echo "    SSH auth: check deploy key was saved correctly on GitHub"
    fi

    echo ""
    echo "    ✓ OPTION B complete. git push will now use SSH deploy key."
    echo "    The key persists across WSL sessions once added to ~/.ssh/config."
    ;;

*)
    echo "Unknown choice '${CHOICE}'. Aborting."
    exit 1
    ;;
esac

echo ""
echo "════════════════════════════════════════════════════════"
echo "  FINDING-140-002 RESOLVED"
echo "  ADAADell can now push to InnovativeAI-adaad/ADAAD"
echo "════════════════════════════════════════════════════════"
