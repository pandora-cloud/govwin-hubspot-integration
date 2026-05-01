# Security key material

This directory holds the project's public PGP key used for encrypted security disclosures.

## Files

- `pandora-cloud-public.asc` - the active public key. Reporters can use this to encrypt vulnerability disclosures sent to <pc@pandoracloud.net>. Verify the fingerprint against the value in [SECURITY.md](../../SECURITY.md) before encrypting.

## Verifying the key fingerprint

```bash
gpg --import .well-known/security/pandora-cloud-public.asc
gpg --fingerprint pc@pandoracloud.net
```

The output should match the fingerprint published in `SECURITY.md` and on `keys.openpgp.org`.

## How this key was generated

The maintainer ran `scripts/generate_security_pgp.sh` once on a trusted workstation. The private key was imported into the mailbox that handles security disclosures and the export file shredded. Only the public side is committed here.

## Rotation

The key is set to expire two years after generation. Rotation procedure (issued before expiry):

1. Generate the new key: `scripts/generate_security_pgp.sh`
2. Sign the new key with the old key: `gpg --default-key <OLD_KEY_ID> --sign-key <NEW_KEY_ID>`
3. Publish the new public key: replace `pandora-cloud-public.asc`, update `SECURITY.md` fingerprint.
4. Upload the new key to `keys.openpgp.org`.
5. Revoke the old key after a 30-day overlap window.
