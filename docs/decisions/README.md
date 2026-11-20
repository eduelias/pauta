# Decisions

Short records of decisions about Pauta: the context, what was decided, and what it costs. One
file per decision, numbered in order; a later decision that changes an earlier one says so in
both files.

| # | Decision | Status |
|---|---|---|
| [1](0001-acceptance-environment.md) | An acceptance environment on du7, next to production (how builds reach it: decision 9) | Accepted; built by hand on 2026-10-29, outside a release. The release gate and the ribbon are not built |
| [2](0002-collaborators-and-a-public-repo.md) | Maintainers via PRs, owner-only releases, rulesets, a job guard on du7's runner, a public repo | Accepted; shipped in 1.3.0, du7's part included |
| [3](0003-request-files-in-onedrive.md) | Files on requests, stored in a team member's OneDrive through Pauta | Shipped in 1.4.0 |
| [4](0004-a-domain-of-its-own.md) | Move to `pauta.cc`: the app on `app.pauta.cc`, the public site on `www.pauta.cc`, `pauta.team` a redirect; a "Mudar para app.pauta.cc" hand-off for today's team; DNS as code in `dns-zone` | Accepted; shipped in 1.6.0 and 1.6.1. The old address is still open |
| [5](0005-other-teams.md) | Other teams: a control DB plus one SQLite file per team, team in the URL, invite-only beta, off du7 before the first outside team | Proposed |
| [6](0006-subscriptions.md) | Subscriptions sold by Du7 Technology Services through Paddle (Pix, Pix Automático, card); the Brazilian ME with Asaas as fallback | Proposed |
| [7](0007-financeiro.md) | Financeiro: a receivables ledger per client, with the team's conventions as settings | Shipped in 1.5.0 |
| [8](0008-campaign-tracking.md) | Campanhas (planned as "Acompanhamento"): every live campaign's numbers from Meta, with a daily "seen" mark per client | Shipped in 1.7.0, with Meta only. The manual list and the AI text were not built: see "As built" in the record |
| [9](0009-branch-deploys-to-acceptance.md) | Any branch on acceptance, by hand, by the owner, as its own user (amends 1) | Shipped; announced in 1.7.0 |
| [10](0010-perfil-e-configuracoes.md) | Perfil for the person (name, WhatsApp, passkeys, new-passkey link); Equipe becomes Configurações | Shipped in 1.7.0 |
| [11](0011-analytics.md) | Analytics: a first-party usage log inside the app, Plausible (cloud, EU) on the public site; no session replay | App part shipped in 1.8.1; site part proposed |
| [12](0012-public-report-link.md) | A public, expiring, read-only link to one campaign report for the client (amends 2: the first open page) | Shipped in 1.8.2; the lifetime is 5 days since 1.8.3 |
