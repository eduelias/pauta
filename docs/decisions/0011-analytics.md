# 11. Analytics: a usage log inside the app, Plausible on the public site

- **Status:** the app part is accepted (2026-11-03) and shipped in 1.8.1: the `usage` table,
  `POST /api/usage`, `track()` with the events below and `pauta usage` are in the app
  (retention 90 days, pruned by the nightly `pauta backup`; `pauta usage --disable` switches
  a team's log off). The owner
  confirmed the signals from the production journal and the `event` table by hand: screens
  and actions per person, where errors appear, how long the phone waits, and the same step
  repeated on several requests of one client (the report's "Repeated steps" line). The site
  part (Plausible) is still proposed: nothing is installed, no account exists.
- **2026-11-20:** the code differs: prop values are not from a fixed list. The keys are
  fixed per event; a value is any boolean, number or string cut at 64 characters, and
  `request_created.kind` carries the team's own name for the request kind.
- **2026-11-20:** not built as of 1.15.1: `pauta usage --team` (it waits for decision 5) and
  `--save`; the report reading the journal's server-side events; `docs/privacy/lia-usage.md`.
- **Depends on:** nothing for the app part. The site part needs decision 4's site (live) and,
  for the checkout goal, decision 6's `/assinar` page.
- **Fits:** decision 5 (one database per team, Du7 as *operador*; the usage rows live in the
  team's file and die with it) and decision 6 (the lead → team → paying team chain).
- **Changes:** adds a `usage` table and `POST /api/usage` to the app, a `pauta usage` report, a
  script tag on `www.pauta.cc`, and three paragraphs in the privacy policy. Decision 5's legal
  texts (privacy policy, DPA) gain a usage-data clause; see "Texts that must change".

## Context

Two questions, two audiences:

1. **How does the team use the app** (app.pauta.cc)? Which screens and actions get used
   (Pedidos, Quadro, Clientes, Financeiro, Campanhas, Configurações, Perfil), where people
   hesitate or hit errors (error toasts, 4xx), whether a request flows from open to done, how
   many clients get their "Visto hoje" each day, which features are dead, what device and
   viewport people have (mostly phones, installed as a PWA), and which API calls are slow.
   Today the only signals are `src/pauta/obs.py`'s request log (route pattern, status, ms,
   account id; never bodies, IPs or names) and `/metrics` (counters, p50/p95, failing routes),
   both built for a watchdog, not for product questions.
2. **Who comes to the public site** (www.pauta.cc, static, GitHub Pages) and what do they do:
   traffic source (WhatsApp links, Instagram, Google), sections read, clicks on "Chamar no
   WhatsApp" (the beta CTA) and later on the checkout at `/assinar`, conversion per campaign
   (UTM), country and language. The site today has no script beyond the hash redirect and
   its privacy page promises "não tem rastreadores, pixels nem ferramentas de análise".

Constraints the owner set, all of which the recommendation meets:

- Self-hosted or EU-hosted; LGPD-friendly: no third-party cookies, no cross-site tracking,
  IPs truncated or never stored, data identifiable to the team only.
- The app's CSP is `default-src 'self'`, no inline scripts, no CDN: nothing in the app may
  load a script from elsewhere unless this decision says so.
- A stdlib Python server and one vanilla-JS file; a footprint measured in tens of lines.
- Cheap at a handful of teams. The app will see tens of events per person per day; the site
  a few hundred pageviews a month during the beta.
- GitHub Pages serves static files only: the site can only run client-side code and talk to
  a hosted or self-hosted service.

Hosting facts checked on 2026-11-01: du7 is a **Raspberry Pi 5, 16 GB RAM, NVMe**, four cores,
~12 GB free, load ~1, already running Caddy, Immich (with its own Postgres), famulus, SearXNG
and the arr stack in Docker. The planned production box (decision 5) is a Hetzner CAX11 (2
vCPU ARM, 4 GB), which costs about €5.99/month since Hetzner's June 2026 increase (€10.49 for
the 8 GB CAX21); the "about €4" in decision 5 is the old price.

### Law, in short

- **Brazil (LGPD).** The ANPD's cookie guide (October 2022, interpretive, not a regulation)
  names *legítimo interesse* as an acceptable basis for analytics cookies such as audience
  measurement, and reserves consent for advertising and non-essential functionality. The
  2024 guide on legitimate interest wants a documented balancing test (*teste de
  balanceamento*): a legitimate purpose, necessity, the data subject's reasonable
  expectations, transparency and an easy way to object. So: first-party, aggregate,
  no-advertising measurement, named in the privacy policy, with an opt-out, **needs no
  consent banner**. Tools that identify people across sites, or feed advertising, do.
- **EU (GDPR + ePrivacy).** Storing or reading anything on the device (cookies, localStorage)
  needs consent unless strictly necessary. Cookieless tools that keep nothing on the device
  and only produce aggregates (Plausible, Umami, GoatCounter, Matomo in its "no consent"
  configuration) position themselves as exempt, following CNIL's audience-measurement
  exemption: first-party, aggregate, no personal data kept, transparency, opt-out, no sharing.
  Not every EU authority agrees on the details (daily-salted hashes are still a
  pseudonymisation step), so the record below says what each tool keeps.
- **The app is different from the site.** People in the app are signed in; Du7 is the
  *controlador* of their account data (name, passkey, session), per the current privacy
  draft. Logging which screens an account opened is processing of that same account data for
  product improvement: legitimate interest again, no consent, but it **must be in the
  privacy policy** and must stay pseudonymous (account id, never name) and retained for a
  fixed period. The team's clients' data (names, phones, ad accounts) is the team's, with Du7
  as *operador*: nothing from it may enter the analytics. That rules out session replay in
  the app without masking every text node, and even then it needs a line in the DPA.

### Sources

plausible.io/#pricing and /data-policy (fetched 2026-11-01); github.com/plausible/
community-edition (v3.2.1 README); posthog.com/pricing.md, /docs/self-host,
/docs/session-replay/privacy, /docs/privacy/gdpr-compliance; matomo.org/pricing and FAQs 157
and "without consent or cookie banner"; openreplay.com/pricing and
docs.openreplay.com/en/deployment/deploy-docker; developers.cloudflare.com/web-analytics and
its FAQ; umami.is docs via search (umami.is refused direct fetches from this environment);
goatcounter.com/terms and reviews (the hosted price page could not be fetched; verify);
ANPD "Guia orientativo: cookies e proteção de dados pessoais" (2022) and "Guia orientativo:
legítimo interesse" (2024), as summarised by Lefosse, Mattos Filho and Machado Meyer;
Hetzner price tables (bitdoze.com, October 2026). Prices are monthly, before tax, as
published on that date; verify before buying.

## The options

| Tool | Cost at our size | Hosting effort (du7 today, Hetzner later) | CSP and footprint | Privacy: cookies, identifiers, consent (BR / EU) | Replay / heatmaps |
|---|---|---|---|---|---|
| **A. Home-grown usage log** (`usage` table, `POST /api/usage`, `pauta usage` report, later an owner page) | €0. 1–2 days of code; a few MB per team per year | None: it is Pauta. Same deploy, same backup, same per-team file | **No CSP change**: same origin. ~60 lines in `app.js`, ~80 in the server, a CLI command | No cookie beyond the session. Account id (pseudonymous), screen, action, device class, ms. No IP, no names. Stays in the team's SQLite file, deleted with the team. Legitimate interest, no banner (BR, EU); privacy text needed | None (by design) |
| **B. Plausible Cloud** (Starter $9, Growth $14, Business $19 per month, 10k pageviews; 30-day trial, no free plan) | $9/month for the site. Funnels and custom properties need Business ($19) | None (SaaS). EU-only servers, Estonian company | Site: `script-src https://plausible.io`, `connect-src https://plausible.io` (or proxy it). Events without inline JS via `class="plausible-event-name=..."`. ~1 KB script | No cookies, no localStorage; visitor = hash(daily salt + site + IP + UA), salt deleted daily, raw IP and UA never stored. Claims no consent needed (GDPR, PECR, CCPA). LGPD: legitimate interest, name it in the policy | No replay, no heatmaps (a feature, here) |
| **B'. Plausible Community Edition** (self-hosted) | €0 software. Postgres + ClickHouse: ≥2 GB RAM recommended, needs NEON (fine on Pi 5 and Ampere). Funnels, revenue goals, SSO and the Sites API are cloud-only | On du7: fits (16 GB) as a Compose stack behind Caddy on `stats.pauta.cc`, an evening's work, plus upgrades. On a CAX11 next to Pauta: too tight; a CAX21 (€10.49) or a separate box | As B, with our own host instead of plausible.io. Ad blockers block it less when it is on our domain | As B, on our server | None |
| **C. Umami Cloud** (Hobby free: ~100k events/month, 6 months' retention; Pro $20/month, 1M events) | €0 at our size | None (SaaS). Hosting region: US by default; an EU option was not confirmed from here. Verify before choosing | `script-src` and `connect-src` for the Umami host. Events by attribute: `data-umami-event="..."`, no inline JS. ~2 KB | No cookies; visitor = hash(site, IP, UA, monthly salt). Reports in the product: funnels, retention, UTM, goals, journeys | None |
| **C'. Umami self-hosted** (MIT, Node + Postgres) | €0. ~300–500 MB RAM, a small Postgres | On du7: a two-container Compose stack, an evening. On a CAX11: fits next to Pauta if Pauta stays small | As C, on `stats.pauta.cc`. Could serve both the site and the app from one instance | As C, on our server, EU | None |
| **D. PostHog Cloud EU** (Frankfurt) | Free: 1M events and 5,000 replays per month; then $0.00005 per anonymous event, $0.005 per replay. No card needed | None (SaaS). Self-hosting is "officially unsupported" and wants 4 vCPU / 16 GB: not for du7 or a CAX11 | `script-src` and `connect-src https://*.posthog.com` (EU: `eu.i.posthog.com`), `worker-src blob:`. Nonce support exists. ~50–100 KB script with replay | Cookies/localStorage by default; a `cookieless_mode: "always"` exists. PostHog's own docs say to provide a consent mechanism. Identified events would tie a replay to an account. Heavier policy text; a US company with EU hosting (DPA, SCCs) | **Yes**, with `maskAllInputs` (default) and `maskTextSelector: "*"` to mask every text. Heatmaps too. The privacy cost is the point of the next section |
| **E. Matomo** (Cloud €29/month for 50k hits, Frankfurt; On-Premise free: PHP + MySQL) | €29/month, or €0 self-hosted with ~1 GB RAM and PHP/MySQL to maintain | On du7: doable, one more LAMP-ish stack. Heavier than B'/C' for what we need | `script-src`/`connect-src` for the Matomo host; `_paq.push(['disableCookies'])` and IP anonymisation of 2–3 bytes for the no-consent configuration | Can be configured to need no banner (no cookies, anonymised IP, no fingerprinting, first-party only). Default setup sets cookies | Heatmaps and replay are a paid premium plugin (not researched further) |
| **F. OpenReplay** | Self-hosted: 2 vCPU, 8 GB RAM, 50 GB, x86 only, ~17 services (Postgres, ClickHouse, Redis, MinIO, Kafka). Cloud: "Dedicated" from $199/month; a usage-based "Serverless" tier exists without a published price | Not on a Pi or a CAX11; it would need its own server | Script + connect host; large script | Replay is the product: everything on screen unless masked. Needs consent language and a DPA clause with the teams | **Yes**, that is what it is |
| **G. Cloudflare Web Analytics** (free, all plans) | €0 | None. The DNS is at Cloudflare but `www` is DNS-only (CNAME to GitHub Pages), so the automatic beacon does not apply: the **manual snippet works**, with `type="module"`, reporting to `cloudflareinsights.com/cdn-cgi/rum` | `script-src https://static.cloudflareinsights.com`, `connect-src https://cloudflareinsights.com` | No cookies, no localStorage, no fingerprinting (their statement). Unsampled data 7 days, then ~10% sample, six months of history | None. **No custom events, no UTM breakdown** ("not yet"), no outbound-link clicks: it cannot answer the lead questions |
| **H. GoatCounter** (EUPL, single Go binary; hosted free for non-commercial use, a paid Starter plan for commercial sites, ~€5/month per reviews; verify on goatcounter.com) | €0 self-hosted (~50 MB RAM); ~€5/month hosted | Self-hosted: the lightest option of all, one binary and SQLite, fits anywhere | `script-src` for `gc.zgo.at` and `connect-src`/`img-src` for the count endpoint. Click events via `data-goatcounter-click`. ~3 KB | No cookies; uniques come from a short-lived salted hash of IP and UA, kept only to count a visit once (verify the current help page). Built for exactly this. Campaigns via `utm_campaign`/`ref`; no funnels, no properties | None |

Not compared on purpose: Google Analytics 4 (cookies, cross-site, US; needs a banner),
Microsoft Clarity (free replay, but every screen goes to Microsoft; needs a banner and the
DPA clause), Fathom, Simple Analytics, Pirsch (similar to Plausible, nothing extra for us).

### Session replay and heatmaps: no, for now

Replay in the app records the team's clients' names, phones, briefs and amounts: data the team
controls and Du7 only processes on instruction. Recording it for Du7's own purpose (usability)
changes Du7's role for that data and needs the team's written agreement in the DPA, masking of
every text and input (PostHog: `maskTextSelector: "*"`, which also hides what you wanted to
see), and a privacy text that says screens are recorded. For a product with one team and one
developer who can watch the person who runs the campaigns ("the campaign runner" below) use it
over WhatsApp, that is a lot of machinery and risk for little. What replaces it in this
proposal: error toasts and slow calls as events (where people get stuck), a "screen → next
screen" count (where they wander), and usability sessions on **acceptance with demo data**,
where replay would be harmless. If a question ever needs replay, PostHog Cloud EU on acceptance
only, demo data only, is the cheap experiment, and this decision is revisited.

## Decision (proposed)

Two tools, one per audience, because the audiences and the law differ. Both can be swapped
without touching the other.

| Topic | Decision |
|---|---|
| **App: option A**, the home-grown usage log | Events are first-party, stay in the team's own SQLite file, need no CSP change, no account, no consent, and the questions we have (which screens, which actions, where it errors, how slow, which devices) are counts and percentiles SQLite answers in a line. A hosted product-analytics tool would give nicer charts at the cost of a script from another origin inside a passkey-protected app, a second copy of the team's usage data outside the team file, and a policy text naming a third party |
| **Site: option B**, Plausible Cloud Starter ($9/month) | EU-only, cookieless, no banner, a 1 KB script, outbound-link and UTM reports and tagged events out of the box, a public shareable dashboard for the campaign runner. GoatCounter (H) is the cheaper runner-up; Umami Cloud (C) is free but its hosting region must be confirmed first; Cloudflare (G) can't count the CTA or campaigns. If $9/month is not wanted, H or C' on du7 |
| Session replay, heatmaps | **No** (see above). Revisit only for acceptance with demo data |
| Who sees what | The owner: `pauta usage` (CLI) and Plausible. The campaign runner: Plausible's shared dashboard link for the site. Team members: nothing new; the privacy policy says what is logged |
| Data kept | App: 90 days of `usage` rows, pruned by the nightly backup unit's run; aggregates (`pauta usage --save`) kept as monthly JSON next to the backups if wanted. Site: whatever Plausible keeps (aggregates; no raw IP or UA) |
| What never enters the log | Names, phones, request text, client ids as free text, URLs with ids beyond the route pattern (`/api/requests/{id}` style, like `obs.route_label`), IP addresses, exact user agents. Props are from a fixed enum per event; the server drops unknown keys and truncates values at 64 chars |
| Opt-out | App: none per person (the data is the team's own, pseudonymous, and the purpose is the service); the policy says so and a team may ask Du7 to disable logging for its file (`setting usage.enabled=false`). Site: Plausible honours no cookie but the policy links Plausible's data policy; a `localStorage.plausible_ignore=true` opt-out line is in the policy |

### Option A in detail

| Part | What |
|---|---|
| Table | `usage(id, at TEXT, account INTEGER, event TEXT, screen TEXT, props TEXT, dev TEXT)` in the team's file, additive (schema +1). `dev` is a short fixed string, e.g. `phone/standalone/390x844/ios`, built client-side from `matchMedia('(display-mode: standalone)')`, `innerWidth`/`innerHeight` rounded to 10 px and the platform class, never the UA string |
| Ingest | `POST /api/usage` with `{events:[{t, e, s, p}]}`; the client batches events and flushes every 10 s, on `visibilitychange` and with `navigator.sendBeacon` on unload. Session required (so an event is always for an account), `Origin` check as every write, body cap 16 KB, 50 events per call, rate-limited per account. Quiet route like `/healthz`: not in the request log, not counted in `/metrics` |
| Client | One `track(e, p)` in `app.js`, called from `route()` (screens), the places that already call `toast()` with `err=true`, `api()` (duration and status for every call, kept only when > 1.5 s or 4xx/5xx), and a dozen named actions below. No new file, no inline script, no CSP change |
| Server-side events | Already there: `file_uploaded`, `auth_failed`, `rate_limited`, request log lines. They stay in the journal; the report joins them by day, not by account |
| Report | `pauta usage [--days 7] [--team slug]` (also `--enable` and `--disable`): active accounts per day; screens and actions over the whole window, by account; top error toasts (message class + screen); slow calls p95 by route (client-measured, includes the network, unlike `/metrics`); device mix (phone/desktop, standalone %, viewport buckets); and two product funnels from the product tables, no instrumentation needed: **open → done** (`request.created` to `done_on`, median and p90 days, by kind) and **Visto hoje coverage** (clients with live campaigns checked per day, from decision 8's `review` table). Dead features = events with zero rows in the window, listed by name |
| Later, if the CLI hurts | An owner-only `#/uso` page with the same numbers, in the app's own style, and `/metrics` gains the per-team active-accounts count for the watchdog |
| Tests | Unit: the enum check and truncation; API: a batch is stored, an unknown event is dropped, a foreign Origin is refused, the route is quiet; e2e: opening three screens yields three `screen` rows |

The events (name, props): 15 in the first release, 19 names in `usage.EVENTS` today, on
17 rows here (rows 7 and 11 hold two each).

| # | Event | Props | Answers |
|---|---|---|---|
| 1 | `app_open` | `version`, `theme`, `start` (the screen chosen on Perfil, when one was); `dev` is the row's own column | Sessions per day, PWA vs browser, viewport mix |
| 2 | `screen` | `s` (painel, quadro, pedidos, pedido, novo, clientes, cliente, cliente_novo, financeiro, campanhas, campanha, configuracoes, perfil, entrar, mudar), `from`. The report screen (`#/relatorio/<id>`) is not in the list: its rows are stored with an empty screen | Screens used, screen → screen paths, dead screens |
| 3 | `request_created` | `kind`, `has_deadline` (`files` is accepted, never sent) | Volume, which kinds, whether the form is finished |
| 4 | `request_status` | `from`, `to`, `via` (board, page) | Where status changes happen; abandoned "Aguardando" |
| 5 | `request_sent` | — | The WhatsApp share of a request is used or not |
| 6 | `comment_added` | — (`screen` is accepted, never sent) | The timeline is a conversation or a log |
| 7 | `file_added` / `file_failed` | `reason` (size, empty, network, drive) | OneDrive friction |
| 8 | `client_saved` | `new` (true/false) | Client editing frequency |
| 9 | `seen_today` | `n` (the client's campaigns marked; for "Visto hoje: todos", the number of clients) | Decision 8's daily check is done from the list or per campaign |
| 10 | `finance_entry` | `kind` (payment, cycle, void) | Financeiro is used by whom and how often |
| 11 | `search` / `filter` | `what` (status, client, text; on Clientes: view, sort) | How people find requests, and whether the clients list and its orders get used |
| 12 | `error_shown` | `msg` (class: validation, network, auth, drive, server), `screen`, `status`, `route` and `method` (the call that failed within 3 s), `form` (the form id or screen, when no call failed) | Where people hit a wall, and on which call or form |
| 13 | `api_slow` | `route` (pattern), `ms` (rounded, not a bucket), `status`, `method` | Slow calls as felt on the phone |
| 14 | `settings_changed` | `section` (equipe, financeiro, campanhas, listas, arquivos, meta, perfil) | Which settings get touched |
| 15 | `login` | `ok`, `method` (passkey, link) | Sign-in friction on phones |
| 16 | `period` | `p` (the picker key: last_30, this_month, custom…); with `custom`, also `days` (the range's length) and `ago` (how many days back it ends), never its dates | Which period each Campanhas draw used, next to the `api_slow` row it may have cost (added 2026-11-12: a 6.6 s Campanhas read could not be tied to a period) |
| 17 | `client_message` | `kind` (balance, summary) | Whether the message drafts on Visão geral get opened, and which (added 2026-11-12 with "Avisar o cliente"); the Painel's card Saldo acabando sends the same event, told apart by the row's screen (`painel`). Never the client, the number or the text |

### Option B in detail (the site)

| Part | What |
|---|---|
| Install | One `<script defer data-domain="www.pauta.cc" src="https://plausible.io/js/script.outbound-links.tagged-events.js">` in every page's `<head>`, after the hash-redirect line. No cookie, nothing in storage |
| Goals | `Chamar no WhatsApp` (outbound click to `wa.me`, counted by the outbound-links extension and also as a tagged event with `class="plausible-event-name=Beta+WhatsApp"` on the button, so it survives a change of number), `Entrar no app` (outbound to app.pauta.cc), `Planos` (scroll into `#planos`, as a tagged event on the nav link), later `Assinar` (the `/assinar` page view) and `Checkout` (Paddle.js's `checkout.completed` callback calling `plausible('Checkout', {props: {plan}})`, no amounts, no e-mail) |
| CSP on the site | GitHub Pages sets no headers. Optional: a `<meta http-equiv="Content-Security-Policy">` with `default-src 'self'; script-src 'self' 'sha256-<hash of the redirect line>' https://plausible.io; connect-src https://plausible.io; img-src 'self' data:; style-src 'self'`. The Paddle page would add `https://cdn.paddle.com` and `frame-src https://*.paddle.com` (decision 6). Not required for Plausible to work; `tools/check.py` would then fail on any violation, as the app's tests do |
| UTM conventions | `utm_source` = where the link was posted (`whatsapp`, `instagram`, `google`, `email`, `linkedin`); `utm_medium` = how (`chat`, `bio`, `story`, `post`, `cpc`, `email`); `utm_campaign` = `YYYYMM-<slug>` (`202611-beta`, `202612-lancamento`); `utm_content` = the variant (`story1`, `post-etapas`, `link-rodape`). Always as a query string, never in the `#fragment` (the redirect line only acts on `#/`). The `campaign/README.md` in `pauta-site` keeps the list of links in use |
| Connecting www to the app, without cross-site tracking | The site's own JS copies `utm_campaign` (if present) into the WhatsApp button's prefilled text as a short code in brackets: "Oi! Quero entrar no beta do Pauta. [202611-beta]". Nothing is sent anywhere; the lead chooses to send that message. famulus's lead intake already forwards the message to the owner, so the code arrives with the lead. When the owner creates the team (`pauta team create --source 202611-beta`, decision 5), the code lands on the `team` row; decision 6's checkout passes the team id (and so its source) in Paddle's `custom_data`. `pauta team list --by-source` then gives **leads → teams → paying teams per campaign** from `control.db` alone. Plausible knows the click, Pauta knows the team; nothing links a browser to a person |
| The campaign runner's view | Plausible's shared link (read-only, optionally password-protected): sources, campaigns, goals, countries, devices. His weekly question: which campaign brought WhatsApp clicks |

## Texts that must change

Privacy policy (`pauta-site/site/privacidade.html`), section 2, replaces "não tem
rastreadores, pixels nem ferramentas de análise" with (draft, for the legal review):

> **2. Este site (www.pauta.cc).** Este site não usa cookies e não tem formulários. Para saber
> quantas pessoas visitam o site, de onde vêm e quais páginas e botões usam, usamos o
> **Plausible Analytics** (Plausible Insights OÜ, Estônia), com servidores na União Europeia.
> Ele não usa cookies nem guarda nada no seu aparelho, não registra seu endereço IP nem a
> identificação do seu navegador, não cruza dados com outros sites e só produz números
> agregados (visitas por página, por origem e por país). Fazemos isso com base no nosso
> legítimo interesse em entender o que funciona no site (LGPD, art. 7º, IX). Para não ser
> contado, ative "Do Not Track" no navegador [ou: veja plausible.io/data-policy]. O GitHub
> Pages, que hospeda o site, registra dados técnicos de acesso (como o endereço IP) por
> motivos de segurança, conforme a política de privacidade do GitHub.

Section 3 (the app) gains one bullet after "registros técnicos":

> **registros de uso**: quais telas e ações do Pauta a sua conta usou, em que tipo de
> aparelho (celular ou computador, tamanho da tela, app instalado ou navegador), erros que
> apareceram e o tempo de resposta. Esses registros ficam no banco de dados do próprio time,
> guardam o número da conta (não o nome), nunca o conteúdo de pedidos ou clientes, e são
> apagados após 90 dias. Usamos esses dados só para corrigir falhas e melhorar o Pauta, com
> base no nosso legítimo interesse (LGPD, art. 7º, IX). Não gravamos a tela nem usamos
> ferramentas de terceiros dentro do app.

Decision 5's legal texts: the **data-processing agreement** (*contrato de operador*) gains a
clause that Du7 processes team members' usage records (screens, actions, device class,
errors, timings; no client data) as controller, for service improvement, pseudonymously, for
90 days, and that a team may ask for it to be switched off. The **terms** need no change. The
owner documents the balancing test (*teste de balanceamento*, ANPD 2024 guide: purpose,
necessity, expectations, safeguards, opt-out) once, as `docs/privacy/lia-usage.md`, for both
the site and the app; the legal review of the drafts (open item in `pauta-site`) covers it.
The app's release note (CHANGELOG, the version chip) says "O Pauta agora registra quais
telas e ações cada conta usa, para melhorar o app; veja a política de privacidade".

CSP changes: **app: none.** Site: optional meta policy above; nothing today.

## Consequences

- **Money:** $9/month (about R$ 50) for Plausible; €0 for the app. A Business plan ($19) only
  if funnels across site pages are wanted; the one funnel that matters (click → team → paid)
  comes from `control.db`, not from Plausible.
- **Code:** about 1 day for the app (table, route, `track()`, the 15 call sites, the report
  and tests), half a day for the site (script, goals, the WhatsApp code, UTM list, the
  privacy text, `check.py` updated), half a day later for the Paddle and `--source` pieces
  with decision 6.
- **Privacy exposure:** one new third party on the site (Plausible, EU, aggregates only); none
  in the app. Two paragraphs in the policy and one DPA clause. No banner on either.
- **Risk:** ad blockers hide a share of site visitors from Plausible (10–30% on tech
  audiences, less for small-business owners on phones); numbers are for trends, not
  accounting. The app's log is immune (same origin). If Plausible's numbers look too thin,
  proxying its script through `stats.pauta.cc` on Caddy, or self-hosting Umami there, is a
  Caddy block, not a redesign.
- **Operations:** the `usage` table grows by roughly 100–300 rows per active person per day;
  at 90 days and ten teams that is a few tens of MB, inside the nightly backup. Pruning is one
  `DELETE` in the backup unit's run.
- **du7's load:** unchanged. The Pi 5 could run Plausible CE or Umami comfortably if the owner
  prefers self-hosting the site's analytics; the CAX11 could not run Plausible CE next to
  Pauta.

## Staged plan

| Stage | What | When |
|---|---|---|
| 0 | The owner answers the questions below; the legal review of the privacy drafts includes the two paragraphs above | Now |
| 1 | **App:** `usage` table, `/api/usage`, `track()`, the 15 events, `pauta usage`, tests, privacy bullet, release note. Ships in a normal release; first look at the numbers after two weeks | After the Configurações/Perfil and Meta branches land, so the screen names are final |
| 2 | **Site:** Plausible account (owner), script tag, goals, UTM list in `campaign/README.md`, the WhatsApp campaign code, privacy section 2, `make check` green | Before the next campaign push (`campaign/` is ready) |
| 3 | **Chain:** `team.source` and `pauta team create --source`, `--by-source` report; Paddle `custom_data` and the `Assinar`/`Checkout` goals on `/assinar` | With decisions 5 and 6 |
| 4 | **Weekly habit:** the owner reads `pauta usage --days 7` and Plausible on Mondays (reps-triage's slot); the campaign runner gets the shared Plausible link. After two months: delete events nobody reads, add the ones a question needs, decide on the `#/uso` page | From stage 1 on |
| 5 | Revisit: replay on acceptance with demo data if a usability question can't be answered; self-hosting the site's analytics when production moves to Hetzner | When needed |

The weekly look, for the owner (`pauta usage`): active accounts per day; screens and actions
of the week versus the week before; the top five error toasts and the top five slow routes;
open → done median days by kind; Visto hoje coverage per day; device mix. For the campaign
runner (Plausible): visitors by source and campaign, the "Chamar no WhatsApp" goal by campaign, top
countries and devices.

## Questions for the owner

1. **Budget:** $9/month for Plausible on the site, or €0 with GoatCounter (hosted free is for
   non-commercial sites, so self-hosted on du7) or Umami self-hosted on du7?
2. **Self-host or cloud for the site?** Cloud (Plausible) means one named third party in the
   policy and nothing to maintain; self-hosting (B' or C' on du7, later on Hetzner) means a
   public `stats.pauta.cc` on the home connection until the move.
3. **Session replay:** confirm "no", or "yes on acceptance only"?
4. **In-app numbers:** CLI only for now, or build the owner page in the same release?
5. **Retention:** 90 days of raw usage rows, or shorter?
6. **Telling the team:** a line in the release note plus the policy, or also a message to the
   team before the release?
7. **The campaign runner and Plausible:** the shared dashboard link, or a weekly summary from
   the owner?
8. **The campaign code in the WhatsApp text:** fine, or does a visible code in the lead's
   message look odd? (Alternative: none, and the owner asks "como chegou até nós?".)
9. **Site CSP meta tag:** add it with Plausible (and later Paddle) allowed, or leave the site
   without a policy as today?

## Alternatives considered

- **One tool for both (Umami self-hosted on `stats.pauta.cc`):** one dashboard, free, EU, and
  the app would load its 2 KB script from our own subdomain (`script-src`/`connect-src`
  `https://stats.pauta.cc`). Rejected for the app because the usage data would leave the
  team's file (decision 5's isolation and deletion story) and because the app's questions are
  answered by SQL, not by a dashboard; kept as the fallback for the site.
- **PostHog Cloud EU for both:** the most capable and free at our size, with replay. Rejected
  for the app for the replay and third-party reasons above, and for the site because a
  50–100 KB script, cookies by default and a consent recommendation from the vendor itself
  are the opposite of a one-page site's needs.
- **Cloudflare Web Analytics for the site:** free and clean, but no UTM, no custom events, no
  outbound clicks: it can count visitors, not leads. Could be added next to Plausible for
  Core Web Vitals, but two beacons for one page is one too many.
- **Only the journal (`obs.py`) and `/metrics`:** zero code, but route counts per day say
  nothing about screens, toasts, devices or paths, and the journal is rotated by systemd.
  The usage table is the smallest step that answers the questions.
- **Google Analytics 4 / Meta Pixel on the site:** the campaign runner knows them, and the Pixel
  would let Meta optimise ads for site conversions. Both need a consent banner in Brazil and the
  EU and send visitor data to advertisers; not now. If Meta ad optimisation becomes necessary,
  Meta's Conversions API (server-side, from famulus's lead intake, hashed phone) is the
  privacy-preserving route and would be its own decision.
