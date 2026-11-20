# 4. A domain of its own: pauta.cc

- **Status:** accepted (2026-10-31). The owner bought **`pauta.cc`** and **`pauta.team`** at
  Cloudflare on 2026-10-31; both are delegated to the same Cloudflare account as `du7.dev`.
  Revised the same day: the app on `app.pauta.cc`, the public site on `www.pauta.cc`.
  Shipped: 1.6.0 put the app on the apex; the hosts below came with 1.6.1 (eduelias/pauta#18).
  Acceptance is on `acc.pauta.cc` since 2026-10-31. The team is moving.
- **Blocks:** decision 5 (other teams) and decision 6 (billing). Decision 1 (acceptance)
  moves with it (`acc.pauta.cc`).
- **2026-11-20:** the code differs: passkeys from before the move are not stamped with
  `pauta.genic.dev`. `passkey.rp_id` stays empty until the passkey next signs in, so "who
  has moved" lists only the domains seen since.

## Context

Pauta lives at `pauta.genic.dev`, a subdomain of an unrelated name. That was fine for one
team. Two things make it worth moving before anyone else joins:

- **Passkeys are bound to their domain** (the WebAuthn RP ID, `PAUTA_RP_ID`). A passkey made
  on `pauta.genic.dev` never works anywhere else. Moving later means every person in every
  team makes a new passkey at the same time. Today that is three people.
- **Paddle approves the seller's website domain** before it takes payments (decision 6), and
  customers see that domain on their statement and receipts.

The `.com`, `.com.br`, `.app`, `.io`, `.co`, `.dev` and `.ai` names for `pauta` are taken.
Of the free ones, the owner bought `pauta.cc` (short to type and to read out on WhatsApp)
and `pauta.team` (says what it is).

## Decision

| Topic | Decision |
|---|---|
| Hosts | **`app.pauta.cc`**: the app. **`acc.pauta.cc`**: acceptance (decision 1). **`www.pauta.cc`**: the public site (landing page, prices, terms, checkout for decision 6); until it exists, a temporary redirect to the app. **`pauta.cc`**, **`pauta.team`** and `www.pauta.team`: a 301 to `www.pauta.cc`. Old `pauta.cc/#/...` links still reach the app: a fragment survives redirects |
| Passkey RP ID | `pauta.cc`, the parent of every host, so the app could move between subdomains without anyone making a new passkey. Production only accepts the origin `https://app.pauta.cc`, so a page on `acc.` or `www.` can't sign in to it even though a browser would let it ask for a `pauta.cc` passkey. Acceptance keeps its own RP ID (`acc.pauta.cc`) |
| Registrar | Cloudflare, bought in the dashboard. Auto-renew and the registrar lock are switched on there: the Terraform/OpenTofu provider has no registrar resource, and the Registrar API (beta, 2026) can register but not renew |
| DNS | Code in `du7/dns-zone` (OpenTofu), like `du7.dev`: an `import` block for each zone (Cloudflare created them at purchase), then the records. `pauta.cc`, `app.`, `acc.` and `www.` are a CNAME to `du7.sytes.net` (flattened at the apex), **DNS-only**: Cloudflare's free proxy caps request bodies at 100 MB while Pauta takes 200 MB uploads in one request, and the rate limits rely on the client address Caddy passes on. A CAA record for the CAs Caddy uses. Neither domain sends mail, so each gets a null MX, `v=spf1 -all` and a DMARC `p=reject` so nobody can send mail as them |
| Certificates | Caddy on du7, as today (TLS-ALPN on 443; works because the records are DNS-only) |
| Moving the current team | A "move to pauta.cc" hand-off instead of new invites (an invite always makes a *new* account, and a session cookie is host-only, so nobody is signed in on the new domain). On the old address, a banner and a button "Mudar para app.pauta.cc": Pauta makes a one-time token for that account (10 minutes, single use), sends the person to `https://app.pauta.cc/#/mudar/<token>`, they make a passkey there with Face ID or a fingerprint, and are signed in. Accounts, requests and history stay; only the passkeys are new. The same link, made by an admin, later serves "perdi meu celular" |
| The old address | Keeps working unchanged until everyone has moved, then becomes a 301 to `app.pauta.cc` for at least a year (old links sit in WhatsApp chats), then goes |

## The move, step by step

1. **DNS** (`dns-zone`, ~1 hour, no effect on anyone): `pauta.tf`, one file for both
   zones, with the imports and records above. `tofu plan`, then `apply`.
2. **Code** (one PR, ~1 day, owner review: `auth.py`, `deploy/`):
   - `PAUTA_RP_ID` and `PAUTA_ORIGIN` accept more than one domain during the move; the RP ID
     for a ceremony is the configured one that the request's origin belongs to.
   - `passkey.rp_id` (additive column; existing rows get `pauta.genic.dev`), so Pauta knows
     who has moved: `pauta users` and the Equipe page (now Configurações → Time) show it.
   - The hand-off token, the banner and the `#/mudar/` screen.
   - Every `pauta.genic.dev` in the repo becomes `pauta.cc`: `index.html` link-preview tags
     and `og.png` (`tools/render_images.py`), `pyproject.toml`, the CLI's `--base-url`,
     `deploy/` (unit, Caddyfile, README), the `deploy.yml`, `release.yml` and `uptime.yml`
     workflows, README, CLAUDE.md, CONTRIBUTING.md, SECURITY.md and the tests.
   - Tests: RP ID choice, the token (single use, expiry, bound to one account), and a browser
     test that moves an account between two `*.localhost` origins.
3. **du7** (~1 hour, with the release): Caddy blocks for `pauta.cc`, `acc.pauta.cc` and the
   redirects (mind the single-file bind mount: check that the container sees the new
   Caddyfile before reloading), the unit with both domains, then `make release`.
4. **The team moves** (a day of calendar time): a WhatsApp message to the three people:
   open Pauta, tap "Mudar para app.pauta.cc", confirm with Face ID, and add the new address to
   the home screen (an installed app belongs to its old address). Watch `pauta users`.
5. **Close the old address** once everyone has moved: `pauta.genic.dev` becomes a 301 to
   `app.pauta.cc` in Caddy; the unit drops the old RP ID and origin. Acceptance moves the same way
   (`acc.pauta.cc`, demo data, its software-passkey test account made again).
6. **Monitoring**: du7's watchdog `pauta*` checks, the GitHub uptime check, the repo's
   homepage link. OneDrive needs nothing (device-code sign-in has no redirect address).

Until step 5, nothing about the old address changes, so a rollback is the usual one: the
release before the move still runs (the new column is additive) and `pauta.genic.dev` still
works.

## Consequences

- About a day of code plus a couple of hours on DNS and du7; the team taps one button each.
- The hand-off stays as the "lost my phone" path, so it isn't throwaway code.
- Two domains to renew (auto-renew on both). `pauta.cc` is a ccTLD (Cocos Islands) run by
  Verisign; Cloudflare's Registrar API doesn't cover `.cc`, which doesn't matter for a
  domain bought in the dashboard.
- Cloudflare's security scan will keep flagging the DNS-only records as "unproxied"; that's
  deliberate (see DNS).

## Alternatives considered

- **Stay on `pauta.genic.dev`:** free, but every later move costs every customer a new
  passkey, and Paddle's domain review would look at an unrelated `genic.dev`.
- **The app on `pauta.team` (or `app.pauta.team`):** the first plan. `pauta.cc` is shorter to
  type on a phone, and one domain for the app and the public site is simpler; `pauta.team`
  redirects.
- **The app on the apex `pauta.cc`** (1.6.0): shortest, but the apex is where people and
  Paddle's review look for the public site, so the app went to `app.`. The passkeys made in
  between kept working, being for `pauta.cc`.
- **Keep the old RP ID and allow the new origin** (WebAuthn related origins): no
  re-enrollment, but Pauta would be tied to `genic.dev` forever, and browser support is
  still uneven.
- **Proxy through Cloudflare:** hides du7's address and adds DDoS protection, but the 100 MB
  upload cap and the client-address handling make it a separate decision, best taken with
  the move off du7 (decision 5).
- **A new name** (2026-10-31, about 90 names checked by RDAP/WHOIS): *Esteira*, *Tabelinha*,
  *Toca o Job*, *Briefei*, and `pauta.nl`. Kept Pauta: the team already knows it.
- **A `.com.br`:** every good `pauta*.com.br` is taken.
