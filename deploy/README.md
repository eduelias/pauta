# Running on du7

Pauta runs on du7, the home server, as the systemd unit `pauta` (user `pauta`), on
`127.0.0.1:8088` only. Caddy, which serves other sites on du7 too, puts it on the internet at
https://pauta.genic.dev.

```
phone ──https──▶ home router :443 ──▶ du7 :443 on its LAN address (Caddy, TLS) ──▶ 127.0.0.1:8088 (pauta)
```

| What | Where |
|---|---|
| DNS | Squarespace, `genic.dev` → DNS → custom record `pauta`: a CNAME to the dynamic-DNS name the router keeps on the home IP, TTL 1 hr. Editing it asks for the account passkey |
| Router | the existing TCP 443 forward to du7 (shared with du7's other sites; nothing new) |
| Caddy | `/etc/caddy/Caddyfile`, the `pauta.genic.dev` block from `deploy/Caddyfile.pauta`. Certificate via TLS-ALPN on 443 |
| Code | `/opt/pauta/releases/X.Y.Z/` (a venv per release, owned by `pauta`), `/opt/pauta/current` → the live one |
| DB of record | `/var/lib/pauta/pauta.db` (`PAUTA_STATE_DIR`, `pauta` only): accounts, passkeys, invites, clients, requests |
| Backups | nightly 03:40 (`pauta-backup.timer`) → `/var/backups/pauta`, then `pauta-backup-nas.service` copies the newest to the NAS (`/media/nas/backups/pauta`, exFAT, so as its owner, never root; `deploy/pauta-nas-copy` only takes regular files owned by `pauta`), 30 days each; before every deploy → `/var/backups/pauta/pre-deploy`, 90 days. The `pauta` group (the owner is in it) sees their ages, not their contents |
| Units | `/etc/systemd/system/pauta.service`, `pauta-backup.{service,timer}`, `pauta-backup-nas.service` (copies of `deploy/`), sandboxed: own user, read-only system, no `/home`, no network but loopback (the backups: none), no other users' processes, the usual system calls only, writes only to the data and backup dirs |
| Deploys | `/usr/local/sbin/pauta-deploy` (copy of `deploy/pauta-deploy`), log in `/opt/pauta/deploy.log` |
| Runner | GitHub Actions self-hosted runner `du7` (labels `du7`, `pauta`) in `/opt/pauta-runner/actions-runner` (root's; its own user `pauta-runner` writes only `_work` and `_diag`), unit `actions.runner.eduelias-pauta.du7.service`. No other repository's runner may run as `pauta-runner` (it may `sudo pauta-deploy`); dominion-archive's runs as `gh-runner`; every job first passes `/usr/local/lib/pauta/runner-job-guard` (drop-in `job-guard.conf`) |

## Releasing

Releases are the only way code reaches du7. On the Mac, with `main` clean and pushed and the
changes described under **Unreleased** in `CHANGELOG.md`:

```
make release V=1.2.0
```

That runs `scripts/release.py cut 1.2.0 --push`. It refuses unless CI passed on `main`'s
commit and there is no `uv.toml`, lists every commit since the last tag that isn't entirely
the owner's (type the version to go on; set `git config --add pauta.ownerEmail <address>`
for each address you commit with), moves the Unreleased notes into 1.2.0, bumps
`pyproject.toml` and `uv.lock` (by hand: it never runs uv on the checkout), commits "Release
1.2.0", tags `v1.2.0` and pushes both. The tag starts `.github/workflows/release.yml`:

1. **CI**: lint, tests on Python 3.11–3.13 with coverage, browser tests, dependency audit;
   then the wheel and lockfile are built (no cache, no `uv.toml`), hashed and uploaded before
   any of their code runs, and a separate job installs and starts them (`/healthz`).
2. **Publish**: checks the tag, `pyproject.toml` and `CHANGELOG.md` agree, and creates the
   GitHub release with the CHANGELOG notes, the wheel, the sdist, `requirements.lock`
   (runtime dependencies pinned by hash) and `SHA256SUMS`, checks the published files are the
   built ones, and (once the repo is public) attests their build provenance.
3. **Deploy** (`deploy.yml`): on du7, after the job guard has checked that the owner pushed
   the tag, takes this run's own build (the `dist` artifact, not the release page) and runs
   `sudo pauta-deploy 1.2.0 <wheel> <lockfile> <wheel sha256> <lockfile sha256>`, with the
   sha256s the build job computed. pauta-deploy
   - copies both files into a root-owned directory and refuses them unless they match those
     sha256s and the wheel's metadata says `pauta 1.2.0` (nothing from it runs before the
     switch),
   - builds `/opt/pauta/releases/1.2.0` as `pauta` (binary wheels only, every hash checked,
     PyPI only),
   - backs up the DB with the system Python (the new code never touches it before the switch),
   - points `/opt/pauta/current` at the new release and restarts `pauta`,
   - waits for `/healthz` to report 1.2.0, and **switches back to the old release** if it
     doesn't (the job then fails),
   - keeps the last 5 releases.
