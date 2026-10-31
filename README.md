# Pauta

[![CI](https://github.com/eduelias/pauta/actions/workflows/ci.yml/badge.svg)](https://github.com/eduelias/pauta/actions/workflows/ci.yml)
[![Release](https://github.com/eduelias/pauta/actions/workflows/release.yml/badge.svg)](https://github.com/eduelias/pauta/actions/workflows/release.yml)

The request queue between whoever sells the campaign and whoever runs it, live at
**https://pauta.cc**. Whoever talks to the client files a request (*pedido*) with the
briefing; whoever runs the Meta ads works it through *A fazer → Em andamento → Aguardando →
Concluído*, and every change lands on the request's timeline. It replaced the spreadsheet
"Controle de Clientes e Campanhas".

- Sign-in with **passkeys only** (Face ID, fingerprint, device PIN), by invite.
- Dashboard, board, list, clients, and a timeline with comments on every request.
- Files on requests (images, short videos), kept in the team's OneDrive instead of on the
  server, with a view-only link to send the client.
- Brazilian Portuguese UI, installable on phones, link previews for WhatsApp and Slack.
- One Python process and one SQLite file. The only runtime dependency is
  [py_webauthn](https://github.com/duo-labs/py_webauthn).

## Develop

Needs [uv](https://docs.astral.sh/uv/) and Node (only for `node --check`).

```
make setup      # dev tools, plus Chromium for the browser tests
make demo       # made-up clients and requests in ./state
make run        # http://localhost:8088, open mode (no accounts)
make check      # what CI runs: lint, tests with coverage, browser tests
```

`make help` lists the rest. To try passkeys locally, run with `PAUTA_AUTH=passkeys` and make
the first invite with `uv run pauta invite --admin --base-url http://localhost:8088`.

## Tests

| Suite | What it covers | Run |
|---|---|---|
| `tests/unit` | field validation, the store, sessions and invites, passkey flows (with a software authenticator), rate limits, the CLI, the release script | `make test` |
| `tests/api` | the HTTP API end to end on a real server: auth, permissions, origins, headers, health, body limits | `make test` |
| `tests/e2e` | Chromium with a virtual passkey device: joining by invite, filing and working a request, signing out and back in, a member on a phone, every screen on both layouts, no JS errors or CSP violations | `make e2e` |

Coverage must stay at 90% or more (it is about 98%). A failing browser test leaves a
Playwright trace in `test-results/traces/` (`uv run playwright show-trace <file>`); CI keeps
them as an artifact.

## CI and releases

- **CI** (`.github/workflows/ci.yml`) on every push and pull request: ruff (lint and
  format), JS syntax, shellcheck, actionlint, the lockfile, tests on Python 3.11, 3.12 and
  3.13 with coverage, the browser tests, `pip-audit` on the runtime dependencies, and a
  build whose wheel is installed in a clean venv and started.
- **Releases** are tags: write what changed under *Unreleased* in [CHANGELOG.md](CHANGELOG.md),
  then `make release V=X.Y.Z`. The tag runs CI again, publishes a GitHub release with the
  changelog notes and the build, and deploys it to du7 through a self-hosted runner, with a
  database backup first and an automatic rollback if the new version isn't healthy.
- **Dependabot** opens weekly PRs for Python dependencies and GitHub Actions (pinned by SHA).

Hosting, the deploy, rollbacks and setting up du7: [deploy/README.md](deploy/README.md).
