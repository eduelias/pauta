# 10. Perfil for the person, Configurações for the team

- **Status:** shipped in 1.7.0 (2026-11-01). Proposed the same day, in the PR that built it
- **Depends on:** nothing. **Fits:** decision 4 (the one-time link that makes a passkey for an
  existing account; decision 8 (the Meta connection is the team's, so it stays on the team's
  page).
- **Changes:** renames the `Equipe` tab to `Configurações` (`#/configuracoes`, `#/equipe`
  redirects), adds a `Perfil` page (`#/perfil`), schema v12 (additive), `PATCH /api/me`
  gains `whatsapp`, new routes under `/api/me/passkeys` and `/api/me/move`.

## Context

Piero's remark, looking at the tab: "Equipe" is really the settings screen. The team is one
of its parts, next to the OneDrive, the Meta connection, the Financeiro conventions and the
option lists; the name undersold it, and an admin looking for "where do I change how we
bill" didn't think of a tab called Equipe.

The same screen also carried a "Você" block (your name, your e-mail, add a passkey, sign
out) in the middle of team administration: things about one person mixed with things about
the whole team. And decision 4's one-time link, which PR 21 made available for any
teammate on a new or lost phone, only existed as an admin's gesture: the person who lost
the phone had no self-service way to it, and no place to see which passkeys their account
had, or to retire the one on the phone that is gone.

## Decision

| Topic | Decision |
|---|---|
| Name | The tab is **Configurações**, with a gear icon. Route `#/configuracoes`; `#/equipe` and anything under it redirect to the new route keeping the suffix and query, so bookmarks and Meta's login callback keep working. API routes (`/api/members...`) keep their names: the API is not the UI |
| Sections | In this order, each with a heading: **Time** (members, invites, the move / new-passkey links), **Meta**, **Financeiro**, **Listas**, **Arquivos** (the OneDrive). *Acompanhamento* has no settings panel yet and so no section. Admin-only panels stay admin-only; a member sees Time and the link to Perfil |
| Perfil | A page for the person signed in, from the account menu ("Meu perfil"), the avatar on the phone's top bar and a "Seu perfil →" line on Configurações. It holds: the display name (the rename rules of 1.3.0 apply, with their messages), a **WhatsApp** number (new, optional), the e-mail for the Gravatar (moved here), the account's **passkeys** with a label, when made and last used, the "add a passkey on this device" button, a **remove** per passkey as long as one remains, the **new-passkey link** for a new or lost phone as self-service (Copiar / Enviar no WhatsApp to yourself), and "Sair em todos os aparelhos" |
| WhatsApp | `account.whatsapp TEXT NOT NULL DEFAULT ''`, validated like a client's number (`_text(40)`, free text). Only the person sees it (`GET /api/me`); `GET /api/members`, the boot data and the export never carry it. Nothing in Pauta sends messages to teammates today, so there are no notification preferences: the number is there for the person to keep, not for the team: nobody else, admins included, sees it today. An admin path (admins reading teammates' numbers) can come together with notifications, if Pauta ever sends messages to the team |
| Passkey labels | `passkey.label TEXT NOT NULL DEFAULT ''`. A first label when the passkey is made, from the browser's User-Agent and the authenticator's transports ("iPhone", "Mac", "Celular (pelo QR)", "Chave de segurança", else "Este aparelho"); the person renames it. Passkeys from before this release show "Passkey" until named |
| Removing | `DELETE /api/me/passkeys/{id}`: 400 while it is the account's last passkey (without any, nobody could sign in and nobody else could make a link); 404 for a passkey that is not this account's. Removing one also ends the account's sessions (`session_gen`, as "Sair em todos os aparelhos" does): the device whose passkey went is out at once, instead of keeping a cookie for up to 180 days. The response carries a fresh cookie for the device doing the removing, so it stays signed in without a reload |
| Self-service link | `POST /api/me/move` makes the same one-time link an admin makes with `POST /api/members/{id}/move` (`auth.create_move`), for the signed-in account, but it lives **10 minutes** (`MOVE_SECONDS`): the person taps it on the new phone right away, while an admin's link is sent and waited for (3 days, `MOVE_LINK_DAYS`). "Sair em todos os aparelhos" (any logout: `end_sessions`) also expires the links the person made for themselves; an admin's link for them is the admin's and stays. The admin version stays on Configurações → Time |
| Out of Perfil | The team's Meta connection (decision 8: it belongs to the team, one connection per business portfolio, admins only), the OneDrive, and anything about other people |

## Consequences

- Schema v12, additive: a 1.6 release runs on it unchanged.
- One more screen to keep in the browser tests (`tests/e2e/test_perfil.py`) and one more
  route in `test_screens` / `test_entry`.
- `deploy/README.md` still says "Equipe" in its operator notes; it is the owner's file
  (CODEOWNERS) and is updated separately.
- The account menu on the laptop loses "Adicionar passkey neste aparelho": it lives on
  Perfil now, next to the list it changes.

## Alternatives considered

- **Keep Equipe and add a Perfil tab:** two tabs where one tab and one page do; the name
  problem Piero pointed at stays, and the mobile tab bar has no room for either.
- **Perfil inside Configurações** (the "Você" block, grown): mixes the person's things with
  the team's again, and a member would open a page mostly about things they can't touch
  to find their own passkeys.
