# Pauta: integrations, access control and the operator's view

- **Status:** a proposal, set aside on 2026-11-20. It was sections 9, 10 and 11 of
  `multi-tenant-spec.md`, written on 2026-11-11 and 2026-11-12 at the owner's request, with
  the refactor steps and phases that serve them. A review that day found that none of it has
  a user yet and that it was about half of the days before a first outside tenant; the owner
  took the recommendation to split it off (question 22 of that spec). Nothing here is built
  or scheduled.
- **When to take it up again:** when the owner has to help a tenant in a way a dated
  membership does not cover (see below); when a tenant asks for a role other than `member`
  and `admin`; or when a third integration starts (the CRM link).
- **Until then:** a tenant has two roles, `member` and `admin`, as today. The owner has no
  special access: in another tenant the owner is a member with an end date, added from the
  CLI, journaled, and shown in that tenant's member list (Part B of the tenants-and-sellers design).
- **Read against decision 13 (2026-11-23).** This note was written for a control database
  plus one SQLite file per tenant, with the tenant in the path. Decision 13 replaced both,
  and this note has not been rewritten. Until it is, read it with this table:

  | This note says | Now |
  |---|---|
  | `control.db` | The `control` schema of the one Postgres database |
  | A tenant's file, `tenants/<slug>/pauta.db` | The tenant's schema, `t<id>` |
  | `tenants/<slug>/` for token and secret files | The tenant's state folder |
  | `/api/t/<slug>/` and `#/<slug>/` | The tenant's host name; paths have no slug |
  | Roles `member` and `admin` | The `staff` role, without and with `is_admin`. A third kind of member, the seller, exists since decision 13 and this note does not know it |
  | "Section N" with N from 1 to 8, or 12; steps R1, R3, R4, R7; phases F1, F2 | The retired multi-tenant spec. Its rules on people and operations are in Part B of `docs/designs/2026-11-22_tenants-and-sellers.md`; its steps and phases are that design's stages |
  | The review reports in `docs/designs/` | Not kept in the repository. Their findings about this note are named under "Read with" below and are still not applied |

  One thing changes in substance: with a database role per kind of member, a role of
  section 10 such as masked support would be a database role with its own grants, where
  this note plans checks in the application.
- **Numbers are kept.** Sections here are still 9, 10 and 11, steps are R2, R5 and R6,
  phases are F3 to F6, and questions are 11 to 18 and 24, so that
  `access-control-research.md` and the Lean model still point at the right place.
- **Read with:** `access-control-research.md` (section 10 against AWS IAM, OJS and the
  authorization tools); `formal/Access.lean` (section 10's table and rules in Lean); and
  a review by ten fresh readers on 2026-11-20. That review's findings about these sections
  are **not applied here**: the text below is as the reviewers read it, apart from the
  fixes to section 10's table. Before any of this is built, settle its findings (among
  them: how a tenant admin's grant is asked for and stored; where a fresh passkey tap is
  recorded when the cookie has no session id; columns that hold more than one field class;
  names and money that reach a screen without passing through the store).

## 9. Integrations: environment, tenant, account

Added 2026-11-11 at the owner's request. An integration is anything Pauta talks to with a
credential: Meta's Marketing API, a OneDrive, later the CRM, Claude for the report text
(decision 8), Paddle (decision 6), Google sign-in (the CRM draft). Each credential has exactly
one **scope**, which says who owns it, where it lives, who may connect and
disconnect it, and what happens when a person or a tenant goes away.

### The three scopes