4. **Reachable from the internet**: a GitHub-hosted runner fetches
   https://pauta.genic.dev/healthz and expects 1.2.0.

The `production` environment on GitHub only accepts deploys from `v*` tags and `main`, and
lists every deploy under the repo's *Deployments*. Once the repo is public, each deploy also
waits for the owner's approval there. A tag whose release already exists (made by anyone
else) fails at Publish.

## Rolling back

- A release that is still on du7 (`pauta-deploy --status` lists them; the last 5 are kept):
  GitHub → Actions → **Deploy** → *Run workflow* on `main` → the version. Only the owner's run
  passes the job guard. This is also how to redeploy a release whose run is older than 30
  days: re-running that release's du7 job fails once its build artifact has expired.
  Anything no longer on du7 is not reinstalled from the release page: cut a new release from
  the old code instead.
- Straight on du7, to the release before the current one: `sudo pauta-deploy --rollback`.
- What's live: `sudo pauta-deploy --status`.

Schema changes are additive (new tables and columns), so an older release runs on a newer
database. If one ever isn't, restore the matching file from `/var/backups/pauta/pre-deploy`
(stop `pauta`, copy it over `/var/lib/pauta/pauta.db` as `pauta`, start `pauta`).

## Setting up du7 (once)

Done on 2026-10-28; repeat only to rebuild du7. From the Mac, copy `deploy/` to du7, then on
du7 (the runner version and sha256 are on https://github.com/actions/runner/releases):

```
gh api -X POST repos/eduelias/pauta/actions/runners/registration-token --jq .token > token   # on the Mac, then copy it over
sudo deploy/provision-du7.sh 2.338.2 <sha256 of actions-runner-linux-arm64-2.338.2.tar.gz> token
```

It creates the `pauta` user (and, once, moves the DB and backups from the owner's home to
`/var/lib/pauta` and `/var/backups/pauta`, keeping the old copy as `*.moved-DATE`), installs
`pauta-deploy`, the units, a sudo rule letting `pauta-runner` run
`/usr/local/sbin/pauta-deploy` (and nothing else) as root, retires pauta's old runner that
ran as the shared `gh-runner` (once), installs or updates the runner, registers it (with self-update
off) when needed, gives its files to root, and installs the job guard. Run it again after
any change to `deploy/` and to update the runner: it doesn't update itself, and GitHub stops
sending jobs to a runner more than 30 days behind its latest release. The token is only
needed when the runner must register (the first time, and once to turn self-update off).

For a first release on a fresh du7, check where its files came from before installing them:
the release page alone proves nothing (a collaborator can replace its files). Download the
wheel and lockfile of a release and verify them against the release workflow's signed
provenance (public repo), then install with their sha256s:

```
gh attestation verify pauta-X.Y.Z-py3-none-any.whl -R eduelias/pauta \
    --signer-workflow eduelias/pauta/.github/workflows/release.yml
gh attestation verify requirements.lock -R eduelias/pauta \
    --signer-workflow eduelias/pauta/.github/workflows/release.yml
sudo pauta-deploy X.Y.Z "$PWD/pauta-X.Y.Z-py3-none-any.whl" "$PWD/requirements.lock" \
    "$(sha256sum pauta-X.Y.Z-py3-none-any.whl | cut -d' ' -f1)" "$(sha256sum requirements.lock | cut -d' ' -f1)"
```

(While private there is no provenance: build the tag yourself, `uv build` and `uv export
--no-dev --no-emit-project --format requirements-txt -o dist/requirements.lock`.) Then append
`Caddyfile.pauta` to the Caddyfile and `systemctl reload caddy`. Caddy's global block must keep
its admin API off TCP (`admin off`, or `admin unix//run/caddy/admin.sock`): the app may talk
to loopback, and an admin API on 127.0.0.1:2019 would let it rewrite Caddy's config.

The runner only takes jobs for this repo (labels `du7`, `pauta`), runs as a user with no
shell and no groups, and owns nothing but its work and log directories: its home, code,
`.env`, `.path` and unit are root's (the unit is `deploy/pauta-runner.service`, not the
runner's `svc.sh`). Its job-started
hook, `/usr/local/lib/pauta/runner-job-guard`, refuses every job except `du7` of
`release.yml` on a `vX.Y.Z` tag and `du7` of `deploy.yml` run by hand on `main`, each only
when the owner started (and re-ran) it; refusals are in `journalctl -t pauta-runner-guard`.

### If the runner won't start

`provision-du7.sh` stops with the runner's last log lines. If a runner release wants to write
somewhere new in its own directory, give that path to `pauta-runner` and add it to the script;
as a stopgap, `sudo chown -R pauta-runner: /opt/pauta-runner/actions-runner && sudo systemctl
restart actions.runner.eduelias-pauta.du7.service` brings it back (and undoes the lock-down
until the next run of the script).

## Collaborators

Collaborators work through pull requests (`CONTRIBUTING.md`); what they can do, and what
keeps it away from du7, is decision 2. The GitHub side is `scripts/repo-settings.sh`. Invite
nobody before step 4; in this order:

1. Merge the change that brought this section. From then until step 2, release deploys stop
   at the du7 step (du7's old pauta-deploy takes no hashes), saying so.
2. At home, on du7, from a fresh copy of `deploy/` and with a runner registration token
   (see "Setting up du7"): `sudo deploy/provision-du7.sh <runner version> <sha256> token`.
   It needs the token because the runner moves to its own user. Then update
   `~/du7-watchdog.py`'s `pauta-backup` check to `/var/backups/pauta` (the owner can list
   it: they are in the `pauta` group).
3. Check it:
   - `systemctl show actions.runner.eduelias-pauta.du7.service -p Environment` names the
     guard, and `sudo cat /opt/pauta-runner/actions-runner/.env` does too;
   - `sudo pauta-cli users` lists the accounts (the DB moved);
   - Actions → Deploy → Run workflow on `main` with the live version deploys, and its du7
     job log shows `runner-job-guard: … may deploy`;
   - the guard refuses what it should: push a branch `guard-test` whose workflow runs
     `echo hi` with `runs-on: [self-hosted, du7, pauta]`; its job must fail before the step,
     with `refusing this job on du7` (and a line in `journalctl -t pauta-runner-guard`).
     Delete the branch after.
4. On the Mac: `PAUTA_ALERTS_WA_TOKEN_REF='op://…' scripts/repo-settings.sh secrets` (the
   WhatsApp secrets into the `alerts` environment; ideally a token of its own, see "Monitoring
   and alarms"). Make the repository public (Settings → General → Danger Zone), then
   `scripts/repo-settings.sh apply` and `scripts/repo-settings.sh show`.
5. `scripts/repo-settings.sh invite <github login>`: it refuses until the rulesets are on, the
   WhatsApp secrets are out of the repository, releases are immutable and a deploy shows the
   guard. Ask him to open a small PR that touches `Makefile`: it must wait for the owner.

While private, `apply` already sets what it can (forks run no workflows at all) and lists the
rest as `later`.

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
API (`scripts/alert.py`, secrets `WA_TOKEN`, `WA_PHONE_ID`, `WA_TO` in the `alerts`
environment, which only `main` and release tags reach; optional variable `WA_TEMPLATE`).
Today that token is famulus's; a token of its own (a Meta system user allowed only to send
messages on that number) limits what a leak could do, and is what `repo-settings.sh secrets`
asks for. On du7 the watchdog posts `{"text", "alert"}` to its local wa-notify service, which
sends the same template.

To try the alarm: pause healing (`echo $(( $(date +%s) + 1800 )) > ~/.du7-watchdog-off`),
`sudo systemctl stop pauta`, run `python3 ~/du7-watchdog.py` four times (strikes, then the
escalation), and `sudo systemctl start pauta`; the next run posts "recovered" to IRC.

## People

- The first admin: on du7, `sudo pauta-cli invite --admin` prints a link (7 days, one
  person). The first account is always an admin.
- `pauta-cli` (deploy/pauta-cli) runs the live release's `pauta` command as `pauta` in a
  transient, sandboxed systemd unit. Don't run `/opt/pauta/current/bin/pauta` directly with
  `sudo -u pauta`: that runs release code on your terminal (and bookworm's sudo doesn't
  default to `use_pty`; add `Defaults use_pty` to sudoers to be safe), with the network and
  without the service's sandbox.
- After that, admins invite from the app: Equipe → Convidar alguém (QR code, link, WhatsApp).
- `sudo pauta-cli users` lists accounts. Admins disable people or make them admin on the Equipe page.
- A lost phone: sign in on another device that has a passkey (iCloud/Google sync them), or
  ask an admin for a fresh invite and disable the old account. Disabling ends every session
  the account had; "Sair em todos os aparelhos" does the same for your own account.
- Sign everyone out (a leaked cookie, a suspicion): delete
  `/var/lib/pauta/pauta.db.session-key` and `sudo systemctl restart pauta`. The key is
  never in the DB or its backups; a missing key file is simply made again.
- The team always keeps one active admin. If the only admin loses access, make a new admin
  invite with the CLI command above.

## Taking it offline

`sudo systemctl stop pauta` takes it offline; remove the Caddy block and the `pauta` DNS
record to undo it completely. The DB stays in `/var/lib/pauta`. To retire the runner:
`sudo systemctl disable --now actions.runner.eduelias-pauta.du7.service`, delete that unit
file, `/opt/pauta-runner` and `/etc/sudoers.d/pauta-runner`, and remove it under the repo's
Settings → Actions → Runners.
