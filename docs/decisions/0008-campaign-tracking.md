# 8. Acompanhamento: a daily check of every live campaign, then its numbers from Meta

- **Status:** proposed (2026-10-31), nothing built. Revised twice the same day with Piero's
  answers to the open questions.
- **Asked by:** Piero, who runs the campaigns (WhatsApp, 2026-10-31)
- **Depends on:** nothing for phase 1. **Fits:** decision 5 (one database per team: the
  tables are in the team's file, the Meta token is a file next to it) and decision 7 (same
  shape: a settings block per module, statuses derived, never stored).
- **Changes:** adds an `Acompanhamento` tab, a `Campanhas` card on the client page and an
  `Acompanhamento` panel on Equipe; phase 2 adds a Meta connection on Equipe and a sync.

## Context

Piero's job doesn't end when a campaign goes live: he follows each one up (reads the numbers,
adjusts budget, audience, creatives) and reports to the client. Pauta tracks the work up to
"Concluído" and then forgets the campaign. Today that is 3 live campaigns for about 4
clients, kept in his head; he is preparing for more, and the risk he names is skipping a
client.

What he asked for, in his order of ambition:

- **The dream:** campaign numbers pulled from Meta, as cards and charts, filterable by client
  and by portfolio.
- **The minimum, if Meta doesn't work out:** every request of the "fazer campanha" type that
  is marked done lands in a list; from there it moves to a list of active campaigns where he
  records by hand the date of his last analysis of each one, so he goes through every client
  without skipping one.

His answers to the first draft's questions (2026-10-31) changed it:

- **Every day, every campaign.** He looks at all live campaigns daily. What he needs is a
  clear list of the clients with live ads and a mark saying "seen today", so he knows when
  he has been through all of them.
- **Portfolio means Meta's business portfolio** (the client company's), and one portfolio may
  hold several ad accounts: filter by portfolio, then by ad account.
- **A period filter**, defaulting to the current month, adjustable.
- **Both "Criar campanha" and "Reativar campanha"** mean a campaign is live. With Meta
  connected, the live campaigns should come from Meta itself, for every connected client.
- **The numbers he reads:** cost per lead, leads, reach, views, amount spent and the balance
  left on the account, plus whatever else a traffic analysis needs. He wants them as a list he
  picks from, each pick adding its card or chart, and **a text analysis he can send to the
  client on WhatsApp**.
