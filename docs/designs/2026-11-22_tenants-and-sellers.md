# Tenants and sellers: who sees what in Pauta, enforced by the database

*   **Author:** Eduardo Elias Saleh
*   **Status:** Proposed (drafted and reconciled with its brief on 2026-11-22; stage 0, the trial, was run the same day; decisions 12 to 15 were added on 2026-11-23; not reviewed, nothing built)
*   **Date:** 2026-11-22

Context this draft starts from, and how the day's decisions went:
[`2026-11-22_tenants-and-sellers_brief.md`](2026-11-22_tenants-and-sellers_brief.md).

--------------------------------------------------------------------------------

## Overview

Pauta is one team's request queue: someone files a request for a client, and a campaign
manager works it. Today one process serves one team from one SQLite file, and everyone
who can sign in sees every client.

Two things are about to break that:

*   **Other agencies.** Pauta goes on sale to other agencies in February 2027. A second
    agency must be able to use Pauta without seeing anything of the first.
*   **Sellers.** The team is starting a seller programme. Outside sellers sell the
    team's ad management service to their own clients, add those clients to Pauta and
    file requests for them. A seller must see their own clients and nothing else, while
    the team keeps seeing every client in one queue.

This design puts both rules in the database, not in the code that asks. SQLite cannot do
that, so Pauta moves to Postgres:

*   An agency is a **tenant**. Each tenant has its own schema in one Postgres database,
    its own database roles, and its own address (`<name>.pauta.cc`). A session working
    for one tenant has no permission on another tenant's schema.
*   Inside a tenant, a **seller** is one more kind of member, with a database role that
    is granted less and that sees only the clients assigned to it.

The words used below: **staff** are a tenant's admins and members, who run campaigns and
see everything in their tenant. A **seller** is an outside account in a tenant. A
**seller's client** is a client assigned to a seller. A **house client** is assigned to
no seller. The **owner** is Du7's owner, who operates Pauta.

## The Problem

*   **A second agency cannot be given the app.** There is one database and nothing in a
    row says whose it is. Giving another agency a login gives it the first one's clients.
*   **A seller cannot be given a login.** A signed-in account can list every client,
    with its contact name, WhatsApp number, ad account and campaign numbers, and read
    every request, file and payment.
*   **The team cannot run one Pauta per seller.** The people who execute need one queue,
    ordered by importance, across all sellers. A seller is therefore inside the team's
    tenant, not a tenant of their own.
*   **The seller, not the team, talks to the seller's client.** The balance warning and
    the campaign summary that Pauta drafts today are written for the person who talks to
    the client. For a seller's client that person is the seller.
