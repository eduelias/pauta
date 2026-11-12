# Campanhas, "Visão geral": every client at once, the ones that need a look first

- **Status:** phases A and B built with this document (2026-11-12), at the owner's word
  ("whatever we can now"); see "What was built" at the end for what differs from the
  sketch. Phase C and the questions for Piero are open.
- **Asked by:** Piero, in a voice note of 2026-11-11, thinking aloud about the day he has 50
  or 60 clients instead of 12.
- **Builds on:** decision 8 (Acompanhamento: the daily check, the numbers from Meta) and
  decision 12 (the client's report link, which this view is *not*).

## What Piero asked for

With 12 clients, scrolling the Campanhas list and reading each client's numbers is fine, and
he says so. With 50 or 60 he would want an internal dashboard tab, never sent to a client,
that shows every client at once and tells him "this one is dropping, look at this one". He
imagined a chart with one line per client and said himself that it was a first thought.

## Evaluation

**The need is real, and it is decision 8's risk grown up.** Decision 8 named the risk as
skipping a client, and "Visto hoje" answers it: did I look at everyone. At 12 clients he
looks at everyone daily. At 50, a minute per client is most of an hour, and the question
changes to: who do I look at first. That is triage, and the list has none.

**It is cheap, because the numbers are already here.** The sync stores one row per campaign
per day (`insight`: spend, impressions, link clicks, results and their indicator), refreshed
hourly for today and yesterday and nightly for 28 days. An overview is one grouped query
over that table for two adjacent periods. No new call to Meta, no new table, no schema
change. For 60 clients over 28 days that is a few thousand rows.

**The chart as imagined would not work; its intent does.** Fifty lines on one chart cannot
be read, and clients differ by a factor of a hundred in spend, so the small ones are flat
at the bottom. What he wants from it is to see a shape per client and spot the one bending
the wrong way. A small trend line on each client's row does that for all of them at once,
and a comparison chart of a few picked clients, each on an index of 100, covers the rest.

**"It tells me" should be rules, not an AI, in the first cut.** A sentence such as "custo
por clique subiu 42% em 7 dias" comes from arithmetic he can check against Ads Manager.
Rules are testable and explain themselves. Decision 8's AI text can later write a note
about a flagged client; it should not decide who is flagged.

**Three things make the numbers lie if ignored:**

- **Late conversions.** Results keep arriving for up to 28 days after a click, so the last
  day or two always look worse than they are. Comparisons should end yesterday and never
  include today.
- **Small numbers.** A client spending R$ 5 a day goes from 2 results to 1 and "drops 50%".
  Every rule needs a floor (a minimum spend and count in both windows) or it cries wolf.
- **Different objectives.** Cost per result compares within a client over time, not between
  a lead campaign and a traffic campaign. The one figure that compares across everything is
  the one Piero defined as a lead in decision 8: a click through to the destination.

## Sketch

A second tab on Campanhas, "Visão geral", for members of the team only. It is never part of
`/r/<token>`.

**One row per client with tracked campaigns:**

| Column | From | Note |
|---|---|---|
| Client, segment, portfolio | `client`, `meta_account` | Opens the client's Campanhas |
| Live campaigns | `campaign` | A count |
| Spent in the period | `insight` | In the account's currency; no total across currencies |
| Link clicks, cost per click | `insight` | The comparable pair, on every row |
| Results, cost per result | `insight` | Only when all the client's campaigns count the same thing, the rule the client total already follows; a dash otherwise |
| Change against the period before | Two adjacent windows | An arrow and a percentage for cost and for volume |
| Trend | 14 daily points | A small line; the metric is picked once for the whole table (spend, clicks, cost per click, results) |
| Balance, days left | Meta's cached account list, spend of the last 7 days | Blank when Meta does not give a balance |
| Visto hoje | `review` | The mark the list already has |
| Flags | Below | One short sentence each |

Sorted by "needs a look" first, then by spend. Filters: the period control the list has,
portfolio, segment, "só com alerta". Reach is left out: it does not add up across campaigns
and would need a call to Meta per row.

**Flags.** Fixed rules, with thresholds as team settings and these defaults:

| Flag | Rule | Reads as |
|---|---|---|
| Custo subindo | Cost per click, or per result where comparable, up 30% or more, last 7 days against the 7 before, with at least R$ 20 spent in each | "custo por clique subiu 42% em 7 dias" |
| Volume caindo | Clicks or results down 30% or more while spend stayed within 15% | "resultados caíram 35% com o mesmo investimento" |
| Parou de entregar | A live campaign with no impressions yesterday and today | "sem entrega desde ontem" |
| Saldo acabando | Balance divided by the daily average of the last 7 days is under 3 days | "saldo para 2 dias" |
| Sem números | The portfolio's last sync failed, or the account cannot be read | "sem dados: conecte de novo" or the sync's reason |
| Não visto | Live campaigns and no Visto hoje for 2 days | "sem análise há 3 dias" |

"Sem números" matters as much as the others: a client whose numbers stopped arriving must
not look healthy by being quiet.

**API and code.** One read-only route, `GET /api/campaigns/overview?since=&until=`, open to
members like the list, and one `Store` method that runs the grouped query for the period
and the one before it. The flags are a pure function of the rows, with unit tests. One new
screen in `app-campanhas.js`. No Meta call, no write, no migration.

## Phases

| Phase | What | Size |
|---|---|---|
| **A. The table** | Rows, the comparable pair, change against the previous period, the trend line, sorting and filters | ~2 days |
| **B. The flags** | The six rules, their settings on Configurações with the defaults, balance and days left, "só com alerta" | ~1.5 days |
| **C. Compare** | Pick up to five clients, one chart, each on an index of 100 | ~1 day |
| Later, each its own question | A morning message ("3 clientes pedem atenção"), which needs a sending channel Pauta does not have; thresholds per client; an AI note on a flagged client | |

## Recommendation

Build A and B together, about three and a half days, and do not wait for 50 clients. At 12
it already orders the daily pass and catches the two quiet failures the list hides: a
campaign that stopped delivering and a balance about to run out. C can wait until he asks.

**Against the multi-tenant work:** it neither needs it nor gets in its way. It is one
read-only route and one screen, so it can land before, between or after the refactor steps
of `docs/multi-tenant-spec.md` section 12. Under that spec it is an ordinary tenant route
needing `campaigns.read`; its amounts are in the "financial" class, so the operator's masked
support view would show the flags and the shapes without the money. A natural slot is right
after refactor step R2, which gives the team something visible during a stretch of
releases that otherwise change nothing on screen.

## Questions for Piero

1. When you say a client is "baixando", which number do you look at first: cost per
   result, the volume of results, or the spend? Default assumed: cost first, then volume.
2. Is last 7 days against the 7 before the right comparison, or do you think in months?
   Default: 7 against 7 for the flags, the screen's period for the columns.
3. Is "saldo para X dias" useful, and for which clients (prepaid accounts only)? Default:
   shown wherever Meta gives a balance.
4. Should Visão geral be what Campanhas opens on? Default: no, a tab beside the list, until
   he says he lives in it.
5. Are 30% and R$ 20 sensible floors for your clients' sizes? Default: yes, adjustable on
   Configurações.

## What was built (2026-11-12)

`GET /api/campaigns/overview`, `src/pauta/overview.py` (the windows, the sums, the flags:
pure functions), `Store.campaign_overview` (one read of `insight`), and the "Visão geral"
tab at `#/campanhas/geral`, which shares the list's period. Against the sketch:

- **The thresholds are team settings**, on Configurações → Campanhas, for admins (30%,
  30%, 15%, R$ 20, 5 counted, 3 days of balance, 2 days unseen by default; 0 switches the
  balance and the unseen alert off). They live in the `setting` table under `campaigns`,
  next to Financeiro's block, and come in `GET /api/boot`. The same block now holds the
  request kinds that put a campaign on air, which were fixed in the code until now.
- **A guard the sketch missed.** A client whose numbers start inside the earlier window is
  not compared with it: a new campaign's first weeks otherwise read as "cliques subiram
  1000%". The row shows a dash with the reason, and the cost and volume flags stay quiet
  until there are two whole windows.
- **"Custo subindo" and "volume caindo" never both.** At the same spend the second implies
  the first, so the row says it once.
- **"Não visto" only for a team that marks Visto hoje at all**, so a team that never used
  it isn't nagged on every row.
- **"Sem números" tells admins why** (the connection's error); members read only that the
  numbers are not arriving, as on the rest of Campanhas.
- **The balance is what is left before the account's spending limit**, the only figure
  Meta gives; an account without a limit shows a dash and never the flag.
- **Filters:** "só com alerta", segment, and what the trend line draws. No portfolio
  filter yet. The row opens the client's page, where its campaigns are.

### Avisar o cliente (added the same day)

The screen says who needs attention; the next step was still by hand (find the client's
conversation, type the message). A row now writes it:

- **Avisar do saldo**, only next to the "saldo para N dias" alert: how long the balance
  lasts at the last seven days' pace, what is left, and when to put credit in. It is the
  one alert whose fix is the client's to make.
- **Enviar resumo**, on any row with spend in the period: the period's investment, link
  clicks and, when the client's campaigns count the same thing, the results with the cost
  of each. No comparison with the period before: how to say a bad week is the person's
  call, not a template's.

A balance at zero is its own case (fixed the same day, after a real account sat at R$ 0,00
for two days under "saldo acaba hoje"): the alert reads "saldo acabou", absorbs "sem entrega
desde ontem" when both hold, is raised even with nothing spent in the last 7 days, and the
message says the balance ran out and the campaigns stay paused without it.

Both are plain `wa.me` links to the client's registered number with the text in the
address, so WhatsApp opens with the message in the box and nothing is sent until the person
sends it. The greeting takes the first name of the client's contact. A client without a
number gets `wa.me/?text=…`, where WhatsApp asks for the conversation. The other alerts
(cost, volume, delivery, no data, unseen) are the team's own work and get no message. The
texts are fixed in `app-campanhas.js` (`balanceText`, `summaryText`); a team's own wording
on Configurações is the next step if Piero wants it. A report link in the summary is not
there because links are per campaign (decision 12) and a client may have several.
