# Stage 5: initial zoom-out review

Target: `docs/designs/2026-11-22_publishing-mirrors-meta.md` (lines 1-377), reviewed on
2026-11-22 against the zoom-out standard. Two reviewers: the zoom-out reviewer (part A) and
the inventive catalyst (part B).

## Part A: zoom-out reviewer

**Verdict: not ready as written. No Blocker, 5 Major, 6 Nit.** The core model (connection,
account, post) is right-sized and follows a pattern the codebase already proved. Four of the
five Majors come from one place: the `legacy-` upgrade path and the `ON DELETE CASCADE` on
`ig_account`.

Standard, section by section: context sufficiency passes; root problem passes (the three
reasons match the code); simplicity fails on the upgrade path (A1, A2, A5); altitude
passes; leveraging existing code mostly passes, with one real divergence from the ads model
(A3) and smaller misstatements (A7, A8, A10).

### Reuse claims checked against the code

| Claim (line) | Result |
|---|---|
| Ads: one connection and token per portfolio (22, 26) | Holds: `<db>.meta-token.<business_id>`, `meta_connection` keyed by `business_id` |
| Admin assigns each ad account, with a suggestion (24) | Holds: `Store.link_meta_account`, `Store.suggest_client`, `PATCH /api/meta/accounts/...` |
| `campaign` keeps both account and client (27, 108) | Holds |
| Publishing stores the same token once per account (26, 110) | Holds: `Instagram._keep(ig_id, ...)` |
| Revocation is marked per client (36-38) | Holds: `_failed` calls `set_profile(post["client"], state="revoked")` |
| `finish_connect` reads the portfolio name the same way (226-227) | Holds |
| `handle()` exists for the suggestion (233-234) | Holds: `instagram.py:97` |
| Rate-limit entry keeps its path (309) | Holds: `server.py:78` |
| Tests named for replacement exist | Hold |
| "The ads side has the same rule" on never auto-assigning (107) | Only partly: see A7 |
| `ig_account` is "like `meta_account`" (93) | Not on disconnect: see A3 |

### Major

**A1. The `legacy-` path is permanent code for a one-time move of two test accounts.**
Lines 67-68, 125-134, 145, 188-199, 213-218, 265-270, 306, 317-318, 332-333, 373-376. The
path adds `legacy-<ig_id>` connections, the `_key` mapping, a "Conexão antiga" block, a
`legacy-` route pattern, takeover logic in `save_connection`, a token-forget loop in the
callback and a takeover test. It serves one database: acceptance, with the owner's own two
accounts and 7 scheduled posts. Goal 4 says "with no step by a person", yet the plan
requires the owner to reconnect once anyway. The ads side's precedent for an old token it
cannot place is the opposite: `LEGACY` is listed with a "reconecte" state and never read.
*Option a:* drop goal 4 and the `legacy-` connections; the upgrade copies each `ig_profile`
row into `ig_account` with no connection and fills `post.ig_id`; the owner connects right
after `make acc`; a post due in between fails with "conecte de novo" and is sent again.
This needs `ig_account.business_id` to allow empty, as `meta_account.business_id` does, and
also removes A2, A3 and A5. *Option b:* keep the path, justify it, and name the release that
deletes it.

**A2. As written, the upgrade block brings deleted legacy connections back at every
start.** Lines 188-199 against 127-134 and 265-270. The v17 block runs at every start and
`ig_profile` is never dropped, so after the owner's login deletes the `legacy-` connections
the next start recreates them, with no account and state `ok`; chores then mark them
`expired`. With the cascade, disconnecting and restarting also brings back the accounts
with their upgrade-day clients. The planned test reopens the store before any takeover and
does not catch it. *Fix:* run the copy once, or adopt A1 option a.

**A3. Disconnecting deletes the account-to-client assignments, which the ads model
deliberately keeps.** Lines 93, 179, 276-277. `meta_account.business_id` has no foreign
key; `meta_disconnect` keeps the rows "so the client mapping survives a reconnect", and
decision 8 records the lesson. Here Desconectar then Conectar loses every assignment.
*Fix:* drop the cascade and keep account rows without a connection (listed, not postable),
or say the difference is intended and why.

**A4. The change makes the `instagram_basic` justification saved with Meta untrue, and
Phase 5 does not cover it.** Lines 121-123 and 366. `docs/app-review.md` (126-134) tells
Meta the username is read "to confirm that the shared profile matches the handle the agency
recorded for that client"; after this change nothing enforces that match. Step 6 of the
screencast script ("Desconectar on the profile") changes too. *Fix:* Phase 5 rewrites that
paragraph and step 6; an owner step saves the new text in Meta's dashboard before
submitting.

**A5. Goal 5 holds for the database but not for the token file.** Lines 69-70, 133-134,
156, 299-301. The callback forgets the `<ig_id>` token keys at takeover; the previous
release reads tokens by `ig_id`, so a rollback after the reconnect finds every publish
failing with "conecte de novo". *Fix:* do not forget the old keys at takeover, or say in the
risk row and the changelog that a rollback after reconnecting needs a reconnect.

### Nit

- **A6. `/api/export` is not in the plan.** `EXPORT_TABLES` (`db.py`) lists `ig_profile`;
  the export would carry a frozen `ig_profile` and neither new table. Add the two tables.
