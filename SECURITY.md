# Security policy

## Secrets and infrastructure information

- Never commit `.env`, access keys, API tokens, private keys, production passwords or MinIO credentials.
- Commit only `.env.example` with placeholders. Production values belong in a secret manager, Docker secret or CI/CD secret store.
- Do not publish internal IP addresses, VPN topology or operational runbooks containing real credentials in public documentation.
- Use a read-only MinIO service account scoped to the required bucket and `gold/` prefix.

## Before pushing

Install the repository hook once on each developer machine:

```powershell
python -m pip install pre-commit
pre-commit install
pre-commit run --all-files
```

GitHub Actions also scans every pull request and push. Enable GitHub Secret Scanning and Push Protection in the repository's **Settings → Security**.

## If a secret is exposed

1. Revoke or rotate it immediately.
2. Remove it from the code and CI configuration.
3. Remove it from Git history if necessary, but treat the original credential as compromised even after removal.
