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
- `src/pauta/server.py`: `/api/...` JSON; everything but login/join needs a session (client
  data is private). Writes from a foreign `Origin` are refused; cookie is SameSite=Strict.
- `src/pauta/static/`: one vanilla-JS app (`app.js`, hash routes `#/...`), `style.css` (light
  and dark), vendored `qrcode.js` (MIT). CSP is `'self'` only (no CDNs, no external fonts);
  the one exception is `img-src https://gravatar.com` for people's avatars. Accounts may
  set an email, which is only used for that: teammates get the SHA-256 hash, never the
  address. `d=blank` means no Gravatar shows the initials underneath.

## Commands

```
uv venv && uv pip install -e '.[dev]'
.venv/bin/pytest -q && .venv/bin/ruff check src tests      # line length 100
PAUTA_STATE_DIR=/tmp/pauta .venv/bin/pauta demo            # made-up clients and requests
PAUTA_STATE_DIR=/tmp/pauta .venv/bin/pauta serve           # http://localhost:8088, open mode
```

Deploy and hosting: `deploy/README.md` (du7, Caddy, systemd, nightly backups). Never run
`pauta demo` against du7's DB.
