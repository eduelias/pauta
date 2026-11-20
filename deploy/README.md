# Running on du7

Pauta runs on du7 (192.168.2.68) as the systemd unit `pauta`, on `127.0.0.1:8088` only.
Caddy puts it on the internet at https://app.pauta.cc, next to dom.du7.dev. Acceptance is
https://acc.pauta.cc; https://www.pauta.cc is for the public site (a temporary redirect to the
app until it exists), and pauta.cc and pauta.team lead there. The old address,
https://pauta.genic.dev, serves the same app until everyone has moved (see "Moving to pauta.cc").

```
phone ──https──▶ home router :443 ──▶ du7 192.168.2.68:443 (Caddy, TLS) ──▶ 127.0.0.1:8088 (pauta)
```

| What | Where |
|---|---|
| DNS | `pauta.cc` and `pauta.team` (registered at Cloudflare, auto-renew and lock on): zones and records are code in `du7/dns-zone` (`pauta.tf`, OpenTofu). `pauta.cc`, `app.`, `acc.`, `www.` and `pauta.team`, `www.` are CNAMEs to `du7.sytes.net` (the No-IP name the router keeps on the home IP), DNS-only. The old `pauta.genic.dev` is a Squarespace record (`genic.dev` → DNS → `pauta` CNAME `du7.sytes.net`; editing it asks for the account passkey) |
| Router | the existing TCP 443 → 192.168.2.68:443 forward (shared with dom.du7.dev; nothing new) |
| Caddy | The `caddy` container's Caddyfile (`~/dns-stack/caddy/Caddyfile`, bind-mounted as a single file), the blocks from `deploy/Caddyfile.pauta`. Certificates via TLS-ALPN on 443 |
| Code | `/opt/pauta/releases/X.Y.Z/` (a venv per release), `/opt/pauta/current` → the live one |
| DB of record | `~/.local/share/pauta/pauta.db` (`PAUTA_STATE_DIR`): accounts, passkeys, invites, clients, requests |
| Request files | In a OneDrive (`Apps/Pauta/<cliente>/Pedido <n>/`), not on du7; the DB keeps their ids. The OneDrive token is `~/.local/share/pauta/pauta.db.onedrive-token`. See "Files and OneDrive" |
| Thumbnail cache | `~/.local/share/pauta/pauta.db.thumbs/<file id>.<item digest>.<type>`: a file's OneDrive thumbnail, fetched once. A cache: not backed up, safe to delete wholesale (the next view fetches again); clear it when restoring a backup |
| Backups | nightly 03:40 (`pauta-backup.timer`) → `~/backups/pauta` + `/media/nas/backups/pauta`, 30 days; before every deploy → `~/backups/pauta/pre-deploy`, 90 days |
| Units | `/etc/systemd/system/pauta.service`, `pauta-backup.{service,timer}` (copies of `deploy/`), sandboxed: read-only system, writes only to the data and backup dirs |
| Deploys | `/usr/local/sbin/pauta-deploy` (copy of `deploy/pauta-deploy`), log in `/opt/pauta/deploy.log` |
| Runner | GitHub Actions self-hosted runner `du7` (labels `du7`, `pauta`) in `/opt/gh-runner`, user `gh-runner`, unit `actions.runner.eduelias-pauta.du7.service`; every job first passes `/usr/local/lib/pauta/runner-job-guard.sh` (drop-in `job-guard.conf`) |

## Releasing

Releases are the only way code reaches du7. On the Mac, with `main` clean and pushed and the
changes described under **Unreleased** in `CHANGELOG.md`:

```
make release V=1.2.0
```

That runs `scripts/release.py cut 1.2.0 --push`: it moves the Unreleased notes into 1.2.0,
bumps `pyproject.toml`, commits "Release 1.2.0", tags `v1.2.0` and pushes both. The tag
starts `.github/workflows/release.yml`:

1. **CI**: lint, tests on Python 3.11–3.13 with coverage, browser tests, dependency audit,
   then the wheel is built, installed in a clean venv and started (`/healthz` must answer).
2. **Publish**: checks the tag, `pyproject.toml` and `CHANGELOG.md` agree, and creates the
   GitHub release with the CHANGELOG notes, the wheel, the sdist, `requirements.lock`
   (runtime dependencies pinned by hash) and `SHA256SUMS`.
