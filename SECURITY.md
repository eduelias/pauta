# Security

Pauta holds a small team's client contacts and runs at https://pauta.genic.dev.

## Reporting a vulnerability

Please report it privately: **Security → Report a vulnerability** on this repository
(GitHub's private vulnerability reporting). Don't open a public issue, and don't test
against https://pauta.genic.dev: run your own copy (`make run`) instead. You'll get an answer
within a few days.

## What protects it

- Passkey-only sign-in (py_webauthn), invites only, no passwords; sessions in SameSite=Strict
  cookies; writes from a foreign `Origin` refused; a `'self'`-only Content Security Policy.
- `main` changes only through pull requests with green CI; changes to CI, the deploy,
  sign-in, rate limits and dependencies also need the owner's review (`.github/CODEOWNERS`).
- Only the owner can release. Releases are immutable, and du7 installs a release only if it
  matches the published checksums. du7's runner refuses every job except that deploy.

Details: `docs/decisions/0002-collaborators-and-a-public-repo.md`, `deploy/README.md`.
