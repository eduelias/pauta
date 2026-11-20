# 7. Financeiro: a receivables ledger per client

- **Status:** shipped in 1.5.0 (2026-10-30), fixed in 1.5.1. Proposed the same day
- **Depends on:** nothing. **Fits:** decision 5 (one database per team: everything here is
  in the team's file) and decision 6 (plans live in `control.db`; nothing here touches them).
- **Changes:** adds a `Financeiro` tab, a `Pagamentos` card on the client page and a
  `Financeiro` panel on Equipe; the mobile tab bar shows Financeiro instead of Quadro.
- **Amended by:** decision 10 (1.7.0): Equipe is Configurações, so the panel is on
  Configurações → Financeiro.
- **Amended by:** decision 8 (1.7.0): on the phone, Campanhas takes Quadro's slot when Meta
  is on; Financeiro has it only with Meta off.
- **2026-11-20:** not built as of 1.15.1: a way to set a cycle's explicit start (the column
  `billing.started` exists; no route, command or screen writes it).
- **2026-11-20:** the code differs: the screens do not use the currency stored on the
  cycle. The panel formats every amount with the team's current setting, and the client
  card formats all payments with the open cycle's currency; `payment` has no currency.
- **2026-11-20:** the code differs: "integer cents, never floats" holds for the tables.
  The default fee setting is a float in currency units, and the API answers amounts as
  cents divided by 100.
- **2026-11-20:** the code differs: `/api/export` carries the payments and the finance
  settings, not the `billing` rows (the cycles).

## Context

The person who runs the campaigns gets paid per active client, as each client pays: R$ 100 in
the first month, a little more later. The partner who pays doesn't wait for the month to close,
so he needs to know, per client, when he was last paid, which month that covered, who is late
and who is due this week. The deal counts months from the client's first payment (paid on the
29th: the month turns on the 29th), and a client that pauses or closes and comes back starts
counting again.

Pauta is going to be sold to other teams (decision 6), and most agencies have a version of
this: a monthly fee per client, paid by Pix or card, tracked today in a spreadsheet. What
differs between teams is the convention, not the need: when the month turns, how many days
of tolerance before "late", who in the team may see money, which currency.

## Decision

A **receivables ledger**: each billed client carries a recurring fee; the team records the
payments as they arrive; the app derives who is paid, late, due soon or still waiting for a
first payment. Pauta records money that already moved. It does not invoice, charge, send
Pix, reconcile bank statements or compute taxes: those are products of their own, none of
them is needed to answer that question, and keeping away from them means no card data,
no bank credentials and nothing of ours touching a customer's money.

| Topic | Decision |
|---|---|
| Data | Three additive tables in the team's database: `setting` (per-team configuration, JSON per module), `billing` (one **cycle** per stretch of a client being Ativo and billed: fee in cents, currency, optional explicit start, `ended` when closed) and `payment` (client, cycle, date, cents, method, note, who recorded it, and `voided_by/voided_at`). A `billed` flag on `client`. Schema v6 |
| Money | **Integer cents**, never floats; the currency code is stored on the cycle so a team changing its currency later doesn't rewrite history. The browser formats with `Intl` |
| Cycles | A cycle opens when a billed client becomes Ativo (or is created Ativo) and closes when it leaves Ativo or stops being billed. Coming back opens a **new** cycle: the month count restarts and the day is set again by the next payment, which is what was asked for. Coming back on the same day (un-ticking "Cobrado" by mistake and ticking it again) reopens the cycle that was closed, count and payments kept (2026-11-20). The cycle's age is the "4º mês ativo" |
| Ledger | Payments are **voided, never deleted**: the list is an audit trail. The person who recorded a payment, or an admin, may void it |
| The engine | `finance.py`, pure functions with no SQLite: from a cycle, its live payments and today, it generates the expected periods (monthly, weekly or yearly; the day of month clamps to the month's last day and comes back after a short month), allocates payments **oldest-first** against them, and derives the status, next due date, amount owed and months active. Nothing derived is stored, so a configuration change recalculates everything consistently; partial and double payments and future price steps need no special cases |
| Statuses | For Ativo, billed clients only, in this order on the panel: `late` (a period's due date plus the grace days has passed unpaid), `due` (a period is due, inside the grace days), `due_soon` (the next period starts within the configured window), `awaiting_first` (no payment yet, with the first-payment anchor), `paid` (everything up to today covered) |
| Anchor | How a cycle's first period starts is a team setting: `first_payment` (this team: the first recorded payment sets the day), `client_since` (the "cliente desde" date), `fixed_day` (everyone on the same day of the month). A client without a "cliente desde" date counts from the day its cycle opened |
| Settings (per team, admins, Configurações → Financeiro) | `enabled`, `currency`, `amount` (the default fee new clients get), `cadence`, `anchor`, `fixed_day` (1 to 28, for the `fixed_day` anchor), `due_soon_days` (7), `grace_days` (0), `visibility` (`all` or `admins`), `bill_new_clients`. Validated like `CLIENT_FIELDS`; sent in the boot data so the UI never guesses |
| Visibility | `visibility` is enforced in the routes, not only hidden in the UI: with `admins`, members get 403 on every finance route and the client payload carries no money. With `enabled` off the routes answer 404 and the tab is gone; the two settings routes still answer admins |
| API | `GET /api/finance` (summary and one row per client; with `?month=YYYY-MM`, also that month's payments and what was received in it and in total); `GET|PATCH /api/finance/settings` (admin); `PATCH /api/clients/{id}/billing` (fee, billed); `POST /api/clients/{id}/payments`; `DELETE /api/payments/{id}` (void). `GET /api/clients/{id}` gains `billing` and `payments`; `/api/export` includes both |
| UI | **Financeiro** tab after Clientes (on the phone it takes Quadro's slot: the person who runs the campaigns filters Pedidos instead); summary numbers, which are also filters ("Recebido" opens the month's payments, with a month picker), then the groups above, each row with the client, months active, due date, last payment and a **Registrar pagamento** button (date defaults to today, amount to the fee). A **Pagamentos** card under Atalhos on the client page with the fee, the list and the form |
| Multi-team | Everything is in the team's file and keyed by nothing global, so decision 5 picks it up unchanged. `/metrics` stays counts only, never amounts |

## Consequences

- About 2 days: schema, engine and its tests, routes, three screens, browser tests.
- Existing Ativo clients get an open cycle when the database migrates; with the
  `first_payment` anchor they show as "Aguardando 1º pagamento" until the first real payment
  is recorded with its real date, which anchors the cycle. Backdating is the normal way in.
- The mobile tab bar loses Quadro (still in the sidebar, the dashboard and `#/quadro`).
- "Continue counting after a pause" is not offered: with one `ended` per cycle it would
  either charge the paused stretch or need pause intervals. If a team asks, it becomes a
  setting with a `paused` table, additive.
- Later, in this order: per-month price steps (`[months → amount]` in settings; the FIFO
  allocation already copes), a CSV export, a WhatsApp nudge "3 clientes vencem esta semana"
  through the existing alert path, and a "dia de vencimento" override per client.

## Alternatives considered

- **Storing which month each payment covers:** simpler to read back, but wrong as soon as a
  payment is partial, doubled, voided or backdated; the allocation has to be recomputed then
  anyway. Deriving it keeps one source of truth.
- **A `payments` sheet in OneDrive:** keeps Pauta out of money entirely, but no statuses, no
  "due this week", and two places to look. The ledger is small and private data anyway.
- **Full invoicing (NFS-e, Pix charges):** out, see the decision. Asaas/Paddle-style
  integrations can hang off the ledger later without changing it.
