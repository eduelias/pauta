# 8. Acompanhamento: following up live campaigns, then their numbers from Meta

- **Status:** proposed (2026-10-31), nothing built
- **Asked by:** Piero, who runs the campaigns (WhatsApp, 2026-10-31)
- **Depends on:** nothing for phase 1. **Fits:** decision 5 (one database per team: the
  tables are in the team's file, the Meta token is a file next to it) and decision 7 (same
  shape: a settings block per module, statuses derived, never stored).
- **Changes:** adds an `Acompanhamento` tab, a `Campanhas` card on the client page and an
  `Acompanhamento` panel on Equipe; phase 2 adds a Meta connection on Equipe and a daily sync.

## Context

Piero's job doesn't end when a campaign goes live: he follows each one up (reads the numbers,
adjusts budget, audience, creatives) and reports to the client. Pauta tracks the work up to
"Concluído" and then forgets the campaign. Today that is 3 live campaigns for about 4
clients, kept in his head; he is preparing for more, and the risk he names is skipping a
client.

What he asked for, in his order of ambition:

- **The dream:** campaign numbers pulled from Meta, as cards and charts, filterable by client
  and by "portfolio".
- **The minimum, if Meta doesn't work out:** every request of the "fazer campanha" type that
  is marked done lands in a list; from there it moves to a list of active campaigns where he
  records by hand the date of his last analysis of each one, so he goes through every client
  without skipping one.

