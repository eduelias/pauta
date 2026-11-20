# 5. Other teams: one database per team

- **Status:** proposed (2026-10-30)
- **Depends on:** decision 4 (the domain). **Needed by:** decision 6 (billing).
- **Changes:** `auth.py`'s "there is one team" and the one `pauta.db`; decision 1's
  "a separate host" alternative becomes the plan for production (see Hosting).

## Context

Everything in Pauta assumes one team: `cli.cmd_serve` opens one `Store(PAUTA_STATE_DIR/
pauta.db)` at startup; `account.is_admin` is global; an invite has no team; the OneDrive
token, `/metrics`, the nightly backup and the export are all for that one file. Nobody can
sign up. To sell Pauta (decision 6), other teams need their own space, and one team must never
see another's clients: those are the teams' customers' names, phones and ad accounts (LGPD).

## Decision

| Topic | Decision |
|---|---|
| Layout | A **control database** (`control.db`) for people and teams: `account`, `passkey`, `invite`, `team`, `membership`, and later the billing tables (decision 6). **One database per team** (`teams/<team-id>.db`) for `client`, `request`, `event`, `file` and `option`, the same schema as today minus the people tables. The tables added since go there too, as their own decisions say: `setting`, `billing`, `payment` (7); `meta_account`, `campaign`, `review`, `insight`, `meta_connection`, `meta_log` (8); `usage` (11). `report_link` (12) is not placed: its public address carries no team. The `Store` query code stays as it is; it is just opened on the right file |
| Why files, not a `team` column | Isolation that doesn't depend on remembering a `WHERE team=?` in every query; export and LGPD deletion are file operations; a team's backup or restore can't touch another team; a big team can't slow a small one's queries |
| Which team a request is for | In the URL: the API under `/api/t/<slug>/...`, the app under `#/<slug>/...`. Links to a request carry the team, so a link sent on WhatsApp opens the right team. One host (`app.pauta.cc`), one certificate, one passkey RP ID (`pauta.cc`) |
| Membership and roles | `membership(team, account, role, disabled)`: `admin` or `member` per team, replacing the global `is_admin`. One person, one passkey, any number of teams, with a team switcher in the top bar. "At least one active admin" holds per team |
| Invites | An invite belongs to one team. Joining with a passkey you already have adds the team to your account instead of making a new one |
| People's names in a team | Kept per team (the timeline shows names, and two teams may each have a "Piero"); the uniqueness checks from 1.3.0 apply per team |
| Creating teams | Invite-only beta: the owner runs `pauta team create <slug> "<Nome>"`, which prints an admin invite for the team's first person. No open signup until decision 6's checkout; with passkeys only there's no email to verify, so open signup would attract junk teams |
| Owner tooling | CLI first: `pauta team list / suspend / resume / export / delete`. A web console for the owner only when the CLI hurts |
| Per-team things | OneDrive token next to the team's DB (decision 3 already planned this); option lists (already per DB); export (already admin-only); `/metrics` reports totals plus a per-team count of requests and errors; the nightly backup loops over every file. Since then the code also keeps the Meta token files and app secret (decision 8) and the thumbnail cache next to the database |
| Moving today's data | One explicit migration: today's `pauta.db` becomes team 1's file, its people tables are copied into `control.db`. This is the one change that **can't follow the additive-schema rule** (an older release can't read the new layout), so the release that does it says so, takes a backup first, and a rollback past it means restoring that backup. Passkeys don't change: the RP ID stays `pauta.cc` (the domain move in decision 4 happens first, on its own) |
| Hosting | Before the **first outside team**, production moves off du7 to a small EU server (Hetzner ARM, about €6/month; about €4 when this was written, see decision 11): other companies' client data shouldn't sit on a home connection and a Pi. Same release pipeline; the self-hosted runner moves with it. Backups go encrypted to a second place. du7 can keep acceptance (decision 1) |
| LGPD | Each team is the controller of its clients' data; Du7 Technology Services is the processor (*operador*). Before the first outside team: terms of use, privacy policy and a data-processing agreement in Portuguese on the public site. Deleting a team deletes its file at once and from backups within their 30-day rotation; the policy says so |
| Limits | Per-team rate limits on writes and uploads, on top of today's per-IP ones; plan limits come from decision 6 |
| Tests | An isolation test that walks every `/api/t/<slug>/` route as a member of another team and expects 404; a browser test with one person in two teams |

## Consequences

- About 2–3 days for the core (control DB, routing, memberships, invites, switcher,
  migration, isolation tests), plus ~1 day for the CLI, per-team backups and metrics, plus
  ~1–2 days for the server move. The legal texts need a review by someone who knows LGPD.
- Changes touch `auth.py`, the deploy and the backup unit: all owner-reviewed paths.
- Many open SQLite files instead of one: fine at tens or hundreds of teams; the server keeps a
  small cache of open stores.
- A schema change now migrates every team file on start. Migrations stay additive (as today)
  so they're safe to run file by file.
- `pauta demo` makes a demo team instead of filling the only database.

## Alternatives considered

- **A `team` column on every table, one database:** less code to move, but one forgotten
  filter leaks a team's clients to another, and export/delete become careful queries.
- **One process (and unit) per team:** strongest isolation, but a unit, a port and a Caddy
  block per team, and passkeys would need a domain per team. Too much machinery.
- **Teams on subdomains** (`acme.pauta.cc`): nicer addresses, but wildcard certificates and
  a cross-subdomain session. Decision 4's RP ID keeps it possible later.
