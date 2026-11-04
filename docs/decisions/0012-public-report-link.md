# 12. A public link to one campaign report

- **Status:** proposed (2026-11-04), built in this PR for the owner's review. It is the first
  exception to decision 2's rule that everything in Pauta needs a signed-in account.
- **Depends on:** PR 35 (the client's report, `#/relatorio/<id>`). **Amends:** decision 2
  (one read-only, expiring, unguessable page is open; nothing else changes).
- **Changes:** schema v13 (a `report_link` table, additive), `POST`/`DELETE
  /api/campaigns/{id}/links`, `links` on `GET /api/campaigns/{id}`, two open routes
  (`GET /r/<token>` and `GET /api/r/<token>`), `static/report.html`, `static/app-report.js`.

## Context

PR 35 gave the campaign page a report for the client: a card with the campaign, the client,
the period and the metrics marked on the page, each with one plain line and a bar per day,
to send on WhatsApp. It can go as a PNG through the phone's share sheet, and "Abrir conversa"
opens WhatsApp with the message ready. Piero then asked for "um link pro cliente acessar".
A `wa.me` link carries text only, and `#/relatorio/...` needs a passkey: the client has no
account and never will (decision 2: the team's data is private, the app is invite-only).
A PDF would have the same problem, since any file or page for the client needs an address
that opens without signing in.

So the question is not the format. It is whether Pauta may serve one page to someone who is
not on the team, and under what limits.

## Decision

Yes, for one card at a time, behind a random token, for a limited time, revocable, carrying
only what the card shows.

| Topic | Decision |
|---|---|
| What is public | One campaign's report card as the team saw it: the campaign's name, the client's name (with the initials avatar), the period, whether the campaign is active, paused or ended (and when), one tile per metric chosen when the link was made (the period's value, Ads Manager's label for Resultados, the plain line, a bar per day), the date of Meta's numbers and the first name of the teammate who prepared it. Nothing else: no phone, contact or address, no ad account or Meta campaign ids, no budgets, notes, requests or other campaigns |
| Only the chosen metrics | `GET /api/r/<token>` returns the period sums and the daily rows **filtered to the fields the chosen metrics need** (`report.py`, `METRIC_FIELDS`). A link for "Resultados" alone does not carry the spend; one for "Cliques no link" does not carry the Resultados. The period's reach (a live number from Meta) is read once, when the link is made, and stored on the link: an anonymous page never calls Meta |
| The token | `secrets.token_urlsafe(32)` (43 characters, 256 bits): not guessable, not enumerable. Stored as is, not hashed, so the campaign page can show the link again and the person can revoke it by its address; a copy of the database already holds everything a link shows, so hashing would protect nothing here. The route patterns keep tokens out of the request log (`/r/{param}`) |
| Lifetime | 30 days (`report.LINK_DAYS`) from creation, then 404. Not renewable: a new link is made instead |
| Revoking | From the campaign page ("Links do relatório": period, metrics, who made it, until when, **Revogar**). A revoked link is a 404 from then on; the row stays as history |
| One link per card | Asking for a link to the same campaign, period and metrics while one is still live returns that one, so a report shared twice has one address and one Revogar |
| The period is fixed | A link holds `since` and `until` as dates. "Este mês" on 4 November becomes 1–4 November for good: the client sees the report that was sent, not a page that keeps moving |
| The page | `/r/<token>` serves `static/report.html` with the title and `og:` tags filled in server-side (WhatsApp's preview crawler runs no JS): "Relatório da campanha X · Cliente Y · período", the campaign and client names in the preview as on the card. The page loads `app.js` and `app-campanhas.js` (the same `reportCard` the team's screen draws) and `app-report.js`, which fetches `GET /api/r/<token>`. CSP stays `'self'`; `noindex` stays on every response; `og:image` is Pauta's static one |
| Not available | Unknown, expired and revoked tokens get a 404 with a plain page, "Este relatório não está mais disponível", not the app shell and not a JSON error |
| Making a link | `POST /api/campaigns/{id}/links` with `{since, until, metrics}` needs a session (any member, as the report does), validates the period like `GET /api/campaigns/{id}` and the metrics against the card's keys (the ten fixed ones and `act:<type>`, 12 at most), and answers `{url, expires}` with the rest of the row. The address is the one the app is open on (`Origin`, else `Host`), so acceptance makes `acc.pauta.cc` links and production `app.pauta.cc` ones |
| Abuse limits | Making a link counts in the existing `invite` bucket (30 an hour per address); opening `/r/...` or `/api/r/...` counts in the `login` bucket (120 a quarter hour per address), as the Meta callback does: a guess is a login attempt. Both are matched by pattern in `server.py` (`RATE_PATTERNS`), so `ratelimit.py` is untouched. A bucket of its own for the public page would be cleaner; that is the owner's file |
| On the report screen | **Copiar link** makes the link on the first tap (and reuses it after) and copies it, with "válido até <date>" shown under the buttons. **Abrir conversa** sends "Veja o relatório aqui: <url>" at the end of the WhatsApp message: when the link already exists the button is a plain link, when it does not the tap makes it first and opens WhatsApp in a new tab (on an iPhone that first time may land on wa.me's page with its own "Continuar" button, since a navigation from script is not a tap) |
| Not exported | `report_link` is not in `/api/export`: the tokens are live addresses, and the export is a copy of the team's data, not of its credentials |

## What a link exposes, and for how long

Anyone holding the address, for 30 days or until it is revoked, sees: the campaign's name,
the client's name, the period, the campaign's state, the values of the chosen metrics
(money included, when "Valor gasto", "Custo por resultado", "Custo por clique no link" or
"Custo por mil impressões" were chosen) with their daily bars, the date of Meta's numbers
and the teammate's first name. A forwarded link forwards all of that: the client can send
it on, and WhatsApp, iMessage and the like fetch the page to draw their preview (the
campaign and client names are in the preview). The team can see that a link exists and
revoke it, but not who opened it: the request log counts opens of `/r/{param}` without the
token or the address.

## Consequences

- Decision 2's "there is no public view" becomes "there is one, by token, read-only, for
  30 days": the server's docstring and decision 2 say so.
- Schema v13 is additive (`CREATE TABLE IF NOT EXISTS`): a 1.7 release runs on it.
- Two more open routes to keep in `test_security_headers_everywhere`'s spirit: every
  response still carries `noindex`, the CSP and `Referrer-Policy: same-origin`.
- `static/report.html` and `static/app-report.js` are new files in the wheel; the list CI
  checks the wheel against (`ci.yml`, an owner's file) does not name them yet.
- Opening a report never reaches Meta, but it does read the database: a link passed around
  widely costs the Pi one small query per open, capped by the rate limit.

## Alternatives considered

- **A PDF or image in the WhatsApp message.** `wa.me` carries text only; a file goes
  through the share sheet (PR 35's "Enviar imagem"), which is one more step and gives the
  client a picture, not a page. Piero asked for a link.
- **An account for the client.** Decision 2's model is one team per database; a client
  account would need a role that sees one card and nothing else, invites, passkeys on the
  client's phone and support for all of it. Far more than a link, for the same page.
- **A link that follows the period** ("this month", always current). Convenient, but the
  report then changes after it was sent and the client may be looking at numbers nobody on
  the team has seen; and a link that never goes stale needs a longer lifetime. Fixed dates,
  30 days.
- **Hashing the token** as invites are. Invites create accounts; a hashed token could not
  be shown again or listed with its address, and a database copy already contains the
  card's data. Not worth the loss.
- **Rendering the card server-side** (no JS on the public page). It would mean a second
  implementation of the tiles, the labels and the sparklines in Python, drifting from the
  team's screen. Filling the `og:` tags server-side is enough for the preview; the page
  itself draws the card with the same code the team sees.
