#!/usr/bin/env bash
# Generate the GPG keypair used for encrypted security disclosures.
#
# WHY YOU RUN THIS, NOT ME:
#   The private key needs a passphrase that only you should know. This script
#   prompts you for it interactively, generates the key, exports the public
#   side to .well-known/security/pandora-cloud-public.asc (committed to the
#   repo), and writes the private side to a temp file with explicit reminders
#   to import it once and shred the file.
#
# AFTER RUNNING:
#   1. Import the private key into the mailbox that handles security
#      disclosures: gpg --import "$PRIV_OUT"
#   2. Verify the import: gpg --list-secret-keys
#   3. Shred the export file: shred -u "$PRIV_OUT"   (or 'rm -P' on macOS)
#   4. Update SECURITY.md with the fingerprint printed at the end of this
#      script.
#   5. Upload the public key to keys.openpgp.org for verification:
#      gpg --send-keys --keyserver hkps://keys.openpgp.org "$KEY_ID"
#   6. git add .well-known/security/pandora-cloud-public.asc SECURITY.md
#      git commit -m "security: publish PGP public key for disclosures"

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PUB_OUT="$REPO_ROOT/.well-known/security/pandora-cloud-public.asc"
PRIV_OUT="$(mktemp -t pandora-cloud-security-private.XXXXXX.asc)"

NAME="Pandora Cloud Security"
EMAIL="pc@pandoracloud.net"
COMMENT="GovWin-HubSpot Integration Security Disclosures"
EXPIRY="2y"

if ! command -v gpg >/dev/null 2>&1; then
  echo "gpg is not installed. Install with: brew install gnupg" >&2
  exit 1
fi

cat <<EOF
================================================================
Generating PGP key for security disclosures
  Name:    $NAME
  Email:   $EMAIL
  Comment: $COMMENT
  Algo:    EdDSA / ed25519 (auth + sign), cv25519 (encrypt)
  Expiry:  $EXPIRY (renew before this date)
================================================================
You will be prompted for a passphrase.
Choose a strong passphrase you can recall reliably; you'll need it
every time the security mailbox decrypts a report.
================================================================
EOF

gpg --quick-generate-key "${NAME} (${COMMENT}) <${EMAIL}>" ed25519 default "$EXPIRY"

KEY_ID=$(gpg --list-keys --with-colons "$EMAIL" | awk -F: '/^pub/ {print $5; exit}')
FINGERPRINT=$(gpg --list-keys --with-colons "$EMAIL" | awk -F: '/^fpr/ {print $10; exit}')

mkdir -p "$(dirname "$PUB_OUT")"
gpg --armor --export "$KEY_ID" > "$PUB_OUT"
gpg --armor --export-secret-keys "$KEY_ID" > "$PRIV_OUT"

cat <<EOF

================================================================
DONE
================================================================
Public key written to: $PUB_OUT      (commit this)
Private key written to: $PRIV_OUT    (import once, then SHRED)

Key ID:      $KEY_ID
Fingerprint: $FINGERPRINT

Next steps (DO THESE NOW, before closing this terminal):
  1. gpg --import "$PRIV_OUT"
  2. shred -u "$PRIV_OUT"          # macOS: rm -P "$PRIV_OUT"
  3. Update SECURITY.md fingerprint placeholder with:
     $FINGERPRINT
  4. Upload to keyserver:
     gpg --keyserver hkps://keys.openpgp.org --send-keys $KEY_ID
  5. Commit the public key:
     git add .well-known/security/pandora-cloud-public.asc SECURITY.md
     git commit -m "security: publish PGP public key for disclosures"
================================================================
EOF
