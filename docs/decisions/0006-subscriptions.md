# 6. Subscriptions: sold by Du7 Technology Services through Paddle

- **Status:** proposed (2026-10-30). Not legal or tax advice: the seller's accountant
  confirms the tax side before the first sale.
- **Depends on:** decision 4 (the domain Paddle approves) and decision 5 (teams to bill).

## Context

Other teams (decision 5) will pay a monthly or yearly subscription. The customers are small
Brazilian marketing teams and agencies; the seller is the owner's Dutch business, **Du7
Technology Services** (KvK 91476003), with the owner's Brazilian ME as a fallback. Wanted:
low fees, little code, and money that ends up in euros in the Netherlands.

What Brazilian customers pay with (research of 2026-10-30): Pix is about 42% of Brazilian
online payments and cards about 41%; boleto is fading (~8% in 2024). **Pix Automático**
(recurring Pix, since June 2025) is growing fast but still young. For a subscription that
renews by itself, that means card and Pix Automático; one-off Pix is ideal for yearly plans.

Options compared:

| Option | Cost (headline) | Pix / Pix Automático / card renewals | Seller of record, taxes, invoices | Money to NL |
|---|---|---|---|---|
| **Paddle** (merchant of record) | 5% + US$0.50, no monthly fee | Yes / Yes (since 3 Sep 2026) / Yes. Boleto not confirmed | Paddle. It collects and pays Brazilian taxes and issues the customer's receipt. Du7 invoices only Paddle | Monthly EUR payout to a Dutch bank, free, from €100 |
| Stripe, Dutch account | ~6% all-in for Brazil (Pix 2% + 1.5% intl + 2% FX; Billing +0.7%) | Yes / Yes / Yes. No boleto outside Brazil | Du7: its own invoices, its own tax position in Brazil | EUR |
| Stripe Managed Payments (merchant of record) | The above + 3.5% | Pix listed; eligibility for Dutch sellers not confirmed | Stripe | EUR |
| Asaas, through the Brazilian ME | Pix or boleto R$2.15, card 2.99% + R$0.49, NFS-e R$0.49, no monthly fee | Yes / Yes (CNPJ active ≥ 6 months) / Yes, plus boleto | The ME; NFS-e automatic | Through the ME: profit as dividends (10% Brazilian withholding since 2026), then Wise or similar (~1–2%) |

Sources: paddle.com/pricing, developer.paddle.com/changelog/2026/pix-automatico,
docs.stripe.com/payments/pix, stripe.com/nl/pricing, asaas.com/precos-e-taxas; the payment
share figures are EBANX/PCMI numbers as reported in the press.

## Decision

