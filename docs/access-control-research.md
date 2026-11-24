# Access control: what production tools do, and what Pauta takes from it

- **Moved:** since 2026-11-20 section 10 and questions 14 to 18 are in
  `access-and-operator-spec.md`, under the same numbers; "section 10" below means that
  document's.
- **Status:** research note, 2026-11-12, written for section 10 of `multi-tenant-spec.md`
  (roles, assuming a role, viewing as a person) and questions 14 to 18 of its section 8.
  The owner asked what production-ready tools use, whether an open-source tool or pattern
  fits, and what AWS IAM and PKP's Open Journal Systems (OJS) can teach. Nothing here is
  decided; the last section lists what it would change in section 10. **Applied:** the
  owner had the eight changes of section 7 written into section 10 the same day.
- **Verdict in one line:** keep section 10's shape (capabilities named in code, a fixed
  role set per membership, one assumption mechanism, read-only "ver como"), adopt no
  authorization server or library, and make the eight small changes of section 7 below,
  all of them borrowed from AWS, OJS, Microsoft and HubSpot.
- **Sources:** official docs and source only, listed at the end. Facts the research could
  not verify are marked so.

## 1. Three families of tools, and why Pauta needs none of them

Authorization tooling in 2026 comes in three shapes.

| Family | Idea | Tools | Needs | Where it earns its cost |
|---|---|---|---|---|
| **Fixed roles in code** (RBAC) | A role is a named set of permissions; a route declares the permission it needs; the check is a function | Django permissions and groups, Rails Pundit and CanCanCan, Laravel gates and policies, ASP.NET Core policies, Spring `@PreAuthorize`; django-rules for predicates in code | Nothing: it is the framework | When the set of permissions is small and changes with the code |
| **Policy engines** (policy as code) | Rules in a policy language evaluated by an engine, data passed in | Open Policy Agent (Rego), Cerbos (YAML), Casbin (model file plus a policy table), Oso (Polar; the library was deprecated 2023-12 for the hosted product) | OPA and Cerbos run as a sidecar or service; Casbin embeds in-process (`pycasbin`); none is standard library | When policies change faster than code, or several services must agree on them |
| **Relationship graphs** (Zanzibar, ReBAC) | Permissions are tuples `object#relation@user`; a check walks the graph; a consistency token keeps a check from seeing a stale graph | OpenFGA (CNCF incubating since 2025-10), SpiceDB, Ory Keto, Topaz, Warrant (frozen after WorkOS bought it in 2024) | A server, a gRPC or HTTP client, and the tuples kept in sync with the application's own data | When permissions are per object and nested (folders, documents, shares), as in Drive or GitHub repositories |

What Pauta has to express is section 10's table: nine capabilities, four roles, and three
in-handler rules ("own or capability", "who sees money" per tenant setting, the masked
view). Everyone in a tenant sees every client (question 17 is open). That is a 9×4 table,
not a graph, and it changes when the code changes. A policy engine would move those nine
rows out of `access.py` into a YAML file read by a sidecar, which at this size is a second
process to deploy, back up and keep in step with the schema, for no decision the table
cannot already make.

The one tool that would embed is Casbin: its "RBAC with domains" model is literally
`r = sub, dom, obj, act`, where `dom` is the tenant, and its policy rows read
`p, admin, tenant1, data1, read`. That is section 10's model written as data. It is worth
knowing because it confirms the shape (subject, tenant, object, action, with roles scoped
to a tenant), and not worth adopting because `pycasbin` is a dependency plus an adapter
for a table the app can hold as a Python dict, and because the tenant never edits policy.

The relationship-graph family becomes relevant on exactly one condition: per-client
visibility (question 17) growing into shares, delegations and groups. Section 3 below
shows OJS solves that case with a plain assignment table, which is also what Pauta would
do first.

**Takeaway:** stay in the first family. Pauta's `access.py` with `@route(..., "clients.delete")`,
`ctx.can()` and a reviewed permission matrix is the Django, Pundit and Laravel pattern,
and it is what every product in the next section ships on.