What Pauta has today: a request's type is `request.kind`, from the editable `kind` list
whose default is **"Criar campanha"** (Piero's "fazer campanha"); `done_on` is set when a
request reaches Concluído; a request has a `campaign_url` (the link in Ads Manager); a client
has an `ad_account` id and a `state` (Ativo/Pausado/Encerrado). There is no notion of a
campaign that outlives its request.

Meta's side was researched on 2026-10-31 (sources at the end) and is summarised under phase 2.

## Decision

Build it in two phases that each stand on their own. **Phase 1** is the minimum Piero
described and is useful without Meta. **Phase 2** reads the numbers from Meta's Marketing
API into the same campaigns. Pauta only **reads** from Meta: it never creates, edits, pauses
or pays for anything there.

### What a campaign is

A **campaign** is something live that someone follows up: one client, usually born from one
done "Criar campanha" request, with a start, an optional end, and a log of **analyses**
(date, who, a note). It is not a Meta campaign; in phase 2 it can be **linked** to one or
more Meta campaign ids, because what Piero calls "a campanha da clínica" may be several
campaigns in Ads Manager (one per objective or audience).

### Phase 1: the follow-up list (manual)

| Topic | Decision |
|---|---|
| Data | Two additive tables in the team's database, schema v7. `campaign`: `client` (cascade), `request` (nullable, unique, `SET NULL` if the request is deleted), `name`, `started` (date), `state` (`active`, `paused`, `ended`, `skipped`), `ended` (date), `every_days` (nullable: overrides the team's cadence), `note`, `created_by`, `created`, `updated`. `review`: `campaign` (cascade), `on` (date), `account`, `note`, `created`. Settings in the existing `setting` table under `tracking` |
| Where campaigns come from | A request whose `kind` is one of the team's **tracking kinds** (default `["Criar campanha"]`) and whose status is `done`, with no campaign yet, appears in **"Para acompanhar"**. One tap: **Acompanhar** (creates the campaign: name from the request's `what`, `started` from `done_on`, linked to the request) or **Não acompanhar** (a `skipped` row, so it never comes back). This is Piero's first list, and it also picks up the campaigns already done before this ships, with no guessing in the migration. A **Nova campanha** button covers campaigns that never had a request |
| Why not create them automatically | A done "Criar campanha" request isn't always a live campaign (the client gave up, it was merged into another). One tap keeps the list honest; the inbox has a counter in the nav, like Pedidos, so it can't be missed |
| Last analysis | Not a column: the latest `review.on` of the campaign. **Registrar análise** asks for the date (today by default, backdating allowed) and an optional note ("CPL subiu, trocar criativo"). The log is the history on the campaign page; the author or an admin may delete an entry |
| Next due | `last analysis + every_days` (campaign override, else the team's, default **7**). Never analysed: due from `started` |
| Statuses (derived, in this order) | `never` (no analysis yet), `overdue` (next due has passed), `today`, `soon` (due within `soon_days`, default 2), `ok`. Campaigns of a client that is not Ativo, and `paused` campaigns, drop out of the due list and show greyed. Nothing derived is stored, so changing the cadence recalculates everything |
| Pausing and ending | Buttons on the campaign: Pausar, Reativar, Encerrar (sets `ended`). A done "Pausar campanha" request does not pause anything by itself in phase 1 (see Consequences) |
| Settings (per team, admins, Equipe → Acompanhamento) | `enabled`, `kinds` (from the `kind` list; a warning shows if one was renamed away), `every_days` (7), `soon_days` (2). Validated like `FINANCE_FIELDS`, sent in the boot data |
| API | `GET /api/tracking` (inbox and campaigns with derived status); `POST /api/tracking/start` (from a request id, or a client and name); `PATCH /api/campaigns/{id}` (name, state, `every_days`, note); `POST /api/campaigns/{id}/reviews`; `DELETE /api/reviews/{id}`; `GET|PATCH /api/tracking/settings` (admin). `GET /api/clients/{id}` gains `campaigns`; `/api/export` includes both tables |
| UI | **Acompanhamento** tab after Pedidos. Top: "Para acompanhar" (only when not empty). Then **by client**, worst status first, each client showing its campaigns with "última análise há N dias", the next due date, the last note and **Registrar análise**. Grouping by client is the point: Piero goes down the list client by client and nothing is skipped. On the Painel a stat "Análises atrasadas". On the client page a **Campanhas** card. On the request page of a tracked request, a link to its campaign. Marking a "Criar campanha" request Concluído shows a toast "Vai para Acompanhamento" |
| Timeline | Starting, pausing and ending tracking leave an `event` on the originating request, so the request's history says what happened after Concluído |

### Phase 2: numbers from Meta

Phase 2 starts with a **one-hour spike** (step 0 in the table) and is only built if it
passes. What Meta offers, in short: the Marketing API's Insights endpoint gives per-campaign
daily spend, impressions, reach, frequency, clicks, CTR, CPC, CPM and "actions" (messages
started, leads, purchases...) with their cost, plus breakdowns by age, gender, region,
platform and placement, for 37 months back (13 for reach with breakdowns). It is free; the
cost is setup and keeping up with Meta's yearly API versions. An agency reads its clients'
ad accounts when each client adds the agency's **business portfolio** (Meta's new name for
Business Manager) as a partner on the ad account; the agency then gives a **system user**
(a robot account in its own portfolio) "Ver desempenho" on that account and makes a token
for it with `ads_read`. System user tokens don't expire like personal ones (about 60 days).

