# 1. An acceptance environment on du7

- **Status:** accepted (decided 2026-10-28). Built by hand on 2026-10-29, outside a release;
  on `acc.pauta.cc` since 2026-10-31. Builds reach it through decision 9 (announced in 1.7.0).
- **Depends on:** the domain choice, settled by decision 4: `acc.pauta.cc`.
- **Amended by:** decision 9: acceptance takes builds of any branch, started by
  hand by the owner, through `pauta-deploy-branch` instead of `pauta-deploy`; deploying `main`
  on every merge is not built.
- **Amended by:** decision 8: one real client's ad account, unnamed and with no
  contacts, may live on acceptance for testing the Meta integration.
- **Amended by:** decision 5 (proposed): the "separate host" alternative below becomes the
  plan for production; acceptance stays on du7.
- **2026-11-20:** not built as of 1.15.1: the release gate (a tag deploys to production only
  if that commit is healthy on acceptance); the "ACEITAÇÃO" ribbon, title and theme colour
  (`PAUTA_ENV`); production's own `pauta` user (it runs as `esaleh`); and, in this repo, any
  watching of acceptance (the uptime check probes production only).
- **2026-11-20, later:** production's own `pauta` user is built in the repository: the unit
  and its backup run as `pauta` with the state in `/var/lib/pauta` and no `/home`,
  `deploy/provision-du7.sh` moves the state there once, and `pauta-deploy` refuses to deploy
  while the unit runs as anyone else. du7 runs it from the day that script is run there
  (`deploy/README.md`, "Production's own user"). The rest of that list is still not built.

## Context

Pauta has one environment: production at https://pauta.genic.dev, deployed from tagged
releases by the self-hosted runner on du7 (`deploy/README.md`). Changes are tested by CI,
including browser tests, but nobody can try a change on a real server before it reaches the
team. With more requests coming from the team and possibly other teams later, we want a place
where the people who asked for a change can check it before it's released.

## Decision

Run an acceptance environment on du7, next to production, deployed from `main`:

| Topic | Decision |
|---|---|
| Address | `acc.pauta.cc` (decision 4; first planned as `acc.pauta.genic.dev`): a CNAME to `du7.sytes.net` and its own Caddy block |
| Process | A second sandboxed unit, `pauta-acc`, on `127.0.0.1:8089`, with its own state dir and `/opt/pauta-acc`. It runs as a dedicated `pauta-acc` user so code that isn't released yet can't read production data. Production moves to its own `pauta` user at the same time (it runs as `esaleh` today) |
| Deploys | `pauta-deploy` takes the environment as an argument, with the sudo rule updated to match. A merge to `main` → CI → deploy to acceptance. A tag `vX.Y.Z` deploys to production only if that commit is deployed and healthy on acceptance (checked through GitHub Deployments). A manual approval click would need GitHub Pro for a private repo; until then the gate is "green on acceptance" plus a person running `make release` |
| Data | Demo data (`pauta demo`), never a plain copy of production: production holds the team's clients' contacts (LGPD). If realistic volume is needed, add a refresh that copies production and anonymises names, phones, links and comments first |
| Accounts | Passkeys are tied to their domain, so acceptance has its own accounts and invites. Nobody tests on production by accident |
| Visual difference | `PAUTA_ENV=acc` shows an "ACEITAÇÃO" ribbon, a different title and theme colour, and its own `noindex` |
| Monitoring | Watched like production, but alerts at a lower priority |

The working agreement it enables: merge → the person who asked checks it on acceptance → release.

## Consequences

- About a day of work: a templated unit, an environment-aware `pauta-deploy`, a `deploy.yml`
  job for `main`, the release gate, the ribbon, Caddy and DNS (the Squarespace record needs the
  owner's passkey). What exists instead (decision 9): a unit file of its own
  (`deploy/pauta-acc.service`), an installer of its own (`deploy/pauta-deploy-branch`) and a
  workflow started by hand; no job for `main`.
- du7 runs two copies of Pauta: a little more memory (about 30 MB), and two of everything to
  keep healthy.
- Production's deploys get one more prerequisite, so a broken acceptance deploy blocks
  releases until it's fixed or the gate is bypassed deliberately.

## Alternatives considered

- **A separate host for acceptance:** better isolation, but more cost and upkeep for a team
  this size. Revisit if Pauta moves to a VPS for multi-team hosting; acceptance would then
  live there too.
- **Preview environments per pull request:** nice, but too much machinery for a single Pi.
- **Release candidates (`vX.Y.Z-rc.N`) deployed to acceptance:** keeps acceptance stable
  between merges, but adds a step to every change. Continuous deploys from `main` are
  simpler; revisit if acceptance becomes too unstable for the team to test on.