## 2. How products define roles

| Product | Fixed roles | Custom roles | Step-up |
|---|---|---|---|
| GitHub organization | Owner, Member, Moderator, Billing manager, Security manager, App manager | Custom organization and repository roles: Enterprise Cloud only; a custom role is a base role plus permissions | "Sudo mode": passkey, security key, TOTP or password; a 2 h window, renewed by each sensitive action; SMS not accepted |
| GitLab | Guest, Planner, Reporter, Developer, Maintainer, Owner; cumulative, highest role wins across the hierarchy | Ultimate only: a base level plus abilities | |
| Stripe | About 25: Super Administrator, Administrator, IAM Administrator, Developer, Analyst, Support Specialist, View only, Accountant, Dispute Analyst, Sandbox roles…; a person may hold several, permissions are the union; one Account Owner | Private preview | Some roles require account-wide 2FA |
| Grafana | Viewer, Editor, Admin per organization, plus a server admin | Enterprise and Cloud only | |
| Linear | Owner, Admin, Member, Guest | No; owners map a few actions to roles in Settings › Permissions | |
| Notion | Workspace owner, Membership admin, Member, Guest (page by page) | No | |
| Basecamp | Owner/Admin, Employee, Client; a client sees only items toggled to them | No | |
| AWS managed job functions | AdministratorAccess, PowerUserAccess, ReadOnlyAccess, ViewOnlyAccess, SecurityAudit, Billing, SupportUser… | Any policy, which is the whole product | MFA age as a policy condition |

Three regularities:

1. **The default product is a small fixed set, cumulative.** Three to six roles cover
   products with millions of tenants. Custom roles exist, but every vendor sells them on
   the top tier, because a custom role is a support surface: a tenant that builds a role
   nobody understands files a ticket six months later. Section 10 says the same ("every
   custom policy is a support case"), and question 14's default holds.
2. **"A setting switches a named option" is how the small products give a tenant some
   control without custom roles.** Linear maps a handful of actions to roles in a settings
   page; Basecamp toggles items to clients; Pauta's "who sees money" is the same device.
   When a tenant asks for "a member who can also record payments", the answer is a
   `finance` role (section 10 already reserves it), not a policy editor.
3. **Step-up is a time window, not a mode.** GitHub's sudo mode is the clearest: a fresh
   strong factor opens a window (2 h) that sensitive actions renew. Section 10's "a passkey
   assertion in the last five minutes" is the same design, stricter. Five minutes suits a
   list of six rare actions; if the list grows to things people do in a row, a window of
   15 to 30 minutes with renewal is what GitHub's experience says to do.

## 3. PKP OJS: what to take

OJS is interesting because it is multi-tenant (journals are tenants, "contexts"), twenty
years old, and run by small teams that never read a permissions manual. Its model, from
`pkp-lib`:

| OJS | What it is | Pauta's equivalent |
|---|---|---|
| Eight fixed role ids (`ROLE_ID_SITE_ADMIN`, `MANAGER`, `SUB_EDITOR`, `ASSISTANT`, `AUTHOR`, `REVIEWER`, `READER`, `SUBSCRIPTION_MANAGER`) in `Role.php` | The "permission level": hard-coded, what a role may do in any stage | Section 10's capability table |
| `user_groups(context_id, role_id, name…)` | A **tenant-named label over a fixed role**: a journal creates "Editor de Seção" or renames "Managing Editor", but each group is bound to one of the eight ids and gets exactly that id's permissions | Not in the spec. Cheap to add later as `membership.label` or a per-tenant `role_label` table; not needed for two tenants |
| `user_user_groups(user_id, user_group_id, date_start, date_end)` | Membership, per context, with a start and end date | `membership(tenant, account, role)`; section 10's "a role lent until a date is a membership with an end date" is this row |
| `user_groups.context_id IS NULL` for the site admin | A context-less role: the one person who sees every journal | `account.owner` |
| `permit_self_registration`, `permit_settings`, `permit_metadata_edit`, `recommend_only` flags on the group | Per-group switches for the few things that do vary between tenants | "Who sees money" and the reserved `finance` role |
| `stage_assignments(submission_id, user_group_id, user_id)` and `review_assignments` | **Per-object assignment**: an author sees their submissions, a reviewer the ones assigned, an assistant the stages assigned; a manager with no assignment sees everything | Question 17's client scope: `membership_client(tenant, account, client)`, read by `work.read`, with admins unrestricted |
| `AuthorizationPolicy`, `PolicySet` (deny-overrides, permit-overrides), `AuthorizationDecisionManager` with default deny, "authorized context objects" handed to the handler | An XACML-inspired engine: each handler's `authorize()` adds the policies its operation needs; the router enforces it; what the policies resolved (the journal, the submission, the user's roles) is passed to the handler | `Ctx` of refactor step R1 is the "authorized context"; `_dispatch` is the decision manager; default deny is the one piece section 10 should state outright |
| "Login As" (`signInAsUser`) | Manager or site admin only; **full** impersonation (the session user is replaced); refused when the target is a site admin or has roles in a journal the actor does not manage; start, end and refusals are audit events; the menu shows "Logout as {username}" | Section 10's "Ver como <pessoa>", which is stricter: read-only, lower role only, visible to the person |

