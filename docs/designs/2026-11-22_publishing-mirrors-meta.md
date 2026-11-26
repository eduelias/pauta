# Publicações follows Meta's model: a portfolio's Instagram accounts, assigned to clients

- **Status:** built on 2026-11-22, on the publishing beta (`feat/publishing-beta`, on
  acceptance only), after the review whose reports are in
  [`egm-review-publishing-mirrors-meta/`](egm-review-publishing-mirrors-meta/). The plan
  at the end is kept as it was followed.
- **Reads with:** [`publishing-spec.md`](../publishing-spec.md) (what the beta does today),
  [`app-review.md`](../app-review.md) (Meta's review, not yet submitted), and decision 8,
  [`0008-campaign-tracking.md`](../decisions/0008-campaign-tracking.md) (how the ads side
  already follows Meta's model).

## The problem

Pauta is the request queue of a marketing team. Each **client** of the team is a business
whose Meta ads the team runs and, with the Publicações beta, whose Instagram posts the team
publishes. The people who sign in are **members**; some are **admins**, who connect
integrations and manage the team. **The owner** is the person who owns Pauta itself and is
an admin of the one team there is. **Acceptance** is the test installation
(`acc.pauta.cc`), which the command `make acc` deploys a branch to; production is the one
the team works on. Each installation keeps its data in one SQLite file.

Three of Meta's terms are used throughout. A **business portfolio** is Meta's record of a
business and the assets it owns or was given access to: ad accounts, Instagram accounts,
Pages. A **token** is the credential Meta issues when an admin logs in at Meta; Pauta
stores it and sends it with each request. A **system user** is the non-human user Meta
creates in the portfolio to hold that token.

The ads side of Pauta already stores its data as Meta structures it: a portfolio, its ad
accounts, their campaigns. The publishing side does not, and its tables cannot represent
what the owner asks for: **a client with several Instagram accounts**, next to the several
campaigns a client already has. No client has asked for a second account yet: this is the
owner's requirement for the product, set before the module reaches production.

| | Ads (Campanhas, in production) | Publishing (beta, acceptance) |
|---|---|---|
| What is connected | A business portfolio, once. One token per portfolio | A client. One login per client |
| What the connection gives access to | Every ad account of the portfolio | Every Instagram account of the portfolio, of which the code keeps one |
| How an asset reaches a client | An admin assigns each ad account to a client, with a suggestion by name; an ad account whose id is the one typed on a client is linked automatically | The client's free-text `@` field must match the account's handle when the login lists more than one account |
| Per client | Several ad accounts, several campaigns | Exactly one Instagram account (`ig_profile` has the client as its key) |
| Token kept under | The portfolio's id | The Instagram account's id (the same portfolio token, once per account) |
| A piece of work knows | Its ad account and its client (`campaign`) | Only its client (`post`) |
| A disconnect | Keeps the ad accounts and their clients, so a reconnect loses no assignment | Deletes the client's profile row |

Three things follow from the publishing column, and they are the reasons to change it now:

1. **One Instagram account per client is built into the key.** A client with a brand
   account and a second one for a branch cannot be represented.
2. **Connecting through the team's own portfolio depends on a free-text field.** A login
   that lists several accounts is matched to the client by its Instagram field. In
   production 11 of 15 clients have something in that field and 3 of those 11 are not a
   clean handle (a name, or a handle with a note); 4 have nothing. Those 7 clients could
   not be connected from a portfolio that holds more than one account without editing their
   record first.
3. **The connection's state is stored per client, not per portfolio.** A revoked or lapsed
   token is a fact about the portfolio's connection. One revocation has to be found and
   marked once per client.

Changing a table's key touches little data today: only acceptance holds publishing data (2
Instagram accounts, both the owner's own, 16 posts, 7 of them scheduled). Production holds
none. Once production holds posts, the same change must migrate them. (Counted in the two
databases on 2026-11-22.)

## Meta's model, as its documentation states it

The table quotes Meta's developer documentation as read on 2026-11-22; the pages are listed
under it. The first two rows were checked against the two tokens stored on acceptance the
same day. That check covers one portfolio: the app's own, reached through a Facebook login.
A portfolio outside it has not been tried, and `publishing-spec.md` records that signing in
with an Instagram identity failed once. The other rows come from the documentation only.

| Meta's object | What Meta says | Checked on acceptance, or its state in Pauta |
|---|---|---|
| Business portfolio | A login with Facebook Login for Business gives a system-user token that "includes a client business ID"; `GET /me?fields=client_business_id` returns it. The app "can only access the assets that were designated by your business client" | Both stored tokens answer the same `client_business_id` and the same system user |
| Its Instagram accounts | `GET /me/assigned_instagram_accounts` lists the Instagram accounts the token was given | Each of the two tokens lists **both** accounts (`du7dev`, `pautacc`): one login gives access to every Instagram account of the portfolio |
| Ad account → campaign → ad set → ad | "A campaign is the highest-level organizational structure within an ad account" | Already how `meta_account` and `campaign` are stored |
| Instagram media | Belongs to an Instagram account. Fields `id`, `media_type` (`IMAGE`, `VIDEO`, `CAROUSEL_ALBUM`), `media_product_type` (`FEED`, `STORY`, `REELS`, `AD`), `permalink`, `timestamp` | `post` already keeps `media_id` and `permalink` |
| A post and a campaign | Not related directly. An **ad's creative** has the Instagram account it runs as (`instagram_user_id`) and, when the ad is an existing post, that post (`source_instagram_media_id`, `effective_instagram_media_id`) | Not read by Pauta |
| Ad account and Instagram accounts | `GET /act_<id>/instagram_accounts`: "Instagram accounts associated with this Ad Account" | Not read by Pauta |

Sources, all under `developers.facebook.com/docs/`: `facebook-login/facebook-login-for-business`,
`marketing-api/campaign-structure`, `marketing-api/reference/ad-creative`,
`marketing-api/reference/ad-account/instagram_accounts`,
`instagram-platform/reference/instagram-media`.

Meta has no object called a client. In Pauta a client is the team's own grouping of a
business's assets: its ad accounts and, after this change, its Instagram accounts.

## Goals

1. A client can have several Instagram accounts; an Instagram account belongs to at most
   one client.
2. One login connects a portfolio and gives access to all its Instagram accounts. The
   connection's token and state are kept once, on the portfolio. An admin assigns each
   account to a client, as ad accounts are assigned.
3. A post belongs to an Instagram account, as Instagram media does.
4. The upgrade keeps every account's client and every post's account. The owner then logs
   in at Meta once. Nothing else is done by hand, apart from sending again a post whose
   scheduled time fell between the upgrade and that login.
5. The change only adds tables and columns to the schema; it removes none. If the release
   before it is run on the upgraded file (a rollback), that release publishes nothing until
   an admin connects Instagram again in it.

## Non-goals

- **Reading which posts run as ads** (the creative's `effective_instagram_media_id`). It is
  how Meta relates a post to a campaign, and this design leaves room for it by storing no
  link of its own. It is a later, separate change on the ads side.
- **Suggesting a client from the ad account's Instagram accounts**
  (`/act_<id>/instagram_accounts`). The suggestion in this change comes from the handle.
- **Re-reading a portfolio's accounts in the background.** The list of accounts, their
  handles and a revoked token are learned at a login or when a post is sent, as today. The
  ads side re-reads hourly; publishing can get the same later, once there is more than the
  owner's own portfolio to keep current.
- **Facebook Pages, ad sets and ads as tables.** Publishing uses none of them.
- **Moving the Instagram panel to Configurações**, where the ads connection is managed. It
  stays on the Publicações screen: moving it changes no behaviour and is better done when
  the module leaves beta.
- **Renaming a post's kind to Meta's words.** `feed`, `story`, `reel` stay; see alternative
  5.
- **One Meta app for ads and publishing.** They stay two apps with two tokens; see
  alternative 3.
- **Dropping `ig_profile`.** This release keeps it for a rollback. The change that brings
  the beta up to `main` for production removes it from the schema and from acceptance's
  file, and deletes the one-time copy below and its tests: only acceptance's file ever
  runs it.

## The proposed model

```text
ig_connection  (one per portfolio)        like  meta_connection
  business_id, business_name, state, error, expires, connected_by, connected_at

ig_account     (one per Instagram account) like  meta_account
  ig_id, username, business_id (empty when not connected), client (may be empty)

post           (Instagram media in the making)
  ..., ig_id (may be empty), client, kind, media_type, media_id, permalink
```

An account row stores its portfolio's id (`business_id`), with no foreign-key constraint,
as `meta_account` does. A post row stores its account's id (`ig_id`) the same way. The
`ig_connection` row is itself the record of a connection, and the token file holds only the
token (on the ads side the token files are the record and `meta_connection` mirrors them).
A post's `kind` is where it
goes (`feed`, `story`, `reel`: Meta's `media_product_type`) and its `media_type` is what its
file is (`image`, `video`). A connection's `state` is `ok`, `expired` (its token lapsed) or
`revoked` (Meta no longer takes its token).

**A post's life, which this change does not alter.** A post is a `draft` or is `scheduled`
for a date and time; a person moves it between the two. A background thread, the publisher,
runs every 20 seconds and sends each scheduled post whose time has passed; a person can
also send one immediately ("Publicar agora"). While it is being sent a post is
`publishing`: Pauta asks Instagram to prepare it (Instagram calls the thing being prepared
a container) and publishes it when Instagram says it is ready, which for a video takes
minutes. It ends `published` or `failed`, with the reason on it. Pauta never retries a
failed post automatically: a person sends it again or schedules it again.

| Rule | Why |
|---|---|
| A connection is a portfolio, keyed by Meta's `client_business_id` | It is what the token belongs to, and what is revoked or lapses. When Meta sends no portfolio id the system user's own id is the key, as the ads side does |
| An account is keyed by Instagram's own id | The id never changes; a handle can |
| An account's client is set by an admin and may be empty | A portfolio can include accounts the team does not publish for. An unassigned account is listed and is not offered when composing |
| A suggestion, never an automatic assignment | A wrong assignment publishes one client's post on another's account. The ads side links an ad account automatically only when its id equals the one typed on the client; a handle typed in free text is not an id. The suggestion is the one client whose Instagram field is a clean handle equal to the account's; clients without a clean handle get none |
| Pauta asks the admin to confirm, naming both clients, before it moves an assigned account to another client, or else before it gives an account to a client other than the suggested one: one question at most | These are the two cases where the choice contradicts what Pauta already holds: an existing assignment, or the handle on another client's record. Clearing an account's client, and the first assignment of an account with no suggestion, save without a question |
| A disconnect forgets the token and keeps the accounts with their clients | The ads side keeps them "so the client mapping survives a reconnect" (`routes/campaigns.py`, `meta_disconnect`). The accounts are listed as not connected |
| An admin can remove an account that is not connected | After a disconnect the account's id and handle would otherwise stay with no way to delete them. Its posts keep their text and file and show as having no account |
| An account belongs to the portfolio of the most recent login that listed it | An account shared with two portfolios follows the later login. A connection left with no account is listed as empty, and an admin disconnects it |
| An account that a later login of its portfolio no longer lists becomes not connected, and keeps its client | The new token does not reach it, so nothing could be posted to it. It is listed and can be removed like any account that is not connected, and a later login that lists it connects it again |
| A post has an account **and** keeps its client | The account says where it goes; the client says whom it was made for, and is what the lists group by. `campaign` keeps both for the same reason |
| A post may have no account | From the upgrade, when its client had no connected profile; when its account was removed; or when it was made in the older release during a rollback. The list says so, and it cannot be scheduled or sent until a person chooses an account |
| A post goes out only while its account is connected and assigned to the post's client | This is checked when it is scheduled and again when it is sent |
| Reassigning an account, or disconnecting its portfolio, changes no post | The list shows a notice on a post whose account is no longer assigned to the post's client, or is not connected. If its scheduled time arrives before that is put right, it fails with that reason and a person sends it again. A post whose time is still ahead when the assignment or the connection is back goes out as scheduled. Today a disconnect turns scheduled posts into drafts; one rule for both cases replaces that |
| A post's account can be changed to another account of the same client | Two cases need it: a client with two accounts, and a post whose account was reassigned to another client or removed |
| No stored link between a post and a campaign | Meta has none; the relation is an ad that uses the post, and it can be read from Meta later |
| The token is kept once per connection | It is one token. Today it is stored once per account |

### What a person sees

| Who | Today | After |
|---|---|---|
| Admin, connecting | Picks a client, presses **Conectar Instagram**, logs in at Meta. Refused when the login lists several accounts and the client's `@` matches none | Presses **Conectar Instagram** (no client), logs in at Meta. Every account of the portfolio appears in the list under the portfolio's name, each with a client chooser and, when one client's `@` matches, `sugestão: <cliente>` |
| Admin, afterwards | **Desconectar** per client, which turns that client's scheduled posts into drafts | Changes or clears an account's client (confirming in the two cases above); **Desconectar** per portfolio, which leaves its accounts listed as not connected and its posts as they are; **Remover** on an account that is not connected |
| Anyone, composing | Chooses "Cliente (@conta)" among the connected clients | The same chooser, now listing every assigned and connected account: a client with two accounts appears twice. Editing a post offers the other accounts of its client |
| Anyone, on the list | The post shows the client and the `@` | The same, plus a notice on a post that cannot go out as it stands: its account is with another client, is not connected, or it has none |

### What changes for Meta's review

`app-review.md` holds the texts and the screencast script for Meta's App Review, which is
not submitted yet. Four places in it change, all rewritten in Phase 3 of the plan below:
the text that tells Meta why Pauta needs the `instagram_basic` permission (it says the
username is checked against the client's record before connecting, which stops being
true), and steps 2, 3 and 6 of the screencast script. That text is already saved in Meta's
dashboard, so the owner saves the new one there before submitting. The screencasts are not
recorded yet.

### The upgrade

In production the new tables are created empty and nothing is copied: production has no
publishing data. On acceptance the upgrade happens once, in one transaction, when the
database gains the `post.ig_id` column:

1. Each `ig_profile` row becomes an `ig_account` with its client and no connection.
2. Each post gets the `ig_id` of its client's profile; a post whose client has no profile
   gets none.
3. Every `ig_profile` row is marked `expired`.

Step 3 is what goal 5 rests on. The release before this one publishes through `ig_profile`,
only when a row's state is `ok`, and to the one account its `@` match gives the post's
client: it does not read `post.ig_id`. Left as they are, those rows would let a rollback
publish a post on an account that has since been given to another client, or on the wrong
one of a client's two accounts. Marked `expired`, the older release refuses until an admin
connects again in it.

Nothing calls Meta during the upgrade. After `make acc` the owner presses **Conectar
Instagram** once: the login lists both accounts, which keep their clients. Until then the 7
scheduled posts show the notice "conecte o Instagram deste cliente primeiro" (connect this
client's Instagram first); one whose time came before the owner's login would fail with
that reason and the owner would send it again.

## Alternatives considered

Findings cited as "zoom-out A1" or "zoom-out B3" are in
[`zoom_out_report.md`](egm-review-publishing-mirrors-meta/zoom_out_report.md) (part A and
part B); "critic D6" is in
[`critic_report.md`](egm-review-publishing-mirrors-meta/critic_report.md).

| # | Alternative | What it is | Why not |
|---|---|---|---|
| 1 | Loosen the key only | Keep `ig_profile`, let a client have several rows, add `post.profile` | It keeps the per-client login and the match on the free-text `@` (reason 2), the token stored once per account, and the state stored per client (reason 3). It addresses reason 1 only |
| 2 | Mirror everything | Tables for Pages, ad sets, ads and creatives too | Publishing reads and writes none of them. Each would be a table to sync and migrate with no screen using it |
| 3 | One Meta app and one connection for ads and publishing | Add the Instagram permissions to the ads app, share `meta_connection` | The ads app holds `ads_read` only and never writes; publishing writes to a client's public profile. One token for both widens what a leak of the ads token can do, and the ads app would need an App Review it has not needed so far |
| 4 | A stored `post.campaign` | A chooser on the post for one of the client's campaigns | Meta relates the two through an ad's creative. A hand-kept link says what someone intended, drifts from what runs, and would have to be reconciled with the real relation once Pauta reads it |
| 5 | Meta's words for a post's kind | `FEED`, `STORY`, `REELS` in place of `feed`, `story`, `reel` | The values are in the database, the API, the page and the tests since 2026-11-22. The mapping to Meta's is three fixed pairs, written where media is first read back from Meta. Renaming changes no behaviour |
| 6 | Keep the scheduled posts going through the upgrade with no login | A connection per old profile (`legacy-<ig_id>`) that keeps its token until the real portfolio takes over; or a call to `/me` per stored token, at start-up or from the publisher, to build the real connection immediately | The first is a second kind of connection, with its own token key, route pattern, label, takeover and tests, for two accounts on one server that both belong to the owner. The second puts a call to Meta in an upgrade, or adds a background path for the same two rows. One login by the owner is enough (zoom-out A1 and B1) |
| 7 | Turn scheduled posts into drafts when their account changes client or its portfolio is disconnected | What a disconnect does today | One wrong selection in a client chooser would unschedule every post of the account, and choosing the right client again would not schedule them back. The check at sending time already refuses them (zoom-out B3). The same rule for a disconnect keeps one behaviour to explain |
| 8 | Delete a portfolio's accounts when it is disconnected | A foreign key with a cascade | Every disconnect would delete every assignment, and an admin would make them again by hand. Assignment is the step where a mistake publishes one client's post on another client's account (see Risks). The ads side keeps them on purpose (zoom-out A3 and B5). Removing a single unconnected account covers the case where the data must go |
| 9 | Refuse an assignment whose handle does not match the client's record | Today's rule, moved from the login to the assignment | The record is free text: 3 of 11 are not a clean handle, and a client's second account never matches its one `@` field. Asking the admin to confirm in the doubtful cases keeps the check without those refusals (zoom-out B6) |
| 10 | Start the login from a client, and suggest that client for the accounts the login newly lists | Keeps the one signal that is not free text: the client the admin was connecting for | It needs the hint stored on each account (a column) or an assignment made at the login, which is the automatic assignment the rules exclude. After the login the admin lands on the panel with the new accounts under the portfolio's name, which for a client's own portfolio is that client's name (critic D6) |
| 11 | Leave `ig_profile` as it is at the upgrade | The older release keeps publishing after a rollback, with no login | The older release sends by the post's client and ignores `post.ig_id`: after any reassignment it can publish on another client's account. Publishing nothing until a deliberate login is the safe failure |
| 12 | Wait until a client needs a second account | Ship the beta's model to production as it is | The change is a new key for the profile table. Today it migrates 2 accounts and 16 posts on acceptance; after production holds posts for real clients it migrates those, with the rollback risk above attached to real profiles |

## Risks and limits

| Risk | What happens | Mitigation |
|---|---|---|
| An account assigned to the wrong client | A post for one client is published on another's profile. The check at sending time protects only posts made before the mistake: a post composed afterwards for the wrong pair goes out | Assignment is admin-only and never automatic. Pauta asks the admin to confirm before moving an assigned account and before contradicting the handle on a client's record. The chooser and every post row show "Cliente (@conta)". Each assignment is written to the server's log (the systemd journal) with who made it and for which account. The handle check helps only for clients whose record holds a clean handle |
| One token publishes to every account of a portfolio | A leaked token can post to all of them | This is already the case today (each stored token lists both accounts). The token file stays mode 600 next to the database. It is not part of the database or of its backups |
| A portfolio has more than 100 accounts | Meta returns the list in pages of 100 | The login reads page after page with Meta's cursor, building each request itself as the ads side does (never following a URL returned in a response), at most 20 pages. A page that fails, or a list that does not end within them, fails the login and nothing is stored: a partial list would disconnect the accounts it missed |
| An account leaves the portfolio, is renamed, or the token is revoked | Pauta learns it at the next login, or when a post to it fails with the reason Instagram gives, which may be a generic refusal | After the next login the account is listed as not connected and its posts show the notice. Learning it sooner is the background re-read in the non-goals |
| A scheduled post whose account is not connected or not its client's | It looks scheduled and fails at its time | The list shows a notice on it from the moment that is true. A failed post is never sent automatically |
| Posts left scheduled go out after a reconnect or a reassignment | A post scheduled for a future time is sent at that time once its account is connected and its client's again, with nobody approving a second time | Only a post whose time is still ahead does so, which is what its schedule says; one whose time passed meanwhile has failed and stays failed. The disconnect's confirmation says that scheduled posts stay scheduled |
| A scheduled post comes due between the upgrade and the owner's login | It fails with "conecte o Instagram deste cliente primeiro" | The owner logs in right after `make acc`, before the next scheduled post's time; a failed one is sent again by hand |
| The upgrade fails half-way | With the column added and nothing copied, a restart would not repair it | The column, the copy and the marking are one transaction: a failure leaves the file as it was, and the next start does all of it. A test will force a failure and check that |
| A rollback | The older release finds every profile `expired` and publishes nothing. After an admin connects a client again there, that release sends the client's scheduled posts to the one account its `@` match picks, whatever account each post was made for | After a rollback, review the scheduled posts before connecting. Only the owner deploys to acceptance, so this note is where that is recorded. Posts made in the older release come back, at the next upgrade, with no account |
| Instagram ids and handles are kept after a disconnect | A client who leaves, or asks for removal, would stay listed | An admin removes an account that is not connected. `ig_profile`, which holds the same two fields, is dropped by the change that takes the beta to production |
| Two branches used schema number 16 | `main` used it for another table while the beta used it for `post.kind` | This change takes 17 on the beta. The upgrade steps are guarded by what the file contains, not by the number. Reconciling the numbers is part of bringing the beta up to `main`, a separate task |

## Detailed Implementation Plan

Work happens in the worktree of `feat/publishing-beta`. Paths are relative to the repository
root. There are three phases and one commit per phase. `make check` (lint, unit and API
tests with coverage, browser tests) passes after each phase; inside Phase 2, whose parts
depend on each other, it passes only at the end. Tests use the fake in
`tests/fakeinstagram.py`; nothing calls the real Meta.

In this plan "user" means a person signed in to Pauta (a row of the `account` table) and
"account" means an Instagram account (a row of `ig_account`).

### Files

Every file is modified; none is created or deleted.

| Phase | File |
|---|---|
| 1 | `src/pauta/db.py`, `tests/unit/test_publishing.py` |
| 2 | `src/pauta/instagram.py`, `src/pauta/publishing.py`, `src/pauta/routes/publishing.py`, `src/pauta/static/app-publicacoes.js`, `tests/fakeinstagram.py`, `tests/unit/test_publishing.py`, `tests/api/test_publishing_api.py`, `tests/e2e/test_publicacoes.py` |
| 3 | `docs/publishing-spec.md`, `docs/app-review.md`, `deploy/README.md`, `CHANGELOG.md`, this file |

Not touched: `src/pauta/server.py`, `src/pauta/routes/account.py`, `src/pauta/cli.py`,
`src/pauta/static/style.css`, `src/pauta/static/index.html`, `tests/conftest.py`,
`tests/e2e/conftest.py`, `tests/appserver.py`.

### Phase 1: the schema and the store's upgrade

**`src/pauta/db.py`**

1. `SCHEMA_VERSION = 17`.
2. In `SCHEMA`, after the `post` table's index, add:

   ```sql
   CREATE TABLE IF NOT EXISTS ig_connection (
       business_id TEXT PRIMARY KEY, business_name TEXT NOT NULL DEFAULT '',
       connected_by INTEGER REFERENCES account(id), connected_at TEXT NOT NULL,
       state TEXT NOT NULL DEFAULT 'ok', error TEXT NOT NULL DEFAULT '', expires TEXT
   );
   CREATE TABLE IF NOT EXISTS ig_account (
       ig_id TEXT PRIMARY KEY, username TEXT NOT NULL DEFAULT '',
       business_id TEXT NOT NULL DEFAULT '',
       client INTEGER REFERENCES client(id) ON DELETE SET NULL
   );
   CREATE INDEX IF NOT EXISTS ig_account_client ON ig_account(client);
   ```

3. In the `post` table's `CREATE`, add the column `ig_id TEXT NOT NULL DEFAULT ''` after
   `media_type`.
4. In `Store.__init__`, after the v16 block, read the columns of `post` again and add the
   v17 block inside `if "ig_id" not in cols:`, so it runs once per file. Python's `sqlite3`
   commits a schema statement immediately unless a transaction is already open, so the
   block starts with `if not db.in_transaction: db.execute("BEGIN")`. The four statements
   then commit together when `Store.__init__` leaves its `with self.db()` block (which
   commits on success and rolls back on an error), or not at all:
   - `ALTER TABLE post ADD COLUMN ig_id TEXT NOT NULL DEFAULT ''`
   - `INSERT OR IGNORE INTO ig_account(ig_id, username, client) SELECT ig_id, username,
     client FROM ig_profile`
   - `UPDATE post SET ig_id=COALESCE((SELECT ig_id FROM ig_profile WHERE
     client=post.client), '')`
   - `UPDATE ig_profile SET state='expired'`

   A file made new by this release has the column from `SCHEMA`, so the block is skipped.
5. `EXPORT_TABLES`: replace `"ig_profile"` with `"ig_connection", "ig_account"`.

After this phase the rest of the code still reads `ig_profile` and ignores the new tables
and the new column, so every existing test passes unchanged: a fresh test database has no
`ig_profile` rows to mark.

**Tests, `tests/unit/test_publishing.py`**

A helper `v16_file(path)` builds the previous release's file by hand: the `client`,
`account`, `ig_profile` and `post` tables as that release's `SCHEMA` has them, two clients
with an `ig_profile` row each in state `ok`, a third client with none, and one post per
client.

- `test_the_upgrade_keeps_each_profiles_client_and_each_posts_account`: open a `Store` on
  that file and assert: two `ig_account` rows with their clients and an empty
  `business_id`; no `ig_connection` row; each post's `ig_id` (empty for the third client's
  post); both `ig_profile` rows `expired`; the schema number 17.
- `test_the_upgrade_happens_once`: after the upgrade, delete one `ig_account` row and open
  the `Store` again: the row is not back.
- `test_an_upgrade_that_fails_leaves_the_file_as_it_was`: before the first open, add to the
  file a trigger that aborts any update of `ig_profile`
  (`CREATE TRIGGER t BEFORE UPDATE ON ig_profile BEGIN SELECT RAISE(ABORT, 'no'); END`);
  opening a `Store` raises `sqlite3.IntegrityError`; `post` has no `ig_id` column and
  `ig_account` is empty. Drop the trigger, open a `Store` again: the upgrade is complete.
- `test_the_export_has_the_connections_and_the_accounts`: `store.table("ig_connection")`
  and `store.table("ig_account")` answer a list; `store.table("ig_profile")` raises
  `Invalid`.

### Phase 2: the model, from the Instagram client to the page

One commit. The parts are in the order to write them; the code does not run between them.

#### 2a. `src/pauta/instagram.py`: one token per connection

1. The tokens file keeps its name and shape, `{key: {"token", "expires", "obtained"}}`. A
   connection's key is `biz-<business_id>`. `_token(conn)`, `_keep(conn, token,
   expires_in)`, `forget(conn)` and `expires_in(conn, now=None)` take the connection's id
   (`conn: str`) in place of `ig_id` and use that key.
2. `start(by: int | None) -> str`: `by` is the user who pressed the button (`None` only in
   local mode, which has no users). The one-time OAuth state holds `(by, expiry)`.
   `take_state(state) -> int | None` returns that user.
3. `finish(code: str) -> tuple[dict, list[dict], str | None]` replaces `finish(code, want)`.
   After the code exchange, which is unchanged:
   - `GET /me?fields=id,name,client_business_id`; a failure raises `self._fail(status, doc,
     "me")` as today. The connection's id is the digits of `client_business_id`, or, when
     there are none, the digits of `id`, as `Meta.finish_connect` does. With neither, raise
     `InstagramError(UNAVAILABLE, step="me", status=503)`.
   - The portfolio's name: when there was a `client_business_id`, `GET
     /<business_id>?fields=name`; when that call fails, or there was none, the name is the
     `name` from `/me`.
   - The accounts, read as `Meta._pages` reads a list: `GET
     /me/assigned_instagram_accounts?fields=id,username&limit=100`, then the same request
     with `after=<paging.cursors.after>`, stopping when the answer has no `paging.next`, no
     cursor, or the cursor it was asked with. Each request is built here; the URL in
     `paging.next` is never followed. At most `ACCOUNT_PAGES = 20` requests: when the 20th
     answer would still continue, raise `InstagramError(UNAVAILABLE, step="accounts",
     status=503)`. A request that fails raises `self._fail(status, doc, "accounts")`. An
     empty list raises the existing `NO_ACCOUNT` error with `step="me"`, as today.
   - Until here nothing has been stored. Then `_keep(conn, token, expires_in)`, and remove
     from the tokens file the old keys that are the bare `ig_id` of each account listed:
     the token under `biz-<id>` replaces them.
   - Return `({"business_id", "business_name"}, [{"ig_id", "username"}, ...], expires)`,
     where `expires` is what `_keep` returns.
4. Delete `NOT_SHARED`, `MANY_ACCOUNTS` and the matching code in `finish`. Keep `handle()`:
   the suggestion uses it.
5. The publishing calls take the connection's id for the token. Their signatures become:
   `create_container(conn, ig_id, url, caption, alt_text="", kind="feed", video=False)`,
   `publish(conn, ig_id, container)` and `quota(conn, ig_id)`, where `ig_id` stays in the
   request's path; and `container_state(conn, container)`, `wait_ready(conn, container)`
   and `permalink(conn, media_id)`, where `conn` replaces `ig_id`, which those three used
   only for the token. `quota` has no caller; it changes so that it keeps working.
6. The module's opening comment describes the tokens file by connection.

#### 2b. `src/pauta/publishing.py`: connections, accounts and one rule

1. Messages. New: `NO_ACCOUNT_POST = "escolha a conta do Instagram desta publicação"`
   (choose this post's Instagram account) and `MOVED = "a conta desta publicação não é
   mais deste cliente: escolha outra conta"` (this post's account is no longer this
   client's: choose another). `NO_PROFILE` keeps its text, "conecte o Instagram deste
   cliente primeiro": the person reading it thinks of the client, not of the portfolio.
2. One rule for whether a post can go out, as a module function:
   `why_not(post_client: int, account: dict | None) -> str`. `account` is the post's
   `ig_account` row with its connection's `state` (`""` when the account has no
   connection), or `None` when the post's `ig_id` is empty or is no account's. It returns
   `NO_ACCOUNT_POST` when `account` is `None`; else `MOVED` when `account["client"] !=
   post_client`; else `NO_PROFILE` when `account["business_id"]` is empty or
   `account["state"] != "ok"`; else `""`.
3. Replace `profiles`, `profile`, `save_profile`, `set_profile`, `remove_profile` with:
   - `connections() -> list[dict]`: `ig_connection` rows with `by_name` (the connecting
     user's name) and `accounts` (how many accounts have this `business_id`), oldest
     first.
   - `accounts() -> list[dict]`: `ig_account` rows with `client_name` and `state` (the
     connection's state; `""` when the account has no connection), ordered by `username`.
   - `account(ig_id) -> dict | None`: one of those rows.
   - `save_connection(portfolio: dict, accounts: list[dict], expires, by) -> None`, where
     `portfolio` is `{"business_id", "business_name"}` as `finish` returns it. In one
     transaction: upsert the connection (`state='ok'`, `error=''`, `connected_at=now`, the
     name, `expires`, `connected_by=by`); set `business_id=''` on every account of this
     portfolio that the login did not list; for each listed account, insert it with this
     `business_id`, or, when it exists, set `business_id` and `username` and **leave its
     client**. Then `obs.event("ig_connected", account=by, business=<id>,
     accounts=<how many>)`.
   - `assign(ig_id, client: int | None, by) -> dict`: `NotFound("conta do Instagram não
     encontrada")` for an unknown account; `NotFound("cliente não encontrado")` for an
     unknown client. Sets the client, changes no post, writes
     `obs.event("ig_account_assigned", account=by, ig=ig_id, client=client)`, and returns
     the account.
   - `set_connection(business_id, **fields)`: `state`, `error`, `expires`.
   - `remove_connection(business_id) -> bool`: in one transaction, set its accounts'
     `business_id` to `''` and delete the connection. No post changes. False when there
     was none; otherwise `obs.event("ig_disconnected", business=business_id)`.
   - `remove_account(ig_id, by) -> None`: `NotFound("conta do Instagram não encontrada")`
     for an unknown account; `Invalid("desconecte o portfólio desta conta antes de
     remover")` when its `business_id` is not empty; else delete the row and write
     `obs.event("ig_account_removed", account=by, ig=ig_id)`. Posts keep their `ig_id`,
     which then is no account's.
4. `_ready(db, post_client: int, ig_id: str) -> dict` reads the account on the open
   connection `db`, raises `Invalid(why)` when `why_not(...)` is not empty, and returns the
   account. `ready(post_client, ig_id) -> dict` opens a connection and calls it. They are
   the one check before a post is scheduled or sent.
5. `_POST` joins `ig_account g ON g.ig_id=p.ig_id` and `ig_connection n ON
   n.business_id=g.business_id`, selecting `g.username AS ig_username`, `g.ig_id AS
   ig_known`, `g.client AS ig_client`, `g.business_id AS ig_business` and `n.state AS
   ig_state`. `posts()` and `post()` add `blocked` to each row. For a post in `draft`,
   `scheduled` or `failed` it is `why_not(row["client"], account)`, where `account` is
   `None` when `ig_known` is null and otherwise `{"client": ig_client, "business_id":
   ig_business, "state": ig_state or ""}`. For any other status it is `""`. `ig_known`,
   `ig_client`, `ig_business` and `ig_state` are then removed from the row; `ig_id` and
   `ig_username` stay.
6. `_when(db, client, ig_id, status, due)` gains `ig_id`. When the status is `scheduled`
   it calls `_ready(db, client, ig_id)` in place of the `ig_profile` query. It is still
   called before the `INSERT` or `UPDATE`.
7. `create(body, by)` reads `ig_id` (a string) in place of `client`. It raises
   `Invalid(NO_ACCOUNT_POST)` when no `ig_account` row has that id or the row has no
   client. The post's `client` is that row's client, and `ig_id` is stored.
8. `update(pid, body)`: when the body has a non-empty `ig_id` that differs from the
   post's, it raises `Invalid(NO_ACCOUNT_POST)` when no `ig_account` row has that id and
   `Invalid(MOVED)` when the row's client is not the post's client; the new `ig_id` goes
   in the same guarded `UPDATE` as the other fields. An absent or empty `ig_id` leaves the
   post's account as it is. `_when` is called with the `ig_id` the post will have.
9. `publish`: call `ready(post["client"], post["ig_id"])` before `posts.claim`, in place of
   the `posts.profile` check; its `Invalid` reaches the caller as `NO_PROFILE` does today.
   Pass the account's `business_id` as `conn` to every `Instagram` call.
10. `advance`: after its early return for a post that is not waiting, call `ready`; on
    `Invalid`, fail the post through `_failed` with `InstagramError(str(e),
    step="status")`, as it does for `NO_PROFILE` today. Pass `conn` the same way.
11. `_failed(posts, post, conn, e)` and `_published(posts, ig, post, conn, media_id)` gain
    `conn` (`""` when the post has no connected account). In `_failed`, when `e.revoked`
    and `conn` is not empty, call `posts.set_connection(conn, state="revoked",
    error=str(e))` in place of `set_profile`. `_published` calls `ig.permalink(conn,
    media_id)`.
12. `Publisher.tick`: no change. `publish` raises the `Invalid` from `ready`, and the
    existing `except Invalid` marks the post `failed` with its text.
    `Publisher.chores`: for each connection in state `ok`, call
    `self.ig.expires_in(business_id, self.clock())`; when it returns `None` (no token in
    the file) or a `timedelta` of zero or less, call `set_connection(business_id,
    state="expired", error="a conexão venceu")`, as it does per profile today.
13. The module's opening comment describes connections and accounts.

#### 2c. `src/pauta/routes/publishing.py`

1. `GET /api/publishing` returns `{"enabled", "connections", "accounts", "posts",
   "limits"}`; on a server without the Instagram app, `{"enabled": false, "connections":
   [], "accounts": [], "posts": []}`. Each account carries `match`: `{"id", "name"}` of
   the client whose `instagram` field, read through `handle()`, is not empty and equals
   the account's handle, when exactly one client's does; else `None`. Each post carries
   `blocked`. `_state()` builds this document; the routes below that change something
   return it.
2. The five routes below call `_on()` first, as the routes they replace do.
3. `POST /api/instagram/connect` (admin) returns `{"url": ig.start(viewer["account"])}`.
   It replaces `POST /api/clients/{id}/instagram`, which is deleted.
4. `GET /api/instagram/callback` (open): `by = ig.take_state(state)`; `portfolio,
   accounts, expires = ig.finish(code)`; `posts.save_connection(portfolio, accounts,
   expires, by)`; redirect to `/#/publicacoes?ig=ok`. Failures redirect with `motivo` by
   the rule there is today: `cancelado`; `vencido` for step `state`; `perfil` for step
   `me`; else `instagram` (which a failed or over-long list of accounts gives).
5. `PATCH /api/instagram/accounts/([0-9]{5,20})` (admin). The body must have `client`: an
   integer or `null`; anything else raises `Invalid("informe o cliente (ou null para
   deixar sem cliente)")`. Then `posts.assign(ig_id, client, viewer["account"])`, and it
   returns `_state()`.
6. `DELETE /api/instagram/accounts/([0-9]{5,20})` (admin): `posts.remove_account(ig_id,
   viewer["account"])`, returns `_state()`.
7. `DELETE /api/instagram/connections/([0-9]{5,20})` (admin): `posts.remove_connection`,
   then `ig.forget`; `NotFound("esta conexão não existe")` when there was none; returns
   `_state()`. It replaces `DELETE /api/clients/{id}/instagram`, which is deleted.

#### 2d. `src/pauta/static/app-publicacoes.js`

Texts and hooks of the panel (the section keeps `id="igprofiles"`):

| Element | Text or attribute |
|---|---|
| Heading | "Contas do Instagram" |
| Nothing connected and no account | `.empty`: "Nenhuma conta do Instagram conectada ainda." |
| A connection's block | `data-connection="<business_id>"`; its title is the portfolio's name |
| A connection's state line | `ok`: "conectado", plus " até dd/mm" when it has `expires`; `expired`: "a conexão venceu: conecte de novo"; `revoked`: "o Instagram não aceita mais a conexão: conecte de novo" (today's texts) |
| A connection with no account | "nenhuma conta" under its title |
| The block of unconnected accounts | title "Sem conexão" |
| An account's row | `data-account-row="<ig_id>"`; shows `@username` |
| Its client, for an admin | `<select data-account="<ig_id>">`: first option "Sem cliente", then every client |
| Its client, for a member | the client's name, or "sem cliente" |
| The suggestion | `sugestão: <cliente>`, when the account has no client and `match` is set |
| Buttons, for an admin | **Desconectar** (`data-disconnect="<business_id>"`) on every connection; **Conectar de novo** (`data-connect`) only when the connection's state is not `ok`; **Remover** (`data-remove="<ig_id>"`) on each row under "Sem conexão"; **Conectar Instagram** (`id="igconnect"`) below the blocks. The chooser `#igclient` is removed |
| Helper text under **Conectar Instagram** | "Abre o login da Meta. Escolha o portfólio e as contas do Instagram em que a Pauta pode publicar: elas precisam ser profissionais (Empresa ou Criador de conteúdo). Depois escolha aqui o cliente de cada conta." |
| A member, nothing connected | "Um administrador conecta o Instagram e escolhe o cliente de cada conta." |
| The post list's empty text, nothing to post to | "Conecte o Instagram e escolha o cliente de uma conta para criar a primeira publicação." |
| Toasts | disconnect: "Instagram desconectado" (as today); remove: "Conta removida"; assign: "Conta de <cliente>" or "Conta sem cliente" |

1. `profilesPanel(doc, clients)` draws that panel from `doc.connections` and
   `doc.accounts`.
2. The click listener. `igconnect` and `data-connect` post to `/api/instagram/connect` and
   go to the returned `url`. `data-disconnect` calls `DELETE
   /api/instagram/connections/<id>` after the confirm "Desconectar este portfólio? As
   contas dele continuam na lista, sem conexão, e o que estiver agendado para elas não sai
   até conectar de novo. Nada muda no Instagram." `data-remove` calls `DELETE
   /api/instagram/accounts/<ig_id>` after the confirm "Remover @<conta> da Pauta? As
   publicações dela ficam sem conta. Nada muda no Instagram." Each then toasts and calls
   `again()`, which loads and draws the screen again, as the actions do today.
3. A `change` listener on the panel, for the account choosers. Choosing "Sem cliente" asks
   nothing. Choosing a client asks one question at most, the first that applies, and a no
   puts the chooser back: when the account already has another client, "@<conta> está com
   <atual>. Passar para <escolhido>?"; otherwise, when the account has a `match` and the
   chosen client is another one, "O cadastro de <match> diz @<conta>. Colocar esta conta
   em <escolhido> mesmo assim?". Then `PATCH /api/instagram/accounts/<ig_id>` with the
   chosen client (`null` for "Sem cliente"), the toast and `again()`; a failure toasts the
   error and calls `again()`.
4. `viewPost`, a new post: the chooser `#pclient` lists the accounts that have a client and
   an `ok` connection, as "Cliente (@conta)", with the account's `ig_id` as its value, and
   the post is created with `ig_id` in place of `client`. The value is sent as the string
   it is: an Instagram id has 17 digits, more than a JavaScript number holds, so the
   `Number()` around the chooser's value goes.
5. `viewPost`, an existing post: the chooser lists every account of the post's client,
   connected or not, the same way. The post's account is selected when it is in that
   list; otherwise a first option "escolha a conta" with an empty value is added and
   selected. The `PATCH` carries `ig_id` only when the selected value is not empty and
   differs from the post's.
6. On the list, the **Nova publicação** button shows when some account has a client and
   an `ok` connection.
7. `postRow`: when `p.blocked` is not empty, one line under the post with that text, in
   the class the failure reason uses (`perr`).
8. `IG_WHY.perfil` becomes "Este login não trouxe nenhuma conta profissional do
   Instagram."

#### 2e. Tests

**`tests/fakeinstagram.py`**

- `GET /graph/v*/me` answers `{"id": "122000000000000496", "name": "Pauta System User",
  "client_business_id": self.business_id}`; attribute `business_id` defaults to
  `"2251000000000741"`, and `None` leaves the field out.
- `GET /graph/v*/<business_id>` answers `{"name": "Du7 Portfólio"}`; attribute
  `no_business_name = True` makes it answer the error it gives an unknown object.
- `assigned_instagram_accounts` answers the accounts the login lists (`self.accounts`, or
  the single default profile when that is `None`, as today), `limit` at a time (25 when
  the request has no `limit`), starting after the account whose id is `after`. Every
  answer has `paging.cursors.after` (the last id sent); it has `paging.next` (any URL)
  only while more remain, as the real Graph does. Attribute `fail_page` (`None` by
  default) is the number, counting from 1, of the request of one login that answers
  status 500.
- The container, publish and limit calls accept the id of any account the login lists,
  and what is published is recorded with the id from the request's path as its `ig_id`.
  Without this no test can say which account a post went to.

**`tests/unit/test_publishing.py`** (no HTTP: these tests publish nothing)

- Helpers. `an_account(posts, client, ig_id=IG_ID, username=USERNAME, connected=True)`
  calls `posts.save_connection` for the portfolio `"2251000000000741"` with that one
  account, then `posts.assign(ig_id, client, None)`, and, when `connected` is false,
  `posts.remove_connection("2251000000000741")`: an account without a login, for tests
  that do not call Instagram. `connect(ig, fake_ig, posts, client)` walks
  the login as today, calls `save_connection` with what `finish` returns and assigns the
  fake's account to the client. `draft()` and `video()` take the `ig_id` to post to
  (default `IG_ID`) and their callers call `an_account` first.
- Existing tests, and what each becomes:
  - `test_the_clients_at_picks_its_profile_out_of_the_portfolios`: deleted.
  - `test_one_profile_serves_one_client`: deleted (an account has one row; the rule is the
    primary key).
  - `test_an_empty_login_brings_no_profile`: asserts `NO_ACCOUNT` and that
    `posts.connections()` and `posts.accounts()` are empty.
  - `test_connecting_keeps_the_token_out_of_the_database`: the token is under
    `biz-<business_id>` in the file and in no table.
  - `test_refusals_become_reasons_a_person_can_act_on` and
    `test_what_instagram_is_asked_for_each_kind`: the calls gain `conn`.
  - `test_scheduling_needs_a_connected_profile_and_a_moment`: scheduling without an
    account is refused with `NO_ACCOUNT_POST`, with an unconnected one with `NO_PROFILE`;
    its last part now asserts that after `remove_connection` the scheduled post is still
    `scheduled` and its `blocked` is `NO_PROFILE`.
  - `test_the_publisher_says_when_a_connection_lapsed`: reads the state from
    `posts.connections()[0]`.
  - `test_a_draft_needs_only_a_client_and_an_image`: a draft needs an account with a
    client; a missing or unknown `ig_id` is refused with `NO_ACCOUNT_POST`.
  - `test_deleting_a_post_takes_its_image_and_orphans_are_swept`,
    `test_a_post_left_publishing_is_marked_unsure_not_retried`,
    `test_publish_refuses_before_sending_what_a_person_can_fix`,
    `test_what_a_post_keeps_by_kind` and
    `test_a_video_waits_longer_before_it_counts_as_died`: call `an_account` first; the
    third uses `connected=False` and expects `NO_PROFILE`; the bodies built by hand in the
    fourth send `ig_id`.
- New tests:
  - `test_a_login_gives_the_portfolio_and_all_its_accounts`: two accounts, the business id
    and name, one token under `biz-<id>`, the two old per-account keys gone; with
    `no_business_name` the name is the one from `/me`.
  - `test_a_long_list_of_accounts_is_read_to_its_end`: 230 accounts give three requests
    and all 230; with `fail_page = 2` the login raises and the tokens file is unchanged;
    with `instagram.ACCOUNT_PAGES` patched to 1 it raises with `step == "accounts"`.
  - `test_a_login_without_a_portfolio_id_is_keyed_by_its_system_user`.
  - `test_an_account_goes_to_a_client_by_hand_and_can_move`: assign, reassign, clear; no
    post changes; the journal line, read through `caplog` on the logger `pauta` as
    `tests/api/test_observability.py` reads one, has the user, the account and the client.
  - `test_why_a_post_cannot_go_out`: `blocked` is `NO_ACCOUNT_POST` for a post with no
    account and for one whose account was removed, `MOVED` when the account's client was
    changed or cleared, `NO_PROFILE` when the account is not connected or its connection
    is `revoked`, and `""` otherwise and for a published post.
  - `test_a_posts_account_changes_only_within_its_client`: `update` with the other account
    of the same client changes `ig_id`; with another client's account it raises `MOVED`;
    with an unknown id `NO_ACCOUNT_POST`; with an empty `ig_id` the post keeps its account.
  - `test_an_account_a_login_no_longer_lists_is_not_connected`: a second
    `save_connection` for the same portfolio with one account of two; the other keeps its
    client and has an empty `business_id`.
  - `test_the_last_login_takes_the_account`: the same account in a second portfolio's
    `save_connection` moves there; the first connection then counts no account.
  - `test_only_an_unconnected_account_is_removed`: refused while connected; after
    `remove_connection` it goes, and its post's `blocked` is `NO_ACCOUNT_POST`.

**`tests/api/test_publishing_api.py`** (a real server: these publish against the fake)

- Helpers. `connect(base, admin)` posts to `/api/instagram/connect` and walks the login;
  `linked` connects once and assigns the fake's account to the client with the `PATCH`;
  `new_post`, `a_reel` and the two bodies built by hand in the Story and video tests send
  `ig_id`.
- Existing tests, and what each becomes:
  - `test_off_without_the_instagram_app`: expects the new empty answer, and the `OFF`
    message with 404 from `POST /api/instagram/connect`, the `PATCH`, and both `DELETE`s.
  - `test_an_admin_connects_a_clients_profile` becomes
    `test_an_admin_connects_a_portfolio_and_assigns_its_accounts`: members get 403 on
    connect, assign, disconnect and remove; `match` is set when one client's `@` equals the
    handle and not when two do or when the handle is empty; a `PATCH` without `client`, or
    with a string, is 400; an unknown account or client is 404; `DELETE` of an unknown
    connection is 404 and of a connected account is 400.
  - `test_the_clients_at_picks_its_profile_when_the_portfolio_shares_several`: deleted.
  - `test_what_the_upload_and_the_post_refuse`: an unknown `ig_id` is 400 with
    `NO_ACCOUNT_POST` (it was 404 for an unknown client).
  - `test_a_refusal_is_the_posts_state_and_it_can_go_again`: after the revoked token,
    `connections[0]["state"]` is `revoked`.
  - `test_a_scheduled_post_leaves_at_its_time`: its last part now disconnects with
    `remove_connection`; the scheduled post comes due and the tick returns it `failed`
    with `NO_PROFILE`.
  - `test_a_video_that_does_not_come_out_fails_and_can_go_again`: uses
    `set_connection(<business_id>, state=...)` in place of `set_profile`.
- New tests:
  - `test_one_client_two_accounts`: the fake lists two accounts, both assigned to one
    client; a post made for each is published to its own `ig_id` on the fake.
  - `test_a_post_whose_account_moved_is_refused_and_goes_out_when_it_is_back`: with the
    account given to another client, scheduling and "publish now" each answer 400 with
    `MOVED`; the tick marks a post that is due `failed` with `MOVED`; a video already
    waiting at Instagram ends `failed` with nothing published; a second scheduled post,
    not yet due, is published by the tick after the assignment is restored and its time
    has come.
  - `test_a_disconnect_keeps_the_accounts_and_their_clients`: after the `DELETE` the
    account is listed with its client and no connection, and no post changed; a second
    login connects it again with its client, and a post still scheduled then goes out at
    its time.

**`tests/e2e/test_publicacoes.py`**

- `connected()` and `test_connect_publish_schedule_edit_delete` press **Conectar
  Instagram** with no client chosen, then choose the client in the account's row
  (`[data-account-row] select`); the assertions on the old panel (`[data-profile=...]`,
  `#igclient`, "Nenhum perfil conectado ainda.") use the hooks and texts of the table in
  2d. Before **Desconectar** the test schedules one more post; after it the account is
  listed under "Sem conexão", that post is still under "Agendadas" and shows "conecte o
  Instagram deste cliente primeiro", and **Remover** takes the account off the list.
- `test_two_accounts_of_one_client`: the fake lists two accounts, the first with the
  client's `@`. The first row shows the suggestion. Assigning the first to another client
  asks the `match` question, and a no leaves it without a client. Assigning the first to
  its suggested client, and the second to the same client, asks nothing. The form's
  chooser then lists the client twice. A post made for the second account is published to
  that account's id. A draft made for the first account is edited onto the second. A post
  is scheduled for the second account; moving the second account to another client asks
  the "está com" question, and after a yes that scheduled post shows the `MOVED` text.

### Phase 3: the documents

- `docs/publishing-spec.md`. Each place below is rewritten to say what follows it:
  - the Connect row of "What the beta does": an admin presses **Conectar Instagram** with
    no client chosen, and then assigns each account listed to a client;
  - the Who row: admins connect and disconnect portfolios, assign and remove accounts;
  - the table under "A second integration, on purpose": one token per portfolio, under
    `biz-<business_id>`; a connection belongs to a portfolio;
  - "How a post goes out": a token Instagram no longer takes marks the connection;
  - "Which profile a login is for": a login is for every account the portfolio shares;
    the `@` on a client's record gives only a suggestion; what the second connection
    taught stays as history;
  - the Data section: `ig_connection`, `ig_account`, `post.ig_id`, schema v17, and that
    `ig_profile` stays unread until the beta is brought up to `main`;
  - the Stories and Reels section: "a profile gone meanwhile" becomes "an account no
    longer connected or no longer its client's", and question 3 no longer cites
    `ig_profile.account_type`, which no account row has;
  - "What it would take for other people's profiles": with Advanced Access a client
    connects its own portfolio, which then appears as a connection of its own.
- `docs/app-review.md`:
  - the `instagram_basic` paragraph keeps its first two sentences. From the third sentence
    ("After a client's Instagram professional account is shared...") to its end it
    becomes: "After a business shares its Instagram professional accounts with our app
    through Facebook Login for Business, we call `/me/assigned_instagram_accounts` and read
    only each account's id and username. We use them for two things: to show the agency
    which accounts it can publish to, so that an administrator assigns each one to the
    client it belongs to, and to ask that administrator to confirm when an account's
    handle is the one recorded for a different client, so a post is not published to the
    wrong client's profile. We do not read or store media, insights, or any other profile
    data."
  - screencast step 2: "Press **Conectar Instagram**. Show Meta's login, the portfolio and
    the Instagram account being selected, and the confirmation screen."; step 3: "Back in
    Pauta, show the account listed with its `@`, and choose its client: this is
    `instagram_basic` being used."; step 6: "Press **Desconectar** on the portfolio to show
    that the agency can revoke it."
  - a line under "Ready to paste": the owner saves the new `instagram_basic` text in Meta's
    dashboard before submitting.
- `deploy/README.md`: in the acceptance section, "the profiles' tokens" becomes "the
  connections' tokens (one per portfolio)".
- `CHANGELOG.md`, under Unreleased. In the existing Publicações entry, the sentences on
  connecting a client's profile, the routes `POST`/`DELETE /api/clients/{id}/instagram` and
  "Esquema v15 (`ig_profile`, `post`)" are rewritten to this model (one login per
  portfolio, `/api/instagram/...`, schema v17 with `ig_connection` and `ig_account`). One
  new sentence: on acceptance the owner connects once after the upgrade.
- This file: its status line becomes "built on <date>".

### After the phases, on acceptance

1. `make acc`. The panel shows both accounts under "Sem conexão" (no connection), each
   with its client; the scheduled posts are still scheduled and show "conecte o Instagram
   deste cliente primeiro".
2. The owner presses **Conectar Instagram** once, before the next scheduled post's time
   (2026-11-23 16:00 local time when this was written). The panel then shows one portfolio
   with both accounts, still assigned, and the notice is gone from the posts.
3. One post is published from each account, with the owner's yes for each.
4. The owner saves the new `instagram_basic` text in Meta's dashboard.
