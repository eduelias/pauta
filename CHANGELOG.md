# Changelog

What changed in each release of Pauta. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/). Write new entries under **Unreleased** as you
go; `scripts/release.py cut X.Y.Z` turns them into the next release's notes.

## [Unreleased]

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

[Unreleased]: https://github.com/eduelias/pauta/commits/main