Lessons from OJS's own issue tracker, which are the useful part:

- **Hard-coded permission levels do not survive contact with users.** Capability-style
  permissions have been requested since 2017 (pkp-lib discussion 8118, issue 2128
  "recommend only"), and the workaround became flags on the group (`permit_metadata_edit`,
  `recommend_only`), each a special case in code. Section 10's capabilities-in-code with
  a matrix avoid the first half of that: adding `finance` or `viewer` is a row, not a
  schema change. The flags are the warning: when a tenant asks for "admin, but without X",
  the answer should be a new row in the matrix, reviewed, not a boolean on the membership.
- **Merging two roles into one level confused people for a decade.** OJS 3 merged Journal
  Manager and Editor into one "manager" level; forum threads since 2017 ask how to get an
  editor who cannot change settings. Pauta's `admin` bundles `tenant.settings`,
  `members.manage`, `finance.manage` and `tenant.export`. For an agency of three that is
  right; the first tenant that asks for "atende clientes e mexe no Financeiro mas não
  convida gente" is the signal to split `finance` out, as section 10 reserves.
- **Impersonation across tenants breaks on the first multi-tenant user.** Issue 7424: a
  journal manager cannot log in as a user who also has a role in a journal they do not
  manage, because OJS's impersonation is account-wide. Section 10's assumption cookie is
  scoped to `/api/t/<slug>/` and the effective role is per tenant, so "ver como Ana" in
  tenant A says nothing about Ana in tenant B. That scoping is the thing to keep.
- **Refusals are logged.** OJS writes `SESSION_IMPERSONATE_DENIED` at warning level. The
  spec journals `assume_start` and `assume_end`; it should journal the refused attempt too.

## 4. AWS IAM: what to take

AWS's model is bigger than Pauta will ever need, but its assumed-role mechanism is the
best-documented one there is, and section 10 maps onto it line by line.

