# Changelog

What changed in each release of Pauta. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/). Write new entries under **Unreleased** as you
go; `scripts/release.py cut X.Y.Z` turns them into the next release's notes.

## [Unreleased]

## [1.5.0] - 2026-10-30

### Added

- Financeiro: uma aba nova (depois de Clientes; no celular ela entra no lugar do Quadro) com
  quem está em dia, em atraso, vencendo na semana e esperando o primeiro pagamento, e o
  recebido no mês. Cada cliente Ativo tem um valor por mês; o mês dele começa no primeiro
  pagamento registrado (ou na data "cliente desde", ou num dia fixo: escolha em Equipe →
  Financeiro), e o painel mostra em que mês de vida ele está ("4º mês"). Pausar ou encerrar
  tira o cliente do painel; ao voltar, a contagem recomeça. Na página do cliente, um card
  Pagamentos com o valor, a situação, a lista e o botão para registrar. Pagamentos nunca são
  apagados, só anulados (por quem registrou ou um administrador). Equipe → Financeiro guarda
  as regras do time: moeda, valor padrão, periodicidade, tolerância, aviso de vencimento e
  quem pode ver. Os cartões do topo filtram a lista (toque em "Em atraso" e só eles
  aparecem; toque de novo para ver todos) e "Recebido no mês" abre os pagamentos do mês,
  com um seletor para ver quanto entrou em cada mês. Decisão 7.

## [1.4.0] - 2026-10-29

### Added

- Arquivos nos pedidos: envie imagens e vídeos direto na página do pedido (botão ou arrastar),
  com miniatura, quem enviou e quando, e uma linha na conversa e histórico. Os arquivos ficam
  no OneDrive do time, não no servidor; "Link para o cliente" gera um link só de
  visualização para mandar no WhatsApp. Um administrador conecta o OneDrive uma vez em
  Equipe → OneDrive, com um código (decision 3).

## [1.3.0] - 2026-10-29

### Security

- Ready for collaborators and a public repository (decision 2): CODEOWNERS for CI, deploy,
  sign-in and dependencies, rulesets and settings as code (`scripts/repo-settings.sh`), the
  WhatsApp secrets in an `alerts` environment, immutable releases, and on du7 a runner that
  refuses every job but the deploy and a `pauta-deploy` that only installs the published
  release's files. `SECURITY.md` and `CONTRIBUTING.md` are new.

Fixes from a security review of 1.2.3. Everyone has to sign in again once after this release
(the session key moved), which takes a tap with the passkey.

- The key that signs sessions now lives in a file next to the database
  (`pauta.db.session-key`, readable only by the service) instead of inside it, so the nightly
  backups on the NAS can no longer be turned into an admin login. The old key is deleted on
  first start. Deleting the file and restarting signs everyone out.
- Sessions can be ended: "Sair" ends the person's sessions on every device, and disabling an
  account ends its sessions for good (re-enabling it doesn't bring old ones back). Before, a
  copied cookie kept working for 180 days after "Sair".
- A single-use invite could create several accounts if the join was sent many times at once;
  joining is now one at a time and an invite can't be used past its limit.
- Passkeys must verify the person (Face ID, fingerprint or PIN); a touch alone is refused.
- The team always keeps at least one active admin, and admin changes take only true/false
  (sending `0` used to get past the "you can't demote yourself" check).
- Nobody can take a teammate's name (ignoring case, accents and invisible characters) or
  email, so the timeline can't be made to show someone else as the author. Hidden control and
  text-direction characters are dropped from all text.
- "Exportar dados" is for admins only, as documented.
- The ads page and Instagram fields refuse `javascript:`, `data:` and similar links (the app
  never made them clickable, but the export and copy button passed them on).
- Malformed requests get a 400 instead of a 500, so nobody can set off the 5xx alarm from
  outside; bodies must be exactly `application/json` with a valid length.
- A connection that stalls for 15 seconds is dropped, and at most 64 are served at once, so
  slow clients can't pile up threads on the Pi.
- New headers: `X-Frame-Options`, `Cross-Origin-Opener-Policy` and `Permissions-Policy`.
- The pauta unit gets `TasksMax` and `MemoryMax` (applied by `provision-du7.sh`).
- The Equipe page says plainly what the Gravatar hash does and doesn't hide.

### Fixed

- A browser test expected an afternoon greeting and failed every morning ("Bom dia").
- A browser test waited by evaluating a string in the page, which the Content Security Policy
  sometimes refused, so CI failed at random.

## [1.2.3] - 2026-10-28

### Fixed

- On a phone, the Quadro's columns widened the whole page, which pushed the tab bar off the
  screen, so there was no way to leave the Quadro without the browser's back button.

### Added

- Browser tests for every way a signed-in person arrives (an invite link then "Abrir a
  Pauta", the back button, an edited address, a fresh load on any screen), on a laptop and a
  phone, each walking every screen through the menu and checking it drew, not the 😕 error.

## [1.2.2] - 2026-10-28

### Added

- The version that's live shows in small type next to the Pauta name, in the sidebar and in
  the phone's top bar (it's also at the bottom of the Equipe page).

## [1.2.1] - 2026-10-28

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

[Unreleased]: https://github.com/eduelias/pauta/compare/v1.5.0...HEAD
[1.5.0]: https://github.com/eduelias/pauta/compare/v1.4.0...v1.5.0
[1.4.0]: https://github.com/eduelias/pauta/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/eduelias/pauta/compare/v1.2.3...v1.3.0
[1.2.3]: https://github.com/eduelias/pauta/compare/v1.2.2...v1.2.3
[1.2.2]: https://github.com/eduelias/pauta/compare/v1.2.1...v1.2.2
[1.2.1]: https://github.com/eduelias/pauta/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/eduelias/pauta/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/eduelias/pauta/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/eduelias/pauta/releases/tag/v1.0.0