| Topic | Decision |
|---|---|
| Step 0: the spike | Before any code: the team's Meta admin creates a Business-type app owned by the team's business portfolio, adds the Marketing API product (it starts on the **Limited** tier), creates one regular system user, assigns it one client's ad account with "Ver desempenho", generates a token with `ads_read`, and the owner reads that account's last 30 days with one `curl` to `/act_<id>/insights?level=campaign&time_increment=1` on v26.0. The token's real expiry is checked with Meta's token debugger. Pass = numbers come back without App Review. If they don't, phase 2 waits for business verification and App Review, or the team buys a tool (Alternatives) |
| Whose Meta app | Phase 2 is for **this** team: the app and the system user belong to the team's own business portfolio, so Pauta reads accounts the team itself has been given. A Pauta-owned app that every customer team connects with "Login do Facebook para empresas" is the decision-6 version: it needs Full access, App Review and business verification of Du7, so it is a decision of its own, taken when a second team asks |
| Access tier | Start on **Limited**. Meta calls it "for development", and its wording says apps reading "other people's ad accounts" need advanced access; whether partner-shared client accounts read by the agency's own system user count is not settled in Meta's docs. A few calls per account per day is far inside Limited's quota (600 + 400 × active ads per hour per account). Moving to **Full** needs App Review, 500 successful calls in 15 days and under 15% errors; plan for it if Meta pushes back, and add the privacy policy, terms and data-deletion instructions URLs Meta wants for Live mode or review anyway (decision 5's legal texts on the public site cover them) |
| Token | A file next to the team's DB, `pauta.db.meta-token`, mode 600, like the OneDrive token (decision 3): never in the DB, its backups, the export or the logs. An admin pastes it on Equipe → Meta; the field is write-only, and Pauta only shows "conectado", the business it belongs to and its expiry (from `debug_token`). One token per team under decision 5 |
| Which accounts | The client's existing `ad_account` id. Pauta lists the accounts the token can see and marks each Ativo client "Meta: lendo" or "Meta: sem acesso", which turns the existing `access` field (Liberado/Solicitado/Pendente) into something checked, and tells Piero which clients still have to add the agency as partner |
| Linking | `campaign_meta(campaign, meta_id)`: a Pauta campaign links to one or more Meta campaigns of its client's account. Suggested automatically when the request's `campaign_url` (an Ads Manager link) carries the campaign id; otherwise picked from a list of the account's campaigns |
| Sync | `pauta meta sync`: per linked account, one Insights call at campaign level, daily rows (`time_increment=1`) for the **last 28 days**, re-read every night because conversions keep arriving for up to 28 days after a click; older days are frozen. A nightly `pauta-meta-sync.timer` next to the backup timer (a `deploy/` change, owner-reviewed), plus an "Atualizar agora" button limited to once per 15 minutes. Backoff on Meta's throttle headers and error codes; nothing retries in a loop. `/metrics` gains `meta.{enabled,connected,error,last_sync}` for du7's watchdog |
| Data | `insight` (additive): `meta_id`, `day`, `spend_cents`, `currency`, `impressions`, `reach`, `clicks`, `results`, `result_type`, `link_clicks`, `fetched`; key (`meta_id`, `day`). Reach and frequency aren't additive over days, so totals for a period (7, 30, 90 days) are fetched as such and kept in `insight_total`. Money in integer cents in the ad account's currency, as in decision 7. Raw Meta JSON is not stored |
| "Resultado" | What counts as a result depends on the request's `goal`: a team setting maps each goal to a Meta action type, defaulting to Mensagens no WhatsApp/Direct → conversations started, Cadastros → `lead`, Vendas no site → purchases (plus ROAS), Tráfego → link clicks, Reconhecimento → reach, Engajamento → post engagement. The defaults are checked against the team's real accounts in the spike |
| Screens | **Acompanhamento** keeps the phase-1 list and gains, per campaign, a row of cards (Investimento, Resultados, Custo por resultado, CTR, CPM, Frequência) with the change against the previous period, and a daily chart of spend and results. A **Painel de campanhas** view above it totals the same cards for the filter: **cliente**, **carteira** (Piero's "portfolio", see Open questions; deliberately not called "portfólio", which in Meta means the business portfolio), period and status. Charts are plain SVG drawn by `app.js`: no chart library, CSP stays `'self'`, no new dependency |
| Analyses get numbers | **Registrar análise** stores a snapshot of the cards at that moment on the `review` (an additive `snapshot` JSON column), so "CPL subiu" is next to the CPL it was about |
| Breakdowns | Age/gender, region and platform/placement on the campaign page, fetched on demand for the chosen period and cached for the day, not synced nightly |
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
- Phase 2 is about 3–4 days of code after a spike that passes, plus Meta-side setup outside
  the code: the app, the system user, and each client adding the agency as partner. Business
  verification, if Meta asks for it, can take days to weeks.
- Phase 2 depends on Meta's rules for the Limited tier, which Meta describes as for
  development. If Meta tightens it, the integration stops until App Review is done; the
  phase-1 list keeps working, since the numbers are an addition to it, not its basis.
- Meta changes metrics and retires API versions every year: expect a small maintenance
  release per year, and a goal → result mapping that needs a look when Meta renames actions.
- The token can read every ad account assigned to the system user. Anyone with du7 root
  can read it; it is not in backups. Revoking it in Meta's Business Settings cuts Pauta off
  at once.
- Insights are aggregated numbers about ads (no names of people who saw or clicked), so
  LGPD exposure is low; they are still the client's data, in the team's file, covered by
  decision 5's processor terms when other teams arrive. The Meta data is never shown outside
  the team or passed to anyone.
- The tracking kinds are matched by name. Renaming "Criar campanha" in Equipe takes it out
  of the inbox until the setting is updated; the settings panel warns about it.
- A done "Pausar campanha" or "Reativar campanha" request doesn't change the campaign's state
  in phase 1. If Piero wants it, it's a small rule later (a done request of those kinds on a
  client with one active campaign changes it, otherwise asks).
