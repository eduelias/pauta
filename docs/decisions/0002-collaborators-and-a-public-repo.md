# 2. Collaborators, and a public repository

- **Status:** accepted (decided 2026-10-29, revised the same day after two reviews of the
  delivery chain). The repo-side parts are built; the du7 parts apply the next time du7 is
  reachable (deploy/README.md, "Collaborators").

## Context

Until now only the owner pushed to this repository. The team's lead will become a
collaborator so he (and his Claude) can make the changes the team needs without waiting for
the owner. That changes who can make code run, and where:

- **du7's self-hosted runner** runs whatever a workflow says. Anyone with write access can
  push a branch whose workflow targets it, start or re-run a workflow, and in a public repo
  a fork's pull request can target it too. The runner's user may `sudo pauta-deploy`.
- **Releases are editable.** On a personal account there is one collaborator role, with
  write access: it can create releases and replace the files of existing ones (immutable
  releases are not retroactive). pauta-deploy used to check a wheel against the release's
  own `SHA256SUMS`, so swapped files plus swapped sums would have installed, and the old
  check ran the new wheel (`pauta --version`) as `esaleh`, outside any sandbox.
- **The service ran as `esaleh`**, whose home holds SSH keys and other services' secrets;
  `ProtectHome=read-only` still let it read them.
- **Repository secrets** (the WhatsApp token) reach any workflow on any pushed branch.
- **Caches**: a push to `main` writes the uv cache that a release's build would restore.

The account is on GitHub Free: rulesets (branch protection), required reviews, environment
reviewers, secret scanning and private vulnerability reporting only exist for **public**
repositories. The history holds no secrets (gitleaks over every commit) and no client data.

## Decision

**What a collaborator can do on GitHub, and what keeps it from du7.** The collaborator role
on a personal repository can't be narrowed, so everything rests on du7 trusting only the
owner's runs and only bytes the owner's release run built:

| A collaborator can | What contains it |
|---|---|
| push branches, open and merge PRs | only `contrib/**` branches (the `branches` ruleset keeps every other branch the owner's and Dependabot's, so nobody slips a commit into a PR the owner merges with the bypass; the owner merges with `--match-head-commit`). `main` takes PRs with all CI checks green from GitHub Actions (`integration_id` 15368). CODEOWNERS is default-deny: only `src/pauta/`, `tests/`, `CHANGELOG.md` and `README.md` (minus sign-in, rate limits and the test passkey signer) are merged without the owner |
| add build or tool configuration (`uv.toml`, a new workflow, an index) | default-deny CODEOWNERS; `release.py cut` refuses while a `uv.toml` exists and never runs uv on the checkout (it edits `uv.lock`'s version itself); the build runs with `UV_NO_CONFIG` and a pinned hatchling |
| merge app code without review | it reaches du7 only in a release, and `release.py cut` lists every commit since the last tag that isn't the owner's and asks for the version again. CI hashes the build before any of its code runs. On du7 it runs as `pauta`: no `/home`, no network but loopback, no other users' processes, the usual system calls only, and its installed releases are root's |
| create or edit releases, swap their files | du7 never installs from the release page. A release run passes the sha256s of what *it* built straight to pauta-deploy, which installs this run's own artifact only if it matches. A run publishing a tag that already has a release fails |
| start Deploy by hand, re-run any job | the runner's job guard refuses every du7 job not started *and* (re-)run by the owner; a hand-started deploy can only switch to a release already installed on du7, its version is checked first, and only the owner's runs send the failure alert. Once public, the owner also approves each `production` deploy |
| approve a fork's workflow run | fork runs get a read-only token and no secrets, and the guard refuses them on du7 |
| create tags | not `v*`: the `release tags` ruleset leaves those to the owner, and releases are immutable once published |
| read secrets from a pushed branch | the WhatsApp secrets live in the `alerts` environment, which only `main` and `v*` reach |
| disable a workflow (say, Uptime), cancel or delete runs | accepted: it costs history and an outside check, not data. du7's own watchdog keeps watching |

On GitHub (`scripts/repo-settings.sh apply`, kept in the repo so it can be re-run and reviewed):

- **`main` ruleset**: no direct pushes, force pushes or deletion; a PR with all CI checks
  green from GitHub Actions; code owner review for the paths in `.github/CODEOWNERS`
  (CI, deploy, scripts, Makefile, sign-in, rate limits, the passkey test signer,
  dependencies and the coverage gate, CLAUDE.md, CONTRIBUTING.md, SECURITY.md, these
  decisions); stale approvals dismissed on new pushes; merge commits or squash.
- **`release tags` ruleset** and **immutable releases**.
- **Environments**: `production` (the du7 job; once public, the owner approves each deploy)
  and `alerts` (the WhatsApp secrets), both reachable only from `main` and `v*` tags. The
  alerts send with a WhatsApp token of their own if possible, not famulus's.
- **Actions**: GitHub's own actions plus `astral-sh/setup-uv` and `rhysd/actionlint`, each
  pinned to a full SHA; `GITHUB_TOKEN` read-only by default and unable to approve PRs; while
  private, forks run no workflows; once public, outside contributors' runs need approval.
  The build and the dependency audit use no cache.
- **Security**: Dependabot alerts and security updates, secret scanning with push
  protection, private vulnerability reporting, CodeQL.
- `repo-settings.sh invite` refuses until the rulesets are active, no WhatsApp secret is
  repository-wide, releases are immutable, and a deploy's log shows the du7 guard.

On du7 (`deploy/provision-du7.sh`):

- **Job guard** (`deploy/runner-job-guard`, root-owned, set by a root-owned systemd drop-in):
  only job `du7` of `release.yml` on a `vX.Y.Z` tag, or of `deploy.yml` started by hand on
  `main`, and only when `GITHUB_ACTOR` and `GITHUB_TRIGGERING_ACTOR` are the owner.
- **The runner is root's and has a user of its own**: `pauta-runner` (until now it shared
  `gh-runner` with dominion-archive's runner, so either repo's jobs could `sudo` the other's
  deploy script; dominion's runner needs the same treatment). A fresh install: its code,
  home, `.env`, `.path` and unit (`deploy/pauta-runner.service`) belong to root;
  `pauta-runner` can write only `_work` and `_diag`. It no longer updates itself;
  `provision-du7.sh` does.
- **pauta-deploy** works from `/`, runs Python isolated (`-I`), copies its inputs (no links
  followed) into a private root-owned directory before hashing them and installs from there,
  reads the version from the wheel's metadata, requires the build's sha256s, and hands each
  installed venv to root; `--activate` only switches to an installed release. The guard is
  the barrier: anything running as `pauta-runner` could still bring its own wheel and hashes.
- **A `pauta` user** runs the app and its backups (`/var/lib/pauta`, `/var/backups/pauta`),
  sandboxed as above; the nightly copy to the NAS (exFAT, writable only by the owner's uid)
  runs as the owner, never as root, and only takes regular files owned by `pauta`. The owner
  runs the CLI through `pauta-cli`, a transient sandboxed unit. This is the production half of decision 1's "own user".

## Consequences

- Order: merge; update du7 (needs a runner registration token once, to turn self-update
  off); check a deploy passes the guard; move the WhatsApp secrets; make the repo public
  and `apply`; invite (`invite` checks the rest). Nobody is invited before the guard is live.
- From the merge until du7 is updated, release deploys stop at the du7 step (du7's old
  pauta-deploy doesn't take hashes); it says so in the job.
- The runner has to be updated by hand (`provision-du7.sh` with the new version) within 30
  days of each runner release, or GitHub stops sending it jobs.
- The owner's releases still need only `make release`; any commit not entirely the owner's
  is shown first. Once public, each deploy also waits for the owner's approval.
- Going private again would switch the rulesets and environment reviewers off (Free).
- The commit history shows the owner's two e-mail addresses; rewriting it is the owner's
  call. `deploy/` no longer names du7's LAN address, its DNS name or its other services.
- The parked PR #8's decision (a guard for agent PRs) becomes 0003 if it's revived.