3. **Deploy** (`deploy.yml`): downloads those assets, checks the sums, and on du7 runs
   `sudo pauta-deploy 1.2.0 <wheel> requirements.lock`, which
   - fetches the release's `SHA256SUMS` from GitHub itself and refuses a wheel or lockfile
     that isn't byte for byte the published one (releases are immutable),
   - builds `/opt/pauta/releases/1.2.0` as the service user (binary wheels only, every hash
     checked, PyPI only),
   - backs up the DB with the system Python (the new code never touches it before the switch),
   - points `/opt/pauta/current` at the new release and restarts `pauta`,
   - waits for `/healthz` to report 1.2.0, and **switches back to the old release** if it
     doesn't (the job then fails),
   - keeps the last 5 releases.
4. **Reachable from the internet**: a GitHub-hosted runner fetches
   https://app.pauta.cc/healthz and expects 1.2.0.

The `production` environment on GitHub only accepts deploys from `v*` tags and `main`, and
lists every deploy under the repo's *Deployments*.

## Moving to pauta.cc

Decision 4. Passkeys belong to the domain they were made on, so everyone makes one new
passkey for `pauta.cc`, from inside their account on the old address. The app itself is on
`app.pauta.cc` (since 1.6.1; 1.6.0 had it on the apex): a passkey for `pauta.cc` works on
any address under it, and production only accepts the origin `https://app.pauta.cc`. In
order (steps 1–5 done 2026-10-31):

1. **DNS**: `cd ~/reps/du7/dns-zone && op-env run -- tofu plan`, then `apply` (`pauta.tf`).
2. **Caddy** on du7: add the blocks from `deploy/Caddyfile.pauta` to
   `~/dns-stack/caddy/Caddyfile` *in place* (same inode), then check the container sees them
   (`sudo docker exec caddy grep -c app.pauta.cc /etc/caddy/Caddyfile`; if 0, the mount is stale:
   `sudo docker restart caddy`) and `sudo docker exec caddy caddy reload --config
   /etc/caddy/Caddyfile --adapter caddyfile`. `curl -sI https://app.pauta.cc/healthz` answers
   (with the old release) once the certificate is issued.
3. **Unit**: install the new `deploy/pauta.service` (both domains), `sudo systemctl
   daemon-reload`.
4. **Release** the version with the move (`make release`). The deploy checks `app.pauta.cc`, so
   steps 2 and 3 come first.
5. **Move the team**: send each person their own link, which is one tap and Face ID. From
   the app: Equipe → *Link para mudar* next to the person → *Enviar no WhatsApp*. Or on du7
   (`PAUTA_STATE_DIR=~/.local/share/pauta /opt/pauta/current/bin/pauta move-link Piero`).
   A link works once, for 3 days, for that account only: send it to that person only.
   Without a link, the bar on the old address does the same (*Mudar para app.pauta.cc*).
   Either way, afterwards add `app.pauta.cc` to the phone's home screen (the old icon keeps opening the
   old address). `pauta users` and the Equipe page show who has moved.
6. **Close the old address** when everyone shows `pauta.cc`: in the unit, `PAUTA_RP_ID=pauta.cc`
   and `PAUTA_ORIGIN=https://app.pauta.cc`; in Caddy, the `pauta.genic.dev` block becomes
   `redir https://app.pauta.cc{uri} 301`. Keep the redirect (and the Squarespace record) for at
   least a year.
7. **Acceptance** (done 2026-10-31): `acc.pauta.cc` in Caddy (the old name redirects),
   `PAUTA_RP_ID=acc.pauta.cc` and `PAUTA_ORIGIN=https://acc.pauta.cc` in `pauta-acc.service`
   (now `deploy/pauta-acc.service`, see "Acceptance: trying a branch"), and an admin invite from its CLI because its old
   passkeys don't work there.
8. **Monitoring**: du7's watchdog `pauta*` checks and the repo's homepage link point at
   `app.pauta.cc`, as the GitHub uptime check does.

Until step 6 a rollback is the usual one: the release before the move runs on the new
database (the `passkey.rp_id` column is additive) and the old address still works.

## Rolling back

- Any earlier release: GitHub → Actions → **Deploy** → *Run workflow* → the version. It is
  reinstalled from its GitHub release (or reused if it is still on du7).
- Straight on du7, to the release before the current one: `sudo pauta-deploy --rollback`.
- What's live: `sudo pauta-deploy --status`.

