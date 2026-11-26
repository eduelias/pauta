# Stage 9: implementation readiness test

Target: the Detailed Implementation Plan of
`docs/designs/2026-11-22_publishing-mirrors-meta.md` (lines 258-603 of the version revised
after stage 8), reviewed on 2026-11-22 by three reviewers: implementation readiness,
codebase details and style.

## Style

**Result: no Blocker, 11 Major, 1 Nit.** No step is unreadable, but eleven can be read two
ways or leave the change unnamed.

1. **Major (559-565), `test_two_accounts_of_one_client`.** The sequence omits two steps:
   after the "no" the first account has no client, yet the chooser must list the client
   twice; and "the scheduled post" has no antecedent.
2. **Major (443-446), `publishing.py` step 8.** One step carries four changes, and "a
   revoked token marks the connection" names no function, state value or connection (it
   belongs in `_failed`, which has the post but not the account).
3. **Major (447-450), step 9.** It does not say whether `tick` gains its own `ready` call or
   is unchanged because `publish` now raises; "lapsed" is undefined.
4. **Major (437-442), steps 6 and 7.** `_when`'s new argument is never stated; an `ig_id`
   that names no account in `update` gets `MOVED` on a literal reading; the exception
   classes are not named.
5. **Major (485-488), the moved-account test.** "Refuse" covers two outcomes (an `Invalid`
   raised, a post marked `failed`), and "a post still scheduled" must be a second post the
   sentence never introduces.
6. **Major (513-515), `profilesPanel`.** "When not `ok`" can govern one button or both; the
   state line's text is not given.
7. **Major (539-543), `viewPost`.** "When the post has none" covers three states (an empty
   `ig_id`, an account that moved, an account that was removed).
8. **Major (330-333, 397-401, 416-419), the term "account".** A Pauta user and an Instagram
   account in adjacent phases. Name the parameter `by` and say "user" in prose.
9. **Major (569-572), Phase 5.** "Are rewritten to this model" gives no content for five
   sections of `publishing-spec.md`.
10. **Major (344-348), `finish`.** The step label `"me"` is used for two requests while the
    next sentence uses `"accounts"`; the reader cannot tell which redirect a failed page
    gives. "In all three cases" requires counting back.
11. **Major (577-585), `app-review.md` text.** "The only thing it is used for" contradicts
    "we use them for two things" a few lines above.
12. **Nit (433-436), `blocked`.** "The four `ig_` columns except `ig_username`" makes the
    reader count; the mapping from the joined columns to `why_not`'s argument is implied.

## Implementation readiness

**Verdict: not ready. 2 Blocker, 7 Major, 9 Nit.** Phase 1 is executable as written.
Phases 2 to 4 cannot each end with `make check` green, which is the main problem, and the
test plan names the new tests but not the existing ones the change breaks.

### Blocker

- **R-B1 (261-262, 323-385). Phase 2 cannot end green.** It changes the signatures of
  `Instagram.start`, `take_state`, `finish` and the six publishing calls; their callers in
  `routes/publishing.py` and `publishing.py` change only in Phase 3, and the unit helper
  `connect()` is rewritten only in Phase 3 but breaks in Phase 2. *Fix:* merge Phases 2 and
  3 into one phase and one commit.
- **R-B2 (387-507 against 509-565). Phase 3 cannot end green either.** `make check` includes
  the browser suite; after Phase 3 the API returns `connections` and `accounts` and the two
  client routes are gone, while the page changes only in Phase 4. *Fix:* fold Phase 4 into
  the same phase, or say which check applies after which part.

### Major

- **R-M1 (355-357). Three method signatures are ambiguous:** `container_state`,
  `wait_ready` and `permalink` never put `ig_id` in a path. List the six final signatures.
- **R-M2 (478-507). Existing tests the change breaks are not listed**, and several need a
  new expected behaviour: in the unit tests `test_one_profile_serves_one_client`,
  `test_an_empty_login_brings_no_profile`,
  `test_scheduling_needs_a_connected_profile_and_a_moment` (it asserts that a disconnect
  drafts scheduled posts), `test_the_publisher_says_when_a_connection_lapsed`,
  `test_a_draft_needs_only_a_client_and_an_image`, and six tests that call `draft()` or
  `video()` with no login; in the API tests `test_what_the_upload_and_the_post_refuse`,
  `test_a_refusal_is_the_posts_state_and_it_can_go_again`,
  `test_a_scheduled_post_leaves_at_its_time`,
  `test_a_video_that_does_not_come_out_fails_and_can_go_again`,
  `test_off_without_the_instagram_app`.
- **R-M3 (506-507). "The export test" does not exist.** Add a named test to Phase 1.
- **R-M4 (336-341, 471). An undecided edge on the connection id:** whether `finish` keeps
  only digits, and what it raises when `/me` gives neither id.
- **R-M5 (539-544, 440-442). The edit form can silently move a post to another account**
  when the post's account is no longer among its client's; and what the PATCH sends when
  the placeholder is selected is undecided.
- **R-M6 (513-522, 554-558). Panel copy and markup are left to the implementer:** the empty
  states, the helper paragraph, the state line per state, the toasts, what a member sees,
  the data attributes the browser tests select by, and whether `style.css` may change.
- **R-M7 (459-473, 416-427). Preconditions and input checks for the new routes are
  missing:** whether they call `_on()`, the PATCH body rule, and the `NotFound` texts.

### Nit

- **R-N1.** The paging stop condition differs from `Meta._pages` (which also stops when
  `paging.next` is absent or the cursor repeats); the fake's `limit` default and `fail_page`
  counting are not said.
