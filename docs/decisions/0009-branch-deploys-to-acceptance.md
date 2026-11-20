# 9. Any branch on acceptance, by hand, as its own user

- **Status:** shipped and in use; announced in 1.7.0 (2026-11-01). Proposed 2026-10-31
- **Amends:** decision 1 (acceptance was to be deployed from `main` only, by `pauta-deploy`
  taking the environment as an argument). **Fits:** decision 2 (the runner's job guard, the
  sudo rule as the only way to root).
- **Changes:** adds `.github/workflows/deploy-branch.yml`, `deploy/pauta-deploy-branch`,
  `deploy/provision-branch-env.sh`, `deploy/pauta-acc.service` and a third rule in
  `deploy/runner-job-guard`. Nothing changes for production.

## Context

Acceptance (https://acc.pauta.cc, unit `pauta-acc`) exists since 2026-10-29, built by hand:
its own user, `/var/lib/pauta-acc`, `/opt/pauta-acc/releases/<version>` and a `current`
link. Every build on it so far was installed by hand. The next changes (the Meta connection
of decision 8 first) have to be tried on a real server with a real domain *before* they are
merged: passkeys, the OneDrive device code and Meta's login redirect only work on
`acc.pauta.cc`. Decision 1's "deploy `main` to acceptance on every merge" doesn't help with
that, and installing by hand doesn't scale and bypasses every check.

## Decision

| Topic | Decision |
|---|---|
| What | Any branch, tag or commit, chosen when the workflow is started: Actions → *Deploy branch to acceptance*, or `gh workflow run deploy-branch.yml -f ref=feat/x`. A `rollback` box switches back to the build before |
| Who | The owner only. The workflow file is `main`'s (CODEOWNERS), and the runner's guard lets its du7 job through only when the run was started, and any re-run triggered, by the owner |
| Build | On GitHub's machines, never on du7: the branch's code with a read-only token and no secrets. Version `X.Y.(Z+1).devN+gSHA` (next patch, run number, commit), a wheel, `requirements.lock` with hashes from the branch's `uv.lock`, `pip-audit`, and the same install-and-`/healthz` smoke test as a release |
| Install | `/usr/local/sbin/pauta-deploy-branch acc VERSION WHEEL LOCK SOURCE`, the runner's second sudo rule. It builds the venv as `pauta-acc` (binary wheels, hashes required, so nothing from the build runs), makes it root's so nothing running as `pauta-acc` can change it, reads the version from its metadata (the build's code first runs inside the unit's sandbox, after the switch), backs up the DB read-only to `/var/backups/pauta-acc`, switches `current`, restarts `pauta-acc`, waits for `/healthz` to report the version and switches back if it doesn't. It keeps 5 builds. `pauta-deploy-branch acc --rollback` and `--status` work on du7 too |
| Never production | The installer only knows the environments it lists (`acc`), and builds every path from that name: `/opt/pauta-acc`, unit and user `pauta-acc`, `/var/lib/pauta-acc`, port 8089. A second check refuses `/opt/pauta`, the `pauta` unit, the users `root`, `esaleh` and `pauta`, and port 8088 even if the list is edited badly. It never writes the state dir (the DB, `pauta.db.meta-secret`, the OneDrive token, the session key) |
| Isolation, checked every time | Before every deploy and rollback the installer asks systemd, not the repo: the unit runs as `pauta-acc`, that user is in no other group, the unit has `ProtectHome=yes` (or `tmpfs`), and it runs `/opt/pauta-acc/current/bin/pauta`. Any of these wrong: no deploy |
| Data | Decision 1 holds: demo data and accounts made on acceptance, never a copy of production. Decision 8's one test ad account is the only real business data, and has no contacts |
| More environments | `dev` is one line in `env_config`, a `deploy/pauta-dev.service`, a Caddy block, a choice in the workflow and `provision-branch-env.sh dev` |

## What this costs: acceptance runs unreviewed code

A release has been through CI, the owner's review of every outside change, and a tag only
the owner can push; `pauta-deploy` installs only the published, byte-for-byte files. None of
that applies here. Whatever the chosen branch contains, including a dependency it adds to
`uv.lock`, runs on du7 as `pauta-acc`. Today only the owner and the owner's own Claude
sessions write branches, so the realistic threats are a compromised dependency and a mistake,
not a person. What that code can and can't reach:

| | |
|---|---|
| **Can't** | Production's database, backups, session key or OneDrive token: they are in `/home/esaleh` (0700, and the unit can't see `/home` at all), or in `/var/lib/pauta` once decision 2's `pauta` user lands (0700, another user). Production's code: root's `/opt/pauta`. Root: `NoNewPrivileges`, no capabilities, no sudo rule for `pauta-acc`. The other builds of acceptance: root's after install |
| **Can** | Acceptance's own state: its demo DB and accounts, its session key, **the OneDrive it is connected to** (within the scope it was granted) and **the Meta app secret** in `pauta.db.meta-secret` (an app in development mode with `ads_read` only, decision 8). Keep acceptance connected to a test drive and treat that secret as acceptance-only: rotate it if a bad build ever ran |
| **Can, and shouldn't** | Everything on du7's network that trusts its callers: services on loopback and on `0.0.0.0` (production's own `/metrics` on 127.0.0.1:8088, which carries no personal data; wa-notify, which can send WhatsApp messages; **Caddy's admin API on 127.0.0.1:2019, which can rewrite what `app.pauta.cc` serves** and from there act in the team's sessions), the home LAN, and the internet. The unit's sandbox limits files, not the network: it must answer Caddy on loopback, so it can't simply be cut off from it |

So the trade-off is: acceptance's own secrets are exposed to every build put there (accepted:
that is what a test copy is for), and du7's network is exposed through loopback (not accepted
long-term). Until the follow-ups below are done, deploy only branches whose dependencies you
know, which is what the owner-only rule enforces.

Follow-ups, on du7 rather than in this repo, in order of value:

1. Caddy's admin endpoint on a root-only unix socket (`admin unix//run/caddy/admin.sock` in
   the global options) instead of 127.0.0.1:2019. This also protects production from every
   other local process, not just acceptance.
2. An egress filter for the `pauta-acc` user (nftables `meta skuid pauta-acc`): no LAN, no
   loopback except replies from port 8089, DNS and HTTPS to the internet only.
3. wa-notify and the other `0.0.0.0` services behind a token or on a unix socket.

Before anyone but the owner may deploy a branch (a maintainer, a coding agent), all three must
be done, and this decision revisited.

## Alternatives considered

- **Deploy `main` on every merge (decision 1 as written):** keeps unreviewed code off du7,
  but the changes that most need a real domain (sign-in, OneDrive, Meta) would have to be
  merged before they could be tried. Can still be added: a push to `main` could start this
  same workflow with `ref=main`.
- **`pauta-deploy` with an environment argument (decision 1 as written):** one script for
  both, but production's script would gain a mode that skips the published-release check,
  and a bug in the environment handling would reach production. A second script that can't
  name production is easier to review and to trust.
- **Build on du7:** the branch's build backend and `uv` would run on du7 as the runner user,
  before any check. Building on GitHub means only a wheel (no install-time code) arrives.
- **Release candidates (`vX.Y.Z-rc.N`) through the published-release path:** every check of a
  release, but a tag per try and a release page per experiment.
- **Containers for acceptance:** stronger network isolation (its own network namespace), but
  a second way of running Pauta on du7 to keep working. Revisit with the egress filter if
  that turns out awkward.
