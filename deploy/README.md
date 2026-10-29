# Running on du7

Pauta runs on du7 (192.168.2.68) as the systemd unit `pauta`, on `127.0.0.1:8088` only.
Caddy puts it on the internet at https://pauta.genic.dev, next to dom.du7.dev.

```
phone ──https──▶ home router :443 ──▶ du7 192.168.2.68:443 (Caddy, TLS) ──▶ 127.0.0.1:8088 (pauta)
```

| What | Where |
|---|---|
| DNS | Squarespace, `genic.dev` → DNS → custom record `pauta` CNAME `du7.sytes.net`, TTL 1 hr (the No-IP name the router keeps on the home IP, same as `dom.du7.dev`). Editing it asks for the account passkey |
| Router | the existing TCP 443 → 192.168.2.68:443 forward (shared with dom.du7.dev; nothing new) |
| Caddy | `/etc/caddy/Caddyfile`, the `pauta.genic.dev` block from `deploy/Caddyfile.pauta`. Certificate via TLS-ALPN on 443 |
| Code | `/opt/pauta/releases/X.Y.Z/` (a venv per release), `/opt/pauta/current` → the live one |
| DB of record | `~/.local/share/pauta/pauta.db` (`PAUTA_STATE_DIR`): accounts, passkeys, invites, clients, requests |
| Backups | nightly 03:40 (`pauta-backup.timer`) → `~/backups/pauta` + `/media/nas/backups/pauta`, 30 days; before every deploy → `~/backups/pauta/pre-deploy`, 90 days |
| Units | `/etc/systemd/system/pauta.service`, `pauta-backup.{service,timer}` (copies of `deploy/`), sandboxed: read-only system, writes only to the data and backup dirs |
| Deploys | `/usr/local/sbin/pauta-deploy` (copy of `deploy/pauta-deploy`), log in `/opt/pauta/deploy.log` |
| Runner | GitHub Actions self-hosted runner `du7` (labels `du7`, `pauta`) in `/opt/gh-runner`, user `gh-runner`, unit `actions.runner.eduelias-pauta.du7.service`; every job first passes `/usr/local/lib/pauta/runner-job-guard` (drop-in `job-guard.conf`) |

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
   https://pauta.genic.dev/healthz and expects 1.2.0.

The `production` environment on GitHub only accepts deploys from `v*` tags and `main`, and
lists every deploy under the repo's *Deployments*.

## Rolling back

- Any earlier release: GitHub → Actions → **Deploy** → *Run workflow* → the version. It is
  reinstalled from its GitHub release (or reused if it is still on du7).
- Straight on du7, to the release before the current one: `sudo pauta-deploy --rollback`.
- What's live: `sudo pauta-deploy --status`.

Schema changes are additive (new tables and columns), so an older release runs on a newer
database. If one ever isn't, restore the matching file from `~/backups/pauta/pre-deploy`
(stop `pauta`, copy it over `~/.local/share/pauta/pauta.db`, start `pauta`).

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
`/usr/local/lib/pauta/runner-job-guard`, refuses every job except `du7` of `release.yml` on a
`vX.Y.Z` tag and `du7` of `deploy.yml` run by hand on `main`; refusals are in
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
- A lost phone: sign in on another device that has a passkey (iCloud/Google sync them), or
  ask an admin for a fresh invite and disable the old account. Disabling ends every session
  the account had; "Sair em todos os aparelhos" does the same for your own account.
- Sign everyone out (a leaked cookie, a suspicion): delete
  `~/.local/share/pauta/pauta.db.session-key` and `sudo systemctl restart pauta`. The key is
  never in the DB or its backups; a missing key file is simply made again.
- The team always keeps one active admin. If the only admin loses access, make a new admin
  invite with the CLI command above.

## Taking it offline

`sudo systemctl stop pauta` takes it offline; remove the Caddy block and the `pauta` DNS
record to undo it completely. The DB stays in `~/.local/share/pauta`. To retire the runner:
`cd /opt/gh-runner/actions-runner && sudo ./svc.sh uninstall`, remove it under the repo's
Settings → Actions → Runners, and delete `/etc/sudoers.d/gh-runner-pauta`.
