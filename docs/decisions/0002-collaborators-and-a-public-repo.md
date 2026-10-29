# 2. Collaborators, and a public repository

- **Status:** accepted (decided 2026-10-29). The repo-side parts are built; the du7 parts
  apply the next time du7 is reachable (deploy/README.md, "Collaborators").

## Context

Until now only the owner pushed to this repository. The team's lead will become a
maintainer so he (and his Claude) can make the changes the team needs without waiting for
the owner. That changes who can make code run:

- **du7's self-hosted runner** runs whatever a workflow says. Anyone with write access can
  push a branch whose workflow targets it, and in a public repo so can a pull request from
  a fork. The runner's user may `sudo pauta-deploy`, which installed any wheel it was
  handed; the service runs as `esaleh` and holds the clients' data.
- **Repository secrets** (the WhatsApp token) reach any workflow on any pushed branch.
- **Tags deploy**: pushing `vX.Y.Z` releases and deploys.

The account is on GitHub Free: rulesets (branch protection), required reviews, secret
scanning and private vulnerability reporting only exist for **public** repositories. The
history holds no secrets (gitleaks over every commit) and no client data (only example
names, numbers and addresses), so going public is the way to get them.

## Decision

| Who | May |
|---|---|
| Owner (admin) | everything; bypasses the rulesets (releases push a commit to `main`) |
| Maintainer | branch, open and merge PRs once CI is green; a PR touching an owned path also needs the owner's approval. No settings, secrets, environments, rulesets or release tags |
| Anyone else | fork and open PRs; their workflows only run after the owner approves the run |

On GitHub (`scripts/repo-settings.sh apply`, kept in the repo so it can be re-run and reviewed):

- **`main` ruleset**: no direct pushes, force pushes or deletion; a PR with all CI checks
  green; code owner review for the paths in `.github/CODEOWNERS` (CI, deploy, scripts,
  Makefile, sign-in, rate limits, the passkey test signer, dependencies and the coverage
  gate in `pyproject.toml`, CLAUDE.md, CONTRIBUTING.md, SECURITY.md, these decisions).
  Stale approvals are dismissed on new pushes. Merge commits or squash, no rebase.
- **`release tags` ruleset**: only the owner creates, moves or deletes `v*` tags, so only
  the owner releases and deploys. **Immutable releases**: a published wheel and its
  `SHA256SUMS` can never be swapped.
- **Environments**: `production` (the du7 job) and `alerts` (the WhatsApp secrets) only run
  from `main` and `v*` tags. The WhatsApp secrets move from the repository into `alerts`,
  so a pushed branch can't read them.
- **Actions**: GitHub's own actions plus `astral-sh/setup-uv` and `rhysd/actionlint`, each
  pinned to a full SHA; the `GITHUB_TOKEN` is read-only by default and can't approve PRs;
  runs from outside contributors' forks wait for the owner's approval.
- **Security**: Dependabot alerts and security updates (version updates were already on),
  secret scanning with push protection, private vulnerability reporting, CodeQL.

On du7 (`deploy/provision-du7.sh`):

- **Job guard**: the runner's job-started hook (`deploy/runner-job-guard`, root-owned,
  enabled by a root-owned systemd drop-in) refuses every job except `du7` of `release.yml`
  on a `vX.Y.Z` tag and `du7` of `deploy.yml` run by hand on `main`. A branch, a pull
  request or a fork gets a failed job before any step runs.
- **Published releases only**: `pauta-deploy` fetches the release's `SHA256SUMS` from GitHub
  itself and refuses a wheel or lockfile that doesn't match it.

## Consequences

- The order matters: merge this, make the repo public and run `apply` and `secrets`, update
  du7, and only then invite the maintainer (`repo-settings.sh invite` asks). Until du7 is
  updated, the runner is unguarded: approve no fork runs and add nobody in between.
- `pauta-deploy` needs the release downloadable without a token, so du7 is updated *after*
  the repo is public (while private, deploys would stop with "can't fetch SHA256SUMS").
- The owner's own releases are unchanged (`make release`); every release still needs the
  owner, by design.
- Without Pro, going private again would switch the rulesets off.
- The commit history shows the owner's two e-mail addresses (work and personal), and
  `deploy/` shows du7's LAN address and paths. Neither is a credential.
- Proposal 0002 in the parked PR #8 (a guard for agent PRs) becomes 0003 if it's revived.