- **His Meta access:** he signs in with his personal profile; his business portfolio has the
  clients as partners; he is its admin; the profile has two-step verification. (That is
  login security, not Meta's *business verification*.)

And to the second round:

- **No business verification** on his portfolio. He expects to sign in to Meta's site and
  generate "a key" there.
- **Balance:** only to read how much is left on the ad account, if the API gives it.
- **Lead = a click that takes someone to the destination** the ad is set up for (site,
  WhatsApp, whatever it is). It varies per campaign; this definition covers all of them.
- **One client is one portfolio**; a client may have several ad accounts.
- **The text for the client should be written by an AI.**

What Pauta has today: a request's type is `request.kind`, from the editable `kind` list
whose defaults include **"Criar campanha"** (Piero's "fazer campanha") and **"Reativar
campanha"**; `done_on` is set when a request reaches Concluído; a request has a
`campaign_url` (the link in Ads Manager) and a manual `balance` (Tem saldo / Saldo baixo /
Sem saldo); a client has one `ad_account` id, a `whatsapp` and a `state`
(Ativo/Pausado/Encerrado). There is no notion of a campaign that outlives its request.

Meta's side was researched on 2026-10-31 (sources at the end) and is summarised under phase 2.

## Decision

Build it in two phases that each stand on their own. **Phase 1** is the daily check list,
useful without Meta. **Phase 2** reads the numbers from Meta's Marketing API into the same
list, and from then on Meta says which campaigns are live. Pauta only **reads** from Meta:
it never creates, edits, pauses or pays for anything there, and it never sends anything to a
client by itself.

### What a campaign is

A **campaign** is something live that someone follows up: one client, a start, an optional
end, and a log of **checks** (date, who, an optional note). In phase 1 it is born from a
done request; in phase 2 it is usually born from a live campaign in Meta, and links to that
Meta campaign (one or more: what Piero calls "a campanha da clínica" may be several in Ads
Manager). The **unit Piero checks is the client**: "seen today" on a client marks all its
live campaigns as checked.

### Phase 1: the daily check list (manual)

| Topic | Decision |
|---|---|
| Data | Two additive tables in the team's database, schema v7. `campaign`: `client` (cascade), `request` (nullable, unique, `SET NULL` if the request is deleted), `name`, `started` (date), `state` (`active`, `paused`, `ended`, `skipped`), `ended` (date), `every_days` (nullable: overrides the team's cadence), `note`, `created_by`, `created`, `updated`. `review` (a check): `campaign` (cascade), `on` (date), `account`, `note`, `created`. Settings in the existing `setting` table under `tracking` |
| Where campaigns come from | A request whose `kind` is one of the team's **tracking kinds** (default `["Criar campanha", "Reativar campanha"]`) and whose status is `done`, with no campaign yet, appears in **"Para acompanhar"**. One tap: **Acompanhar** (creates the campaign: name from the request's `what`, `started` from `done_on`, linked to the request; a "Reativar" request on a client with an ended campaign offers to reactivate that one instead) or **Não acompanhar** (a `skipped` row, so it never comes back). This also picks up campaigns done before this ships, with no guessing in the migration. A **Nova campanha** button covers campaigns that never had a request |
| Why not create them automatically | A done request isn't always a live campaign (the client gave up, it was merged into another). One tap keeps the list honest; the inbox has a counter in the nav, like Pedidos, so it can't be missed. In phase 2 Meta settles the question and the inbox becomes a fallback |
| The daily check | The team's cadence defaults to **every day** (`every_days` = 1; a campaign may override it, say a weekly brand campaign). The list shows one row per client with live campaigns, and **Visto hoje** on the row records a check for each of its live campaigns (today's date, optional note). A campaign can also be checked alone. The author or an admin may delete a check |
| Statuses (derived, in this order) | Per campaign: `never` (never checked), `overdue` (last check + `every_days` has passed), `due` (due today), `done` (checked within its cadence). Per client: the worst of its live campaigns. Campaigns of a client that is not Ativo, and `paused` ones, drop out of the list and show greyed. Nothing derived is stored, so changing the cadence recalculates everything |
| Pausing and ending | Buttons on the campaign: Pausar, Reativar, Encerrar (sets `ended`). A done "Pausar campanha" request does not pause anything by itself in phase 1; in phase 2 Meta's own status does |
| Settings (per team, admins, Equipe → Acompanhamento) | `enabled`, `kinds` (from the `kind` list; a warning shows if one was renamed away), `every_days` (1). Validated like `FINANCE_FIELDS`, sent in the boot data |
| API | `GET /api/tracking` (inbox, clients and campaigns with derived status); `POST /api/tracking/start` (from a request id, or a client and name); `PATCH /api/campaigns/{id}` (name, state, `every_days`, note); `POST /api/campaigns/{id}/reviews`; `POST /api/clients/{id}/reviews` (Visto hoje: one check per live campaign); `DELETE /api/reviews/{id}`; `GET|PATCH /api/tracking/settings` (admin). `GET /api/clients/{id}` gains `campaigns`; `/api/export` includes both tables |
| UI | **Acompanhamento** tab after Pedidos. At the top a progress line, **"Hoje: 3 de 5 clientes vistos"**. Then "Para acompanhar" (only when not empty). Then one row per client, not-yet-seen first: the client, its live campaigns, "visto há N dias" or "visto hoje por Piero", the last note and **Visto hoje**. Seen clients sink to the bottom with a check mark, so the list empties as he goes. On the Painel a stat "Clientes para ver hoje". On the client page a **Campanhas** card. On a tracked request's page, a link to its campaign. Marking a tracking-kind request Concluído shows a toast "Vai para Acompanhamento" |
| Timeline | Starting, pausing and ending tracking leave an `event` on the originating request, so the request's history says what happened after Concluído |