*   **The code cannot be trusted to remember a filter.** `Store` is 2,294 lines of
    hand-written SQL with 218 statements. A rule that every statement must apply by
    itself will be forgotten once. Two attempts on 2026-11-22 to enforce the seller rule
    above or around that SQL were set aside for that reason (see "Alternatives
    Considered").
*   **The list of clients is about to outgrow one person.** The plan is 200 to 250
    clients by December 2027 with more campaign managers. Nothing on a client says whose
    it is, so nobody can ask for "my clients".

## Goals

1.  **A seller can do their part alone.** A seller invited by an admin signs in with a
    passkey and, for their own clients only, can add a client, file a request, comment,
    upload files and follow the request to "Concluído".
2.  **A seller can manage their client with Pauta's numbers.** For their own clients a
    seller sees the campaign numbers and the ad balance, can create the client report
    link, and gets the "Avisar do saldo" and "Enviar resumo" WhatsApp drafts.
3.  **A seller cannot learn that anything else exists.** No other client, request, file,
    campaign, payment or seller reaches a seller's browser: not in a list, not by putting
    an id in an address, not in a sum or a count, not in a notification, not in the list
    of people, and not through an error message such as "this client name is taken".
    Asking for someone else's record gives the same answer as asking for one that does
    not exist.
4.  **Two agencies cannot see each other.** A member of one tenant gets nothing of
    another tenant, by any route, and the database refuses it even if the application
    asks.
5.  **Closed unless opened.** A table or a column that a role was not granted is closed
    to it, and so is a table added later. A seller with no clients sees an empty Pauta.
    A request for which no tenant and account were set sees nothing.
6.  **Staff see everything in their tenant in one queue, and whose it is.** Every list
    staff use shows which seller a client belongs to and can be filtered and sorted by it.
7.  **A client has a responsible campaign manager.** Lists can be filtered to "mine".
    The field restricts nothing: any staff member can still open and work any client.
8.  **One person, several agencies.** One account with one passkey can be a member of
    several tenants, with a different kind of membership in each.
9.  **Nothing changes for today's team.** Their address stays `app.pauta.cc`; installed
    apps, notifications and saved links keep working; every existing route gives an
    admin and a member the answer it gives today. The existing tests pass. One
    exception, accepted on 2026-11-23 (decision 14): lists sorted by name put names with
    accents among their letters.
10. **The move to Postgres loses nothing.** Every row of the SQLite file arrives, with
    its id, and the count and a checksum of every table are compared before the service
    starts on Postgres. There is a tested way back for the first hour.
11. **Both walls are tested as a whole, by a machine.** One test calls every route in the
    route table as seller A with seller B's ids, and as tenant A's staff with tenant B's
    ids. It fails on any answer other than "not found", "not allowed" or an empty list,
    and it fails when a route is added that the test does not know.
12. **Two channels.** A tenant runs on the stable release or on the next one. Moving a
    tenant between them copies no data.

## Non-Goals

| Not in this design | Why |
|---|---|
| What a customer agency needs beyond the wall: signing up, paying, a plan's limits, the agency's logo on reports | The multi-tenant spec (draft PR 43) and decision 6 cover them. This design gives them the layout to stand on. That spec's file-per-tenant layout (decision 5) is replaced by this one and has to be revised |
| A screen where a manager edits roles, or allows and denies actions per user | Roles are fixed: admin, member, seller. With a database role per kind of member, a custom role could later be one more database role with different grants; nobody has asked yet |
| A release per tenant | Two channels only (goal 12). Every extra live version is one more place each fix has to be weighed |
| An ORM, or a rewrite in another language | Weighed on 2026-11-22 (see "Alternatives Considered"). `Store` keeps its hand-written SQL as it is written today, and an adapter carries it to Postgres (decision 12). The author is uneasy about hand-written SQL; it is open question 13 |
| Native Postgres types for dates and flags | The move keeps text timestamps and integer flags so that every answer stays as it is. Changing them is a later change of its own |
| Restricting a campaign manager to some clients | Goal 7 is a filter. Staff who must not see every client are a different problem, and nobody has it today |
| E-mail from Pauta to a seller's client (the weekly numbers, the balance warning) | Asked for by the seller programme's owner. It is a feature of its own: `pauta.cc` cannot send mail today, the message would have to go out in the seller's name, and each recipient needs a way to opt out. The seller's WhatsApp drafts of goal 2 cover the need until then |
| Money between the team and a seller: what a seller owes, a seller's own Financeiro view | What the team charges a seller is not settled (open question 3). Until it is, sellers do not see Financeiro at all |
| Signing up without an invite, for a seller or an agency | Invites only, and tenants are created by the owner from the command line |
| Publicações | The module is a beta on its own branch and is not in `main` |
| The owner's masked support view and "assume a role" of the access spec | Not needed for either wall. Until they exist the owner enters a customer's tenant only as an invited member |

## Open Questions

1.  **Does any seller expect a second person in Pauta?** The assignment table allows
    two seller accounts on the same clients. To ask the seller programme's owner.
2.  **The seller's name in the interface:** "Parceiro", "Vendedor" or "Afiliado".
3.  **What does the team charge a seller, and does the seller see it in Pauta?**
4.  **Do staff keep the WhatsApp buttons on a seller's client?** The team has no contact
    with a seller's client. The button could open a chat with the seller instead.
5.  **Who links a seller's client to its ad account?** Today an admin does it on
    Configurações. If that stays, a seller's new client shows no numbers until then.
6.  **Two clients with the same name.** Answered by the technical plan: the unique index
    goes, and the name check runs under the caller's own view, so a seller is checked
    against their own clients only.
7.  **What a seller may change after filing.** The plan's default: the briefing, while
    the request is "A fazer"; never status, assignee or the campaign link.
8.  **What happens to a seller's clients when the seller leaves.** The plan gives an
    admin a "move to another seller" action; nothing happens by itself.
9.  **Whose data is it under the LGPD?** A seller is probably the controller of their
    clients' data and the team the operator; a customer agency is the controller of its
    own tenant and Du7 the operator. Both call for a written agreement. This needs
    someone qualified in Brazilian data protection law.
10. **Which comes first after the move: sellers or other agencies?** Both stand on the
    move and neither needs the other. February points at agencies; the seller trial
    starts in the week of 2026-11-23.
11. **Does a seller read every comment on their request?** Pauta has no private comment.
    The plan shows a seller the whole timeline; staff would have to know that.
12. **Where production runs when the first outside agency arrives.** The author chose a
    Postgres container on du7 on 2026-11-22. Decision 5 says production leaves du7
    before the first outside team. Both cannot hold in February.
13. **A model layer.** The author finds hand-written SQL without entity classes hard to
    maintain. With the database enforcing both walls, a model layer is no longer needed
    for safety. Whether to add one, and when, is undecided.
14. **The first tenant's name.** Its address stays `app.pauta.cc`; its name and short
    name appear in the tenant list and in the schema's name.
15. **The order of names with accents.** Answered on 2026-11-23 (decision 14): the
    natural order, with "Ação" among the A's. It is the one stated exception to goal 9.
16. **The name of the people view.** Answered on 2026-11-23 (decision 13): two views,
    named `account` and `passkey`, so that the 19 statements in `Store` that read those
    names run as written.

## Critical User Journeys (CUJs)

### CUJ 1: A seller's first day

*   **Given**: An admin has created a seller invite and sent the link.
*   **When**: The seller opens the link, creates a passkey and signs in.
*   **Then**: Pauta opens with no clients and no requests, and offers "Novo cliente". The
    menu has no Financeiro and no Configurações. The seller adds a client and files a
    request for it.

### CUJ 2: A request goes from the seller to the team and back

*   **Given**: A seller has filed a request for one of their clients.
*   **When**: A campaign manager opens the queue, picks the request up, comments, and
    later marks it "Concluído".
*   **Then**: The request appears in the team's one queue with the seller's name on it.
    The seller is notified of the comment and of each status change. No other seller is
    notified, and no other seller's device is woken.

### CUJ 3: A seller tries to look outside

*   **Given**: Seller A is signed in. Client 12 belongs to seller B.
*   **When**: Seller A opens the address of client 12, of one of its requests, of one of
    its files or of its report links, or sends a change to any of them.
*   **Then**: Each attempt gets "not found", the same answer as for a client that does not
    exist. Nothing is changed.

### CUJ 4: A seller's client is running out of balance

*   **Given**: The ad account of one of seller A's clients has balance for two days.
*   **When**: Seller A opens Pauta; a campaign manager opens Campanhas → Visão geral.
*   **Then**: Seller A sees the client in "Saldo acabando", with "Avisar do saldo", which
    opens WhatsApp with the warning written. The campaign manager sees the same alert in
    Visão geral, marked with seller A's name. Seller B sees neither.

### CUJ 5: A campaign manager asks for "my clients"

*   **Given**: 200 clients, each with a responsible campaign manager.
*   **When**: A campaign manager opens Clientes or Campanhas.
*   **Then**: The list can be narrowed to the clients they are responsible for, and
    widened back to all. Opening and working someone else's client is still allowed.

### CUJ 6: A second agency starts

*   **Given**: The owner has run the command that creates a tenant named "norte" and has
    sent its first admin an invite link.
*   **When**: That person opens the link at `norte.pauta.cc`, creates a passkey and
    signs in.
*   **Then**: They see an empty Pauta of their own and can invite their team. Nothing
    changes for anyone at `app.pauta.cc`.

### CUJ 7: A member of one agency opens another agency's address

*   **Given**: Someone is a member of the tenant at `app.pauta.cc` and of no other.
*   **When**: They open `norte.pauta.cc` and sign in with their passkey.
*   **Then**: The passkey is accepted, since it belongs to the person. Pauta answers
    that they are not a member here, and no data of "norte" is read for them.

## Technical Plan (Architecture)

### Decided by the author

Decisions 1 to 11 were made on 2026-11-22; decisions 12 to 15 on 2026-11-23, after the
trial.

| # | Question | Decision |
|---|---|---|
| 1 | What a seller's client belongs to | An assignment table of (account, client) pairs |
| 2 | Where the rules are enforced | In Postgres. The third answer of the day; the first two are under "Alternatives Considered" |
| 3 | How routes are opened to sellers | The same routes as staff, with no marking for sellers |
| 4 | A guard in `pauta-deploy` against rolling back past seller access | Chosen earlier in the day, then dropped when this plan was approved: it has nothing left to guard. See "The releases" |
| 5 | What happens when nothing says who is asking | Nothing is visible. Work that must see everything says "system" explicitly |
| 6 | "SQLite, standard library, one dependency" | Dropped. It was written in the first commit and never decided |
| 7 | Where Postgres runs | A container on du7 (but see open question 12) |
| 8 | How tenants are kept apart | A schema per tenant in one database, with the tenant's own database roles |
| 9 | Database roles per tenant | One per kind of access. This plan starts with two: staff and seller |
| 10 | Which tenant a request is for | The host name: `<name>.pauta.cc` |
| 11 | Versions | Two channels, stable and next; a tenant is on one of them |
| 12 | How `Store`'s SQL reaches Postgres | Through an adapter. The SQL stays as it is written today; what Postgres refuses is fixed in place. Porting every statement was the plan until the trial; see Part A |
| 13 | What a tenant's view of its people is called | Two views in each tenant's schema, `account` and `passkey`: the names `Store`'s SQL already reads. The plan called it `member` until the trial; see Part B |
| 14 | The order of names with accents | The natural order: "Ação" sorts among the A's, where SQLite puts it after "z". The one exception to goal 9; see Part A |
| 15 | How a seller policy says "assigned to the account" | One array of the seller's client ids, computed once per statement. The trial also ran a function called per row, which was slower; see Part C |

### The layout

```text
 one Postgres database
 |
 |-- schema "control"            who exists, and where they belong
 |     tenant(id, name, channel)         tenant_host(host, tenant)
 |     account, passkey                  membership(account, tenant, role, is_admin)
 |     invite(tenant, ...)
 |
 |-- schema "t1"                 today's team; host app.pauta.cc
 |     client, request, event, file, campaign, insight, review, meta_account,
 |     report_link, assignment, option, setting, billing, payment, push_sub,
 |     usage, meta_connection, meta_log, meta
 |     views account, passkey            this tenant's people, read from control
 |
 |-- schema "t2"                 the next agency; host norte.pauta.cc
 |     the same tables
 |
 roles
   pauta_system    owns everything; migrations, sign-in, the sync, the CLI, fan-out
   pauta_app       what the service connects as; has no rights of its own
   t1_staff, t1_seller, t2_staff, t2_seller, ...
                   rights on one tenant's schema only; pauta_app may switch to them
```

Of today's 21 tables, three move to `control` (`account`, `passkey`, `invite`) and 18
are created in each tenant's schema, with `assignment` as the nineteenth. Each tenant's
schema also has two views named `account` and `passkey` (decision 13, Part B).

### A request, end to end

1.  The proxy passes the request with its host name. `_dispatch` looks the host up in
    `control.tenant_host`. An unknown host gets "not found" before anything else runs.
2.  The session cookie gives the account. `control.membership` gives that account's
    role in this tenant: `staff` or `seller`, with `is_admin` beside it. No membership:
    "not a member here" (CUJ 7).
3.  `_dispatch` tells the store the tenant, the account and the role. The handler runs.
    Handlers do not change and never pass any of the three on.
4.  For every transaction, `Store.db()` on the `pauta_app` connection does three things
    that last for that transaction only: switch to the role `t<tenant>_<role>`, point
    the search path at schema `t<tenant>`, and record the account id for the policies.
5.  The SQL already in `Store` then runs through the adapter of Part A:
    `SELECT ... FROM client` finds the tenant's `client`, with that role's grants and
    policies.

If step 4 points at the wrong schema, the role has no permission there and Postgres
refuses. If nothing was set at all, `pauta_app` has no rights of its own and `Store.db()`
raises before asking.

The role's name is built from what `control.membership` says, not from a list in the
code. A release that has never heard of a role still switches to the right one.

### Part A: the move to Postgres

**What changes and what does not.** `Store` keeps its shape: hand-written SQL, one
method per operation, the same answers. The driver changes from `sqlite3` to `psycopg`
(version 3), with a small connection pool. The hand-written schema migrations are
rewritten as a numbered list, one for `control` and one that is applied to each tenant
schema.

**The SQL stays as it is written (decision 12).** The trial ran `Store` on Postgres
without rewriting it, so the 218 statements are not ported one by one. Three things
carry them:

*   **An adapter between `Store` and the driver,** about forty lines in `scope.py`. It
    hands `Store` a connection with the two calls it uses, `execute` and `executemany`,
    and rows that read by name and by position as SQLite's do. Before a statement goes
    out it turns each `?` into the driver's `%s`, `IS ?` and `IS NOT ?` into Postgres's
    null-safe comparisons, and a literal `%` into `%%`. The result is kept per statement
    text, so each statement is translated once.
*   **Two stand-ins in the database,** in a small shared schema named `pauta` that every
    search path ends with: a function `datetime('now')` that returns the time in today's
    text format (33 places call it), and a collation named `nocase` (10 places).
*   **The `nocase` collation sorts names in their natural order (decision 14).** It
    ignores case and keeps accents, for every letter. SQLite's `NOCASE` ignores case for
    the 26 unaccented letters only, which has two effects:

    | Where | SQLite today | Postgres |
    |---|---|---|
    | The 8 places that sort by a client's, a campaign's or an ad account's name | An accented capital sorts after "z" | "Ação" sorts among the A's. Seen in the client list, the campaign list and the overview |
    | The check that a client's name is taken, and the unique index behind it | "AÇÃO" and "ação" are two names | They are one name. "Acao" and "Ação" stay two |

    The second effect means the import can meet two existing clients whose names differ
    only in the case of an accented letter. `pauta import-sqlite` looks for such a pair
    before it copies anything and stops with both names. Whether production has one is
    not known; the trial did not load a copy of production.
*   **Fixes in place for what Postgres refuses.** No translation of text can express
    these, so the statement itself changes:

    | Construct | Places | Becomes |
    |---|---|---|
    | `INSERT OR IGNORE`, `INSERT OR REPLACE` | 5 | `ON CONFLICT` |
    | `lastrowid` | 3 | `RETURNING id` |
    | `rowid` | 2 | The table's own id |
    | `datetime('now', <an offset>)` | 2 | The offset is computed in Python, or a second form of the stand-in |
    | `group_concat` | 1 | `string_agg` |
    | An integer used as true or false | Found by the tests; 1 so far | An explicit comparison |
    | `GROUP BY` that does not name every column | Found by the tests; 1 so far | The columns are named |
    | A Python `True` or `False` sent to an integer column | Found by the tests; 1 so far | `int(...)` |
    | `PRAGMA` | 9 | Gone with the old migrations |
    | SQLite's backup call | 2 | `pg_dump` |

    One difference does not fail and has to be looked at by hand: `LIKE` ignores case in
    SQLite and not in Postgres. There is one `LIKE`, on a campaign's URL.

The trial tried 33 of `Store`'s 82 methods and none of `auth.py`'s 42 statements or
`usage.py`'s 6. Each construct above is of a kind already seen; how many more places the
tests find is not known.

What this choice costs is under "What this plan leaves weak": the repository keeps SQL
in SQLite's spelling while it runs on Postgres.

To keep every API answer as it is today (goal 9), the move keeps the stored forms:

| Today in SQLite | In Postgres | Why not the native type |
|---|---|---|
| Timestamps as text, written by `datetime('now')` (35 places, 2 of them with an offset) | Text columns, written by the stand-in function, which returns the same format | A `timestamptz` would change every answer that carries a date, and the page that reads them |
| Flags as integers 0 and 1 | Integers | A boolean would turn `1` into `true` in every answer |
| `INTEGER PRIMARY KEY` | An identity column; the copy keeps today's ids | Links, files and report tokens refer to ids |

**Where it runs.** One Postgres container on du7, from a compose file in `deploy/`,
listening on 127.0.0.1 only, its data on the Pi's own disk and not on the NAS disks,
which can mount late after a power cut. Acceptance is a second database in it. Passwords
come from 1Password and reach the Pi as a file only the service user can read.

**Files beside the database.** The Meta secret, the OneDrive token, the push signing
key and the thumbnail cache sit next to `pauta.db` today. They move to one folder per
tenant in the state directory; the push signing key stays shared.

**Tests.** The 58 test files (about 17,000 lines) give every test its own SQLite file
today. With Postgres each test worker gets its own database with `control` and one
tenant schema, emptied between tests. CI gets a Postgres service; a developer starts the
same compose file with `make db`. The inner loop is 5 seconds today and will be slower;
by how much is not known until it runs.

**Backups.** `pauta backup` and the pre-deploy backup in `pauta-deploy` change from
SQLite's backup call to `pg_dump`. One tenant can be dumped or dropped by its schema.

**The cut-over.**

1.  The release that runs on Postgres goes to acceptance first and stays there a week.
2.  Production: the deploy stops the service, backs up the SQLite file as today, and
    runs a new command, `pauta import-sqlite`. It creates `control` and tenant 1, gives
    tenant 1 the host `app.pauta.cc`, turns every account into a staff membership
    (keeping `is_admin`), copies every table, compares the row count and a checksum of
    each, and starts the service on Postgres. The file it imports is the one the
    running release has just closed, never an older copy: opening a file with `Store`
    runs a start-up step that can write, and a copy that step has not yet touched would
    not match.
3.  The SQLite file is kept, untouched. A rollback to the previous release reads it, and
    so loses whatever was written after the cut-over. The decision to roll back is made
    in the first hour; after that, problems are fixed forward.

### Part B: the wall between tenants

**Grants, not conditions.** `t1_staff` is granted the tables of schema `t1` and nothing
else. There is no tenant column and no tenant condition in any statement. A statement
that names another tenant's table is refused by Postgres whoever wrote it.

**The `control` schema is closed to tenant roles.** Sign-in, passkeys, invites and
memberships are handled by `auth.py`, which runs as `pauta_system`. A tenant's roles see
the people of their own tenant through two views in the tenant's schema (decision 13).
They carry the names of the tables `Store`'s SQL reads today, so the 16 statements that
read `account` and the 3 that read `passkey` run as written.

| View | Columns | Rows |
|---|---|---|
| `account` | `id`, `name`, `avatar`, `role`, `is_admin`, `disabled`, `created` | The members of this tenant. For the seller role: staff and the seller's own row, never another seller |
| `passkey` | `account`, `last_used`, `rp_id` | The passkeys of this tenant's members. For the seller role: the seller's own. No key material |

*   **The columns are the ones `Store` reads, and no more.** `handle`, `session_gen`,
    `whatsapp` and `start` are read by `auth.py` only and stay in `control`. `is_admin`
    and `disabled` come from the membership, so they are this tenant's answer.
*   **The e-mail address is not in the view.** `Store.members` reads `email` today to
    compute the avatar hash and then drops it. The view carries the hash as `avatar`,
    and `members` reads that; it is one of the statements already edited for
    `group_concat`. This is the plan's default; the other way is to put `email` in the
    view and leave the statement alone.
*   **`Store` never writes either name.** All 19 statements are reads. Writes to people
    are in `auth.py`.
*   **One name, two things.** `account` is a table in `control` and a view in each
    tenant's schema, and the search path decides which one a statement reads. A tenant
    role's path has no `control`, so it reads the view. A system scope that works for
    one tenant (the sync, the fan-out, creating a seller's client) has the same path and
    reads the same view, which shows the system role every member of that tenant.
    `auth.py`'s scope puts `control` first and reads the tables. The trial ran the views
    as staff and as a seller. It did not run `auth.py`, and as system it saw staff only,
    which the view's condition for the system role is there to fix.

**Hosts.** `*.pauta.cc` points at the proxy. A wildcard certificate needs the proxy to
answer a DNS challenge; its image is named for the Cloudflare DNS plug-in, which is to be
confirmed. The first tenant keeps `app.pauta.cc`, because installed
apps and notification subscriptions are tied to that address. A few names are reserved
(`app`, `acc`, `www`, `next`, `api`).

*   **Sessions** are per host, as cookies are today. Signing in at a second tenant's
    address is one more passkey tap. The passkey is the same: it belongs to `pauta.cc`.
*   **The origin check** on writes accepts the request's own host, when it is a known
    tenant's.
*   **Meta sign-in returns to one fixed address.** Meta accepts only return addresses
    registered in the app, and no wildcards. The callback stays on `app.pauta.cc`. The
    one-time `state` it already keeps for the admin who clicked also remembers the
    tenant; the callback finishes there and sends the browser back to the tenant's own
    address.

**Creating a tenant** is one command, `pauta tenant add <name>`, run by the owner. In one
transaction it creates the schema, its two roles, the tables, grants and policies, the
row in `control.tenant` and the host; then it prints an invite for the first admin.

**Work that crosses tenants** runs as `pauta_system` and loops: the hourly Meta sync,
backups, migrations, the usage report. Each pass sets the search path to one tenant.

### Part C: sellers

**Data model, in each tenant's schema.**

| Change | Why |
|---|---|
| `assignment(account, client, created, by)`, primary key `(account, client)`, rows removed with their client | Decision 1. A row for a seller means "this seller sees this client". A row for a staff account means "this person is responsible for this client" (goal 7) and restricts nothing |
| The unique index on a client's name becomes a plain index | Goal 3: two sellers may have a client with the same name |

A seller is a membership with role `seller`. It is set by the invite and does not change
afterwards; `is_admin` is refused on it. A seller with no assignment rows sees nothing.

**What each role is granted.** Staff are granted every table of their schema, as the
application uses them today. The seller role:

| Table | Rows the seller role sees | What it may write |
|---|---|---|
| `client` | Clients assigned to the account | Update, all columns but `billed` |
| `request` | Requests of those clients | Insert; update of the briefing columns. Not `status`, `assignee`, `campaign_url`, `done_on` |
| `event`, `file` | Those of a visible request | Insert; delete of a file the seller uploaded |
| `campaign`, `meta_account`, `insight`, `review` | Those of an assigned client or a visible campaign | Nothing |
| `report_link` | Those of a visible campaign | Insert; update (to revoke) |
| `assignment` | Rows of assigned clients | Nothing |
| `push_sub` | The account's own devices (the same rule for staff) | Own rows |
| `option` | All | Nothing |
| `setting` | All but the `finance` row | Nothing |
| `meta` | The reload mark only, not the sync error text | Nothing |
| `usage` | Nothing | Insert |
| `billing`, `payment`, `meta_connection`, `meta_log` | Not granted | Not granted |
| The `account` view | Staff and the seller's own row | Nothing |
| The `passkey` view | The seller's own passkeys | Nothing |

Three kinds of rule, each done by the thing Postgres has for it:

*   **Which tables and columns:** grants. A column the seller role was not granted
    cannot be written. For that to work, `Store`'s insert statements name only the
    columns the caller set; its update statements already do.
*   **Which rows:** a policy on each table, written for the seller role. "Those of a
    visible request" is a subquery on `request`; Postgres applies `request`'s own policy
    inside it, so the rule for a comment or a file is the rule for its request, stated
    once.

    "Assigned to the account" is written with one array (decision 15). Each tenant's
    schema has a function, `my_clients()`, that returns the ids of the clients assigned
    to the account of the transaction. The policies on `client`, `request`, `campaign`
    and `meta_account` say "the client is one of `my_clients()`". Postgres computes the
    array once per statement, not once per row. The function reads `assignment` with its
    owner's rights, so it does not depend on the seller's own policy on that table; like
    every policy, it trusts the account set for the transaction. `insight` has no client
    column: its policy is "there is a visible campaign with this `meta_id`".
*   **Report views.** A view runs with its creator's rights unless it says otherwise.
    Every report view is created with `security_invoker`, so the policies apply to the
    person asking. The exceptions are the `account` and `passkey` views above, which
    have to read `control`; they are the only two, and a test says so.

**What a refusal looks like.** Reading someone else's record finds no row, so `Store`
raises the `NotFound` it raises today (404). A refused write raises Postgres's
"insufficient privilege" error, which `Store.db()` turns into "not allowed" (403).

**Three things run as `pauta_system` on a seller's behalf,** each one visible line:

*   **Creating a client.** The assignment row that makes a client visible does not exist
    when the client is inserted. `Store.save_client` checks the name under the seller's
    role, then writes the client and its assignment row in one system transaction. A
    client created by a seller starts with `billed` off (open question 3).
*   **A seller's own profile and passkeys.** All of `auth.py` (21 uses of the store)
    runs as `pauta_system`.
*   **Telling other people's devices.** `Store.on_news(by)` becomes
    `on_news(by, client)`. The fan-out wakes the devices of every staff member of the
    tenant and of the sellers assigned to that client, minus the one who acted.

**What rows and grants cannot cover.** These are the only places a handler looks at
`viewer["is_seller"]`:

*   `finance_visible()` returns false for a seller. Hiding the `finance` setting row is
    not enough on its own: without the row the code falls back to its defaults, and the
    default is on and visible to all. The money tables are closed to the seller role
    either way.
*   `sync_error` on the campaign list is free text from the last Meta sync and can name
    an account. A seller gets the neutral line members already get for other Meta errors.
*   Meta's live account list and reach numbers come from `meta.py`, not from the
    database. The campaign handlers already build their answers by walking rows from
    `Store` and looking Meta's numbers up by ad account id, so the filter carries over.
    The rule for new code: look up in a list from Meta, never walk one.

**What a seller gets from the routes.** No route is marked for sellers. An `admin` route
refuses a seller because a seller is never an admin. Of the 40 `member` routes, a seller
gets their own account (10 routes), their own clients, requests, files, campaigns and
report links (20), the start-up data and the people list (2), and the news for a
notification (1). The other seven refuse: "Visto hoje" (2), a campaign's tracking
state (1) and Financeiro (4).

**What staff get.**

| Change | Where |
|---|---|
| `clients()` and `client()` answers carry `sellers` and `responsible`, each a list of `{id, name}` read from `assignment` | `Store` |
| `PUT /api/clients/{id}/assignments` with `{accounts: [...]}`. A member may add and remove staff accounts. Adding or removing a seller needs an admin, because it changes who can see the client | New route |
| `POST /api/members/{id}/assignments/move` with `{to}`: every row of one seller moves to another seller | New route, admin. For a seller who leaves or hands over |
| A seller's name on client cards and rows, on request cards, and on Visão geral rows; a filter by seller and a "Meus" filter on Clientes, Pedidos, Quadro and Campanhas | `static/` |
| "Convidar parceiro" beside the member invite; the people list shows who is a seller | Configurações → Time |

That is 73 routes, up from 71. One page and one bundle serve staff and sellers. The menu
and the staff-only controls are hidden when `ME.is_seller`; the server refuses those
actions whatever the page shows.

### Part D: two channels

*   `control.tenant.channel` is `stable` or `next`. Two services run, one per channel,
    from two release folders, against the same database. Each serves only the tenants of
    its channel.
*   **The proxy** sends every host to the stable service, except the hosts in a short
    list of tenants that are on next. The list is a generated file; the command that
    changes a tenant's channel rewrites it and reloads the proxy.
*   **A release** goes to next first and is promoted to stable later. `pauta-deploy`
    takes the channel as an argument.
*   **Tenant schemas** carry their own schema version. A channel's deploy migrates the
    schemas of its tenants one at a time and records each, so a failure halfway is
    visible and can be resumed. The repo's rule that schema changes are additive is what
    lets a tenant move back from next to stable.
*   **Meta's return address is per channel.** The one-time `state` of a Meta sign-in
    lives in the memory of the service that started it. A tenant on next must return to
    the next service, so Meta's app lists two return addresses, `app.pauta.cc` and
    `next.pauta.cc`.
*   **The `control` schema is used by both versions at once.** A change there must work
    with the old code and the new code together: add first, remove only after both
    channels are past it.

### The releases

| Release | What lands | A rollback to the one before |
|---|---|---|
| 1. The move | Part A, with the final layout: `control`, tenant 1, its staff role, the role switch per transaction, the host lookup. Nothing a user can see changes but the order of accented names (decision 14) | Reads the kept SQLite file; loses what was written since |
| 2 or 3. Sellers | Part C | Safe. Release 1 already switches to whatever role the membership names, so the database still restricts a seller |
| 2 or 3. Tenants | The rest of Part B: `pauta tenant add`, the wildcard host, the Meta return address | Safe. Release 1 already looks the host up and switches to that tenant's role |
| Later | Part D | |

Sellers and tenants both stand on release 1 and neither needs the other. Their order is
open question 10.

**The rollback guard (decision 4).** It was chosen when an older release would have
treated a seller as a member. In this plan no such release exists on Postgres: from
release 1 on, the role comes from the membership and the database enforces it. What an
older release lacks is the three small checks under "What rows and grants cannot cover";
the worst of those is a seller reading the text of a Meta sync error. The guard is
therefore dropped. Keeping it would have cost a change to the root-run deploy script.

### Tests

| Test | What it proves |
|---|---|
| **The existing tests, on Postgres** | Release 1 changes nothing a user can see (goal 9). They are the main check of the move, and they are what finds the statements the adapter cannot carry |
| **The boundary test** (goal 11), `tests/api/test_boundaries.py` | One database with two tenants; tenant 1 has a staff account, sellers A and B and a house client. Every record of B, of the house and of tenant 2 carries a canary string in every text field. The test reads the server's route table and calls every route as seller A with B's and the house's ids, and as tenant 1's staff with tenant 2's ids. It passes when every answer is 403, 404 or a body with no canary. It holds a table that says how to fill each route pattern, so a route that is not in the table fails |
| **The grants test**, `tests/unit/test_grants.py` | For each role, the tables and columns it can read and write are exactly the ones in this plan's table. A tenant role can read nothing in another tenant's schema or in `control`. `pauta_app` has no rights of its own. Every view but `account` and `passkey` has `security_invoker`, and those two have exactly the columns of Part B's table |
| **Push** | A change to one of A's requests wakes no device of B; a change in one tenant wakes no device of another |
| **The copy** | `pauta import-sqlite` on a copy of production: every table's row count and checksum match |

### What the trial showed (stage 0, run on 2026-11-22)

Run on a Mac against Postgres 17.12 in a throwaway container, with `psycopg` 3. The
layout was generated from Pauta's real schema at 1.17.0. The data was Pauta's demo data
grown to the design's target size: 250 clients, 500 campaigns, 60,000 daily campaign
rows, 2,000 requests, six accounts (three staff, three sellers) and a second tenant.
Nothing in the repository was changed. The scripts are scratch files and are not kept
in the repository.

**1. The layout, the roles and the rules: 43 of 43 checks pass.**

*   `control`, two tenant schemas with 19 tables each, the four tenant roles, the grants
    and the seller policies were created in one transaction, roles included. Each tenant
    ends up with 34 policies and 34 indexes.
*   As seller A (10 assigned clients): exactly 10 clients, 80 requests, 240 timeline
    rows, 20 campaigns, 2,400 daily rows and 10 ad accounts; none of another seller's.
    Payments, billing, the Meta logs and the usage log are refused. The finance setting
    and the sync error text are hidden. The people list shows staff and the seller.
*   A seller edits the briefing of their own request, files a request and comments.
    Changing `status` or `assignee`, naming `status` on insert, changing `billed`, filing
    or commenting for another seller's client, and assigning themself a client are all
    refused. Editing another seller's request or client changes no row.
*   A seller with no clients, and a seller role with no account set, see nothing.
*   Staff see all 250 clients. Each tenant's roles are refused in the other tenant's
    schema and in `control`. `pauta_app` without a role is refused everywhere and cannot
    become `pauta_system`.

**2. The three settings per transaction hold under load.** 16 threads ran 4,800
transactions on a pool of 4 connections, each as a random one of five identities. No
transaction saw another's role, schema or account, and nothing was left on a connection
for its next user. Sent as one statement the settings add about 0.5 ms to a transaction
(1.4 ms against 0.9 ms); sent as three they add 1.2 ms. That is through Docker on a Mac.

**3. Most of `Store` runs on Postgres without being rewritten.** Pauta's own `Store`
class was run unchanged on a Postgres connection, through an adapter of about forty
lines that turns `?` into `%s` and `IS ?` into a null-safe comparison. Two objects in the
database stood in for SQLite: a function named `datetime` and a case-insensitive
collation named `nocase`.

| | Tried | Result |
|---|---|---|
| Read methods, as staff | 22 | 15 give the identical answer. 3 give the same rows in another order (below). 4 fail |
| Write methods, as staff | 11 | 9 run. 2 fail |
| The three the plan named | `clients`, `update_request`, `campaign_overview` | All run. As seller A, `clients` and the overview return only the 10 assigned clients; `update_request` saves an own request, answers `NotFound` for another seller's, and is refused for `status` |

The six failures, each a small, known kind:

*   `members`: `group_concat` does not exist (1 place in `src/pauta`).
*   `finance`: an integer used as a truth value in `AND`.
*   `seen_on`: `GROUP BY` must name every selected column.
*   `report_links`: SQLite's `rowid` (2 places).
*   `create_request` and a new `save_client`: `lastrowid` (3 places).
*   A new `save_client`: a Python `True` sent to an integer column.

The order: SQLite's `NOCASE` sorts accented capitals after `z`; the Postgres collation
sorts "Ação" among the A's. Clients, the campaign list and the overview come back in
that other order.

`Store` has 82 methods and `auth.py` uses the store 21 times; 33 methods were
tried. The rest is unknown until the tests run on Postgres.

**4. The import is exact and fast.** 21 tables and 69,449 rows were copied with their
ids, and every row was compared on both sides: none differed. Creating the layout,
copying, adding the keys and the rules took 0.3 seconds. A copy of production was not
loaded: that means copying real client data to this Mac, which was not done without
asking.

**5. Timings** (median of 15 runs; a Mac and Docker, not the Pi):

| | Campaign overview | Client list | Request list |
|---|---|---|---|
| SQLite, today | 62 ms | 3.0 ms | 13.7 ms |
| Postgres, staff | 120 ms | 4.3 ms | 20 ms |
| Postgres, seller A, policy as a function per row | 38 ms | 4.3 ms | 5.9 ms |
| Postgres, seller A, policy as one array of client ids | 25 ms | 2.0 ms | 3.9 ms |

Against the limits proposed for the trial:

| Limit | Result |
|---|---|
| The overview as a seller at most twice the staff time | Met: a fifth to a third of it. The policies cost staff nothing measurable |
| The import under five minutes | Met: 0.3 seconds for 69,449 rows |
| The inner test loop under 20 seconds | Not measured. Emptying one tenant's tables between tests takes 4.4 ms, which is about 2.8 seconds across the roughly 635 test functions on one worker. The tests themselves were not run on Postgres |

Postgres is about twice as slow as SQLite for the largest read, as staff. Both are far
below what a person notices.

**6. What the trial changes in this plan.** The four marked "agreed" were agreed by the
author on 2026-11-23 and are written into Parts A, B and C and the stages. The other
three are findings, not choices; each says where the plan takes it up.

*   **Agreed: stage 1 is an adapter, not a rewrite of 218 statements** (decision 12).
    A thin adapter, the two stand-ins in the database, and fixes for the kinds of
    failure listed above.
*   **Agreed: the order of names changes** (decision 14). Accented names sort among
    their letters. It is the one visible change of the move and a stated exception to
    goal 9. The same collation also makes "AÇÃO" and "ação" one name; Part A says what
    the import does about that.
*   **Agreed: the people view is named `account`, not `member`,** and a second view is
    named `passkey` (decision 13). `Store`'s SQL reads those two names in 19 statements;
    with the views under those names it runs unchanged. In the trial the system role saw
    staff only through them; Part B's views show it every member of the tenant. The
    trial's views also carried more columns than `Store` reads; Part B's do not.
*   **Agreed: the seller policy is written with one array of the seller's client ids**
    (decision 15), not a function called per row. It is a third faster and reads more
    simply. Written into Part C.
*   **`insight` has no client column.** Its policy goes through the campaign's
    `meta_id`. A fact about the schema, written into Part C with the array.
*   **A session can switch itself from the seller role to the staff role.** Postgres
    checks role membership against the connection's login, `pauta_app`, which may switch
    to any tenant role. So the walls hold against a mistake in a query, not against SQL
    injected into a seller's request. That rests on Pauta's SQL always passing values as
    parameters; checking that it does belongs with the security review of stage 2.
*   **The cut-over imports a file the current release has already opened.** Opening the
    SQLite file with `Store` runs its start-up step, which can write (it opens billing
    cycles). In production that has long since happened; the import must not be pointed
    at an older copy.

**7. Not tried.**

*   A copy of production.
*   The Pi: an ARM Linux host with the database on the same machine. The timings above
    are not the Pi's.
*   Pauta's test suite on Postgres, and with it the true time of the test loop.
*   `auth.py`, the Meta sync, the server itself with a pool, and about 50 `Store` methods.
*   Report views with `security_invoker`: Pauta has no report views yet.

### What this plan leaves weak

*   **It is a migration of a live system before any new feature.** Release 1 gives users
    nothing and can break anything. Sellers and other agencies come after it. About ten
    weeks remain until February.
*   **The application chooses the role.** One function reads the membership and switches
    to the matching role. If it picked the staff role for a seller, the database would
    obey. That function is the one place this design trusts the application, and it has
    its own tests.
*   **A session can change its own role and account.** The service's login may switch
    to any tenant role and set any account, and so can SQL that reaches the database
    through it. The walls hold against a mistaken query, not against SQL injected into a
    request. That rests on every statement passing its values as parameters, which is
    checked in the security review of stage 2 and has not been audited yet.
*   **The app process holds the system role's password.** The walls protect against a
    mistake in the application's code. They do not protect against someone who takes
    over the process.
*   **The system role is an escape.** Any code that asks for it sees every tenant. The
    plan names its callers; a review has to keep that list short.
*   **Everything is created once per tenant.** Nineteen tables with their indexes,
    policies and views, and two roles. A few hundred tenants is thousands of objects,
    which Postgres handles. Thousands of tenants would need a different layout.
*   **A host per tenant adds moving parts outside the application:** a wildcard
    certificate, the proxy's list for the next channel, and Meta's fixed return address.
*   **Two versions share `control`.** The discipline of "add first, remove later" is a
    rule people must follow; nothing enforces it.
*   **The stored forms stay as they are.** Text timestamps and integer flags in Postgres
    are a deliberate shortcut to keep answers identical.
*   **The SQL is spelled for SQLite and runs on Postgres (decision 12).** A reader of
    `Store` sees `?`, `datetime('now')` and `COLLATE NOCASE`, and has to know that an
    adapter and two database objects stand behind them. New SQL is written in the same
    spelling. The adapter works on the statement's text: it would also change a `?`
    inside a quoted string (there is none in `src/pauta` today), and Postgres's own
    operators that contain `?` cannot be written through it. Once nothing runs on SQLite
    the spelling protects nothing; it is kept because it avoids touching 218 statements
    before February. Rewriting the placeholders once would remove the adapter (see
    "Future Improvements").
*   **`account` means two things (decision 13).** It is a table in `control` and a view
    in every tenant's schema, and the search path decides which one a statement reads.
    A statement moved between `auth.py` and `Store` changes what it reads without
    changing a character.
*   **Two seller accounts on one client** is allowed and nobody has asked for it.
*   **Everything on a request is visible to its seller**, every comment included (open
    question 11).

## Alternatives Considered

All of these were weighed on 2026-11-22, except where a row gives another date. The order within each group is the order in
which they came up. "Rejected by author" means the author chose something else when
asked; "not pursued" means it was raised and set aside without a formal choice.

### Where the rule is enforced

| Alternative | For it | Against it | Outcome |
|---|---|---|---|
| **A seller-only store object and a separate seller API.** A second class wraps `Store` and exposes only what a seller may do; sellers get their own routes under `/api/s/` | Works on today's SQLite. The smallest change that does the job. Seller code cannot reach a staff handler | 22 routes written twice. The account is carried at the route. A new `Store` method is only safe if someone remembers to wrap it | Rejected by author: the account should not be held at the route; the filter belongs at the base, where the data is opened |
| **Filters built into a SQLite connection.** A temporary view over every table, an authorizer that refuses reads around the views, guard triggers on writes | The SQL in `Store` reads filtered rows unchanged. A new table is hidden by default. Tried on Pauta's real schema: reads, guarded inserts and updates behaved as designed; opening such a connection took 2.6 ms | Views cannot be written through, so all 61 write statements had to name the real table. A direct read of a writable table could not be refused. A "system" escape was needed for the sync, the CLI, sign-in, push and background threads | Rejected by author: too many interlocking parts to maintain |
| **A rewrite in C#, Rust or Java.** In C#, entity classes with an owned-by base and EF Core's global query filters | The pattern the author has seen work. A typed model layer for the whole application | About 9,000 lines of backend and 17,000 lines of tests rewritten, with nothing for users meanwhile. The common Rust data libraries have no global filters. Every such filter can be switched off per query and is skipped by raw SQL | Rejected by author, who chose Python on Postgres |
| **An ORM in Python as the enforcing layer.** Mapped classes with a default filter the session adds to every query | The same pattern as the C# one, and it can be adopted method by method | SQL that stays hand-written is not filtered. The heavy reports tend to stay hand-written | Not chosen as the place of enforcement. Whether to add a model layer for maintainability is open question 13 |
| **A graph database (Neo4j, Cypher) for the access rules** | Suits permissions found by walking many relationships | The question here is one lookup deep. A Postgres policy cannot ask a second database, so the filter would return to application code. Two databases would have to agree | Not pursued |

### How tenants are kept apart

| Alternative | For it | Against it | Outcome |
|---|---|---|---|
| **A tenant per seller** | Reuses the tenant wall for sellers | The team would open one Pauta per seller, which the request rules out. A seller does not run campaigns | Rejected by author |
| **One SQLite file per tenant** (decision 5) | Already specified in draft PR 43. A tenant is a file to copy or delete | SQLite cannot enforce the seller rule, and the two rules should not live in two engines | Replaced by this design |
| **A tenant column and a policy on every table, in one database** | One migration, one connection pool; work across tenants is a normal query | The wall is a policy: a mistake in it, or in who is asking, crosses agencies. Restoring or deleting one agency means picking rows out. Every statement gains a tenant | Rejected by author |
| **A database per tenant** | The connection itself is the wall. A tenant is a database to dump or drop | Accounts shared by several tenants cannot be referenced across databases. A pool per tenant runs into Postgres's connection limit at a few hundred tenants | Rejected by author, who raised it and then chose a schema per tenant |
| **A schema per tenant, chosen by search path only** | One database and one pool | Nothing stops the application from pointing a session at the wrong schema; the wall is back in application code | Rejected in favour of the same layout with a database role per tenant |
| **One database role per tenant** | Fewer roles | Tables and columns a seller may not touch need policies and a trigger | Rejected by author, who asked for several roles per tenant |

### Which tenant a request is for

| Alternative | For it | Against it | Outcome |
|---|---|---|---|
| **From the account:** an account belongs to exactly one tenant | No change to routes or addresses | One person in two tenants needs two accounts and two passkeys | Rejected by author |
| **In the address:** `/api/t/<name>/...` and `#/<name>/` (the multi-tenant spec's decision of 2026-11-11) | One account in several tenants from the first day; no DNS or certificate work | All 71 routes and about 80 calls in the page gain a prefix; every saved link changes | Rejected by author |

### Roles and permissions

| Alternative | For it | Against it | Outcome |
|---|---|---|---|
| **A role editor:** custom roles, any action on or off per role | Each agency shapes its own roles without asking | About 4,000 combinations per role, and every screen must behave under each. It does not remove the work of limiting rows | Rejected by author |
| **Allow and deny per user** on top of a role editor | The finest control | Precedence rules, and a screen to explain why someone cannot see something | Rejected by author |
| **A seller's client belongs to the seller's account,** with an action to move all of them to another account | Two columns and one route | One login per seller at any time | Rejected by author |
| **A seller record** that accounts and clients point to | Several logins share one seller; a person leaving changes nothing | One more table and an admin screen | Rejected by author, who chose the assignment table |

### Sellers without a login

| Alternative | For it | Against it | Outcome |
|---|---|---|---|
| **The team files requests for sellers;** a seller is a label on the client | No outsider signs in. It can ship on today's application | Sellers are to register their own clients from the start | Rejected by the seller programme's owner. The label itself is still useful until sellers can sign in |
| **A per-seller link** with a read-only page and an intake form | No account to manage | A seller creates clients, files requests and uploads files. A long-lived link is a weaker credential for the same access | Not pursued |

### Operations

| Alternative | For it | Against it | Outcome |
|---|---|---|---|
| **Postgres from Debian's packages on du7** | No container; a Unix socket and no password | The version follows Debian's | Rejected by author |
| **A managed Postgres off the Pi** | Backups and upgrades are the provider's | A monthly cost; clients' data leaves the author's hardware; every query crosses the internet from the Pi | Rejected by author. Open question 12 may bring it back when production leaves du7 |
| **Two designs:** the move to Postgres first, as its own design and release | A smaller first step | The move would then be designed without the layout tenants and sellers need | Rejected by author |
| **A release per tenant** | A customer could stay on an old version | Several live versions to route and to weigh each fix against | Not pursued; two channels instead |
| **Port every statement to Postgres's own spelling** in the move | No translation step and no stand-ins; the repository reads as what runs | 218 statements, 42 more in `auth.py`, and the SQL in the tests are touched in the release that can break anything. The trial showed most of them run as written | Planned until the trial; rejected by author on 2026-11-23 for the adapter (decision 12) |
| **When nothing says who is asking: see everything** | No change to the sync, the CLI or sign-in | The safe state would be something code must switch on | Rejected by author |
| **Against a rollback past seller access: store sellers as disabled for old code, or a step in the runbook** | No change to the deploy script | The first splits the meaning of `disabled`; the second depends on someone reading the runbook during an incident | Rejected by author, who chose a guard in `pauta-deploy`. The guard itself was dropped when the technical plan was approved: from the first Postgres release the role comes from the membership |

--------------------------------------------------------------------------------

## Non-Functional Requirements

*   **Security and privacy.** Both walls are enforced by Postgres (Parts B and C) and
    proved by the boundary and grants tests. What they do not cover is listed under
    "What this plan leaves weak": the function that chooses the role, the system role,
    and a takeover of the process. Who is the controller of whose data under the LGPD is
    open question 9.
*   **Performance.** Not measured. The trial measures the test loop, the cost of the
    seller policies on the campaign overview, and the three settings per transaction.
    The expected sizes are small: 250 clients, a few hundred tenants at most.
*   **Rollout and rollback.** "The cut-over" and "The releases". The one step that
    cannot be undone without loss is the move itself, after its first hour.

--------------------------------------------------------------------------------

### Additional Resources

*   [`2026-11-22_tenants-and-sellers_brief.md`](2026-11-22_tenants-and-sellers_brief.md): what was
    asked and answered, and how the day's decisions went.
*   `docs/multi-tenant-spec.md` and `docs/access-and-operator-spec.md` on branch
    `docs/multi-tenant-spec` (draft PR 43): tenant identity, invites and integrations per
    tenant, and the access roles. Their file-per-tenant layout is replaced by this design.
*   `docs/decisions/0005-other-teams.md` and `0006-subscriptions.md`.

### Future Improvements

*   **A model layer.** Entity classes over the tables, with report queries as views
    (open question 13).
*   **Custom roles per tenant.** One more database role with different grants.
*   **Native Postgres types** for dates and flags.
*   **Postgres's own spelling in `Store`.** One mechanical rewrite of the placeholders,
    `datetime('now')` and `COLLATE NOCASE` removes the adapter and the two stand-ins.
*   **One account in several tenants without a second sign-in,** if per-host sessions
    turn out to be a nuisance.

## Detailed Implementation Plan

Five stages. Each is its own pull requests and its own release, and each ends with
`make check` green. Stage 1 is the only one the others depend on. No stage is sized in
days here: the sizes are set after stage 0, from its numbers.

Names fixed for all stages: schema `control`; tenant schemas `t<id>`; roles
`pauta_system`, `pauta_app`, `t<id>_staff`, `t<id>_seller`; the per-transaction setting
`pauta.account`; the driver `psycopg` 3 with its pool. Postgres is pinned to one major
version, 15 or later (report views need `security_invoker`), chosen in stage 0.

Paths marked **(owner)** are in `.github/CODEOWNERS` and need the owner's review.

### Stage 0: the trial

Nothing in the repo changes except this document. The work is done in a scratch folder
against a Postgres container started from a throwaway compose file.

**Run on 2026-11-22.** The results are under "What the trial showed" in the technical
plan. Two of its steps are still open: loading a copy of production, and timing the real
test loop.

| Step | Done when |
|---|---|
| Create `control`, `t1` and `t2` with every table of today's schema, the four tenant roles, the grants and the seller policies of Part C | A script shows, for each role, the rows and columns it can read and write, and they match Part C's table. A tenant role is refused in the other tenant's schema and in `control` |
| The three settings per transaction through a `psycopg` pool, from several threads | No transaction ever sees another's role, search path or account |
| Port `Store.clients`, `Store.update_request` and `Store.campaign_overview` | Each returns the same answer as on SQLite for the same data |
| Load a copy of production with a first version of the import | Row counts and checksums match for every table |
| Measure | The test loop for the three ported methods' tests; the campaign overview as staff and as a seller; the import's duration |

Proposed limits, for the author to confirm when the numbers are in: the inner test loop
under 20 seconds (5 today), the overview as a seller no slower than twice the staff
time, the import under five minutes. The results replace "What was tried, and what was
not" in this document.

### Stage 1: the move (release 1)

| File | | What changes and why |
|---|---|---|
| `pyproject.toml`, `uv.lock` **(owner)** | Modify | Add `psycopg[binary,pool]`. The comment that calls `webauthn` "the one exception to stdlib only" goes |
| `src/pauta/scope.py` | Create | The connection pools for `pauta_app` and `pauta_system`; the context that holds tenant, account and role for a request; the context manager `Store.db()` uses, which raises when nothing is set, applies the three settings per transaction as one statement, and turns Postgres's "insufficient privilege" into a new `Denied` error; the adapter of decision 12, which gives `Store` a connection with `execute` and `executemany`, translates `?`, `IS ?`, `IS NOT ?` and `%` once per statement text, and returns rows that read by name and by position |
| `src/pauta/schema.py` | Create | The SQL that creates `control` and a tenant schema, the two numbered migration lists (one for `control`, one applied to each tenant schema, with the version kept in each schema's `meta`), the roles and grants of a tenant, the `account` and `passkey` views of each tenant schema (Part B), and the shared schema `pauta` with the two stand-ins: the function `datetime('now')` that writes timestamps in today's text format and the collation `nocase`. Moved out of `db.py` so the 2,294-line file does not grow |
| `src/pauta/db.py` | Modify | The SQL stays as written (decision 12). Fixed in place, as listed in Part A: `INSERT OR` (5), `lastrowid` to `RETURNING id` (3), `rowid` (2), `datetime('now', <an offset>)` (2), `group_concat` (1), and the integer truth tests, `GROUP BY` lists and Python booleans the tests find. The one `LIKE` is checked by hand. `members` reads `avatar` from the `account` view instead of computing it from `email`; the other 18 statements that read `account` or `passkey` stay as written. Remove the schema and the `PRAGMA` migrations (now in `schema.py`). `Store` takes a scope instead of a file path. `backup` calls `pg_dump`. Rows come back as dictionaries, as today |
| `src/pauta/auth.py` **(owner)** | Modify | All 21 uses of the store run as `pauta_system`, in a scope whose search path puts `control` first, so that `account`, `passkey` and `invite` are the tables in `control` and not a tenant's views. `is_admin` and `disabled` move from the account to its row in `control.membership`; `viewer` takes the tenant and returns `role` and `is_admin` from the membership |
| `src/pauta/server.py` | Modify | `_dispatch` looks the host up in `control.tenant_host`, reads the membership, sets the scope before the handler and clears it after; open routes run as system for that host's tenant; `/healthz` and `/metrics` run as system; `Denied` maps to 403; an account with no membership here gets "not a member" |
| `src/pauta/routes/requests.py` | Modify | The thumbnail cache folder comes from the tenant's state folder; the warm-up thread declares the system scope |
| `src/pauta/meta.py`, `src/pauta/onedrive.py` | Modify | The secret and token files are read from the tenant's state folder. Background reads declare the system scope and the tenant |
| `src/pauta/push.py` | Modify | The signing key file is read from the state directory; the fan-out declares the system scope and the tenant |
| `src/pauta/sync.py` | Modify | The hourly pass and "Atualizar agora" declare the system scope and the tenant |
| `src/pauta/usage.py` | Modify | Its 6 statements run through the adapter, fixed where the tests show a need; the report takes a tenant |
| `src/pauta/obs.py` | Modify | Request log lines carry the tenant's id beside the route pattern |
| `src/pauta/importer.py` | Create | `pauta import-sqlite <file>`: creates `control` and tenant 1 with host `app.pauta.cc`, copies every table keeping ids, turns each account into a staff membership, sets the identity counters, moves the files beside the database into tenant 1's folder, and compares the row count and a checksum of every table. It refuses a database that is not empty. Before copying it looks for two clients whose names are one name under the `nocase` collation and stops with both names |
| `src/pauta/cli.py` | Modify | New commands `import-sqlite` and `migrate`. `backup` uses `pg_dump`. `serve` reads the database address and the passfile from the environment. `demo`, `users`, `invite`, `usage`, `reload`, `meta` and `onedrive` take `--tenant`, which may be left out while there is one |
| `tests/pg.py` | Create | One database per test worker, built from `schema.py` with `control` and tenant 1, emptied between tests |
| `tests/conftest.py`, `tests/appserver.py`, `tests/e2e/conftest.py` | Modify | The `store` fixture and the test servers use `tests/pg.py`; tenant 1's host is the test server's own |
| The 11 test files that open the SQLite file themselves, and the 91 places tests call `store.db()` | Modify | The 11 files stop opening a file with `sqlite3` and read through the store, whose adapter carries their SQL as written. All of them declare the system scope. The files: `tests/api/test_app.py`, `test_hardening.py`, `test_http.py`; `tests/unit/test_auth.py`, `test_campaigns.py`, `test_cli.py`, `test_meta_accounts.py`, `test_meta_connections.py`, `test_move_unit.py`, `test_store.py`, `test_report_links.py` |
| `tests/unit/test_scope.py` | Create | No scope raises; the three settings never leak between transactions or threads; the adapter translates `?`, `IS ?`, `IS NOT ?` and `%` as Part A says; no statement in `src/pauta` has a `?` inside a quoted string |
| `tests/unit/test_schema.py` | Create | A fresh database and a migrated one end with the same tables, columns, grants and policies |
| `tests/unit/test_importer.py` | Create | A SQLite file built by today's `pauta demo` arrives whole; a changed row fails the checksum; two clients named "AÇÃO" and "ação" stop the import before anything is copied |
| `tests/unit/test_grants.py` | Create | `pauta_app` has no rights of its own; `t1_staff` reads nothing in `control` or in a second tenant's schema; the `account` and `passkey` views have exactly Part B's columns and show the system role every member of the tenant |
| `tests/unit/test_deploy_scripts.py`, `tests/unit/test_deploy_branch.py` | Modify | The backup step is `pg_dump`; the cut-over runs the import once |
| `deploy/postgres/compose.yml` **(owner)** | Create | The Postgres container: one pinned image, 127.0.0.1 only, its data on the Pi's own disk, a health check |
| `deploy/provision-du7.sh`, `deploy/provision-branch-env.sh` **(owner)** | Modify | Start the container; create the production and acceptance databases and the roles `pauta_system` and `pauta_app` for each; write the passfile for the service user from 1Password |
| `deploy/pauta.service`, `deploy/pauta-acc.service`, `deploy/pauta-backup.service` **(owner)** | Modify | Start after Docker; the database address and passfile in the environment; the backup runs `pg_dump` |
| `deploy/pauta-deploy`, `deploy/pauta-deploy-branch` **(owner)** | Modify | The pre-deploy backup is `pg_dump` once the database is Postgres. At the cut-over only: stop the service, back up the SQLite file, run `pauta import-sqlite`, start. `--capabilities` reports "postgres" |
| `.github/workflows/ci.yml` **(owner)** | Modify | A Postgres service for the test jobs |
| `.github/workflows/deploy.yml` **(owner)** | Modify | Refuse to deploy release 1 to a host whose `pauta-deploy` does not report "postgres" |
| `Makefile` **(owner)** | Modify | `make db` starts the compose file locally; `run`, `demo` and the test targets say so when no database answers |
| `deploy/README.md` **(owner)** | Modify | The container, the roles, the passfile, the cut-over and its one-hour rollback, restoring from a `pg_dump` |
| `CLAUDE.md`, `CONTRIBUTING.md` **(owner)**, `README.md` | Modify | "Shape" and "The loop": Postgres, `psycopg`, `make db`, the scope and who says "system", and that SQL in `Store` is written in SQLite's spelling and why. The line "stdlib HTTP server, SQLite, the only runtime dependency is `webauthn`" is rewritten |
| `docs/decisions/` **(owner)** | Create one record, modify two | A new record, under the next free number, for decisions 6 to 15 of this design. `0005-other-teams.md` is marked as replaced in its layout. `README.md` lists the new record |
| `CHANGELOG.md` | Modify | A line under Unreleased: Pauta runs on Postgres; on screen only the order of names with accents changes |

**Done when:** the existing tests pass on Postgres without a change to what they assert,
except a test that asserts the old order of an accented name, which is changed and named
in the pull request;
acceptance has run on it for a week; the import of a copy of production matches; the
owner has installed the new `pauta-deploy` and the container on du7.

### Stage 2: sellers

| File | | What changes and why |
|---|---|---|
| `src/pauta/schema.py` | Modify | A tenant migration: the `assignment` table; the client name index no longer unique; the `t<id>_seller` role with Part C's grants and policies, and the `my_clients()` function they use; `security_invoker` on every report view |
| `src/pauta/db.py` | Modify | `clients()` and `client()` carry `sellers` and `responsible`. `save_client` checks the name under the caller's role and, for a seller, writes the client and its assignment as system with `billed` off. Insert statements name only the columns the caller set. `set_assignments` and `move_assignments`. `on_news(by, client)`; `push_targets` returns staff and the sellers assigned to that client |
| `src/pauta/auth.py` **(owner)** | Modify | An invite may be for a seller; the membership it creates has role `seller`. `set_member` refuses `is_admin` on a seller and does not change a membership's role. `viewer` carries `is_seller` |
| `src/pauta/push.py` | Modify | Passes the client to the fan-out |
| `src/pauta/routes/__init__.py` | Modify | `finance_visible()` is false for a seller |
| `src/pauta/routes/clients.py` | Modify | `PUT /api/clients/{id}/assignments`: a member changes staff rows, an admin also seller rows |
| `src/pauta/routes/team.py` | Modify | The people list shows each person's role; `POST /api/members/{id}/assignments/move`, admin |
| `src/pauta/routes/account.py` | Modify | `POST /api/invite` takes `seller`; `boot` answers `me.is_seller` |
| `src/pauta/routes/campaigns.py` | Modify | A seller gets the neutral line for `sync_error` |
| `src/pauta/cli.py` | Modify | `pauta invite --seller` |
| `src/pauta/static/app.js`, `app-router.js` | Modify | `ME.is_seller`; the menu without Financeiro and Configurações for a seller |
| `src/pauta/static/app-clients.js`, `app-requests.js`, `app-campanhas.js` | Modify | The seller's name on cards and rows; the filters by seller and "Meus"; the editor of a client's sellers and responsible people; staff-only controls hidden for a seller |
| `src/pauta/static/app-team.js` | Modify | "Convidar parceiro"; the role in the people list; "Mover clientes para…" |
| `src/pauta/static/style.css` | Modify | The seller label, in light and dark |
| `tests/api/test_boundaries.py` | Create | Goal 11, the seller half: every route as seller A with B's and the house's ids; the table of how to fill each route pattern |
| `tests/unit/test_grants.py` | Modify | The seller role's tables, columns and rows match Part C's table; every view but `account` and `passkey` has `security_invoker` |
| `tests/api/test_sellers_api.py` | Create | CUJs 1 to 4 through the API: the invite, the first client, a request and its comments, the refused status change, the report link |
| `tests/unit/test_push.py`, `tests/api/test_push_api.py` | Modify | A change to A's request wakes no device of B |
| `tests/e2e/test_seller.py` | Create | CUJ 1 and CUJ 5 in the browser: a seller's menu and first client; a campaign manager's "Meus" filter |
| `CHANGELOG.md`, `README.md`, `CLAUDE.md` **(owner)** | Modify | Sellers, the assignment table, who may change it |

**Decide before this stage:** open questions 2, 3, 4, 7 and 11 (the name in the
interface, money, the WhatsApp buttons, what a seller may edit, comments).

**Done when:** the boundary test passes with no route missing from its table, and
`/security-review` has been run on the change.

### Stage 3: tenants

| File | | What changes and why |
|---|---|---|
| `src/pauta/tenants.py` | Create | Creating a tenant in one transaction: schema, roles, tables, grants, policies, its row and host, its state folder. One `Meta`, one OneDrive client and one thumbnail cache per tenant, found by the request's tenant, so that the route modules keep using `meta` and `drive` as they do today |
| `src/pauta/cli.py` | Modify | `pauta tenant add <name>`, `tenant list`, `tenant host`; `--tenant` becomes required where there is more than one |
| `src/pauta/server.py` | Modify | An unknown host is "not found"; the origin check accepts the request's own host when it is a tenant's; reserved names |
| `src/pauta/auth.py` **(owner)** | Modify | An invite belongs to a tenant and creates a membership there; an existing account that accepts one gains a second membership |
| `src/pauta/routes/campaigns.py`, `src/pauta/meta.py` | Modify | The one-time `state` of a Meta sign-in remembers the tenant; the callback on the fixed address finishes and sends the browser to the tenant's host |
| `src/pauta/sync.py`, `src/pauta/push.py`, `src/pauta/usage.py` | Modify | Loop over tenants; a tenant's failure does not stop the others |
| `src/pauta/obs.py` | Modify | `/metrics` counts per tenant, by id |
| `deploy/Caddyfile.pauta` **(owner)** | Modify | `*.pauta.cc` with a certificate by DNS challenge |
| `deploy/README.md` **(owner)** | Modify | Adding a tenant, the wildcard record and certificate, dumping and dropping one tenant |
| `tests/api/test_boundaries.py` | Modify | Goal 11, the tenant half: every route as tenant 1's staff with tenant 2's ids, on tenant 1's host |
| `tests/api/test_tenants_api.py` | Create | CUJs 6 and 7: a new tenant's first admin; one account in two tenants; a member of one at the other's address |
| `tests/unit/test_tenants.py` | Create | `tenant add` leaves the same objects as tenant 1 has; a failure leaves nothing behind |
| `tests/unit/test_sync.py`, `tests/unit/test_push.py` | Modify | The loops; no device of another tenant is woken |
| `CHANGELOG.md`, `README.md`, `CLAUDE.md` **(owner)** | Modify | Tenants, hosts, the per-tenant state folder |

**Decide before this stage:** open questions 12 and 14 (where production runs; the first
tenant's name). The DNS record `*.pauta.cc` is added in the `dns-zone` repository, not
here. The multi-tenant spec (draft PR 43) is revised to this layout in its own pull
request.

**Done when:** a second tenant exists on acceptance, both halves of the boundary test
pass, and `/security-review` has been run on the change.

### Stage 4: two channels

| File | | What changes and why |
|---|---|---|
| `src/pauta/schema.py` | Modify | `control.tenant.channel`; tenant migrations applied one tenant at a time, each recorded |
| `src/pauta/server.py` | Modify | A service answers only for tenants of its own channel |
| `src/pauta/cli.py` | Modify | `pauta tenant channel <name> <channel>`, where the channel is `stable` or `next`, rewrites the proxy's list and says to reload it; `pauta migrate --status` lists each tenant's schema version |
| `deploy/pauta-next.service` **(owner)** | Create | The second service, on its own port, from its own release folder |
| `deploy/pauta-deploy` **(owner)** | Modify | A channel argument; a release is installed on next and promoted to stable |
| `deploy/Caddyfile.pauta` **(owner)** | Modify | Hosts in the generated list go to the next service; all others to stable |
| `.github/workflows/release.yml`, `deploy.yml` **(owner)** | Modify | A release deploys to next; promotion is a separate, manual run |
| `deploy/README.md`, `CONTRIBUTING.md` **(owner)** | Modify | The two channels; the rule for changes to `control`: add first, remove after both channels are past it |
| `tests/unit/test_deploy_scripts.py`, `tests/unit/test_schema.py` | Modify | Promotion; a migration that fails on one tenant is visible and can be resumed |

**Done when:** tenant 1 runs on next for a week while a demo tenant stays on stable, and
moving the demo tenant between them needs no data copy.

### Verification Plan

*   **Inner loop:** `make test-fast` while working; it needs `make db` from stage 1 on.
*   **Before pushing:** `make check` (lint, unit and API tests with coverage at 90% or
    more, browser tests). Warnings stay errors.
*   **Static analysis:** `make lint`.
*   **New tests:** the boundary test, the grants test, the scope test, the schema test
    and the importer test, as named in each stage.
*   **Security review:** `/security-review` on every change to `auth.py`, `routes/`,
    `scope.py`, `schema.py` and the Meta code, and the owner's review on the paths marked
    **(owner)**.
*   **On acceptance:** each stage runs there before production; stage 1 for a week.
*   **By hand, once per stage:** the stage's "done when".

--------------------------------------------------------------------------------

*Drafted with EGM*