| AWS | Section 10 | Note |
|---|---|---|
| Default deny; explicit allow; explicit deny wins over any allow; a permission boundary or session policy that does not allow is an implicit deny | A route with no capability must not register (test in R2); `as_account` turns every write into a 403; the masked view is an explicit deny on classes, not a filter the handler may forget | State the default-deny rule in the spec; today it is implied by the matrix |
| `AssumeRole`: temporary credentials, `DurationSeconds` default 1 h, maximum the role's `MaxSessionDuration` (1 to 12 h) | An assumption lasts an hour, renewable; "Ver como membro" at most an hour | Same numbers, no change |
| Role chaining is capped at 1 h and session policies can only narrow, never widen | "Never upward, no chaining" | Same rule |
| The trust policy says who may assume; `ExternalId` guards against the confused deputy | "Only the owner may assume `support`; an admin may assume `member` or `viewer`"; the tenant admin's grant is the trust policy for `support` full | Same shape |
| `RoleSessionName` is required and `SourceIdentity` is set once, cannot be changed in the session, and appears on every CloudTrail line, so that an action by a role is attributable to the human | Section 10's "actor never changes; every record reads the actor" | Same rule. The `assumption` row id in the `pauta_as` cookie plays the session name |
| CloudTrail logs the `AssumeRole` call in both accounts and every later call as `assumed-role/ROLE/SESSION`, with `mfaAuthenticated` | The journal carries `actor`, `tenant`, `role`, `as` on every line | Same |
| Console "Switch Role": a display name and a colour that replace the user name in the navigation bar ("green Test, red Production"), "Switch back", a short history of roles used | The fixed banner in its own colour, "Sair" | Same design, with a colour per role being the detail to copy: one colour for "como membro", another for "suporte" |
| `aws:MultiFactorAuthAge` as a policy condition: this action only if MFA happened in the last N seconds | The fresh passkey tap in the last five minutes for sensitive actions | Same device; AWS expresses it per action in the policy, which is what a `fresh=True` flag on the route declaration gives |
| Managed job-function policies: a fixed small set, with `ViewOnlyAccess` (metadata, no content) distinct from `ReadOnlyAccess` (content too) | `support` masked (structure, ids, counts) versus `support` full | The ViewOnly/ReadOnly split is exactly section 11's masked view; AWS reached the same two levels |
| ABAC (tags) is recommended "when policy management has become complex" and resources scale faster than roles | Not applicable: nine capabilities, four roles | Confirms staying with roles |
| Break-glass guidance (Well-Architected SEC03-BP03): pre-created, auditable, **alerts when used**, never for routine work, credentials rotated after | The owner's `support` | Add the alert: a support assumption should notify the tenant's admins when it starts, not only appear in a list |
| AWS Support's own access: a service-linked role, resource metadata only, customer data redacted, every call visible to the customer in CloudTrail; no per-access consent | Masked `support`, visible on Configurações | Same model at the small size; AWS does not do consent, Google and Microsoft do (next section) |

## 5. Operator access and impersonation in products

What the big operators and the common frameworks do when staff must see a customer's
data, and what application frameworks give for "log in as":

| Who | May | Scope | Visible to the customer or person | Time |
|---|---|---|---|---|
| Microsoft 365 Customer Lockbox | An engineer requests, a Microsoft manager approves, then a customer "access approver" approves | Pre-approved operations only | Request, approval and every action in the audit log | Request expires in 12 h; access at most 4 h, auto-revoked |
| Google Cloud Access Approval + Access Transparency | Google staff request; the customer approves each request (auto-approval possible for outages, logged as such) | Per request | Logs with resource, action, justification code, accessor's job category | Per request |
| AWS Support | A service-linked role | Metadata only, customer data redacted | CloudTrail | Standing |
| HubSpot "Log in as" | Super Admin with 2FA, Enterprise tier; never as a super admin or billing user | Full, except changing permissions or profile, and cannot bypass the target's 2FA | **E-mail to the person** | **30 minutes** |
| GitLab admin impersonation | Instance admins | Full; "Stop impersonating"; can be disabled | Audit events, actions attributed to the admin | No |
| OJS "Login As" | Manager or site admin, not as a site admin | Full | Audit log, incl. refusals; "Logout as" in the menu | No |
| Discourse, Zendesk "Assume identity" | Admins, agents | Full | Staff log; the person is not told | No |
| django-hijack, laravel-impersonate, pretender | Whatever you configure | Full; hijack shows a yellow bar to the hijacker; the others fire events for your own log | Not to the person | No |
| Supabase dashboard | Project members | Database only: a JWT as that user so row-level security applies; a policy tester | No | Per session |
| Shopify collaborator accounts | Partner requests, the store owner approves per permission | A separate login with the granted permissions; not impersonation | Listed under users | Expires after 90 days of inactivity |
| Auth0 Impersonation API | Deprecated, cannot be enabled on new tenants; staff said it could not be made safe | | | |