- **R-N2.** The fake with `self.accounts is None` (the default) must still accept
  `self.ig_id`.
- **R-N3.** `match` must need a non-empty handle: `handle("")` equals every blank field.
- **R-N4.** In `blocked`, a removed account and an unassigned one both give a NULL client;
  say what "no account" is. "The four `ig_` columns except `ig_username`" is three.
- **R-N5.** Specified edges with no test: the 20-request cap; `DELETE` of an unknown
  connection and of a connected account over the API; PATCH with an unknown account or
  client; a revoked token marking the connection; and one test has a name but no
  assertions.
- **R-N6.** "Second sentence onward" of the `instagram_basic` paragraph would delete "An
  agency records one row per client."
- **R-N7.** Phase 5 leaves stale text it does not list: four more places in
  `publishing-spec.md`, the existing Unreleased changelog entry, three module docstrings and
  `deploy/README.md`.
- **R-N8.** Whether the `ig_connected` and `ig_disconnected` events are kept; how the
  assignment test reads the journal line; that a missing token still counts as lapsed.
- **R-N9.** No consolidated file list; in the browser test, "the scheduled post stays
  scheduled" has no scheduled post at that point.

**Confirmed against the code:** the schema number, the index position and the v16 block in
`db.py`; that `Store.db()` commits or rolls back through `with conn`; that the
`in_transaction` guard is needed and sufficient; that the trigger raises
`sqlite3.IntegrityError`; that existing table-list tests use subset checks; the callback's
rate-limit entry; `Meta.finish_connect`'s key and name; that `Publisher.tick` already turns
an `Invalid` from `publish` into a failed post; the `Number()` to remove; and the three
screencast steps.

## Codebase details

**Verdict: not ready. 2 Blocker, 9 Major, 12 Nit.** Most of the plan's statements about the
code are accurate; the gaps are the phase checkpoints, one wrong sentence about the
`Instagram` method signatures, and a test plan that omits about fourteen existing tests the
change breaks.

### Blocker

- **C-B1. Phases 2 and 3 cannot pass `make check` on their own** (the same as R-B1 and
  R-B2, with the callers: `routes/publishing.py:60, 78, 83`; `publishing.py:573, 601-609,
  631, 641, 696`; `app-publicacoes.js:79, 81, 109, 124, 137, 224`).
- **C-B2. "`ig_id` stays the id in the request's path" is false for three of the six
  methods.** `container_state`, `wait_ready` and `permalink` use `ig_id` only for the token
  (`instagram.py:413-451`). *Fix:* `container_state(conn, container)`,
  `wait_ready(conn, container)`, `permalink(conn, media_id)`; `create_container(conn,
  ig_id, ...)`, `publish(conn, ig_id, container)`, `quota(conn, ig_id)`.

### Major

- **C-M1. Existing tests the change breaks that the plan does not list** (the list in R-M2,
  plus `test_what_instagram_is_asked_for_each_kind` and the API helper `connect()`, used in
  eight places; six unit tests create posts with no account and the plan does not say where
  an account comes from in tests that never log in).
- **C-M2. Three new unit tests need a real publish, which `tests/unit` cannot do:** the fake
  downloads the file from the app's address, and unit tests have no server. Put them in the
  API tests.
- **C-M3. "The export test" does not exist** (as R-M3).
- **C-M4. The browser test has no scheduled post when it presses Desconectar**, and the
  second test's "scheduled post" is never created.
- **C-M5. Behaviour of the replaced code that the plan neither keeps nor drops:** the
  `_on()` guard on the routes; the `ig_connected` and `ig_disconnected` events; a token gone
  from the file counting as lapsed in `chores`.
- **C-M6. The connection's id is not sanitised and can be missing** (`Meta.finish_connect`
  reduces it to digits and raises when there is none).
- **C-M7. The panel's existing texts and hooks are not accounted for** (as R-M6).
- **C-M8. Saving a post whose account is missing is undefined** (as R-M5).
- **C-M9. Files are not marked Create, Modify or Delete, and there is no single list.**

### Nit

- **C-N1.** `_failed` and `_published` need the connection id passed in.
- **C-N2.** `_when` runs before the `UPDATE` on the open connection; give its new signature.
- **C-N3.** `advance` returns early for a post that is not waiting, and `_failed` reads
  attributes `Invalid` lacks: re-raise `ready`'s `Invalid` as an `InstagramError`.
- **C-N4.** `Publisher.tick` needs no code change.
- **C-N5.** `Instagram.quota` has no caller and no test.
- **C-N6.** `test_a_state_is_used_once_and_a_code_too` needs no update.
- **C-N7.** `match` needs a non-empty handle (as R-N3).
- **C-N8.** Use the stop rule of `Meta._pages`, or make the fake keep the cursor on the last
  page.
- **C-N9.** No function draws from a given document: say "then `again()`".
- **C-N10.** The fake's default (`accounts is None`) is the single profile.
- **C-N11.** `NotFound` texts and the handling of a non-integer `client` are not given.
- **C-N12.** Stale text the documents phase does not list (the changelog's existing entry,
  the `instagram_basic` paragraph's second sentence, four places in `publishing-spec.md`,
  `deploy/README.md`, and module docstrings).

**Statements checked and found correct:** all of Phase 1, including the transaction (an
explicit `BEGIN` inside `store.db()` has precedent in `auth.py`); the current signatures and
constants in `instagram.py`; `Meta.finish_connect`; the five profile methods, the routes
and the callback's reasons; the page's functions, ids and the `Number()`; every heading
named in the two documents; and every named test and helper except the export test.
