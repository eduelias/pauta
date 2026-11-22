# pauta

The team's request queue at https://app.pauta.cc. It replaces the spreadsheet "Controle de
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
  sign-up: invites only (`pauta invite --admin` for the first, then Configurações → Time). The first
  account is an admin. Without `PAUTA_AUTH=passkeys` the app runs open (local dev).
  Passkeys belong to a domain: during a move (decision 4) `PAUTA_RP_ID` lists the new home
  first and the old one after; each ceremony uses the domain its page is on, and a one-time
  link (`#/mudar/<token>`) gives a signed-in account a passkey on the new one.
- `src/pauta/onedrive.py`: request files live in one OneDrive through Microsoft Graph (stdlib
  `urllib`, no SDK). Device code sign-in, no client secret; the refresh token is a file next
  to the DB. Uploads stream through in 5 MiB chunks; downloads are redirects to Graph's
  short-lived links. The `file` table keeps ids and names only. Tests use the fake Graph in
  `tests/fakegraph.py`; never call the real one.
- `src/pauta/obs.py`: JSON request logs (route patterns, never raw paths, bodies or personal
  data) and the numbers behind `GET /metrics` (loopback only, for du7's watchdog).
- `src/pauta/push.py`: notifications on people's own devices (Web Push), switched on per
  device on Perfil. A push is empty: it wakes the device's service worker (`static/sw.js`,
  notifications only, no cache), which reads what to show from `POST /api/push/news` as the
  person signed in, so nothing of the team's data goes through a push service and the only
  crypto is the VAPID signature (`cryptography`, which `webauthn` already brings). The
  `Store` calls `on_news` after a new request, a status change or a comment; the signing key
  is a file next to the DB; a device's address is only called on a known push service.
  Tests use `tests/fakepush.py`; never call a real one.
- `src/pauta/usage.py`: the usage log (decision 11): the fixed table of events and prop keys,
  the cleaning `POST /api/usage` (`routes/usage.py`, a quiet route) applies to the client's
  batches, and the `pauta usage` report. Rows hold the account id, never a name, nothing
  from the team's data; `pauta backup` prunes them after 90 days.
- `src/pauta/server.py`: the HTTP plumbing (dispatch, headers, static files, health, metrics)
  and `/api/me`, `/api/boot`, `/api/export`. The rest of `/api/...` is in `src/pauta/routes/`,
  one module per area (`requests`, `clients`, `campaigns`, `finance`, `team`, `account`), each
  an `install(route, store, auth, drive, meta)` registering plain functions on the same route
  table; what they share is in `routes/__init__.py`. Everything but login/join needs a session
  (client data is private). Writes from a foreign `Origin` are refused; cookie is SameSite=Strict.
- `src/pauta/assets.py`: how the pages name static files, with no build step. The scripts a
  page lists between `<!-- bundle NAME -->` and `<!-- /bundle -->` are served as one file
  (`/app.bundle.js`, `/report.bundle.js`), and every local `src`/`href` (and `url(/...)` in
  the stylesheet) gets `?v=<start of the file's SHA-256>`: that address is cached for a year,
  a bare one for five minutes, the shell never. A new script goes in the page's bundle block.
- Open tabs and releases: every JSON answer carries `X-Pauta-Version` and `X-Pauta-Reload`.
  Another version shows the "A Pauta foi atualizada" bar (the person reloads); another
  reload mark makes the tab reload itself at its next change of screen. The mark changes
  with `pauta reload` on the server, or by raising `RELOAD_EPOCH` in `db.py` in a release
  whose server no longer works with an older page.
- `src/pauta/static/`: one vanilla-JS app in plain scripts sharing one global scope, in the
  order `index.html` lists them: `app.js` (helpers, shell), then one file per screen area
  (`app-requests.js`, `app-clients.js`, `app-financeiro.js`, `app-campanhas.js`, `app-team.js`,
  `app-perfil.js`), then `app-router.js` (hash routes `#/...`, start-up; last, since it names
  every view). `style.css` (light
  and dark), vendored `qrcode.js` (MIT, fetched only when an invite is made). CSP is `'self'` only (no CDNs, no external fonts);
  the one exception is `img-src https://gravatar.com` for people's avatars. Accounts may
  set an email, which is only used for that: teammates get the SHA-256 hash, never the
  address. `d=blank` means no Gravatar shows the initials underneath. `#/perfil` is the
  person's own page (name, WhatsApp, e-mail, their passkeys, a link for a new phone);
  `#/configuracoes` (until 1.6 "Equipe") is the team's: Time, Meta, Financeiro, Listas,
  Arquivos (decision 10).

## Commands

```
make setup     # uv sync with dev + e2e extras, Chromium for Playwright
make test-fast # the inner loop: unit and API tests in parallel, no coverage (~5 s)
make check     # lint + unit/API tests (coverage >= 90%) + browser tests: what CI runs (~30 s)
make test      # just unit and API tests with coverage (~7 s)
make e2e       # just the browser tests, parallel (~25 s)
make acc       # owner only: push this branch and put it on https://acc.pauta.cc (~1-2 min)
make run       # http://localhost:8088, open mode, data in ./state
```

The loop (what to run when, and the measured timings) is in `CONTRIBUTING.md`, "The loop".

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
version still installed on du7, or `sudo pauta-deploy --rollback` there. Details:
`deploy/README.md`. Never run `pauta demo` against du7's DB. Keep schema changes additive
so an older release can run on a newer database.

Decisions (what was decided and why, including things not built yet) are in `docs/decisions/`.

## Working here as a collaborator

Maintainers (and their Claude) follow `CONTRIBUTING.md`: a branch and a pull request per
change, never a push to `main` (the ruleset refuses it), `make check` before pushing, a line
under Unreleased in `CHANGELOG.md`. Merge your own PR once CI is green. Paths in
`.github/CODEOWNERS` (CI, `deploy/`, `scripts/`, `Makefile`, `auth.py`, `ratelimit.py`,
`tests/softpasskey.py`, `pyproject.toml`, `uv.lock`, this file, the decisions) need the
owner's review: don't change them to get a feature through; say what you need in the PR.
Never create or move `v*` tags, never touch du7, https://app.pauta.cc (or the old pauta.genic.dev) or real data, and
never put secrets or real phone numbers anywhere in the repo. Security model:
`docs/decisions/0002-collaborators-and-a-public-repo.md`.
