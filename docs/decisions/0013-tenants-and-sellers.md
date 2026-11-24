# 13. Tenants and sellers: Postgres, a schema per tenant, the tenant by host name

- **Status:** accepted in its main lines on 2026-11-22 and 2026-11-23; nothing is built. A
  first trial on Postgres ran on 2026-11-22. The design has not been reviewed.
- **Design:** `docs/designs/2026-11-22_tenants-and-sellers.md`, with its brief beside it.
  Set aside: `docs/access-and-operator-spec.md`.
- **Replaces in decision 5:** the layout (a control database plus one SQLite file per
  team) and the address (the team in the URL). **Keeps from decision 5:** one account in
  several teams, invites only, the owner's command-line tooling, each agency as the
  controller of its clients' data, and the rule that production leaves du7 before the
  first outside team (see "Open" below).
- **History:** an earlier text of this record, written on 2026-11-20 and never merged,
  kept decision 5's file per tenant and put the tenant in the path. Two days later the
  seller programme needed a rule SQLite cannot enforce, and the owner moved both walls
  into Postgres. The rows marked 2026-11-11 and 2026-11-20 below were decided for that
  earlier text and still hold; the brief says what became of the rest.
- **Agrees with:** decisions 3, 4, 8, 10, 11, 12. **Needed by:** decision 6.

## Context

Pauta serves one team from one SQLite file, and everyone who signs in sees every client.
Two things break that. Pauta goes on sale to other agencies in February 2027, and a
second agency must see nothing of the first. And the team is starting a seller programme:
outside sellers add their own clients and file requests for them, and must see only those,
while the team keeps one queue across all sellers.

`Store` is 2,294 lines of hand-written SQL. A rule that every statement has to apply by
itself is forgotten once. Two attempts to enforce the seller rule above or around that
SQL were set aside for that reason.

## Decision

| Topic | Decision | Decided |
|---|---|---|
| Where the rules are enforced | In the database. Pauta moves from SQLite to Postgres | 2026-11-22 |
| Layout | One Postgres database. A `control` schema holds accounts, passkeys, invites, tenants, hosts and memberships. Each tenant has a schema of its own, `t<id>`, with today's work tables and an `assignment` table | 2026-11-22 |
| The wall between tenants | Database roles per tenant, granted that tenant's schema only. The service connects as a login with no rights and, for each transaction, switches to the role of the member who is asking. There is no tenant column and no tenant condition in any statement | 2026-11-22 |
| Sellers | A seller is a member with the seller role: fewer grants, and row policies that show only the clients assigned to that account. Staff and sellers use the same routes | 2026-11-22 |
| When nothing says who is asking | Nothing is visible. Work that must see everything asks for the system role by name | 2026-11-22 |
| Which tenant a request is for | The host name, `<name>.pauta.cc`. Today's team keeps `app.pauta.cc`. Sessions are per host; the passkey is the same everywhere | 2026-11-22 |
| Identity | One account, one set of passkeys, any number of memberships. A membership has a role, an admin flag and an optional end date. `account.handle` is the person's stable id. A second membership is made from the owner's command line at first | 2026-11-11; the command line 2026-11-20 |
| A tenant admin's reach | An admin disables a membership, never an account, and may make a new-passkey link only for a person whose only membership is that tenant | 2026-11-20 |
| The owner | No flag and no special access. In another tenant the owner is a member with an end date, added from the command line, logged, and visible in that tenant's people list. A masked support view is set aside | 2026-11-20 |
| Per tenant | A Meta client, a OneDrive client, a sync lock, a state folder with its token files, a `/metrics` block, a dump in the backup. The Meta app and its secret and the session key are one per environment | 2026-11-11 |
| How `Store`'s SQL reaches Postgres | Through a small adapter. The SQL stays as it is written; what Postgres refuses is fixed in place. Text timestamps and 0/1 flags are kept so that every answer stays the same | 2026-11-23 |
| The move | A command imports the SQLite file into `control` and tenant 1, keeping every id, and compares every table before the service starts. The file is kept; a rollback reads it and loses what was written since, so it is decided in the first hour | 2026-11-22 |
| What today's team notices | Nothing, except that names with accents sort among their letters | 2026-11-23 |
| Where Postgres runs | A container on du7 | 2026-11-22 |
| Versions | Two channels, stable and next; a tenant is on one of them | 2026-11-22 |
| "SQLite, the standard library, one dependency" | Dropped. It was written in the first commit and never decided | 2026-11-22 |
| Order | A trial; then the move, with the final layout and nothing new on screen; then sellers and tenants, in either order; then the two channels | 2026-11-22 |
| Set aside | Roles beyond these, capabilities per route, assuming a role, the owner's masked view, integration scopes: `docs/access-and-operator-spec.md`, taken up when a reason arrives | 2026-11-20 |
| Tests | One test calls every route in the route table as one seller with another's ids and as one tenant's staff with another tenant's ids, and fails on a route it does not know. A second test compares each role's grants with the design's table | 2026-11-22 |

## Consequences

- The first release gives users nothing and can break anything: it moves a live system to
  another database. Sellers and other agencies come after it.
- Pauta gains a database server to run, back up and upgrade, and a second runtime
  dependency.
- The function that reads a membership and picks the database role is the one place the
  design trusts the application. If it picked the staff role for a seller, the database
  would obey.
- A session can change its own role. The walls hold against a mistaken query, not against
  SQL injected into a request.
- The SQL in the repository is spelled for SQLite and runs on Postgres through the adapter.
- A host per tenant needs a wildcard certificate, and Meta's sign-in returns to one fixed
  address.
- Everything is created once per tenant. The layout is meant for tens to a few hundred
  tenants.
- **Before a first outside tenant**, four things outside the code, each with its own lead
  time: Meta App Review for the production app (decision 8), OneDrive sign-in for work and
  school accounts, the legal texts of decision 5, and where production runs.

## Open

- **Where production runs in February.** This record puts Postgres in a container on du7.
  Decision 5 says production leaves du7 before the first outside team. Both cannot hold.
- Whether sellers or other agencies come first after the move.
- Whether to add a model layer over the hand-written SQL.

The design lists the rest, each with a default.

## Alternatives considered

One SQLite file per tenant with the tenant in the path (decision 5, and this record's
earlier text); filters built into a SQLite connection; a seller-only store and API; a
rewrite in C#, Rust or Java; an ORM as the enforcing layer; a tenant column and a policy
on every table; a database per tenant; the tenant taken from the account or from the
address; one seller per client as a column; a permissions screen; porting every statement
to Postgres's own spelling. The design's "Alternatives Considered" weighs each.