### Phase 2: numbers from Meta

Phase 2 starts with a **one-hour spike** (step 0 in the table) and is only built if it
passes. What Meta offers, in short: the Marketing API's Insights endpoint gives per-campaign
daily spend, impressions, reach, frequency, clicks, CTR, CPC, CPM and "actions" (messages
started, leads, purchases...) with their cost, plus breakdowns by age, gender, region,
platform and placement, for 37 months back (13 for reach with breakdowns). It is free; the
cost is setup and keeping up with Meta's yearly API versions. Piero's business portfolio
already has the clients as partners and he is its admin, which is exactly the setup Meta
expects: his portfolio gets a **system user** (a robot account, not his personal profile)
with access to the clients' ad accounts, and Pauta reads with that system user's token.
System user tokens don't expire like personal ones (about 60 days), and Pauta never sees
Piero's own login.

| Topic | Decision |
|---|---|
| Step 0: the spike | Before any code, with Piero (the admin) and the owner together, signed in with Piero's profile: on developers.facebook.com, register as a developer and create a **Business**-type app linked to Piero's business portfolio, and add the Marketing API product (it starts on the **Limited** tier). In business.facebook.com → Configurações da empresa → Usuários → **Usuários do sistema**, create one regular system user, add the app to it, assign it one client's ad account with "Ver desempenho", and **Gerar token** with `ads_read` and expiry "Nunca". That token is the "key" Piero expected. Then read that account's current month with one `curl` to `/act_<id>/insights?level=campaign&time_increment=1` on v26.0. In the same hour: check the token's real expiry with Meta's token debugger; try the balance with "Ver desempenho", then with "Gerenciar campanhas" (see "Saldo"); check whether Ads Insights has a "views" field or still only `impressions`; check that link clicks to WhatsApp destinations are counted (see "Lead"). Pass = numbers come back on Limited, unverified. If they don't, phase 2 needs business verification first (Meta asks for the company's documents, CNPJ, a matching domain or phone) and then App Review, or the team buys a tool (Alternatives) |
| Whose Meta app | Phase 2 is for **this** team: the app and the system user belong to Piero's business portfolio, so Pauta reads accounts that portfolio has been given. A Pauta-owned app that every customer team connects with "Login do Facebook para empresas" is the decision-6 version: it needs Full access, App Review and business verification of Du7, so it is a decision of its own, taken when a second team asks |
| Access tier | Start on **Limited**; Piero's portfolio isn't business-verified, so Limited is the only tier open to it for now (Full needs App Review, which needs verification). Meta calls Limited "for development", its wording says apps reading "other people's ad accounts" need advanced access, and its app settings say an unverified business "can't access data you don't own"; whether partner-shared client accounts read by the agency's own system user count is not settled in Meta's docs. That is the spike's main question, and the most likely reason for it to fail. A sync every hour over tens of accounts is far inside Limited's quota (600 + 400 × active ads per hour per account). Moving to **Full** needs App Review, 500 successful calls in 15 days and under 15% errors; plan for it if Meta pushes back, and add the privacy policy, terms and data-deletion instructions URLs Meta wants for Live mode or review anyway (decision 5's legal texts on the public site cover them) |
| Token | A file next to the team's DB, `pauta.db.meta-token`, mode 600, like the OneDrive token (decision 3): never in the DB, its backups, the export or the logs. An admin pastes it on Equipe → Meta; the field is write-only, and Pauta only shows "conectado", the portfolio it belongs to and its expiry (from `debug_token`). One token per team under decision 5 |
| Portfolios and ad accounts | **One client is one portfolio** (Piero), with one or more ad accounts. Additive: `client.meta_business` (the portfolio id, unique when set) and a table `meta_account`: `account_id`, `name`, `client`, `currency`, `timezone`, `status`, `seen`. Filled by listing every ad account the system user can read, with the portfolio that owns it. Each new portfolio is matched once to a Pauta client (suggested by name, confirmed by Piero); every ad account under it, now and later, follows. The client's existing `ad_account` field seeds the match and stays for clients without Meta. A client with no readable account shows "Meta: sem acesso", which turns the manual `access` field into something checked |
| Live campaigns come from Meta | Each sync lists the campaigns of every account (`effective_status`). A campaign that is `ACTIVE` in Meta and has no Pauta campaign gets one automatically, under its client, linked by `campaign_meta(campaign, meta_id)`; when Meta stops delivering it (paused, ended, out of budget) the Pauta campaign follows. This is "via API ele trará todos os clientes conectados": the daily list fills itself. A done "Criar/Reativar campanha" request is linked to its Meta campaign when its `campaign_url` (an Ads Manager link) carries the id, or picked from a list |
| Sync | `pauta meta sync`, on two timers (`pauta-meta-sync.timer`, a `deploy/` change next to the backup timer, owner-reviewed): **hourly**, today and yesterday for every live campaign, plus campaign statuses and account balances, so the numbers Piero checks in the morning are current; **nightly**, the last 28 days again, because conversions keep arriving for up to 28 days after a click. Older days are frozen. On first link, the campaign's history back to its start (Meta keeps 37 months). An **Atualizar agora** button, limited to once per 15 minutes. Backoff on Meta's throttle headers and error codes; nothing retries in a loop. `/metrics` gains `meta.{enabled,connected,error,last_sync}` for du7's watchdog |
| Data | `insight` (additive): `meta_id`, `day`, `spend_cents`, `currency`, `impressions`, `reach`, `clicks`, `link_clicks`, `leads`, `results`, `result_type`, plus the extra metrics below, `fetched`; key (`meta_id`, `day`). Money in integer cents in the account's currency, as in decision 7. Raw Meta JSON is not stored. **Reach and frequency don't add up over days** (the same person counts once in a month), so for the chosen period Pauta asks Meta for the period total and caches it for an hour |
| Period | A period picker on every view, defaulting to **the current month** (in the ad account's time zone), with quick choices (hoje, ontem, 7 dias, 30 dias, mês passado) and custom dates. Every card compares against the previous period of the same length |
| "Lead" | Piero's definition, one for every campaign: **a lead is a click on the ad that takes the person to its destination** (site, WhatsApp, Direct, form...). In Meta's terms that is **link clicks** (`inline_link_clicks`), and **Custo por lead** is `cost_per_inline_link_click`. One team setting, `lead_metric`, holds it (default `link_clicks`; other values `landing_page_views` or a Meta action type), so another team, or Piero later, can count something stricter. Because a click isn't yet a conversation or a sale, the picker also offers Meta's own **Resultados** for the campaign (conversations started, forms sent, purchases), so the two can be compared when a client asks why many leads brought few messages. Labels in the UI say "Leads (cliques)" so a client reading the text isn't misled |
| Saldo (balance left) | Piero only wants to read how much is left on the ad account. For a prepaid account (Pix or boleto, common in Brazil) that is on the ad account (`funding_source_details`, `is_prepay_account`), which Meta's reference says it shows only to a user with **Gerenciar campanhas** (MANAGE/ADVERTISE task) on the account, not just "Ver desempenho". The spike tries both. If it needs the wider task: the token stays `ads_read`, so Pauta still can't change anything, but the system user holds a wider role than reading; the owner and Piero decide then. If the balance can't be read, the fallback is the campaigns' `budget_remaining` and spend against the account's spend cap, and the manual `balance` field stays. When read, a low balance turns the client's row orange (threshold per team) |
| Metrics on offer | Piero's: **Custo por lead, Leads** (as defined above), **Alcance, Visualizações** (`impressions` until Meta's Ads API offers "views"; the spike checks), **Valor investido, Saldo**. Suggested for a traffic analysis: **Frequência** (above ~3 the audience is tiring), **CTR (link)** (is the creative pulling clicks; CPC (link) is already Custo por lead), **CPM** (cost of the audience), **Conversas iniciadas / custo por conversa**, **Taxa de conversão** (leads ÷ link clicks: the landing page or the WhatsApp script), **Ritmo de gasto** (spend against budget for the period), for video **ThruPlays and hook rate** (3-second views ÷ impressions), for sales **Compras, ROAS**; and on the campaign page the **best and worst ads** by cost per lead |
| Screens | **Acompanhamento** keeps the daily list; each client row gains its headline numbers for the period (investido, leads, custo por lead, saldo) and opens the client's **campaign panel**. The panel's filters: **Portfólio** (one per client, so it is the client filter by its Meta name), then **Conta de anúncios** (only that portfolio's; "todas" by default), then campaign and period. On the left the list of metrics with checkboxes; each one picked adds its **card** (value, change against the previous period) and, if Piero switches it on, its daily **chart**. Picks are remembered per person. Breakdowns (age/gender, region, platform/placement) on demand. Charts are plain SVG drawn by `app.js`: no chart library, CSP stays `'self'`, no new dependency |
| Text for the client | **Gerar análise** on the panel asks an **AI** for a short Portuguese analysis of the selected period, as Piero asked. Pauta computes every number itself (totals, cost per lead, change against the previous period, frequency, balance, best and worst campaign) and sends the model only those **facts**, as JSON, with a fixed prompt: write for a small-business owner, warm and short, WhatsApp-sized, say what went well, what to watch and one suggestion, use only the numbers given. **No names, phones or ad texts leave Pauta**: the client is "{cliente}" and campaigns are "Campanha 1, 2...", replaced back after the answer. Every number in the answer is checked against the facts; a text with a number that isn't there is thrown away and the **template text** (the same facts in fixed sentences) is shown instead, as it is when the AI is off or unreachable. It opens in an editable box; **Copiar** and **Abrir no WhatsApp** (the client's `whatsapp`, through a `wa.me` link, so Piero sends it from his own phone). Pauta never sends it. Checking the client records the sent text as the check's note |
| Which AI | The **Claude API** (a small, fast model such as Claude Haiku), called with stdlib `urllib` like the Graph calls: no SDK, no new dependency. The API key is a file next to the team's DB (`pauta.db.ai-key`, mode 600), set by an admin on Equipe, like the Meta token; for other teams (decision 6) it is Du7's key and part of the plan's cost. A team setting `ai_text` turns it off. At a few analyses a day the cost is small (measured in the first month and noted here). Anthropic becomes a sub-processor of aggregated, nameless numbers: the privacy texts of decision 5 say so |
| Checks get numbers | A check stores a snapshot of the client's headline numbers at that moment (an additive `snapshot` JSON column on `review`), so a note is next to the numbers it was about |
| No new dependency | Graph calls with stdlib `urllib`, like `onedrive.py`; tests use a fake Meta Graph like `tests/fakegraph.py`, never the real one |
| Version | Pinned to one Graph API version (v26.0 today). Meta retires Marketing API versions in about a year; bumping it is a release-note line and a test run against the fake |

### Phase 3, later: organic Instagram and Facebook numbers

Followers, reach and views of posts on the clients' profiles are a different API (Instagram
API with Facebook Login, Page insights) with different permissions. Reading other
businesses' profiles needs Advanced Access, so App Review and business verification, and
Meta renamed or dropped many of those metrics in 2025 (impressions became views). Not in
this decision; it gets its own once phase 2 is in use and someone asks.

