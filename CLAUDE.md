# pauta

The team's request queue at https://pauta.genic.dev. It replaces the spreadsheet "Controle de
Clientes e Campanhas": the person who talks to clients files a request (pedido), and the
person who runs the Meta ads campaigns works it through A fazer → Em andamento → Aguardando →
Concluído. UI is Brazilian Portuguese; code, comments and docs are English.

## Shape

- Python 3.11+, stdlib HTTP server, SQLite. The only runtime dependency is `webauthn`
  (py_webauthn) for passkeys. Never hand-roll crypto.
- `src/pauta/db.py`: the schema and the `Store`. A request holds both halves (briefing and
  execution) on one row; every change writes an `event` (created/status/edited/comment),
  which is the timeline. Field checks live in `CLIENT_FIELDS` / `REQUEST_FIELDS`; links must
  be http(s). Status keys (`todo/doing/waiting/done/cancelled`) are stable, labels are UI.
  Tipos, objetivos and segmentos are editable lists (`option` table).
- `src/pauta/auth.py`: passkey-only accounts, modelled on dominion-archive's. One team, no
  sign-up: invites only (`pauta invite --admin` for the first, then the Equipe page). The first
  account is an admin. Without `PAUTA_AUTH=passkeys` the app runs open (local dev).
- `src/pauta/onedrive.py`: request files live in one OneDrive through Microsoft Graph (stdlib
  `urllib`, no SDK). Device code sign-in, no client secret; the refresh token is a file next
  to the DB. Uploads stream through in 5 MiB chunks; downloads are redirects to Graph's
  short-lived links. The `file` table keeps ids and names only. Tests use the fake Graph in
  `tests/fakegraph.py`; never call the real one.
- `src/pauta/obs.py`: JSON request logs (route patterns, never raw paths, bodies or personal
  data) and the numbers behind `GET /metrics` (loopback only, for du7's watchdog).
- `src/pauta/server.py`: `/api/...` JSON; everything but login/join needs a session (client
  data is private). Writes from a foreign `Origin` are refused; cookie is SameSite=Strict.
- `src/pauta/static/`: one vanilla-JS app (`app.js`, hash routes `#/...`), `style.css` (light
  and dark), vendored `qrcode.js` (MIT). CSP is `'self'` only (no CDNs, no external fonts);
  the one exception is `img-src https://gravatar.com` for people's avatars. Accounts may
  set an email, which is only used for that: teammates get the SHA-256 hash, never the
  address. `d=blank` means no Gravatar shows the initials underneath.

## Commands

```
make setup     # uv sync with dev + e2e extras, Chromium for Playwright
make check     # lint + unit/API tests (coverage >= 90%) + browser tests: what CI runs
make test      # just unit and API tests (~3 s)
make e2e       # just the browser tests (~10 s)
make run       # http://localhost:8088, open mode, data in ./state
```

Tests: `tests/unit` (no HTTP), `tests/api` (a real server on a free port, `SoftPasskey` in
`tests/softpasskey.py` signs real WebAuthn responses), `tests/e2e` (Playwright + Chromium's
virtual authenticator over CDP; marked `e2e`, skipped by default). Shared fixtures are in
`tests/conftest.py`. Warnings are errors. Browser tests fail on any console error, CSP
violation or unexpected 4xx/5xx: declare expected ones with `device.expected`.

## Releases and deploys

Never deploy by copying files to du7. Describe changes under `## [Unreleased]` in
`CHANGELOG.md`, then `make release V=X.Y.Z` (on a clean, pushed main): the tag runs CI,
publishes the GitHub release and deploys it through the self-hosted runner on du7, which
can only run `/usr/local/sbin/pauta-deploy` as root. Rollback: Actions → Deploy → an older
version, or `sudo pauta-deploy --rollback` on du7. Details: `deploy/README.md`. Never run
`pauta demo` against du7's DB. Keep schema changes additive so an older release can run on
a newer database.

Decisions (what was decided and why, including things not built yet) are in `docs/decisions/`.

## Working here as a collaborator

Maintainers (and their Claude) follow `CONTRIBUTING.md`: a branch and a pull request per
change, never a push to `main` (the ruleset refuses it), `make check` before pushing, a line
under Unreleased in `CHANGELOG.md`. Merge your own PR once CI is green. Paths in
`.github/CODEOWNERS` (CI, `deploy/`, `scripts/`, `Makefile`, `auth.py`, `ratelimit.py`,
`tests/softpasskey.py`, `pyproject.toml`, `uv.lock`, this file, the decisions) need the
owner's review: don't change them to get a feature through; say what you need in the PR.
Never create or move `v*` tags, never touch du7, https://pauta.genic.dev or real data, and
never put secrets or real phone numbers anywhere in the repo. Security model:
`docs/decisions/0002-collaborators-and-a-public-repo.md`.