Three things stand out:

1. **Nobody ships a read-only "view as".** Every framework package and every product
   above except Supabase's policy tester replaces the session wholesale. Section 10's
   read-only rule ("any write under `as_account` is a 403") is stricter than the field and
   cheap in a monolith: one check in `_dispatch`. Auth0's withdrawal is the cautionary
   case: impersonation that mints real credentials at the identity layer could not be
   made safe; impersonation inside the app, with a banner, a write guard and an audit row,
   is what everyone keeps.
2. **Mature operator access converges on four properties:** explicit permission from the
   customer side (Lockbox's approver, Google's approval, Shopify's owner), a stated reason,
   a short expiry (30 min at HubSpot, 4 h at Microsoft), and visibility to the affected
   party (HubSpot's e-mail, Lockbox's audit log). Section 10 has all four. The numbers to
   borrow: masked support 1 h renewable is fine; the **full** grant should default to a
   few hours (Lockbox: 4) and cap at 24, rather than "the grant's time" open-ended.
3. **The person being viewed is usually not told.** HubSpot is the exception, and it is
   the right one for a product sold on "a Du7 não vê seus dados no dia a dia". Section
   10's "Seu Pauta foi visto como você por <nome> em <data>" on Perfil matches HubSpot
   and goes one better than the operators, who tell the tenant, not the person.

## 6. The standard behind "assuming a role"

ANSI/INCITS 359 (the NIST RBAC model, 2004, revised 2012) already contains section 10's
mechanism, which is reassuring and gives it names:

- **Core RBAC has sessions:** a user is *assigned* roles; in a session they *activate* a
  subset; the permissions in effect are those of the active roles. Section 10's assumption
  is a session that activates one role, and "Ver como membro" is activating a subset.
- **Static separation of duty** says which roles one person may not be assigned together.
  Pauta's version: one role per membership (`member` or `admin`, not both), which the
  `membership` primary key already enforces.
- **Dynamic separation of duty** says which roles may not be active in the same session.
  Pauta's version: no chaining, and the account routes ignoring the assumption, so a
  session is never `admin` in Perfil and `member` in the tenant at once by accident.
- **Hierarchical RBAC** (a senior role inherits a junior's permissions) is what every
  product in section 2 means by "cumulative". Section 10's table is cumulative by
  construction (`admin` ⊇ `member`), and `support` masked deliberately is not: it is a
  different role, not a bigger one. Keep that explicit.

## 7. What this would change in section 10

Eight changes, none of them structural. Each names where it comes from.

1. **State default deny.** A route registered without a capability does not install and
   the generated matrix fails. (AWS evaluation logic; OJS's decision manager with
   `_effectIfNoPolicyApplies = DENY`.) Refactor step R2 already builds the matrix; this
   makes the rule a sentence in the spec and a test.
2. **Journal refused assumptions.** `assume_denied` with actor, tenant, the role asked for
   and the reason the check failed, next to `assume_start` and `assume_end`. (OJS
   `SESSION_IMPERSONATE_DENIED`; AWS logs failed `AssumeRole`.)
3. **Alert on `support`.** When the owner assumes `support` in a tenant, its admins get a
   notice at once (WhatsApp through famulus, or the app's own notice), not only a row on
   Configurações afterwards. (Well-Architected break-glass: alert on use; HubSpot's e-mail.)
4. **Cap the full grant.** `support` full defaults to 4 h and the grant form cannot exceed
   24 h; masked stays 1 h renewable. (Customer Lockbox 4 h; AWS maximum session 12 h.)
5. **A colour per assumed role in the banner,** one for "como membro", one for "suporte".
   (AWS Switch Role's display colour, the one UX detail AWS got right.)
6. **The fresh-passkey rule as a flag on the route,** `@route(..., "members.manage",
   fresh=True)`, so the matrix shows which actions step up and no handler checks the time
   itself. (AWS `aws:MultiFactorAuthAge` as a policy condition, not handler code.) Keep
   five minutes; if the list grows, GitHub's renewing window is the model.
7. **Keep `support` outside the hierarchy.** Write in the table that `support` masked is
   not a subset or superset of `member`: it reads structure a member cannot (sync state,
   integration logs) and cannot read content a member can. (NIST: a distinct role, not a
   senior one.)
8. **Reserve, do not build, two OJS things:** a tenant-chosen label over a fixed role
   (`user_groups`: "Sócio", "Atendimento" shown in the members list, permissions unchanged)
   and the per-client assignment table for question 17 (`stage_assignments`: a row per
   person and client, admins unrestricted, `work.read` filtered). Both fit the schema of
   section 4 without a migration later; neither has a user today.

Not changed: the role set (`member`, `admin`, reserved `finance`, `viewer`, `client`), the
one-mechanism assumption with a scoped cookie, read-only "ver como", the actor rule, and
the decision to hold the table in `access.py` rather than in a tool.

## Sources

AWS: policy evaluation logic (`reference_policies_evaluation-logic_policy-eval-denyallow`),
policy elements and condition keys, `AssumeRole` API reference, `id_credentials_temp_control-access_monitor`
(SourceIdentity), `id_session-tags`, `id_roles_use_switch-role-console`, `cloudtrail-integration`,
IAM Identity Center `permissionsetsconcept` and `howtosessionduration`, `access_policies_job-functions`,
`introduction_attribute-based-access-control`, Well-Architected `sec_permissions_emergency_process`,
`awssupport/latest/user/using-service-linked-roles-sup`.

PKP: `pkp/pkp-lib` on GitHub, `classes/security/Role.php`, `schemas/userGroup.json`,
`classes/migration/install/RolesAndUserGroupsMigration.php`, `classes/security/authorization/*`
(`AuthorizationPolicy`, `PolicySet`, `AuthorizationDecisionManager`, `RoleBasedHandlerOperationPolicy`,
`SubmissionAccessPolicy`), `pages/login/LoginHandler.php`, `classes/security/Validation.php`,
`classes/core/PKPSessionGuard.php`, `classes/user/Repository.php`; docs.pkp.sfu.ca
`learning-ojs/3.4/en/users-and-roles`, `faq/en/users-roles`, `dev/documentation/en/architecture-authorization`;
issues 2128, 3022, 7424, discussion 8118. Forum threads on the manager/editor merge were
search results only, not read.

Tools: Zanzibar (USENIX ATC 2019), openfga.dev and the CNCF incubation post (2025-11),
github.com/authzed/spicedb, ory.com/keto, openpolicyagent.org integration docs,
github.com/cerbos/cerbos, casbin.org `rbac-with-domains`, github.com/osohq/oso (deprecation
notice; exact end-of-support date not verified), github.com/permitio/opal,
github.com/aserto-dev/topaz, github.com/warrant-dev/warrant and the WorkOS acquisition post.
Frameworks: Django auth docs, django-guardian, django-rules, Pundit, CanCanCan, Laravel
authorization, ASP.NET Core policies, Spring method security. NIST RBAC project page and
ANSI/INCITS 359-2004.

Products: GitHub roles, custom roles and sudo mode; GitLab permissions; Stripe roles and
custom roles; Grafana roles; Linear members and roles; Notion workspace roles; Basecamp
clients; HubSpot "Log in as another user"; GitLab admin area; Discourse meta on
impersonation; Zendesk "assume identity" (audit behaviour not verified); django-hijack,
laravel-impersonate, pretender; Supabase user impersonation; Shopify collaborator accounts;
Microsoft Purview Customer Lockbox requests; Google Cloud Access Transparency and Access
Approval overviews; Auth0 community thread on the deprecated Impersonation API.