- **A7. Line 107 overstates the ads precedent.** `sync_meta_accounts` links a new ad
  account automatically when its id equals a client's `ad_account`; only the name-based
  guess is "never saved". Reword.
- **A8. Paging differs from the house pattern and its numbers disagree.** "More than 25",
  `limit=100`, and a fake paging at 25. `Meta._pages` builds its own request from
  `paging.cursors.after` and never sends the token to an address taken from a response.
  Say "the same cursor loop as `Meta._pages`".
- **A9. Alternative C misstates the ads app's review history.** That app has never been
  through App Review.
- **A10. Two places where "like the ads side" is looser than stated.** `meta_connection`
  mirrors the token files, which are the truth; `ig_connection` would itself be the truth.
  `finish_connect` falls back to the system user's id when there is no
  `client_business_id`, while this design refuses the login.
- **A11. The need is asserted, not evidenced.** No client is named; say it is the owner's
  request ahead of a real case. "Since this morning" should be the date.

## Part B: inventive catalyst

**Verdict:** the core model (connection per portfolio, account assigned to a client, token
once per connection) is balanced. The false compromises are in the transitions: the upgrade,
the rollback, reassignment and disconnect. One Blocker, six Major, one Nit.

**B1 (Blocker). The upgrade block undoes takeover and disconnect.** Phase 1 step 4 (lines
188-199). `INSERT OR IGNORE` at every start cannot be both re-runnable and removable later,
because `ig_profile` is never dropped: after the takeover the next `Store()` re-inserts the
`legacy-` connections (empty, state `ok`, no token; chores then mark them lapsed), and after
`remove_connection` it re-creates the accounts with their old clients. `Store()` is opened by
the server and by nine CLI entry points, so this needs no restart. The planned tests reopen
the store only straight after the upgrade. *Resolution:* run the copy once, inside the
branch that adds `post.ig_id` (the column is the "already migrated" mark and survives a
rollback); leave only the `post.ig_id` backfill unconditional; test a reopen after
`save_connection` and after `remove_connection`.

**B2 (Major). "Additive" is argued for the database only.** Goal 5, lines 130-134, 156,
268-270, 299-301. After the reconnect the old `<ig_id>` token keys are forgotten, so a
rollback fails every scheduled post. Before the reconnect (or if the keys were kept) the
older release publishes by `post.client → ig_profile.client` and ignores `post.ig_id`: an
account reassigned from C to D still receives C's posts after a rollback, the cross-client
publication the design names as its worst outcome. *Resolution:* decide that after a
rollback publishing is refused until someone reconnects, by setting `ig_profile.state` to a
non-`ok` value the older release already knows.

**B3 (Major). Reassigning demotes scheduled posts irreversibly.** Lines 151, 271-274,
344-345. `publish` and `advance` already refuse when the account's client is not the post's
client, so the demotion adds only an irreversible bulk side effect on a `<select>` with no
confirm. *Resolution:* `assign` leaves posts alone; the mismatch is derived (shown on the
post, refused at publish with that reason), the convention decision 8 states ("statuses
derived, never stored").

**B4 (Major). Stranded posts have no way out.** Lines 108, 195-196, 281-287, 346-349. A post
whose `ig_id` is empty or names an account now with another client cannot be moved (`update`
does not take `ig_id`; "one file, one post" forces a re-upload), can still be scheduled
(`_when` checks only the connection) and fails with the wrong message (`NO_PROFILE`).
*Resolution:* `PATCH /api/posts/{id}` accepts `ig_id` among the accounts of the post's
client; `_when` applies the same three-part test as `publish`; distinct messages.

**B5 (Major). A disconnect costs the admin's assignments.** Lines 64-65, 179, 276-277,
342-343. The ads side keeps them on purpose. *Options:* (a) on reconnect, suggest the client
from `SELECT DISTINCT client FROM post WHERE ig_id=?`; (b) keep `ig_account` rows on
disconnect, as `meta_account` does. The reviewer prefers (a) because (b) keeps Instagram ids
and usernames after a disconnect.

**B6 (Major). The one machine check against a wrong profile is removed.** Lines 107, 116,
121-123, 151, 366. Today a login is refused when the client's `@` does not match; the
`instagram_basic` justification saved with Meta says so. *Resolution:* a soft guard at
assignment (a confirm when the handle recorded for the chosen client differs), softened to
"warn only when the account's handle matches a different client's field" so a legitimate
second account does not train admins to click through; rewrite the justification and add
step 6 and the "Why admin" paragraph to Phase 5.

**B7 (Major). Everything about a portfolio is refreshed only at a login.** Lines 153-155,
228-230, 261-263, 288-289. A removed account, a renamed one and a revoked token are each
discovered by a failing post. *Resolution:* reconcile in the six-hourly chores with the
stored token.

**B8 (Nit). Two points to write down.** Alternative F rejects the `/me` regrouping only for
the start-up path; the off-start-up variant was not weighed. And "when it exists, move it
here" applies to any connection: an account shared with two real portfolios follows
whichever logged in last. State "the last login wins" as a rule.

**Adjacent:** `EXPORT_TABLES` lists `ig_profile` and the plan does not say whether the new
tables join `/api/export`; the ads side records who linked which account in `meta_log` and
the design has no equivalent.