- Later, in this order: a WhatsApp reminder "3 campanhas sem análise há mais de 7 dias";
  a PDF or link report per client for the client itself, built from the cards; per-campaign
  targets (CPL goal) with a warning when a campaign is off target.

## Alternatives considered

- **Creating the campaign automatically when the request is done:** one step less, but
  requests that never went live would fill the list with things to end. The inbox costs one
  tap and keeps the list true.
- **A "última análise" column on the request:** the smallest change, but a campaign outlives
  the request that created it and later requests (new creatives, budget) belong to the same
  campaign; and one date has no history or notes.
- **Buying a reporting tool** (mLabs, about R$ 30 per client per month; Reportei, Windsor.ai
  with Looker Studio, Supermetrics): dashboards, client reports and organic insights today,
  with Meta's review handled by them. A real option for phase 2's "NASA" part, and it combines
  with phase 1: the client page can hold the report's link. It costs money per client as the
  team grows and puts the numbers in another place than the follow-up list.
- **Ads Manager's scheduled email reports or CSV export:** free and already there, but
  per account, by email, and nothing records whether someone looked.
- **Personal user tokens via Facebook Login:** no system user needed, but they expire in
  about 60 days and die when that person's access changes; the system user is the pattern
  Meta recommends for server-to-server reading.
- **Syncing ad sets and ads, or storing Meta's raw responses:** more detail than Piero's
  question needs and more to keep up to date. Campaign level first; ad level can come for
  one campaign on demand if he wants to compare creatives.

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
- Insights, breakdowns, 2025–2026 metric and attribution changes:
  https://developers.facebook.com/docs/marketing-api/insights,
  https://developers.facebook.com/docs/marketing-api/insights/breakdowns,
  https://developers.facebook.com/blog/post/2025/10/16/ads-insights-api-metric-availability-updates/
- Rate limits:
  https://developers.facebook.com/documentation/ads-commerce/marketing-api/overview/rate-limiting
- App modes and data deletion:
  https://developers.facebook.com/docs/development/build-and-test/app-modes,
  https://developers.facebook.com/docs/development/create-an-app/app-dashboard/data-deletion-callback
- Organic insights: https://developers.facebook.com/docs/instagram-platform/overview,
  https://developers.facebook.com/blog/post/2025/08/15/page-insights-api-updates/
- mLabs prices: https://www.mlabs.com.br/blog/mlabs-planos/; Windsor.ai: https://windsor.ai/pricing/

## Open questions for Piero

1. **"Portfolio"**: what is it to you? A group of clients by segment (Estética, Saúde...,
   which Pauta already has), the clients each person in the team looks after (a
   "carteira"), groups of campaigns inside one client (products, units), or the client's
   business portfolio in Meta?
2. How often should each campaign be analysed: every 7 days for all, or does it depend on
   the client or the budget?
3. Which request types should feed the list: only "Criar campanha", or also "Reativar
   campanha"? Is one "Criar campanha" request one campaign to you, or can it be several?
4. When you analyse, what do you write down today, and do you send the client a report? (It
   decides whether the note is enough or we want a report per client.)
5. For Meta: do the clients' ad accounts already appear in the agency's business portfolio
   (as partner), or do you get in with your personal profile? Who is the admin of that
   portfolio, and is it verified?
6. Which numbers matter most per type of campaign (for WhatsApp campaigns: cost per
   conversation?), and over which period do you compare (last 7 days against the 7 before)?
