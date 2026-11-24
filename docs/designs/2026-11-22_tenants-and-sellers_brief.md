# Tenants and sellers: concepts brief

*   **Author:** Eduardo Elias Saleh
*   **Date:** 2026-11-22
*   **Feeds:** `2026-11-22_tenants-and-sellers.md` (the design)

This file records what the design draft starts from: what was asked, what was answered,
what the owner decided, which alternatives were weighed, and what the code looks like
today. It exists so that a later session does not have to rely on anyone's memory of the
conversation.

## Sources

*   The team's group chat, 2026-11-22, 14:00 to 14:12 (Brasília time).
*   Written answers from the person who runs the seller programme, the same day, to four
    questions the owner sent.
*   The code at release 1.17.0 (`8ab73b1`).
*   `access-and-operator-spec.md` on branch `docs/multi-tenant-spec` (draft PR 43),
    section 10 and question 17.

## What was asked

1.  **The seller programme ("microfranquia").** Outside sellers sell the team's ad
    management service. Each seller adds their own clients to Pauta and files requests;
    the team executes. A seller sees only their own clients. The team sees every client
    in one Pauta, in order of importance, and does not want one Pauta per seller. Partner
    agencies are also expected; one of them serves 17 branches of a single brand, and a
    trial with it starts in the week of 2026-11-23.
2.  **Two profiles, in the campaign manager's words.** A campaign manager ("gestor de
    tráfego") sees every company. A seller ("afiliado/vendedor") sees only their own.
3.  **A soft split between campaign managers.** Clients A, B and C are one manager's;
    D, E and F are another's; each may still work on the other's. This is a label and a
    filter. It restricts nothing.
4.  **Scale.** 200 to 250 clients by December 2027, about 20 new ones a month, and more
    campaign managers.

## Answers received

| # | Question | Answer |
|---|---|---|
| 1 | When does the first outside seller need a login of their own, or does the team file requests for them at first? | The seller registers their own clients from the start. The team helps at first; a tutorial video will exist. |
| 2 | Who bills the end client, and what money does a seller see? | The team has no contact with a seller's client; only the seller does. The seller "sees only what is theirs". Whether that sentence is about money or about clients is not clear. |
| 3 | May a seller see their clients' campaign numbers and send the report and the balance warning themselves? | Yes, to manage the client. An extra idea: Pauta e-mails the client once a week with the numbers, and when the balance is running out or a due date is near. |
| 4 | If only one fits by February: Pauta sold to other agencies, or seller logins? | Not answered; the question was not understood. A reworded version was sent. |

## Decided by the owner in this discussion

*   The multi-tenant work (decision 5, draft PR 43) is parked. This design is for one
    team's Pauta with sellers inside it.
*   Permissions are fixed roles in code plus a few named switches. A screen where a
    manager edits roles, or allows and denies actions per user, is not built.

## Alternatives weighed

| Alternative | Outcome | Reason |
|---|---|---|
| A tenant per seller (the multi-tenant design) | Rejected by author | It gives the team one Pauta per seller, which the request rules out, and the multi-tenant spec puts cross-tenant screens out of scope. A seller does not run campaigns; the team does. |
| A full role editor: custom roles, any action on or off per role | Rejected by author | Estimated 4 to 5 more days. Twelve capabilities give about 4,000 combinations per role, and every screen has to behave under each. It does not remove the per-client scoping work, which is the expensive part. |
| Allow and deny per user on top of a role editor | Rejected by author | Estimated 3 to 4 more days, plus precedence rules and a screen that explains why someone cannot see something. |
| The team keeps filing requests for sellers; a seller is only a label on the client | Rejected by the seller programme's owner | Answer 1: sellers register their own clients from the start. |
| No login: a per-seller link with a read-only page and an intake form | Not pursued | A seller creates clients, files requests and uploads files. That is a signed-in user; a long-lived link would be a weaker credential for the same access. |

## Facts from the code (1.17.0)

*   One SQLite file, one team. An `account` has one flag, `is_admin`.
*   71 routes: 11 `open`, 40 `member`, 20 `admin`. The check is in
    `server._dispatch`: `member` means signed in, `admin` means `viewer["is_admin"]`.
*   Every signed-in person sees every client and request. A request has an `assignee`
    and a `created_by`; neither restricts anything. A client has no owner column.
*   `client.name` is unique, case-insensitive (`client_name` index). Creating a client
    whose name exists is refused, which tells the caller that the name exists.
