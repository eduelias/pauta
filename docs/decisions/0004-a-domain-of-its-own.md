# 4. A domain of its own

- **Status:** proposed (2026-10-30). The owner picks and buys the domain; nothing is built
  until then.
- **Blocks:** decision 5 (other teams) and decision 6 (billing). Decision 1 (acceptance)
  should be built on the new domain directly.

## Context

Pauta lives at `pauta.genic.dev`, a subdomain of an unrelated name. That was fine for one
team. Two things make it worth moving before anyone else joins:

- **Passkeys are bound to their domain** (the WebAuthn RP ID, `PAUTA_RP_ID`). A passkey made
  on `pauta.genic.dev` never works anywhere else. Moving later means every person in every
  team makes a new passkey, on an invite link, at the same time. Today that is three people.
- **Paddle approves the seller's website domain** before it takes payments (decision 6), and
  customers see that domain on their statement and receipts.

The `.com`, `.com.br`, `.app`, `.io`, `.co`, `.dev` and `.ai` names for `pauta` are taken
(checked 2026-10-28). These still showed no registration on 2026-10-30 (RDAP):

| Domain | For | Against |
|---|---|---|
| **pauta.team** | Says what it is; room for `<team>.pauta.team` later | ~US$30/year; `.team` is less familiar in Brazil |
| pauta.so | Short, notion.so feel | ~US$50–80/year |
| napauta.app | "Tá na pauta" is natural Portuguese; cheapest (~US$15/year) | Reads oddly to non-Portuguese speakers; two words |

Prices are rough; the registrar shows the real one.

## Decision

| Topic | Decision |
|---|---|
| Domain | **`pauta.team`**, unless the owner prefers `napauta.app` for the Portuguese reading |
| Registrar and DNS | Cloudflare (sold at cost). DNS there lets du7's Caddy image (`du7/caddy-cloudflare`) get certificates by DNS challenge, which wildcard subdomains would need later |
| Hosts | `pauta.team`: the public site (landing page, prices, terms, privacy, refunds, checkout page). `app.pauta.team`: the app. `acc.pauta.team`: acceptance (decision 1) |
| Passkey RP ID | The apex, `pauta.team`, not the app host. A passkey made on `app.pauta.team` with RP ID `pauta.team` keeps working if teams later get their own subdomains. Acceptance keeps its own RP ID (`acc.pauta.team`) so its passkeys can't sign in to production |
| The old address | `pauta.genic.dev` redirects to `app.pauta.team` for a year, then goes |
| Moving the current team | A new kind of link: a one-time "new passkey for this account" link (today an invite always makes a *new* account, and a signed-in person can only add a passkey on the domain they're on). An admin makes one per person on the old address; each opens theirs on the new one and makes a passkey there. Accounts, requests and history stay; only the passkeys are new. Done together with the migration in decision 5. The same link later serves "I lost my phone" |

## Consequences

- About a day: DNS, a Caddy block per host, `PAUTA_RP_ID`/`PAUTA_ORIGIN` in the unit, the
  redirect, and the re-enroll link (in `auth.py`, so it needs the owner's review).
- Everyone re-enrolls once. That is the cost of doing it now instead of with twenty teams.
- `.team` renews at roughly the same price yearly; the owner's registrar account becomes part
  of what keeps Pauta online (enable auto-renew and the registrar's lock).

## Alternatives considered

- **Stay on `pauta.genic.dev`:** free, but every later move costs every customer a new
  passkey, and Paddle's domain review would look at an unrelated `genic.dev`.
- **A `.com.br`:** needs a CPF or CNPJ (the owner's Brazilian ME has one), but every good
  `pauta*.com.br` is taken; `pautadotime.com.br` and similar are clumsy. Worth buying later
  as a redirect if Brazilian customers type it.
- **Teams on subdomains from day one** (`acme.pauta.team`): nicer, but needs wildcard
  certificates and DNS-challenge setup now. The RP ID choice above keeps it possible later.