| Scope | Owner | Examples | The credential lives in | Who connects, who disconnects | When the owner goes away |
|---|---|---|---|---|---|
| **Environment** (Du7's) | Du7, per environment (production, acceptance) | Du7's Meta app (id, login configuration, App Secret), the OneDrive app registration (a public client id), the Claude API key that other tenants use at Du7's cost (decision 8), Paddle's webhook secret (decision 6), the session-signing key, the WhatsApp alert template | The unit's environment for public ids; a file in `$PAUTA_STATE_DIR/` (mode 600, one per secret: `pauta.db.meta-secret`, `ai-key`, `paddle-secret`, `pauta.db.session-key`) for secrets, rendered from 1Password "Du7 Tech" on the Mac and pushed, never in a database, a backup, the repo or a log (the house rule since decision 3) | The owner, on the host. Nothing in the app can read or change them; `/metrics` says `enabled` per integration and nothing else | Rotated by hand (the Meta dashboard, then the file, then a restart); every tenant is affected at once, which is the price of one app for all (decision 8 accepted it) |
| **Tenant** (the agency's) | The tenant | Its Meta portfolio connections (one system-user token per `business_id`, decision 8), its OneDrive (decision 3), its CRM link (outbound webhooks with a signing secret, inbound read tokens; CRM draft section 3), an optional Claude key of its own (decision 8's `pauta.db.ai-key` for a tenant that brings its own), later a Google Drive or a second file store if ever asked | `tenants/<slug>/`: the token files Pauta writes today, unchanged in name (`pauta.db.meta-token.<business_id>`, `pauta.db.onedrive-token`, `pauta.db.ai-key`), plus one file per new secret following the same pattern (`pauta.db.<kind>-secret[.<key>]`). The *rows* that describe a connection (who, when, state, error, last use) are in the tenant file (`meta_connection` today; the generic shape below for new kinds). Inbound tokens the tenant hands out (the CRM's read tokens) are hashed in the tenant file like invites, never stored in clear | A tenant admin, on Configurações, as today for Meta and Arquivos. The row records `connected_by`; the UI says "conectado em <data> por <pessoa>" and never "de <pessoa>" (decision 8's ownership rule applies to every tenant integration, OneDrive included: the drive is someone's, the connection is the tenant's) | Tenant suspended: its integrations are not used (no sync, no uploads) but nothing is revoked. Tenant deleted: the files go with the directory; the CLI prints what to revoke by hand (the portfolio's connected apps in Business Settings, the drive's consent page), because Pauta never had the right to do that itself |
| **Account** (the person's) | The person, across every tenant they are in | Their login methods (passkeys today; Google as an (issuer, subject) pair when the CRM draft's recommendation lands), their e-mail for the Gravatar and their WhatsApp number (decision 10), Web Push subscriptions per device if notifications ever come, a personal API token for their own scripts if ever asked | `control.db` for things that are identifiers, not secrets (`passkey`, `login`, `account.email`, `account.whatsapp`, a `push_subscription` table); `$PAUTA_STATE_DIR/accounts/<account-id>/<kind>-token[.<key>]` (mode 600) for any secret a person connects, loaded only for requests whose viewer is that account | The person, on Perfil ("Minhas conexões"), in no tenant's context. An admin can see that a person has a connection of a kind, never use it | Account disabled: its sessions end (today's rule) and its files are not read. Account deleted (no membership left, 30 days, section 6): the directory goes. Leaving one tenant changes nothing about the person's own connections |

### What this means for today's two integrations

- **Meta** is a tenant integration already, in shape and in storage (decision 8: one
  connection per portfolio, token files next to the DB, "the connection belongs to the
  team"). Per tenant it gains nothing but its directory; across tenants the same portfolio
  may be connected twice, which is two system users in Meta's eyes and two files here.
- **OneDrive** is a tenant integration whose drive happens to be a person's (Ana's
  Microsoft 365). Decision 3 already treats the token as the team's. The spec makes the
  ownership visible: Configurações → Arquivos says "OneDrive de <conta> conectado por
  <pessoa> em <data>", and when an admin disables or removes a member, the page lists the
  tenant integrations that person authorised ("Ana conectou: OneDrive, portfólio X") so the
  admin knows what may stop working when that person revokes access on their side. Nothing
  is disconnected automatically: a revocation is the person's act, not Pauta's.
- **Binding a tenant to a person's connection** (an account-scope token used on the tenant's
  behalf, so that "Arquivos" could point at "Ana's drive" and follow Ana's account
  rather than being copied into the tenant) is **not** proposed. It would make a tenant's
  files depend on a membership, which is the fragility decision 3 lists as a consequence,
  not a feature. If a drive or an ad account is the person's, the person connects it *to the
  tenant* and the row says so. The account scope is for what is genuinely the person's.

### One shape for new tenant integrations

The Meta connection grew its own tables (`meta_connection`, `meta_log`) and OneDrive has
none (its status is read from the token file). New kinds should not each invent a third
way. For every integration added after this spec, in the tenant file:

```
integration(kind TEXT, key TEXT, label TEXT, state TEXT, error TEXT, connected_by INTEGER,
            connected_at TEXT, last_used TEXT, detail TEXT,  -- JSON, never a secret
            PRIMARY KEY (kind, key))
integration_log(id, at, kind, key, account, event, detail)   -- connected, disconnected, revoked, failed
```

with the secret, if there is one, in `tenants/<slug>/pauta.db.<kind>-secret.<key>`. `kind` is
`meta`, `onedrive`, `crm`, `ai`, ...; `key` is what makes two of the same kind distinct (a
`business_id`, a drive id, a webhook endpoint id) or `''`. Meta and OneDrive are not
rewritten onto it in this cut; the Configurações page reads both the old rows and the new
table and shows one list, under one heading, **Integrações**, with Meta and Arquivos as its
first two entries. A later cleanup may move `meta_connection` onto the generic table when it
is touched for another reason.