## Consequences

- Phase 1 is about 1.5 days: two tables and the settings block, the derived statuses with
  unit tests, the routes, the Acompanhamento screen, the client card, browser tests. It is
  useful on its own and doesn't wait for anything at Meta.
- Phase 2 is about 6–7 days of code after a spike that passes (the metric picker, the AI text,
  the auto-created campaigns made it bigger than the first draft's 3–4),
  plus Meta-side setup outside the code: the app and the system user in Piero's portfolio.
  The clients are already partners. Business verification, if Meta asks for it, can take
  days to weeks. It can ship in two releases: numbers, filters and cards first; analysis
  text and suggested metrics second.
- Phase 2 depends on Meta's rules for the Limited tier, which Meta describes as for
  development, and Piero's portfolio is not business-verified. If the spike fails, or Meta
  tightens Limited later, the integration waits for business verification (company
  documents, days to weeks) and App Review; the phase-1 list keeps working, since the
  numbers are an addition to it, not its basis.
- Reading the balance may need the system user to hold "Gerenciar campanhas" on each
  client's account. The token's `ads_read` scope keeps Pauta read-only either way, but the
  role would be wider than reading; if that is unwelcome, the balance stays manual.
- Counting every link click as a lead makes "Custo por lead" the same number as Meta's
  CPC (link), and lower than a cost per conversation or per form. That is the team's
  definition and the labels say so; the text for the client says "cliques" and Meta's
  Resultados sit next to it in the picker.
- The AI text adds a second outside service after Meta, an API key to keep, and a small
  monthly cost. Nothing personal goes to it, every number it writes is checked against
  Pauta's own, and the template text is always there when it's off or wrong. The model can
  still phrase something Piero wouldn't say: the box is editable and he sends it himself.
- Meta changes metrics and retires API versions every year: expect a small maintenance
  release per year, and a goal → lead mapping that needs a look when Meta renames actions.
- The token can read every ad account assigned to the system user. Anyone with du7 root
  can read it; it is not in backups. Revoking it in Meta's Business Settings cuts Pauta off
  at once.
- Insights are aggregated numbers about ads (no names of people who saw or clicked), so
  LGPD exposure is low; they are still the client's data, in the team's file, covered by
  decision 5's processor terms when other teams arrive. The Meta data is never shown outside
  the team or passed to anyone; the analysis text leaves only when Piero sends it himself.
- The tracking kinds are matched by name. Renaming "Criar campanha" in Equipe takes it out
  of the inbox until the setting is updated; the settings panel warns about it.
- Later, in this order: a WhatsApp reminder at the end of the day "2 clientes ainda não
  vistos hoje"; per-campaign targets (custo por lead alvo) with a warning when a campaign is
  off target; a monthly report per client built from the same cards.

## Alternatives considered

- **Creating the campaign automatically when the request is done (phase 1):** one step
  less, but requests that never went live would fill the list with things to end. In phase 2
  Meta's own status does this job, correctly.
- **A "última análise" column on the request:** the smallest change, but a campaign outlives
  the request that created it and later requests (new creatives, budget) belong to the same
  campaign; and one date has no history or notes.
- **Checking per campaign only:** what the first draft proposed. Piero thinks in clients
  ("se já passei pelo cliente"), so the client is the unit and its campaigns follow.
- **A fixed dashboard instead of the metric picker:** simpler, but Piero asked to choose,
  and campaigns for messages, leads and sales need different numbers.
- **Buying a reporting tool** (mLabs, about R$ 30 per client per month; Reportei, Windsor.ai
  with Looker Studio, Supermetrics): dashboards, client reports and organic insights today,
  with Meta's review handled by them. A real option for phase 2, and it combines with phase
  1: the client page can hold the report's link. It costs money per client as the team grows,
  puts the numbers in another place than the daily list, and doesn't know who checked what.
- **Ads Manager's scheduled email reports or CSV export:** free and already there, but
  per account, by email, and nothing records whether someone looked.
- **Template text only, no AI:** no outside service and no cost, and it is what Pauta
  falls back to. Piero asked for the AI: the template reads the same every day, and clients
  notice.
- **A local model for the text** (the house runs Ollama on a gaming PC): free and nothing
  leaves the house, but that machine is often busy or off, it is weaker at Portuguese
  writing, and decision 5 moves production off du7 to a server that can't reach it.
- **Piero's personal token via Facebook Login:** no system user needed, but it expires in
  about 60 days, carries everything his profile can do, and dies when his access changes;
  the system user is the pattern Meta recommends for server-to-server reading.
- **Storing Meta's raw responses or ad-level daily rows for everything:** more than the
  questions need and more to keep up to date. Campaign level daily; ad level on demand.

## Sources

Meta for Developers, read 2026-10-31. Where Meta's own pages disagree or are vague, the
spike decides.

- Versions: https://developers.facebook.com/docs/graph-api/changelog/versions and the
  Marketing API changelog,
  https://developers.facebook.com/documentation/ads-commerce/marketing-api/marketing-api-changelog
- Access tiers and authorization (the 2026-05 rename to Limited/Full):
  https://developers.facebook.com/documentation/ads-commerce/marketing-api/get-started/authorization,
  https://developers.facebook.com/docs/graph-api/overview/access-levels,
  https://developers.facebook.com/docs/permissions/reference/ads_read
- System users and tokens:
  https://developers.facebook.com/docs/business-management-apis/system-users/overview,
  https://developers.facebook.com/documentation/ads-commerce/marketing-api/get-started/authentication
- Ad account fields (`funding_source_details` needs MANAGE; `is_prepay_account` needs
  ADVERTISE or MANAGE): https://developers.facebook.com/docs/marketing-api/reference/ad-account
- Insights, breakdowns, 2025–2026 metric and attribution changes:
  https://developers.facebook.com/docs/marketing-api/insights,
  https://developers.facebook.com/docs/marketing-api/insights/breakdowns,
  https://developers.facebook.com/blog/post/2025/10/16/ads-insights-api-metric-availability-updates/
- "Views" replacing impressions: confirmed for organic Instagram and Page insights; for the
  Ads Insights API, third-party reports (e.g. Fivetran's community board, early 2026) say
  `impressions` is still the field. Unverified at Meta; the spike checks.
- Rate limits:
  https://developers.facebook.com/documentation/ads-commerce/marketing-api/overview/rate-limiting
- App modes and data deletion:
  https://developers.facebook.com/docs/development/build-and-test/app-modes,
  https://developers.facebook.com/docs/development/create-an-app/app-dashboard/data-deletion-callback
- Organic insights: https://developers.facebook.com/docs/instagram-platform/overview,
  https://developers.facebook.com/blog/post/2025/08/15/page-insights-api-updates/
- mLabs prices: https://www.mlabs.com.br/blog/mlabs-planos/; Windsor.ai: https://windsor.ai/pricing/

## Open questions

Answered by Piero on 2026-10-31, in two rounds: portfolio = the client's Meta business
portfolio, one per client, with one or more ad accounts; period filter defaulting to the
current month; both "Criar" and "Reativar campanha"; a daily "seen" mark per client; the
metrics above; a lead is any click to the ad's destination; the balance only to read; the
text for the client written by an AI; his portfolio is not business-verified and the clients
are partners in it.

Still open:

1. **The spike** (Piero and the owner, one hour, one client's account): does Limited work
   for partner-shared accounts on an unverified portfolio, is the balance readable and with
   which role, and does a WhatsApp click count as a link click.
2. **If the spike fails** (owner and Piero): verify the business (does the agency have a
   CNPJ and a domain or phone in its name?) or buy a tool for the numbers and keep phase 1.
3. **If the balance needs "Gerenciar campanhas"** (owner and Piero): accept the wider role
   for the system user, or keep the balance manual.
4. **The AI key** (owner): whose Anthropic account pays, and the monthly cap on it.