*   `Store.push_targets` sends a push to every other account's devices, and
    `Store.push_news` reads the latest events of every request.
*   `GET /api/boot` returns every active member's id and name to any signed-in person.
*   Sums and lists that cross clients: `Store.campaign_overview`, `Store.campaign_rows`,
    `Store.finance`, `Store.clients`, `Store.requests`, `GET /api/export` (admin only).
*   `is_admin` appears 28 times in the static JS.

## Open at the time of writing

*   Is a seller one person, or a group with several logins (a partner agency)?
*   What the team charges a seller, and whether the seller sees it in Pauta.
*   February: seller logins or Pauta sold to other agencies (question 4).
*   The weekly e-mail to a seller's client: it conflicts with "no contact with their
    client" unless it is sent in the seller's name, and `pauta.cc` cannot send mail today.

## Later the same day: what the drafting changed

Recorded here so that the alternatives section does not depend on memory.

| Step | What happened |
|---|---|
| First technical plan | Author's choices: an assignment table, a seller-only store object, a separate seller API under `/api/s/`, a rollback guard in `pauta-deploy` |
| Author's objection | The account should not be held at the route. Filters belong at the base: the database handle opened for a seller should carry default filters; for an admin, none |
| Second technical plan | Filters built into a SQLite connection: a temporary view over every table, an authorizer, guard triggers; the same routes for staff and sellers; `Store.db()` refuses without a scope. Tried on Pauta's real schema in a scratch database |
| Author's objection | Too many interlocking parts to maintain. A C# system the author worked on did this with plain entity classes and inheritance. A move to Rust, C# or Java was raised |
| Directions weighed | A rewrite in C# with EF Core; Python with an ORM; Python on Postgres with row-level security; keeping the SQLite plan |
| Author's choice | Python on Postgres with row-level security |
| Constraint dropped | "SQLite, standard library, one runtime dependency" is in the first commit's `CLAUDE.md` and README and in no decision record. The author did not set it and dropped it |
| A graph database (Neo4j, Cypher) for the access rules | Raised by the author, "if it shows to be faster". Not taken up: the question is one lookup deep, a Postgres policy cannot ask a second database, and two databases would have to agree |
| Scope of the design | One design: the move to Postgres and seller access together |
| Where Postgres runs | A container on du7 |
| Platform sales in February | Confirmed by the author as a real commitment. Tenants are no longer parked; the design covers both walls |
| How tenants are kept apart | Weighed: a tenant column and policy in one database; a database per tenant (raised by the author, with tenants on different versions); a schema per tenant. Author's choice: a schema per tenant, with the tenant's own database roles so that the database enforces the wall |
| Database roles per tenant | Raised by the author: several per tenant. Taken up: one per kind of access, starting with staff and seller. Grants then replace the column trigger and the policies on tables a seller may not touch |
| Versions | Author's choice: two channels, stable and next, a tenant on one of them. A release per tenant was not taken up |
| Which tenant a request is for | Weighed: from the account (one tenant per account); in the address (the multi-tenant spec's decision of 2026-11-11); by host name. Author's choice: by host name, `<name>.pauta.cc` |
| A model layer (ORM) | The author asked how AWS, Salesforce and SAP do it and whether report views could carry the filter. The author asked for a recommendation; it was Postgres policies as the one place of enforcement, with ownership declared on model classes and the ORM adopted gradually. Checked against Ponytail, which keeps the policies and cuts the policy generator and the ORM. Not decided; open question 13 of the draft |
| The rollback guard in `pauta-deploy` | Dropped when the fourth technical plan was approved: from the first Postgres release the database role comes from the membership, so an older release still restricts a seller |
| "A few named switches" on the fixed roles | None are in the final design. The one candidate, whether a seller sees campaign numbers, was answered yes by the seller programme's owner |
| How `Store`'s SQL reaches Postgres | The approved plan ported all 218 statements. The trial of 2026-11-22 ran `Store` unchanged through an adapter of about forty lines and proposed building the move that way. Author's choice on 2026-11-23: the adapter |
| The name of a tenant's view of its people | The approved plan had one view, `member`. The trial named two views `account` and `passkey`, the names `Store`'s SQL already reads in 19 statements. Author's choice on 2026-11-23: `account` and `passkey`. The design then narrowed the views to the columns `Store` reads and kept the e-mail address out of them; that narrowing is the draft's default, not the author's stated choice |
| The order of names with accents | SQLite sorts "Ação" after "z"; the collation the trial used sorts it among the A's and also treats "AÇÃO" and "ação" as one name. Weighed: accept that, or reproduce SQLite's order by editing the 10 statements that use `COLLATE NOCASE`. Author's choice on 2026-11-23: the natural order, as the one exception to "nothing changes for today's team" |
| How a seller policy says "assigned to the account" | The trial ran two forms: a function called per row, and one array of the seller's client ids computed once per statement. The array was about a third faster on the campaign overview (25 ms against 38 ms). Author's choice on 2026-11-23: the array. With it, all four choices the trial put to the author are made |
| Reconciled | 2026-11-22, when the design was finalized. Where this brief's earlier sections and the rows above disagree, the rows above are the later word: tenants are in scope, and the rules are enforced by Postgres |

## The earlier multi-tenant spec, and what became of it

Folded in on 2026-11-23, when the owner asked for one set of documents. Before that day
there were two designs for the same wall: `docs/multi-tenant-spec.md` (first written
2026-11-11, tidied and reviewed by ten readers on 2026-11-20, on branch
`docs/multi-tenant-spec`, draft PR 43, with its last revision and a decision record never
committed) and this design. The spec is retired; this table is what remains of it.

| The spec decided | When | Now |
|---|---|---|
| A control database plus one SQLite file per tenant | 2026-11-11 | Replaced: one Postgres database with a `control` schema and a schema per tenant |
| The tenant in the path, `/api/t/<slug>/` and `#/<slug>/` | 2026-11-11 | Replaced: the host name. With it go the list of routes that have no tenant, the reserved screen names, the front-end helpers and the release of unprefixed aliases |
| Each tenant file keeps its own list of people, because SQLite checks a foreign key inside one file | 2026-11-20 | Not needed: the tenant's tables reference `control.account`, and the tenant reads its people through two views |
| The migration in place on first start, with a rollback for a week that undoes every change to people | 2026-11-20 | Replaced: an import command at the cut-over, the SQLite file kept, a rollback decided in the first hour |
| A report link's token carries the tenant's number | default | Open again (open question 19): the host can say it |
| Four refactor steps first: a route table per tenant, paths in one place, two stores, front-end helpers | 2026-11-12, 2026-11-20 | The route table per tenant became the scope set per request. Paths in one place is kept as `paths.py` in the move. Two stores became `auth.py`'s own scope on `control`. The front-end helpers are dropped |
| "No framework, no ORM, the standard library stays" | 2026-11-20 | Dropped with the SQLite constraint |
| About eleven and a half days | 2026-11-20 | Void. The stages of this design are not sized yet |
| One account, any number of memberships, each with a role and an optional end date; `account.handle` as the stable id | 2026-11-11 | Kept (Part B) |
| A second membership from the owner's command line at first | 2026-11-20 | Kept |
| A tenant admin disables a membership, never an account, and makes a new-passkey link only for a person in that tenant alone | 2026-11-20 | Kept. It closes a way for one tenant's admin into another tenant |
| The owner has no special access: a dated membership, logged and visible | 2026-11-20 | Kept |
| One Meta client, OneDrive client and sync lock per tenant; one Meta app and one session key per environment | 2026-11-11 | Kept |
| Tenant commands: create, list, suspend, resume, export, delete | decision 5 | Kept, on schemas in place of files |
| Restore is stop, copy, start | 2026-11-20 | Kept as stop, restore, start |
| A reserved, empty `login` table for a federated sign-in | default | Kept |
| An isolation test generated from the route table; a test with one person in two tenants | 2026-11-20 | Kept as the boundary test, widened to sellers |
| Before a first outside tenant: Meta App Review, OneDrive work accounts, the legal texts, the hosting move | 2026-11-20 | Kept ("The releases") |
| Integrations, access control and the owner's masked view are set aside | 2026-11-20 | Kept: `docs/access-and-operator-spec.md`, brought to this branch with a table in its header that maps it onto this design |

Not brought over: the spec itself, the ten review reports of 2026-11-20 and the brief for
the first refactor step. The reports' findings on tenancy were either applied to the spec
before it was retired or concern the file layout that is gone; their findings on the
access note are still open and that note says so.

Not touched: the CRM discussion draft (draft PR 42), which assumes the file-per-tenant
layout and a shared package built on it. It needs the same revision when it is taken up.