For the account scope, in `control.db`:

```
account_integration(account INTEGER, kind TEXT, key TEXT, label TEXT, state TEXT,
                    connected_at TEXT, last_used TEXT, detail TEXT,
                    PRIMARY KEY (account, kind, key))
```

`login(issuer, subject)` from section 4 is the first row type that fits it in spirit; it
stays its own table because sign-in reads it on the hot path, before any account is known.

### The CRM link, as the first new tenant integration

The CRM draft's section 3 names what Pauta must expose: signed outbound webhooks
(`lead.created`, `campaign.started`, `campaign.ended`), per-tenant read tokens, and inbound
outcomes. In this model each is a tenant integration of kind `crm`:

| Piece | Where |
|---|---|
| The CRM's URL and the signing secret | `integration('crm', <endpoint id>)` with the URL in `detail`; the secret in `pauta.db.crm-secret.<endpoint id>` (in clear: it signs) |
| Deliveries and retries | `webhook_delivery(id, endpoint, event, body, attempts, next_at, delivered_at, last_error)` in the tenant file; one delivery thread per process that walks tenants like the scheduler does |
| The read token the CRM uses on Pauta | A row in `integration('crm_token', <id>)` with the token's hash in `detail`; checked by a new access level `token` on the few read routes the CRM may call, which resolves the tenant from a tenant-id prefix on the token, as `/r/<token>` does |
| Outcomes coming back | Counts per campaign and day in the tenant file, never contacts (the draft's rule) |

Nothing of this is built here; it is listed so the tenant and account scopes are checked
against a real third integration before the first two are generalised.

### Where this touches the rest of the spec

- Isolation (section 5): a tenant's `Meta` and `OneDrive` objects come from the registry
  keyed by tenant, so a request can only ever load its own tenant's token files; an
  account-scope file is loaded only for the viewer's own account id; environment secrets are
  read once at start and never per tenant.
- Backups (section 6): token and secret files are not backed up today (decision 3's rule:
  never in the DB, so never in its backups) and still are not. A tenant restore brings the
  rows back and the files are still in place; a restore onto a fresh host means reconnecting
  every integration, which the export's integration rows list by kind, key and label. The
  CLI's `tenant export` includes those rows and no secret.
- The journal: every integration event names the tenant (tenant scope) or only the account
  (account scope); environment-level failures (the App Secret refused) are tenant `-`.
- `/metrics`: per tenant, `integrations: {meta: {...}, onedrive: {...}, crm: {...}}`, each
  with `connected`, `error` and `last_used`; at the top level, "any tenant has a problem" per
  kind, for du7's watchdog.
- Phases (section 12): the Integrações heading, the "connected by" line and the member
  removal warning belong to phase F2; the generic `integration` table and the account scope's
  files and table are made with the first new kind that needs them (the CRM link or Google
  sign-in), not before.

## 10. Access control: roles, assuming a role, viewing as a person

Added 2026-11-12. The owner asked for a model in which people can "assume a role" and
"impersonate" another person or role, offered as a suggestion to weigh. This section takes
both, narrowed, and is what the refactor of section 12 is planned over. Nothing here is
decided; section 8 has the questions. `access-control-research.md` (2026-11-12) checks this
section against AWS IAM, PKP OJS, the open-source authorization tools and a dozen products,
and listed eight small changes; the owner had them applied the same day, each marked
"(research)" below.

### Today

| What | Where | How many |
|---|---|---|
| An `access` word on every route: `open`, `member` or `admin` | `server.make_handler`'s route table, checked in `_dispatch` | 67 routes: 11 `open`, 36 `member`, 20 `admin` |
| Checks inside a handler | void a payment and remove a file (your own, or you are an admin); Meta's real error text (admins, in two places); linking a campaign to its request (admins); the finance settings in `boot` (admins); who sees money (`finance_visible`: the team's setting, or admins, in three places) | 6 reads of `viewer["is_admin"]`, 3 calls of `finance_visible` |
| `ME.is_admin` in the static JS | every area file | 25 |
| Who sees which client or request | Everyone sees everything. A request has an assignee; it restricts nothing | |

One flag on the account does all of it. It cannot say "admin in this tenant, member in that
one", it cannot be lent for an hour, and it gives the operator no way to help a tenant
without being its admin.

### The one rule