Schema changes are additive (new tables and columns), so an older release runs on a newer
database. If one ever isn't, restore the matching file from `~/backups/pauta/pre-deploy`
(stop `pauta`, copy it over `~/.local/share/pauta/pauta.db`, remove `pauta.db.thumbs/`, start `pauta`).

## Acceptance: trying a branch

https://acc.pauta.cc is a second copy of Pauta on du7 (unit `pauta-acc`, `127.0.0.1:8089`,
user `pauta-acc`, demo data, its own accounts). It takes builds of any branch before they are
merged or released; decision 9 says why and what that exposes.

```
gh workflow run deploy-branch.yml -f ref=feat/meta-connect     # or Actions → Deploy branch to acceptance
gh workflow run deploy-branch.yml -f rollback=true             # back to the build before
```

Only the owner can start it (the job guard refuses anyone else's run on du7). GitHub builds the
branch as `X.Y.Z.devN+gSHA` (the next patch, the run number, the commit), checks it installs
and answers `/healthz`, and du7 runs `sudo pauta-deploy-branch acc VERSION WHEEL LOCK SOURCE`:

- refuses unless the unit runs as `pauta-acc`, in no other group, with `ProtectHome=yes`, from
  `/opt/pauta-acc/current`; it has no way to name production's `/opt/pauta`, unit or data,
- builds `/opt/pauta-acc/releases/VERSION` as `pauta-acc` (binary wheels, hashes required, and
  a `requirements.lock` with nothing but pinned names and their hashes, as `uv export` writes
  it), then makes it root's; the build's code first runs in the unit's sandbox, after the switch,
- backs up the DB read-only to `/var/backups/pauta-acc` (30 days), never writing
  `/var/lib/pauta-acc` (the DB, `pauta.db.meta-secret`, the OneDrive token, the session key),
- switches `/opt/pauta-acc/current`, restarts `pauta-acc`, waits for `/healthz` to report the
  version, and switches back if it doesn't; keeps 5 builds.

On du7: `sudo pauta-deploy-branch acc --status` (log in `/opt/pauta-acc/deploy.log` and
`journalctl -t pauta-deploy-acc`), `sudo pauta-deploy-branch acc --rollback`. The DB is
acceptance's own: if a branch's schema change breaks the build before, restore the newest
`/var/backups/pauta-acc/pauta-*-before-<version>.db` (stop `pauta-acc`, copy it over
`/var/lib/pauta-acc/pauta.db` as `pauta-acc`, start it).

**Setting it up** (re-runnable; it never starts, restarts or reads into acceptance's state):
from a fresh copy of `deploy/` on du7, `sudo deploy/provision-branch-env.sh acc`. It installs
`pauta-deploy-branch`, the sudo rule `/etc/sudoers.d/gh-runner-pauta-branch`, the
`pauta-acc` user and unit (`deploy/pauta-acc.service`; settings for one environment, like the
Meta app, stay in drop-ins under `pauta-acc.service.d/`), `/var/backups/pauta-acc`, and the
runner's job guard, which a sudo rule for unreleased code must never be without.

**Acceptance's Meta app** (since 2026-11-02): acceptance talks to its own Meta app, the test
app **Pauta (acc)** (App ID `1438754228470933`, login configuration `1631138148751190`,
callback `https://acc.pauta.cc/api/meta/callback`; decision 8, "Whose Meta app"), never to
production's. The ids are the drop-in `/etc/systemd/system/pauta-acc.service.d/meta.conf`
(`Environment=PAUTA_META_APP_ID=…` and `PAUTA_META_CONFIG_ID=…`); its App Secret is
`/var/lib/pauta-acc/pauta.db.meta-secret` (owner `pauta-acc`, mode 600), rendered from the
1Password item "pauta-acc meta app secret" (Du7 Tech) and pushed, never typed or committed.
A portfolio connected there is a system user of the test app: the token files
`/var/lib/pauta-acc/pauta.db.meta-token.<business_id>` and the `meta_connection` rows only
mean something to that app, so switching apps means deleting them and connecting again.
Check: `curl -s 127.0.0.1:8089/metrics` shows `"meta": {"enabled": true, …}` after
`sudo systemctl restart pauta-acc`.

**Another environment** (`dev`): a line in `env_config` in `pauta-deploy-branch` (its port),
`deploy/pauta-dev.service`, a Caddy block, `dev` in the workflow's `environment` choices, then
`sudo deploy/provision-branch-env.sh dev`.

## Setting up du7 (once)

Done on 2026-10-28; repeat only to rebuild du7. From the Mac, copy `deploy/` to du7, then on
du7 (the runner version and sha256 are on https://github.com/actions/runner/releases):

```
gh api -X POST repos/eduelias/pauta/actions/runners/registration-token --jq .token > token   # on the Mac, then copy it over
sudo deploy/provision-du7.sh 2.338.2 <sha256 of actions-runner-linux-arm64-2.338.2.tar.gz> token
```

It installs `pauta-deploy`, the units, a sudo rule letting `gh-runner` run
`/usr/local/sbin/pauta-deploy` (and nothing else) as root, and registers the runner as a
systemd service. Then put a first release in place by hand (`sudo pauta-deploy X.Y.Z
pauta-X.Y.Z-py3-none-any.whl requirements.lock` with the assets of a GitHub release),
`systemctl enable --now pauta pauta-backup.timer`, append `Caddyfile.pauta` to the Caddyfile
and `systemctl reload caddy`.

The runner only takes jobs for this repo (labels `du7`, `pauta`), runs as a user with no
shell and no groups, and keeps itself updated. Its job-started hook,
`/usr/local/lib/pauta/runner-job-guard.sh`, refuses every job except `du7` of `release.yml` on a
`vX.Y.Z` tag, and `du7` of `deploy.yml` or `deploy-branch.yml` run by hand on `main`, each only
when the owner started the run and, for a run started again, did that too; refusals are in
`journalctl -t pauta-runner-guard`. The hook and its systemd drop-in are root-owned, outside
the runner's own directory, so no job can switch it off.

## Collaborators

Maintainers work through pull requests (`CONTRIBUTING.md`); what they may and may not do, and
why, is decision 2. The GitHub side is `scripts/repo-settings.sh`. In this order:

1. Merge the change that brought this section (CODEOWNERS, the guard, the release check).
2. While the repo is private, `apply` already sets what it can (forks run no workflows at all)
   and lists the rest as `later`; it was run on 2026-10-29. Make the repository public
   (Settings → General → Danger Zone), then on the Mac:
   `scripts/repo-settings.sh apply` (rulesets, Actions, environments, security features) and
   `scripts/repo-settings.sh secrets` (the WhatsApp secrets into the `alerts` environment;
   1Password asks for Touch ID). `scripts/repo-settings.sh show` checks it.
3. On du7, from a fresh copy of `deploy/`: `sudo deploy/provision-du7.sh <runner version>
   <sha256>` (no token: the runner stays registered). It installs the new `pauta-deploy`, the
   job guard and its drop-in, and restarts the runner. Check: `systemctl show
   actions.runner.eduelias-pauta.du7.service -p Environment` names the guard, and Actions →
   Deploy → Run workflow (the live version, on `main`) still deploys.
4. Invite: `scripts/repo-settings.sh invite <github login>` (maintain). Ask him to open a
   small PR that touches `Makefile`: it must wait for the owner's review.

Between 2 and 3 the runner is unguarded: approve no fork runs and invite nobody. Step 3 only
works after step 2, because `pauta-deploy` downloads `SHA256SUMS` without a token.

## Monitoring and alarms

| What | Where | Alerts |
|---|---|---|
| Logs | `journalctl -u pauta` (one JSON line per request; `-p err` for errors with tracebacks), `journalctl -t pauta-deploy` | |
| Numbers | `curl -s 127.0.0.1:8088/metrics` on du7 (refused through Caddy): request and 5xx counts, the last 15 min's latency and failing routes, DB size, newest backup age | |
| Watchdog | `~/du7-watchdog.py` (cron, every 5 min; `--status` for the table): `pauta` (unit + `/healthz`, restarts it after 2 strikes, never during a deploy), `pauta-5xx` (3+ in 15 min), `pauta-backup` (newest under 26 h, else runs `pauta-backup` once), `pauta-backup-nas`, `pauta-tls` (over 14 days left), `pauta-runner` (restarts it), `pauta-deploy` (last line of `deploy.log` is `FAILED`) | IRC #du7; WhatsApp when a heal didn't help or there is none (at most once per check per 6 h) |
| From outside | `.github/workflows/uptime.yml`, hourly on GitHub's machines | an issue labelled `uptime` (GitHub email and app push) and WhatsApp; closed with one more WhatsApp when it's back |
| Releases and deploys | the `alert` jobs in `release.yml` and `deploy.yml` | WhatsApp with the failed stages and the run link |

WhatsApp alerts use the approved **utility** template `du7_service_status` ({{1}} source,
{{2}} detail) on the famulus number, so they arrive even when nobody has written to famulus in
24 hours (plain text is silently dropped then). From GitHub they go straight to the Meta Cloud
API (`scripts/alert.py`, repository secrets `WA_TOKEN`, `WA_PHONE_ID`, `WA_TO`; optional
variable `WA_TEMPLATE`). On du7 the watchdog posts `{"text", "alert"}` to wa-notify
(`~/wa-notify/notify.py`, :8095), which sends the same template.

To try the alarm: pause healing (`echo $(( $(date +%s) + 1800 )) > ~/.du7-watchdog-off`),
`sudo systemctl stop pauta`, run `python3 ~/du7-watchdog.py` four times (strikes, then the
escalation), and `sudo systemctl start pauta`; the next run posts "recovered" to IRC.

## People

- The first admin: on du7, `PAUTA_STATE_DIR=~/.local/share/pauta /opt/pauta/current/bin/pauta
  invite --admin` prints a link (7 days, one person). The first account is always an admin.
- After that, admins invite from the app: Equipe → Convidar alguém (QR code, link, WhatsApp).
- `pauta users` lists accounts. Admins disable people or make them admin on the Equipe page.
- Make every open tab reload itself (a fix people must get now): on du7,
  `PAUTA_STATE_DIR=~/.local/share/pauta /opt/pauta/current/bin/pauta reload`. Each tab
  reloads at its next change of screen, never under a form being filled, and the running
  server needs no restart. After an ordinary release tabs only show "A Pauta foi
  atualizada" and wait for the person. Tabs loaded before 1.15.0 know neither.
- A lost phone: sign in on another device that has a passkey (iCloud/Google sync them), or
  an admin sends a fresh link to the same account (Equipe → *Link para mudar* while moving,
  or `pauta move-link <name>` on du7). Disabling ends every session
  the account had; "Sair em todos os aparelhos" does the same for your own account.
- Sign everyone out (a leaked cookie, a suspicion): delete
  `~/.local/share/pauta/pauta.db.session-key` and `sudo systemctl restart pauta`. The key is
  never in the DB or its backups; a missing key file is simply made again.
- The team always keeps one active admin. If the only admin loses access, make a new admin
  invite with the CLI command above.

## Files and OneDrive

Files attached to requests live in one OneDrive (a personal Microsoft account); Pauta passes
uploads through to it and hands out short-lived download links. Why and how:
`docs/decisions/0003-request-files-in-onedrive.md`.

| Setting | Where | Notes |
|---|---|---|
| `PAUTA_ONEDRIVE_CLIENT_ID` | `Environment=` in `pauta.service` | The app registration's client id (public). Unset: no Arquivos panel, uploads off |
| `PAUTA_ONEDRIVE_ROOT` | `Environment=`, optional | A folder in the drive, e.g. `/Clientes/Pauta`. Unset keeps Pauta inside `Apps/Pauta` with `Files.ReadWrite.AppFolder`; set asks for the whole drive (`Files.ReadWrite`) when connecting |
| `PAUTA_UPLOAD_MAX_MB` | `Environment=`, optional | Largest file, default 200 |
| The token | `pauta.db.onedrive-token` next to the DB, mode 600 | Written by the app when someone connects, renewed on use (Microsoft rotates it). Never in the DB or its backups. Nobody edits it by hand |

**The app registration** (done 2026-10-29; repeat only to start over): sign in to
https://entra.microsoft.com as du7@msn.com, in its own "Default Directory"
(du7msn.onmicrosoft.com), never a work directory.

1. App registrations → New registration: name `Pauta` (it becomes the `Apps/Pauta` folder),
   supported accounts **Personal Microsoft accounts only**, no redirect URI. Register.
2. Authentication → Settings: **Allow public client flows** on, Save. There is no client
   secret: sign-in is the device code flow.
3. API permissions → Add a permission → Microsoft Graph → Delegated: `offline_access`,
   `Files.ReadWrite.AppFolder` (`User.Read` is there already). Add `Files.ReadWrite` only if
   you set `PAUTA_ONEDRIVE_ROOT`.
4. Copy the Application (client) ID into `pauta.service`, reinstall the unit
   (`sudo cp deploy/pauta.service /etc/systemd/system/ && sudo systemctl daemon-reload &&
   sudo systemctl restart pauta`).

**Connecting** (once, and again if the connection breaks): an admin opens Equipe → OneDrive
→ Conectar OneDrive. The page shows a code; the owner of the OneDrive opens
microsoft.com/link, signs in, types the code and approves. The page notices within seconds.
From du7 instead (the same environment as the unit):

```
export PAUTA_STATE_DIR=~/.local/share/pauta PAUTA_ONEDRIVE_CLIENT_ID=a6a25189-1541-430b-ba90-be78b92a8e30
/opt/pauta/current/bin/pauta onedrive connect
```

**Checking**: `pauta onedrive status` (same environment) prints the account, folder, space
used and when the token was last renewed, and exits non-zero on a problem. `/metrics` has
`onedrive.{enabled,connected,error}` for the watchdog: alert when `enabled` and (`connected`
is false or `error` is set). A token unused for 90 days expires; any upload or download
renews it.

**Disconnecting**: Equipe → OneDrive → Desconectar, or `pauta onedrive disconnect`. The
files stay in OneDrive; the owner can also revoke Pauta at
https://account.live.com/consent/Manage.

**What's where**: OneDrive keeps `<cliente>/Pedido <n>/<arquivo>` (a clash gets a numbered
name). Removing a file in Pauta sends it to OneDrive's recycle bin (30 days). Deleting a
request or a client in Pauta leaves its files in OneDrive. "Link para o cliente" makes a
view-only link to the request's folder that anyone with it can open; it lasts until it is
removed in OneDrive (folder → Compartilhar → Gerenciar acesso).

## Meta in production

Campaign numbers come from Meta's Marketing API through Facebook Login for Business (decision
8): each team connects its own business portfolio, Meta mints a system-user token for Pauta,
and Pauta keeps it in a file next to the DB. Production has been switched on since
2026-11-01, with Du7's Meta app **Pauta** (App ID `1767206382079558`).

| Setting | Where | Notes |
|---|---|---|
| `PAUTA_META_APP_ID`, `PAUTA_META_CONFIG_ID` | the drop-in `/etc/systemd/system/pauta.service.d/meta.conf` (`[Service]` + two `Environment=` lines), not `pauta.service` itself | The app id and the Facebook Login for Business configuration id (`1649862390172470`, "Pauta - leitura de anuncios"). Both public. Unset: no Meta card on Configurações, no sync. `sudo systemctl daemon-reload && sudo systemctl restart pauta` after editing |
| The App Secret | `~/.local/share/pauta/pauta.db.meta-secret` next to the DB, mode 600, one line | Rendered from the 1Password item "Pauta Meta app" (Du7 Tech) on the Mac and pushed; never in the repo, the unit, a chat or a log. Rotating it in the Meta dashboard means rewriting this file and restarting |
| The tokens | `~/.local/share/pauta/pauta.db.meta-token.<business_id>`, mode 600, one per connected portfolio | Written by the app when an admin connects a portfolio. Never in the DB or its backups. A portfolio disconnected in the UI (Desconectar) or revoked in the team's Business Settings loses its file |
| The callback | Meta dashboard → Pauta → Facebook Login for Business → Settings → Valid OAuth Redirect URIs | **`https://app.pauta.cc/api/meta/callback` only**, strict mode, HTTPS enforced. Acceptance uses its own app (see "Acceptance: trying a branch"), so its callback is not listed here |

Check: `curl -s 127.0.0.1:8088/metrics` → `"meta": {"enabled": true, "connected": …}`.
The Meta card on Configurações shows each connected portfolio and its token's state.

## Taking it offline

`sudo systemctl stop pauta` takes it offline; remove the Caddy block and the `pauta` DNS
record to undo it completely. The DB stays in `~/.local/share/pauta`. To retire the runner:
`cd /opt/gh-runner/actions-runner && sudo ./svc.sh uninstall`, remove it under the repo's
Settings → Actions → Runners, and delete `/etc/sudoers.d/gh-runner-pauta`.
