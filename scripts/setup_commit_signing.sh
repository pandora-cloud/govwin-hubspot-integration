#!/usr/bin/env bash
# One-time: generate a GPG key for your maintainer identity and configure
# git to sign every commit and tag with it. Run from the repo root.
#
# After this completes, every `git commit` produces a signed commit;
# pushes to GitHub will show "Verified" once you upload the public key
# to your GitHub account's signing-keys list.
#
# Why we want this: required_signatures branch protection on main only
# admits signed commits/tags. Signed history is also the highest-leverage
# OpenSSF Scorecard win after Branch-Protection.
#
# WHY YOU RUN THIS, NOT ME:
#   The private key needs a passphrase only you know. The script prompts
#   for it during gpg --quick-generate-key.

set -euo pipefail

NAME="${SIGNING_NAME:-Isi Lawson}"
EMAIL="${SIGNING_EMAIL:-isi@pandoracloud.net}"
EXPIRY="${SIGNING_EXPIRY:-2y}"

if ! command -v gpg >/dev/null 2>&1; then
  echo "gpg not installed. brew install gnupg" >&2
  exit 1
fi
if ! command -v git >/dev/null 2>&1; then
  echo "git not installed." >&2
  exit 1
fi

cat <<EOF
================================================================
Generating commit-signing key
  Name:    $NAME
  Email:   $EMAIL
  Algo:    EdDSA / ed25519
  Expiry:  $EXPIRY
================================================================
You will be prompted for a passphrase. Pick one you'll remember;
git uses it on every commit (the macOS keychain caches it after the
first prompt so you only re-enter it occasionally).

This key is SEPARATE from the security-disclosure PGP key in
.well-known/security/. Do not reuse the same key for both.
================================================================
EOF

gpg --quick-generate-key "${NAME} <${EMAIL}>" ed25519 default "$EXPIRY"

KEY_ID=$(gpg --list-secret-keys --with-colons "$EMAIL" | awk -F: '/^sec/ {print $5; exit}')
FINGERPRINT=$(gpg --list-secret-keys --with-colons "$EMAIL" | awk -F: '/^fpr/ {print $10; exit}')

if [[ -z "$KEY_ID" ]]; then
  echo "Failed to find new key for $EMAIL. Aborting before changing git config." >&2
  exit 1
fi

# Configure git globally; override per-repo if you want a different identity
# for other repos.
git config --global user.signingkey "$KEY_ID"
git config --global commit.gpgsign true
git config --global tag.gpgsign true
git config --global gpg.program "$(command -v gpg)"

# macOS-specific: make sure pinentry can find a TTY when invoked from
# non-terminal contexts (Terminal, VS Code, hooks, etc.).
if [[ "$(uname)" == "Darwin" ]]; then
  if ! grep -q 'GPG_TTY' "$HOME/.zshrc" 2>/dev/null; then
    echo 'export GPG_TTY=$(tty)' >> "$HOME/.zshrc"
    echo "Added 'export GPG_TTY=\$(tty)' to ~/.zshrc (open a new terminal to pick it up)."
  fi
  # Re-export the public key so macOS's keychain GUI can prompt cleanly.
  gpg --armor --export "$KEY_ID" >/tmp/signing-public.asc
fi

cat <<EOF

================================================================
DONE
================================================================
Key ID:      $KEY_ID
Fingerprint: $FINGERPRINT

Next steps:
  1. Test signing locally:
       echo "test" | git commit-tree -m "test signing" \$(git write-tree)
     If gpg prompts you for the passphrase, signing works.

  2. Export the public key and add it to GitHub:
       gpg --armor --export $KEY_ID
     Copy the output, then visit https://github.com/settings/gpg/new
     and paste it. After this, every signed commit you push shows
     a "Verified" badge in the GitHub UI.

  3. (Optional) Tell me when steps 1+2 are done and I'll flip on
     branch protection's required_signatures rule via the API.

  4. Sign existing tags retroactively (optional, for v1.0.0 / v2.0.0 /
     v2.1.0 to show as Verified):
       git tag -s v2.1.0 -f -m "v2.1.0 (signed retroactively)" v2.1.0
       git push origin v2.1.0 --force
     Repeat for v1.0.0 and v2.0.0.
================================================================
EOF