| Topic | Decision |
|---|---|
| Seller | **Du7 Technology Services**, selling through **Paddle** as merchant of record. Paddle is the legal seller to each Brazilian team and handles Brazilian taxes (including the 3.5% IOF on foreign purchases) and the receipt; Du7 has one customer, Paddle (UK), and invoices it monthly: a service outside the EU, so no Dutch VAT charged, still declared on the VAT return |
| Fallback | The owner's **Brazilian ME with Asaas**, if Paddle refuses the account or the domain, or if customers need a Brazilian service invoice (NFS-e) that Paddle can't issue. Pauta's billing code talks to one small provider module, so switching is a module, not a rewrite (see Code) |
| Plans (starting point; prices are the owner's call) | **Grátis:** 2 people, 1 client. **Equipe:** up to 5 people, unlimited clients, R$ 99/month. **Agência:** up to 15 people, R$ 249/month. Yearly = 10 months' price. Flat per team, not per person: agencies dislike per-seat pricing, and Brazilian peers charge R$30–50 per brand (mLabs), R$61 per person (Runrun.it) or R$279–399 flat for 5 people (Bitrix24) |
| What a plan limits | Active people and clients, nothing else. Checked when someone joins or a client is created; existing data is never hidden or deleted because of a limit |
| Trial | 14 days of Equipe for every new team, **without payment details**: Pauta runs the trial itself, Paddle only sees the team when it subscribes. After 14 days without a subscription the team drops to Grátis limits (read-only above them) |
| Payment methods | Card and Pix Automático for monthly and yearly renewals; Paddle shows what it supports for Brazil at checkout. Pix Automático mandates fix the amount, so plan changes apply from the next period (Paddle's rule), never mid-cycle |
| Checkout | A **checkout page on the public site** (`pauta.team/assinar`), which loads Paddle.js and is Paddle's "default payment link". The app's CSP stays `'self'`: the app only links there with the team's transaction id. No card or Pix data ever reaches Pauta |
| Managing the subscription | An **Assinatura** page in Equipe for team admins: plan, status, next charge, people/clients used, and a button to Paddle's customer portal (change card, receipts, cancel) |
| Webhooks | `POST /api/billing/paddle`: checks `Paddle-Signature` (`ts=…;h1=…`, HMAC-SHA256 of `ts:body` with the destination's secret, timing-safe, rejects old timestamps), stores each event once by its id, then updates the team's subscription. No session or Origin check (it's a server call) but its own rate limit and a body size cap. The secret is a file next to `control.db`, like the session key: never in the DB or its backups |
| States | `trialing`/`active`: everything. `past_due`: a banner for the team's admins, 7 days' grace. Then, and after `canceled` once the paid period ends: **read-only** (view, export, no new requests or files). After 90 days read-only, the owner is told and the team can be deleted on notice. Data is never deleted silently |
| Data | In `control.db`: `plan`, `subscription` (team, provider, customer and subscription ids, status, period end, trial end), `billing_event` (id, type, received, raw JSON). Additive, like every schema change |
| Email | A team's billing contact email is required to subscribe (Paddle asks for it at checkout and Pauta stores Paddle's customer id). It is separate from people's optional Gravatar email |
| Code | `billing.py` with a provider interface (`checkout_url`, `portal_url`, `verify_and_parse`) and `paddle.py` behind it, stdlib `urllib` only, like `onedrive.py`. Tests use a fake Paddle (`tests/fakepaddle.py`, like `fakegraph.py`), never the real API; Paddle's sandbox is for acceptance |
| Before the first sale | Paddle account for Du7 Technology Services; website approval for `pauta.team` (public landing page, prices, terms, privacy, refund policy, all in Portuguese); the accountant confirms the Dutch VAT treatment and income booking |

## Consequences

- About 3–4 days of code after decisions 4 and 5, plus the public site's pages.
- Fees: with the fixed US$0.50 (about R$ 2.70), 5% + US$0.50 is about 7.7% of R$ 99/month
  but about 5.3% of a R$ 990 year, one more reason to push yearly plans. Prices in BRL mean
  the euro payout moves with the exchange rate.
- Paddle's receipt is a foreign invoice. If agencies' accountants insist on an NFS-e, that's
  the trigger to revisit the fallback.
- The owner's Dutch income tax covers the payouts; nothing is owed in Brazil by Du7 directly
  as long as Paddle is the seller.
- Paddle can refuse or close an account (its acceptable-use rules, chargebacks). The
  provider module and the fallback keep that survivable.

## Fallback in detail: the Brazilian ME

Only if Paddle doesn't work out. Checks first:

- The ME's CNAE codes must cover software as a service or licensing (for example 6311-9/00
  or 6203-1/00) and the activity must be allowed in its tax regime; an accountant (*contador*)
  confirms and adds the code if needed.
- Asaas: Pix Automático needs the CNPJ active for 6 months; NFS-e issued per payment.
- Money to the Netherlands: the ME pays the owner dividends (10% Brazilian withholding on
  dividends sent abroad since January 2026, contested at the STF), then a transfer through
  Wise or similar. Dutch tax on those dividends, with the treaty credit, is the Dutch
  accountant's question. Paying the owner as a service fee instead costs far more in
  Brazilian withholding (roughly 25–35%).
- The ME, not Du7, would then be the processor for LGPD (decision 5) and the seller in the
  terms.

## Alternatives considered

- **Stripe from Du7's Dutch account:** about the same cost, but Du7 becomes the seller to
  each Brazilian company, with its own invoices and Brazilian tax questions. Kept in mind if
  Paddle refuses the account.
- **Stripe Managed Payments:** merchant of record too, but ~3.5% more and Dutch-seller
  eligibility unconfirmed.
- **EBANX, dLocal:** built for large merchants; no public pricing.
- **Lemon Squeezy, Polar, Creem:** no Pix.
- **Invoicing by hand (Pix to the ME):** fine for the first one or two teams in the beta, no
  code at all; doesn't scale and has the ME's tax costs.
