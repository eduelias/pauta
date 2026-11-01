# Decisions

Short records of decisions about Pauta: the context, what was decided, and what it costs. One
file per decision, numbered in order; a later decision that changes an earlier one says so in
both files.

| # | Decision | Status |
|---|---|---|
| [1](0001-acceptance-environment.md) | An acceptance environment on du7, deployed from `main` | Accepted, not built |
| [2](0002-collaborators-and-a-public-repo.md) | Maintainers via PRs, owner-only releases, rulesets, a job guard on du7's runner, a public repo | Accepted; du7 part pending |
| [3](0003-request-files-in-onedrive.md) | Files on requests, stored in a team member's OneDrive through Pauta | Proposed (this PR) |
| [4](0004-a-domain-of-its-own.md) | Move to `pauta.cc` (bought, with `pauta.team` for the public site); a "Mudar para pauta.cc" hand-off for today's team; DNS as code in `dns-zone` | Accepted, not built |
| [5](0005-other-teams.md) | Other teams: a control DB plus one SQLite file per team, team in the URL, invite-only beta, off du7 before the first outside team | Proposed |
| [6](0006-subscriptions.md) | Subscriptions sold by Du7 Technology Services through Paddle (Pix, Pix Automático, card); the Brazilian ME with Asaas as fallback | Proposed |
| [7](0007-financeiro.md) | Financeiro: a receivables ledger per client, with the team's conventions as settings | Proposed (this PR) |
| [9](0009-branch-deploys-to-acceptance.md) | Any branch on acceptance, by hand, by the owner, as its own user (amends 1) | Proposed |
| [11](0011-analytics.md) | Analytics: a first-party usage log inside the app, Plausible (cloud, EU) on the public site; no session replay | Proposed |
