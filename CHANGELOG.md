# Changelog

What changed in each release of Pauta. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/). Write new entries under **Unreleased** as you
go; `scripts/release.py cut X.Y.Z` turns them into the next release's notes.

## [Unreleased]

### Fixed

- Opening an invite link while signed in ("Você já entrou" → "Abrir a Pauta") left the app
  without its startup data, so every screen after the dashboard said "null is not an object
  (evaluating 'BOOT.options')" until a reload. The app now loads it first.

## [1.2.0] - 2026-10-28

### Added

- Structured logs: one JSON line per request in the journal (`journalctl -u pauta`) with the
  method, the route pattern (`/api/requests/{id}`, never the raw path), the status, the
  duration and the account id. No request bodies, IPs, names, cookies or invite tokens. Also
  `start` (with the version), `auth_failed`, `rate_limited` and `error` (with the traceback)
  events; errors are journal errors (`journalctl -u pauta -p err`).
- `GET /metrics` on 127.0.0.1:8088 only (refused through Caddy): requests and 5xx since the
  start, the last 15 minutes' requests, 5xx, p50/p95 latency and failing routes, the database
  size and the age of the newest nightly backup.
- du7's watchdog checks Pauta every 5 minutes: the service and `/healthz` (restarts it), the
  5xx rate, the nightly backup and its NAS copy (under 26 h), the TLS certificate (over 14
  days left), the GitHub runner, and failed deploys. Alerts go to IRC #du7 and WhatsApp.
- An hourly uptime check from GitHub (`uptime.yml`) that works when du7 or the home internet
  is down: it opens an issue labelled `uptime` and sends a WhatsApp alert, and closes the issue
  when the site is back.
- A WhatsApp alert when a release or a manual deploy fails. Alerts use the approved
  `du7_service_status` template, so they arrive even outside WhatsApp's 24-hour window.

### Fixed

- A crash in a request now answers 500 with a message and logs the traceback; the connection
  used to drop, which Caddy showed as a 502.

### Changed

- `pauta-deploy` also writes its deploys, switches and rollbacks to the journal
  (`journalctl -t pauta-deploy`; failures at error priority).

## [1.1.0] - 2026-10-28

### Added

- Clients have a **Link da página de anúncios** (free text). It shows under *Atalhos* on the
  client, and on every request in the *Briefing* and in *Dados do cliente*, each with a
  *Copiar* button. A link opens in a new tab; anything else is shown as written.
- The *Clientes* page filters by state (Todos, Ativo, Pausado, Encerrado), with counts. The
  filter is kept in the address, so it survives a reload.
- Admins can delete any client. One with requests is deleted together with them and their
  history, after typing the client's name to confirm; to keep the history, mark the client
  *Encerrado* instead.

## [1.0.0] - 2026-10-28

The first versioned release. It covers everything since Pauta replaced the
"Controle de Clientes e Campanhas" spreadsheet.

### Added

- Requests (pedidos) with the briefing and the execution on one record: client, type,
  goal, audience, region, budget, account balance, creatives, due date, priority, status,
  what's missing, campaign link and notes.
- A timeline on every request: who created it, status changes, edits and comments.
- Dashboard, board with drag and drop, filterable list, clients with their requests, and
  editable lists for request types, goals and segments.
- Passkey accounts: join with a single-use invite (link, QR code or WhatsApp), sign in with
  Face ID, fingerprint or the device PIN, add more devices. No passwords anywhere.
- Admin tools: invite admins or members, disable people, export everything as JSON.
- Link previews for WhatsApp, iMessage, Slack and LinkedIn, and installable app icons.
- Gravatar pictures for people who add an email; teammates only see the hash, never the
  address.
- `GET /healthz` for the deploy and uptime checks, and `pauta --version`. The version is
  shown at the bottom of the Equipe page.
- `HEAD` requests for pages and `/healthz` (they used to answer 501).
- Nightly database backups, kept 30 days on du7 and copied to the NAS.

### Changed

- Signing in returns the same profile as `/api/me`, Gravatar included.
- Releases are built and tested by GitHub Actions and deployed to du7 by a self-hosted
  runner: one release per tag, a database backup before every deploy, and an automatic
  rollback when the new version fails its health check.

### Security

- Every page is served with a strict Content Security Policy (scripts from Pauta only;
  images also from gravatar.com), `nosniff`, `same-origin` referrers and no framing.
- Writes from other origins are refused; the session cookie is HttpOnly, SameSite=Strict
  and Secure behind HTTPS. Invite, sign-up and login endpoints are rate limited per IP.
- The service runs with systemd sandboxing: a read-only system, write access only to its
  own data directory, no privilege escalation.

[Unreleased]: https://github.com/eduelias/pauta/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/eduelias/pauta/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/eduelias/pauta/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/eduelias/pauta/releases/tag/v1.0.0
