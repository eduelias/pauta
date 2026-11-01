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

**Revised 2026-11-01**, after Piero's first days on acceptance. Pauta's account-wide
"Investido este mês" (R$ 148,94) didn't match his Ads Manager (R$ 31,58): his view had the two
live campaigns for 1–30 Oct, Pauta added every campaign in the account, five of them ended on
17 Oct, plus today. The owner's decision: numbers **per campaign, for tracked campaigns only**,
stored daily, with a period picker that means what Ads Manager means, and the balance. The
phase-2 rows below say how; the build order is sync and tables, then the Campanhas screen,
then the balance (a configuration change in Meta), then the daily check marks, then the AI text.

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
already has the clients as partners and he is its admin. Pauta's Meta app belongs to Du7,
whose business is verified; Piero connects his portfolio to it with one login, Meta creates a
**system user** (a robot account, not his personal profile) in his portfolio with read
access to the clients' ad accounts, and Pauta reads with that system user's token. The token
doesn't expire like personal ones (about 60 days), and Pauta never sees Piero's own login.

| Topic | Decision |
|---|---|
| Step 0: the spike | Before any code, Piero and the owner together. Piero has a role on the Pauta app (Tester since 2026-10-31: in development mode Meta only shows the login to people with a role), then signs in through the login configuration with a throwaway local page or a `curl`-built URL, picks his portfolio and one client's ad account, and the owner exchanges the code for the token by hand and reads that account's current month with one `curl` to `/act_<id>/insights?level=campaign&time_increment=1` on v26.0. In the same hour: check the token with Meta's token debugger; try the balance with ANALYZE, and if it is refused note it (see "Saldo"); check whether Ads Insights has a "views" field or still only `impressions`; check that link clicks to WhatsApp destinations are counted (see "Lead"). Pass = numbers for a partner-shared client account come back in development mode. If not: App Review for Advanced `ads_read` under Du7 (verified), which needs the Tech Provider step, a screencast and the pauta.cc privacy, terms and data-deletion pages; or buy a tool (Alternatives) |
| Whose Meta app | **Du7's.** Registered 2026-10-31: app **Pauta**, App ID `1767206382079558`, owned by Du7 Technology Services (business-verified), use case "Measure ad performance data with Marketing API", development mode, contact du7@msn.com. A verified owner is what lets an app reach data from other businesses' portfolios and go through App Review, which Piero's unverified portfolio couldn't. Each team connects its **own** portfolio to this one app with **Facebook Login for Business** (configuration "Pauta - leitura de anuncios", ID `1649862390172470`: system-user token, no expiry, ad accounts required, task ANALYZE only, permission `ads_read` only; redirect `https://acc.pauta.cc/api/meta/callback` only, strict, HTTPS; production's `https://app.pauta.cc/api/meta/callback` is added when phase 2 is released). Meta then creates a system user inside the team's portfolio and hands Pauta its token. This is also decision 6's model, so it is built once. The App Secret stays in Meta and the owner's 1Password; it reaches the server as a file next to the DB like the token, never the repo |
| Tested on acceptance | All Meta work is tried on **acc.pauta.cc** (decision 1) before production: the spike's login redirects there, and phase-2 builds reach acceptance first. Acceptance needs one real ad account to show anything, so Piero adds **one** of his clients there himself: a neutral name and the ad account id only, no contacts or phones, and in Meta's login he picks only that client's ad account, so acceptance's token can read nothing else. That is a deliberate, small exception to decision 1's demo-data rule (Meta numbers are aggregated, the client stays unnamed); acceptance keeps its own `pauta.db.meta-token`, and the client and the connection are removed when the test is over, or kept as acceptance's one real fixture if the owner prefers |
| Access tier | Start on **Limited** (what the app has now), with `ads_read` at standard access: "ready for testing", for people with a role on the app. Meta calls Limited "for development", and its wording says apps reading "other people's ad accounts" need advanced access; whether a partner-shared client account read through the team's own portfolio counts is not settled in Meta's docs, and the spike decides it. With Du7 verified, the way up is open: App Review for Advanced `ads_read` (Meta's dashboard asks the app to become a Tech Provider first), and Full tier later if the rate limits ever bite (500 calls in 15 days, under 15% errors). A sync every hour over tens of accounts is far inside Limited's quota (600 + 400 × active ads per hour per account) |
| Token | Piero clicks **Conectar Meta** on Equipe → Meta; Facebook Login for Business sends him back to `/api/meta/callback` with a code; Pauta exchanges it (with the App Secret) for the system-user token and keeps it in a file next to the team's DB, `pauta.db.meta-token`, mode 600, like the OneDrive token (decision 3): never in the DB, its backups, the export or the logs. Pauta shows only "conectado", the portfolio and the token's state (from `debug_token`). The token doesn't expire; Piero revokes it under his Business Settings' connected apps, and Pauta reports that on Equipe and `/metrics`. One token per team under decision 5. The `state` parameter is bound to the admin's session, so a callback nobody started is refused |
| Ad accounts and clients | Built 2026-10-31 (eduelias/pauta#19), schema v8: table `meta_account` (`account_id`, `name`, `currency`, `status`, `client` → `client.id` with `SET NULL`, `seen`). Every real read of Meta upserts the accounts the token lists; rows for accounts that drop out of the list are **kept**, shown as "não aparece mais na Meta", so an untick in Meta or an outage never loses a mapping. Mapping is **account → client**, not through a portfolio: `business{name}` isn't readable with `ads_read`, and partner-shared accounts live in the clients' portfolios anyway. An unlinked account whose id equals a client's existing `ad_account` is linked automatically; otherwise Equipe → Meta shows a **Cliente** select per account with a conservative name-based suggestion (never saved by itself). Linking fills an empty `ad_account`; unlinking leaves it. The client page gets a **Meta** card with the linked accounts' numbers for the month (members see it; admins also get the "vincule em Equipe" pointer). A client may own several accounts (Piero: "mais de uma conta de anúncio por cliente") |
| Tracked campaigns come from Meta | **Tracked = every campaign live in Meta (`effective_status` ACTIVE) under a linked ad account**, created as a `campaign` row by the sync, under the account's client. **Não acompanhar** sets `skipped`, which hides it for good unless undone. A campaign Meta stops delivering (paused, ended, archived, out of budget) becomes `ended` with the date; back to ACTIVE reopens it. Ended or archived campaigns never appear unless asked for. A done "Criar/Reativar campanha" request is linked to its Meta campaign through the campaign id in its `campaign_url` (Ads Manager links carry `selected_campaign_ids=`); phase 1's "Para acompanhar" inbox stays only for teams without Meta |
| Sync | `pauta meta sync` reads, per linked account, the campaign list and then **campaign-level daily insights** (`level=campaign`, `time_increment=1`: spend, impressions, reach, link clicks, the `actions` map) into `insight`, one row per campaign per day; **hourly** for today and yesterday, **nightly** for the last 28 days (conversions keep arriving), and on a campaign's first appearance its history back to its start. Instead of systemd timers (a `deploy/` change, owner-reviewed, not deployable to acceptance by the branch pipeline) the serve process runs an **in-process scheduler thread** (`PAUTA_META_SYNC=off` disables it; a timer can replace it later without changing the code). Account-level reads stay only for the account list and the balance. `Atualizar agora` runs the hourly job, at most once per 15 minutes. `/metrics` gains `meta.last_sync` and `meta.sync_error` for du7's watchdog |
| Data | Additive, schema v9. `campaign`: `client`, `account_id`, `meta_id` (unique), `name`, `objective`, `state` (`active`, `paused`, `ended`, `skipped`), `effective_status` (Meta's), `started`, `ended`, `request` (nullable, unique), `every_days`, `note`, `last_seen`, `created_by`, timestamps. `review`: `campaign`, `on`, `account`, `note`, `snapshot` (JSON). `insight`: `meta_id`, `day`, `spend_cents`, `impressions`, `reach`, `link_clicks`, `actions` (a small JSON map action type → count, not Meta's raw answer), `fetched`; key (`meta_id`, `day`). Money in integer cents in the account's currency. **Reach doesn't add up over days**: for a chosen period it is asked from Meta once for that range and cached for an hour, never summed from the daily rows |
| Period | A period picker at the top of Campanhas that **prints the exact dates** it covers. Default **this month** (Piero's answer). Quick choices use **Meta's own presets** so they mean what Ads Manager means: "Últimos 7/30 dias" run from yesterday back and exclude today; "Hoje", "Ontem", "Este mês", "Mês passado", and custom dates. A "hoje incluso" note appears when today is in the range, because today's numbers are still moving. Sums (spend, impressions, clicks, results) come from the stored daily rows; reach from Meta per range (above) |
| "Lead" | Piero's definition, one for every campaign: **a lead is a click on the ad that takes the person to its destination** (site, WhatsApp, Direct, form...). In Meta's terms that is **link clicks** (`inline_link_clicks`), and **Custo por lead** is `cost_per_inline_link_click`. One team setting, `lead_metric`, holds it (default `link_clicks`; other values `landing_page_views` or a Meta action type), so another team, or Piero later, can count something stricter. Because a click isn't yet a conversation or a sale, the picker also offers Meta's own **Resultados** for the campaign (conversations started, forms sent, purchases), so the two can be compared when a client asks why many leads brought few messages. Labels in the UI say "Leads (cliques)" so a client reading the text isn't misled |
| Saldo (balance left) | Piero only wants to read how much is left on the ad account. Meta's ad-account reference: `funding_source_details` needs the **MANAGE** task on the ad account ("Gerenciar conta de anúncios", the admin level), `is_prepay_account` needs ADVERTISE or MANAGE; **ANALYZE reads neither**, which the spike confirmed ("sem permissão"). Decided 2026-11-01: the Login for Business configuration "Pauta - leitura de anuncios" (1649862390172470) changes its ad-account task from ANALYZE to **MANAGE**; the permission stays `ads_read`, so the token can still only read. Done 2026-11-01 in the app dashboard (with the owner's go-ahead): MANAGE selected, and Meta's dependency rule added ADVERTISE, ANALYZE and DRAFT to it ("4 options selected"); the editor doesn't display saved tasks afterwards, so the proof is Piero **reconnecting** on acceptance (a token carries the tasks of its minting) and the balance appearing. Caveats: Meta's `balance` field is the **bill amount due** (postpay), not a prepaid remainder; for Pix/boleto accounts expect `funding_source_details.display_string`, `spend_cap` and `amount_spent`; with no prepaid remainder, fall back to spend against the cap and the manual `balance` field. And Piero's portfolio can only grant MANAGE to the system user on accounts where the client gave his portfolio that level |
| Metrics on offer | Piero's: **Custo por lead, Leads** (as defined above), **Alcance, Visualizações** (`impressions` until Meta's Ads API offers "views"; the spike checks), **Valor investido, Saldo**. Suggested for a traffic analysis: **Frequência** (above ~3 the audience is tiring), **CTR (link)** (is the creative pulling clicks; CPC (link) is already Custo por lead), **CPM** (cost of the audience), **Conversas iniciadas / custo por conversa**, **Taxa de conversão** (leads ÷ link clicks: the landing page or the WhatsApp script), **Ritmo de gasto** (spend against budget for the period), for video **ThruPlays and hook rate** (3-second views ÷ impressions), for sales **Compras, ROAS**; and on the campaign page the **best and worst ads** by cost per lead |
| Screens | A **Campanhas** tab (the phase-1 tab's name becomes this): one row per client, its tracked campaigns under it with the period's **Investido, Leads (cliques no link), Custo por lead, Alcance, Impressões**, and the account's **Saldo**. Opening a campaign shows the per-day chart and the metric picker (below). Phase 1's daily check (**Visto hoje**, "3 de 5 clientes vistos") lives on these same rows, not on a second screen. **Equipe → Meta keeps only the account list and the client mapping**; the account-wide monthly totals leave it: Piero's "Investido este mês" there (R$ 148,94) added every campaign in the account, five of them ended on 17 Oct, while his Ads Manager view of the two live campaigns showed R$ 31,58. Charts are plain SVG drawn by `app.js`: no chart library, CSP stays `'self'` |
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
  the auto-created campaigns and the login flow made it bigger than the first draft's 3–4).
  The Meta app itself already exists (Du7's, see "Whose Meta app").
  The clients are already partners. Business verification, if Meta asks for it, can take
  days to weeks. It can ship in two releases: numbers, filters and cards first; analysis
  text and suggested metrics second.
- Phase 2 depends on Meta's rules for the Limited tier, which Meta describes as for
  development. If the spike fails, or Meta tightens Limited later, the integration waits
  for App Review under Du7 (verified already; the review itself takes days to weeks and
  needs the pauta.cc legal pages); the phase-1 list keeps working, since the numbers are an
  addition to it, not its basis.
- The Meta app is Du7's: Du7 answers to Meta for it (data use checkups, policy mail to
  du7@msn.com), and a problem with the app affects every team connected to it.
- Reading the balance may need the system user to hold "Gerenciar campanhas" on each
  client's account. The login configuration asks for ANALYZE only today; the wider task
  would be a second configuration (ADVERTISE) and Piero reconnecting. The token's
  `ads_read` scope keeps Pauta read-only either way, but the role would be wider than
  reading; if that is unwelcome, the balance stays manual.
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
- **The app in Piero's portfolio, with a system user he makes by hand** (this record's
  first plan): no login flow to build, but his portfolio isn't verified, so App Review was
  closed to it, and every future team would repeat the manual setup. Du7's verified app
  with Facebook Login for Business does both jobs.
- **Piero's personal token via Facebook Login** (reconsidered 2026-10-31, see "More than
  one ad account"): no system user needed, but it expires in
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

## Spike result (2026-10-31, on acceptance)

Piero connected through Pauta's own "Conectar Meta" (eduelias/pauta#19, not curl), in
development mode, on the Limited tier, as a Tester of Du7's app. Pauta read his one chosen
ad account: active, with this month's spend, impressions, reach, link clicks and cost per
click. So **development mode reads it; App Review is not needed to go on.** The balance was
refused with ANALYZE, as expected: it needs the wider task (see "Saldo"). One field also
needs more than `ads_read`: `business{name}` on ad accounts asks for `business_management`,
so Pauta doesn't request it (the portfolio's name comes from `client_business_id`).

### More than one ad account (Piero, 2026-10-31)

Piero's next remark: "só tá aceitando uma conta"; the ideal is to connect each new client's
account when he starts its campaign. The limit was ours, not Meta's: the token covers every
account ticked in Meta's login and Pauta already listed them all, but once connected the
panel offered only Atualizar and Desconectar (and the spike asked him to tick only one).
**Adicionar contas** (eduelias/pauta#19) runs the login again; he ticks the old and the new
accounts, since Meta's docs don't say whether a second login adds to the earlier choice or
replaces it. The other way in needs no Pauta at all: Business Settings → Integrations →
Connected apps → Pauta → add the account, then Atualizar. One connection per team stays
the model: one system user in the agency's portfolio, reading every client account it is
given; `meta_account` (above) ties each one to its Pauta client.

**Reconsidered and settled (owner, 2026-10-31): the robot stays.** The alternative was a
*user* token: Piero signs in as himself once, and `/me/adaccounts` returns every account his
profile can reach, new clients included, with no per-client step. It costs a re-login about
every 60 days (long-lived user tokens have no refresh), dies with his password or a sign-out
everywhere, and carries his identity rather than a robot's; Meta's management API can only
narrow a token's assets, never widen them, so there is no middle way short of giving the
robot `business_management` and letting Pauta write permissions in his business, which
breaks "Pauta only reads". One Meta-side click per new client, in the place Piero already is
when he accepts that client, was judged the smaller cost. The panel says where that click is.

Adding his other clients **on acceptance** goes past the one-client exception to decision 1
("Tested on acceptance"). That is the owner's call: either acceptance becomes Piero's working
place for the Meta numbers until phase 2 is released (and is treated like production for
data: backups, access), or the next accounts wait for production.

## Open questions

Answered by Piero on 2026-10-31, in two rounds: portfolio = the client's Meta business
portfolio, one per client, with one or more ad accounts; period filter defaulting to the
current month; both "Criar" and "Reativar campanha"; a daily "seen" mark per client; the
metrics above; a lead is any click to the ad's destination; the balance only to read; the
text for the client written by an AI; his portfolio is not business-verified and the clients
are partners in it. The owner then registered Pauta's Meta app under Du7's verified business
(see "Whose Meta app").

Still open:

1. **The spike** (Piero and the owner, one hour, one client's account, on acceptance):
   Piero is a Tester on the Pauta app since 2026-10-31. Does the login reach a partner-shared client account in
   development mode, is the balance readable with ANALYZE, and does a WhatsApp click count
   as a link click.
2. **If the spike fails** (owner): App Review for Advanced `ads_read` under Du7 (Tech
   Provider step, screencast, pauta.cc legal pages), or buy a tool for the numbers and keep
   phase 1.
3. **If the balance needs "Gerenciar campanhas"** (owner and Piero): accept the wider role
   for the system user, or keep the balance manual.
4. **The AI key** (owner): whose Anthropic account pays, and the monthly cap on it.