Every request has an **actor** and an **effective role**, and no code path derives one from
the other.

- The **actor** is the account whose passkey signed in. It comes from the session cookie and
  never changes. Everything that records who did something reads the actor: the `by` of a
  row, the journal, the usage log, the assumption log.
- The **effective role** is what the request may do in this tenant. It comes from the
  membership, or from an assumption that replaces it for a while. Every permission check
  reads the role and nothing else.

### Capabilities and roles

Capabilities are named in code, in one module, and a role is a fixed set of them. A route
declares the capability it needs instead of `admin`; the app asks `can('work.delete')`
instead of `ME.is_admin`. **Default deny (research):** a route registered without a
capability does not install, and the permission matrix of step R2 fails; `open` is itself a
capability (`public`) that the few unauthenticated routes name. Nothing is allowed because
no rule mentions it. Not in the table yet, and for step R2's brief to settle: what a
signed-in route with no tenant declares (`/api/me`, the person's passkeys, logout), and the
member routes no row covers (`boot`, the members list, the usage log). Tenants do not edit
roles: an agency of three does not need a policy editor, and every custom policy is a
support case. A tenant setting may still switch a named option, as "who sees money" does
today.

| Capability | Allows | `member` | `admin` | `support`, masked | `support`, full |
|---|---|---|---|---|---|
| `work.read`, `work.write` | Clients, requests, the timeline, files, the board | yes | yes | read, masked | yes |
| `work.delete` | Delete a client or a request; remove someone else's file | no | yes | no | no |
| `campaigns.read`, `campaigns.write` | Numbers, Visto hoje, a campaign's tracking state, report links | yes | yes | read, masked | yes |
| `finance.read`, `finance.record` | Financeiro, when the tenant has it on; a client's billing; record a payment | per setting | yes | no | read |
| `finance.manage` | Financeiro's settings; void anyone's payment | no | yes | no | no |
| `integrations.read` | State and logs of Meta, OneDrive and section 9's kinds | no | yes | yes | yes |
| `integrations.sync` | "Atualizar agora" | no | yes | yes | yes |
| `integrations.reconnect` | Renew a connection that already exists | no | yes | no | yes |
| `integrations.manage` | Connect, disconnect, link ad accounts | no | yes | no | no |
| `tenant.settings` | The lists (tipos, objetivos, segmentos) and other team settings | no | yes | no | no |
| `members.manage` | Invites, roles, disabling a membership, move links for people who are in this tenant only (section 4) | no | yes | no | no |
| `tenant.export` | The export file | no | yes | no | no |

The `member` and `admin` columns are today's behaviour, read from the route table: 20 of
the 67 routes are `admin`. Which capability each of the 67 gets is step R2's permission
matrix; `formal/` (section 12) states this table and the rules below in Lean and checks
them.

Financeiro has three states today (`finance_visible`): off, admins only, everyone. When a
tenant has it off, nobody holds a `finance.*` capability, admins and full `support`
included; "per setting" in the `member` column is the other two states.

"Own or capability" stays a rule of its own (void your own payment, remove your own file).
`member` and `admin` are cumulative (`admin` holds every capability `member` has). `support`
is not in that line (research): masked support reads structure a member cannot (sync state,
integration logs, error codes) and cannot read content a member can, so it is a different
role, never a bigger or smaller one. No code may treat it as "admin minus something".

Roles that fit later without a schema change: `finance` (a member who also manages
Financeiro), `viewer` (reads, writes nothing), `client` (reserved; the public report link
covers it today). When a tenant asks for "admin, but without X", the answer is a new row in
the matrix, reviewed, never a boolean on the membership (research: that is how OJS grew its
`permit_*` flags). A role lent until a date ("cobrir as férias da Ana") is a membership
with an end date, not an assumption. Reserved, not built (research, from OJS's user groups):
a tenant-chosen label over a fixed role ("Sócio", "Atendimento"), shown in the members list
with the permissions unchanged; a `label` column on `membership` whenever someone asks.

### Assuming a role

One mechanism, used three ways.

| Who | Assumes | Needs | Lasts | Seen by |
|---|---|---|---|---|
| An admin | `member` ("Ver como membro") | Nothing: it only removes rights | Until ended, at most an hour | The admin (a banner) and the journal |
| The owner | `support` in one tenant, masked (section 11) | A reason in a sentence and a passkey tap made just now | An hour, renewable | The tenant's admins, at once: a notice in the app and on WhatsApp where the tenant has it ("Suporte da Du7 entrou agora, motivo: …"); afterwards the tenant's Configurações: "Suporte da Du7, 12/11 14:02, motivo: …" |
| The owner | `support`, full | The same, plus a grant from one of the tenant's admins ("Permitir suporte completo por 4 h", or accepting the owner's request) | The grant's time: 4 h by default, 24 h at most, never open-ended | The same notice and the same list, marked "completo", with who granted it |

The notice on start and the cap on the full grant come from the research: break-glass
access alerts when used (AWS Well-Architected), and customer-approved operator access
expires in hours, not days (Microsoft Customer Lockbox: 4 h; HubSpot's log-in-as: 30 min).

Without an assumption the owner gets the same 404 from a tenant's routes as any stranger. A
stolen owner session opens no tenant by itself, and "Du7 looked at your data" is always a
row the tenant can read.

**Not a role: a fresh passkey for sensitive actions.** Exporting, removing or promoting a
member, disconnecting an integration, deleting a tenant's data and assuming `support` ask
for a passkey assertion made in the last five minutes. With passkeys that is one tap. It is
the step-up that matters at this size; making admins work as members and elevate for each
admin action would be ceremony. The rule is declared on the route, `@route(...,
"members.manage", fresh=True)`, and checked in `_dispatch`, so the permission matrix shows
which actions step up and no handler reads the clock itself (research: AWS expresses the
same thing as a per-action policy condition on MFA age). If the list grows to actions
people do in a row, GitHub's renewing window (2 h, reset by each sensitive action) is the
model to move to.

How it works:

- `POST /api/t/<slug>/assume {role, as_account?, reason?}` writes a row in
  `control.db.assumption(id, actor, tenant, role, as_account, scope, reason, started,
  expires, ended, ended_by, granted_by)` and sets a second cookie, `pauta_as`: the row's id,
  its expiry and a signature, `HttpOnly`, `SameSite=Strict`, `Path=/api/t/<slug>/`. The
  browser itself sends it only to that tenant's API, which is what the path prefix of
  section 3 buys here. The session cookie is not touched. `DELETE` on the same path ends it.
- The prefix resolver of section 3 becomes: an active assumption for this actor and tenant
  gives the role; otherwise the membership does; otherwise 404. The assume route itself is
  the one tenant route the owner may call without either.
- `boot` returns `can: [...]` and `acting: {role, as, scope, expires}`. While `acting` is
  set the app shows a fixed banner, one colour per assumed role (research: AWS's switched
  role replaces the user name in the navigation bar with a display name and a colour):
  "Você está vendo como membro · Sair" in one colour, "Suporte da Du7 · mascarado · 47 min
  · Sair" in another, "completo" in a third. Every tab on that tenant shares the cookie, and
  the banner is what makes that visible.
- Limits, all in code: never upward (an admin may assume `member`, and `viewer` once that
  role exists; only the owner may assume `support`). For a member or an admin an assumption
  only removes capabilities. `support` is not a smaller set but a different one, opened by
  the owner flag and nothing else: an owner who is also a member of the tenant gains
  `integrations.read` by assuming it. No chaining (an assumption cannot start under another); and
  the account routes ignore assumptions, since they are outside the cookie's path. Perfil,
  passkeys and the account-scope integrations of section 9 always act as the actor.
- The journal carries `actor`, `tenant`, `role` and `as` on every line, plus `assume_start`,
  `assume_end` and `assume_denied` (research: OJS and CloudTrail both log the refused
  attempt): the actor, the tenant, the role asked for and which limit refused it (upward,
  chaining, no grant, stale passkey). A refused assumption never reaches the tenant's
  list, only the owner's journal. Usage rows (decision 11) written under `support` are kept
  out of the tenant's usage report.

### Viewing as a person

"Ver como Ana" is an assumption with `as_account`. For an admin the effective role is that
person's, which is always `member` (see "Who may"). For the owner it stays `support`, masked
or full: if the person's role applied, masked support would read a member's unmasked
content. In both, anything personal in a screen (my requests, my filters) is that person's.

- **Read-only.** Any write under `as_account` is a 403, "modo de visualização". The
  timeline, payments, files and reviews all record who did something; writing as someone
  else would falsify that record.
- **Who may:** an admin, as a person with a lower role in the same tenant; the owner under
  `support`, masked unless the grant is full. Never as an admin from below, never as the
  owner.
- **The person can see it happened:** Perfil lists "Seu Pauta foi visto como você por
  <nome> em <data>".
- **Acting on behalf** ("Bia, por Ana", with both names on the row) is not in this
  cut. It needs an `on_behalf_of` column on every authored table and a reason to exist.
- **What it is worth today:** little more than "Ver como membro", because everyone in a
  tenant sees the same clients. It earns its place when visibility becomes per person, for
  example a freelancer who sees three clients. That is section 8's question 17: if it is
  coming, the refactor should carry a client scope on the membership from the start. The
  shape, if built (research, from OJS's `stage_assignments`): an assignment table
  `membership_client(tenant, account, client)`, read by `work.read` and `campaigns.read`
  for a member who has any row, with admins and `support` unrestricted; a member with no
  rows sees everything, as today, so adding the table changes nothing for existing tenants.

## 11. Keeping the operator out of a tenant's sensitive data

Asked by the owner on 2026-11-12, for the future, with the request that the refactor leaves
room for it. The operator is Du7: whoever holds `account.owner` in the app and a shell on
the host.

### What can honestly be promised

On one machine where the operator is root and the server must work on the data unattended
(the nightly Meta sync, backups, report links), no design makes the operator *unable* to
read a tenant's file. What can be built is that reading is never a side effect of running
or supporting the service: it takes a deliberate act, the tenant can see it, and most of it
needs the tenant's yes. In a tenant's words: "a Du7 não vê seus dados no dia a dia; quando
precisa, você autoriza e fica registrado."

| Layer | Stops | Does not stop | Size | When |
|---|---|---|---|---|
| 1. Support is assumed, and masked by default (section 10) | The operator reading names, texts, money or files while helping, by habit or by accident | A shell on the host | Medium, on the refactor's field classes | Before the first outside tenant |
| 2. Quiet tooling: the journal, `/metrics`, the usage log, error texts, the watchdog's messages and the CLI's default output carry ids and counts, never names, texts or amounts | Sensitive data spreading into logs, terminals, WhatsApp alerts and their backups | The same | Small; mostly a test with canary values | In the refactor |
| 3. Encrypted backups: each backup file is encrypted to a public key whose private half is in 1Password, not on the host | The NAS copy, old backups and a lost disk being readable; restoring becomes a deliberate act | The live file | Small | With the backup loop of section 6 |
| 4. A host where the daily operator is not root: the service has its own user, admin access is a separate account whose use notifies | Casual `sqlite3 pauta.db` | A determined root | Part of decision 5's hosting move | Before the first outside tenant |
| 5. Per-tenant encryption at rest, the key only in the process's memory | Reading files without the running process | Root on the live host; also needs an SQLite build with encryption, against "standard library only" | Large | Only if a customer's contract asks |
| 6. Fields encrypted in the browser with a team key (passkey PRF) | The operator entirely, for those fields | Nothing, but it breaks the server's search, the AI report text, thumbnails and any digest, and PRF support is uneven | Very large | Not proposed |

Layers 1 to 4 are the proposal. Layers 5 and 6 are listed so the refactor does not close
them: one function opens a tenant's store, one writes a backup, and every column has a
class.

### Field classes

Every column gets a class, in one table in code, with a test that fails when a column has
none. The classes say what the masked view shows and what may appear in logs.

| Class | Examples | Masked support sees | Journal, metrics, CLI by default |
|---|---|---|---|
| operational | Ids, statuses, kinds, priorities, dates, counts, sync state, error codes | As it is | Yes |
| identifying | A client's name, contact, WhatsApp and Instagram; a member's name and e-mail; ad account, campaign and portfolio names | A stable alias per tenant: "Cliente 7", "Pessoa 3", "Campanha 12" | Ids only |
| content | A request's text, notes, audience and "falta"; comments; file names; review notes; the AI text | A placeholder with the length: "▒▒▒ (212 caracteres)" | Never |
| financial | Billing, payments, spend, budgets, balances, cost per result | Hidden; a chart keeps its shape on an index of 100 where the shape is the bug | Never |
| files | OneDrive items, thumbnails | The name masked, the bytes a 403 | Never |
| secret | Tokens, keys | Never served to anyone, in any view | Never |

Masked support still sees the structure: how many clients and requests in which state,
which sync failed with which code, when, and the state of each integration. That answers
most support questions. "Pauta shows R$ 148,94 and Ads Manager R$ 31,58" needs the numbers,
so it needs the tenant's grant.

## The plan for these sections

These rows were part of section 12 of the tenancy spec. They need its steps R1, R3, R4 and
R7 and its phases F1 and F2 first.

### Today's shapes and what each blocks

| Today | Where | Blocks |
|---|---|---|
| A `viewer` dict with `is_admin`; `member` or `admin` on the route; 6 reads of `viewer["is_admin"]` and 3 calls of `finance_visible` inside handlers; 25 `ME.is_admin` in the JS | `server._dispatch`, `routes/`, `static/` | Roles per tenant, capabilities, assumptions |
| Rows go from `Store` straight to JSON | `db.py`, `_json` | The masked view; a client scope |
| `obs.event` takes whatever fields a caller passes (58 call sites); the CLI prints people's names by default (`pauta users`, `pauta usage`) | `obs.py`, `cli.py` | Quiet tooling |

### The refactor steps

A step starts when its brief exists (the rule of section 12).

| Step | Serves | What changes | Proves it | Size |
|---|---|---|---|---|
| **R2. Capabilities** | Access control (questions 14 to 16) | `access.py` holds section 10's table; `@route(..., "work.delete")` replaces `admin` and `fresh=True` marks the step-up routes; a route without a capability does not install; the checks inside handlers become `ctx.can()` and "own or"; `boot` returns `can`; the 25 `ME.is_admin` become `can()`. today's `member` and `admin` routes keep their answers. **Its brief must settle:** the capability of each of the 67 routes, including the ones no row of section 10's table covers; what `fresh=True` does before F3 enforces it (nothing: it is recorded); and how the matrix shows a route whose answer depends on a setting (Financeiro), on ownership or on the request's body | A permission matrix generated from the route table (role × route → status), kept as a reviewed file under CODEOWNERS, so a new route cannot ship without a line. `formal/Access.lean` states the same role table (question 24) | ~1.5 days |
| **R5. Shapers and field classes** | The masked view (questions 15 and 18) | Section 11's class table for every column, with the test that none is missing. Rows leave `TenantStore` through one shaper per entity (client, request, event, file, payment, campaign) that takes `ctx.view`; `full` returns what is returned today | Byte-identical API responses for `full` against a recorded fixture | ~2 days |
| **R6. Quiet tooling and one audit call** | The masked view (question 18) | `obs.event` takes the context (`actor`, `tenant`, `role`, `as`); error texts, the journal, `/metrics` and the CLI's default output are checked against the classes; the CLI gains `--reveal`, which journals its use. The CLI's default output changes, and the tests that assert names in it change with it. About 46 of the 58 `obs.event` calls run outside a request (the sync, the Meta and OneDrive clients): they take the tenant, not a request | A seeded database with canary names, texts and amounts; a test that none appears in the journal, `/metrics` or default CLI output | ~1 day |

About 4.5 days.

### The phases

| Phase | What lands | Needs | Visible? | Size |
|---|---|---|---|---|
| **F3. Assumptions** | The `assumption` table, the `pauta_as` cookie, the banner, "Ver como membro", the fresh passkey for sensitive actions (section 10) | R2, F2 (the cookie's path is the tenant prefix) | Yes, for admins | ~3 days |
| **F4. The owner's `support`** | Masked shapers and aliases, the notice to the tenant's admins, the tenant's grant for full, the list on Configurações (sections 10 and 11) | F3, R5, R6 | Yes, for the owner and for a tenant's admins | ~4 days |
| **F5. "Ver como <pessoa>"**, read-only | Section 10 | F3 | Yes, for admins | ~1.5 days |
| **F6. Encrypted backups** | Section 11, layer 3 | F1 (the backup loop) | No | ~1 day |

### The order

| # | Work | Size | After it |
|---|---|---|---|
| 1 | R2, F3 | ~4.5 days | Roles are capabilities; an admin can look as a member |
| 2 | R5, R6, F4 | ~7 days | The owner can support a tenant without reading its data |
| 3 | F6 | ~1 day | A backup is unreadable without the key in 1Password |
| 4 | F5 | ~1.5 days | When per-person visibility gives it a reason (question 17) |

About 14 days. Step R2 goes through every route module. R1 of the tenancy spec no longer
does (its brief leaves the handlers alone), so splitting the refactor costs no second pass.

### Risks

- **R5's size is the least certain.** It is the only step whose table (a class for every
  column) does not exist yet, and some columns hold more than one class: `meta_log.detail`
  is JSON with account, client and portfolio names in it. Names and money also reach a
  screen without passing through the store (the Meta client's account list, the OneDrive
  status), so shapers alone do not mask them. If shapers do not fit the finance sums or
  the campaign sums, the fallback is to hide those two blocks whole under the masked view;
  that gives up the masked chart of section 11.

### The Lean model of section 10

`formal/Access.lean` states section 10 in Lean 4 (core only, no Mathlib): the roles, the
capabilities, the table that says which role holds which, and the rule for who may assume
what. Lean checks these when the file is compiled (`lean formal/Access.lean`; the toolchain
is pinned in `formal/lean-toolchain`):

| Theorem | What it says |
|---|---|
| `member_le_admin` | `admin` holds every capability `member` has |
| `support_not_member_minus`, `support_not_member_plus` | `support` holds something `member` lacks, and masked support lacks something `member` has |
| `masked_le_full` | Full support holds everything masked support does |
| `support_never_manages` | No form of `support` deletes work, manages Financeiro, members or the integrations' wiring, changes settings or exports |
| `masked_writes_only_sync`, `masked_no_finance` | Masked support changes nothing but "Atualizar agora" and never sees money, whatever the tenant's setting |
| `finance_off_nobody` | With Financeiro off, no role holds a `finance.*` capability |
| `never_upward` | Someone without the owner flag who assumes a role ends with a subset of what the membership gave |
| `admin_never_assumed`, `stranger_assumes_nothing` | Nobody assumes `admin`; without a membership or the owner flag nothing can be assumed |
| `only_owner_assumes_support`, `support_needs_fresh_and_reason`, `full_needs_grant` | `support` needs the owner flag, a passkey tap made just now and a reason; full needs a tenant admin's grant |
| `no_chaining` | Nothing can be assumed while an assumption is active |
| `actor_unchanged` | Assuming a role never changes the actor |
| `view_as_read_only`, `view_as_never_adds` | Viewing as a person is read-only and adds no capability |
| `view_as_only_downward` | Among a tenant's members, only an admin views, and only as a member. (The owner under `support` viewing as a person is the `effective` function, not this theorem) |

Not in the model: time (the hour, the grant's four hours), the masked view's field classes
(section 11), the routes, "own or capability", and the routes whose answer depends on the
request's body.

What writing it changed in section 10: integrations became four capabilities instead of
two; full support may "Atualizar agora" (without it masked support could do something
full could not, which Lean rejects); `viewer` left the rules until it has a column; the
owner viewing as a person keeps `support`'s capabilities; "never upward" became a
statement about people without the owner flag. The review then found what the model had
missed: Financeiro's off state, now in both.

What it does not do is prove anything about the Python. It is a second statement of the
table, in a form a compiler checks for contradictions. It is run by hand (`lean
formal/Access.lean`); nothing in `make check` or in CI runs Lean, and adding that touches
the owner-reviewed `Makefile`. Whether it stays next to step R2's tests is question 24, decided when R2 exists.

## Open questions, each with a default

The numbers are the ones these questions had in section 8 of the tenancy spec.

11. **Integration scopes as section 9 defines them: environment, tenant, account, with no
    tenant-to-person binding?** Default: yes. The OneDrive stays a tenant integration
    authorised by a person, shown as such; a person's own connections live on Perfil and
    follow the person, not the tenant.
12. **Generalise Meta and OneDrive onto the `integration` table now, or only new kinds?**
    Default: only new kinds; the Integrações heading on Configurações lists all of them
    from day one. Rewriting `meta_connection` buys nothing until a third kind exists.
13. **May an admin see which personal connections a member has?** Default: the kinds only
    (that a person has Google sign-in, or a push device), never the credential or its use.
14. **Access control as section 10 has it: capabilities named in code, fixed roles per
    membership, no roles a tenant can edit?** Default: yes, with `member` and `admin` now.
15. **The owner's `support`: assumed per tenant with a reason and a passkey tap, an hour at
    a time, masked by default, full only on a tenant admin's grant?** Default: yes. Until it
    is built, the owner is not a member of other tenants. With question 18 this is about
    twelve days of work. Decided 2026-11-20: the first outside tenant does not wait for it.
16. **Viewing as a person: read-only, only as someone with a lower role, and visible to
    that person on Perfil?** Default: yes. Acting on behalf, with both names on the row, is
    not built until someone needs it.
17. **Is per-client visibility coming (a freelancer who sees three clients)?** Default: no,
    not planned. Asked now because step R5's shapers are where a client scope would be
    carried, and it is what would make "ver como <pessoa>" worth more than "ver como
    membro". Step R4 of the tenancy spec does not wait for the answer.
18. **How far to keep the operator out: layers 1 to 4 of section 11 (masked support, quiet
    tooling, encrypted backups, a host where the daily operator is not root), and not
    encryption at rest or in the browser?** Default: yes.
24. **Keep the Lean model (`formal/`)?** It found five gaps in section 10's table while it
    was written and missed a sixth (Financeiro's off state). Its theorems are finite case
    checks that tests over `access.py` could run against the real table once step R2
    exists, and nothing in `make check` runs Lean. Decided 2026-11-20: keep it, run by hand, until R2 exists;
    then decide between the two.
