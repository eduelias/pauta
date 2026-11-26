# Ponytail review of the planned change

An independent reviewer read the first version of
`docs/designs/2026-11-22_publishing-mirrors-meta.md` (the one with the `legacy-`
connections) and the code it touches, on 2026-11-22, following the Ponytail review
procedure. Nothing was run. Line numbers are of that first version. The last column of the
table at the end says what the revised brief does with each finding.

**What this change does:** Today each client logs in to Instagram on its own and can have
one Instagram account (table `ig_profile`, keyed by client). The plan replaces that with one
login per business portfolio (`ig_connection`), a list of that portfolio's Instagram
accounts that an admin gives to clients by hand (`ig_account`), and a post that names its
account (`post.ig_id`).

**Load assumed:** 2 to 5 people per installation, one server process with threads, the
publisher thread ticking every 20 seconds, SQLite. Publishing data exists only on
acceptance (2 accounts, 16 posts, 7 scheduled).

## Must fix

1. **Removed connections and accounts come back at every restart** (Phase 1 step 4).
   - **What this is:** At every start the upgrade block copies each `ig_profile` row into a
     `legacy-` connection and an account, with `INSERT OR IGNORE`. `ig_profile` is never
     emptied.
   - **Problem:** After the owner's login deletes the `legacy-` connections, the next start
     inserts them again. Worse: after Desconectar and a restart the accounts are back with
     the client they had on upgrade day, so an account the admin had moved or cleared is
     silently back with the old client.
   - **Fix:** Run the copy once, inside the `if` that adds `post.ig_id`. Extend the test to
     reopen the `Store` after a take-over and after a disconnect.
   - **If we skip it:** Ghost blocks after every deploy, and one path where an account
     returns to a client without anyone choosing it.

## Should fix

2. **A rollback does more than the risk table says.** After the owner's login the old token
   keys are forgotten, so the old release fails every scheduled post. Before it, the old
   release picks the account by the post's client, not by `post.ig_id`: a post made for
   account B can go out on account A. *Fix:* correct the risk row and the changelog; do not
   keep the old keys.
3. **A post that can no longer go out can still be scheduled, and the reason shown is
   wrong.** `_when` (also called by `update()`) gets only one of the three checks; a post
   whose account moved, or an old draft with no account, is accepted and fails at its time
   with "conecte o Instagram deste cliente primeiro". *Fix:* one check used by `_when`,
   `publish` and `advance`, with its own text.
4. **The fake Instagram cannot tell two accounts apart** (`tests/fakeinstagram.py`). It
   answers `/media` and `/media_publish` only for its single `self.ig_id` and records that
   id whatever the path said. *Fix:* accept the id of any account in `self.accounts` and
   record the id from the path.
5. **Two risky paths have no test.** (i) reading a `legacy-` connection's token under the
   old key; (ii) a video waiting at Instagram when its account is reassigned: only
   `advance`'s check stops it. *Fix:* one test each.
6. **The export keeps the frozen table and misses the new ones** (`EXPORT_TABLES`).
7. **The whole `legacy-` path is built for two test accounts on one machine:** about 60
   lines that run once, on acceptance. It is the source of finding 1 and half of finding 2.
   *Fix (the owner's call):* the upgrade only stamps `post.ig_id`; the owner logs in once.

## Nice to have

8. **Read the account list by cursor, not by following an address.** `Instagram._get`
   always adds `?appsecret_proof=…`, so a `next` address would get two `?`; Meta's `next`
   also carries the token.
9. **A portfolio block can have no title.** The name read can fail with this token's two
   permissions; fall back to the `name` from `/me`, as the ads side does.
10. **Columns and fields nothing reads:** `ig_account.created`; `ig_state` and `ig_client`
    in `_POST`; `seen` and `stale` with no test.
11. **Small places the plan does not name:** `Number()` around the chooser's value loses
    the last digit of a 17-digit `ig_id`; the "off" answer and its test still say
    `profiles`; the test helpers and four API test bodies create posts with `client`; the
    "Conectar de novo" button still posts to the deleted client route.

**Verdict:** fix 1 first (or take 7, which removes it). Then 2 to 6 before the build is
called done.

**Lean:** about -60 lines possible with 7, about -10 more with 10.

**Not checked:** Meta's real answers (whether `limit=100` is honoured, whether this token
may read the portfolio's name, what its `paging.next` holds), and acceptance's real rows
(whether any draft belongs to a client that had no profile at the upgrade).

## What the revised brief does with each

| Finding | In the revised brief |
|---|---|
| 1 | Fixed: the upgrade runs once, inside the branch that adds `post.ig_id`; tested by a second start |
| 2 | Fixed another way: the upgrade marks every `ig_profile` row `expired`, so the older release publishes nothing until someone connects again there; the login removes the old per-account token keys |
| 3 | Fixed: `ready()` is the one check, used when scheduling (`create` and `update`) and when sending, with its own messages; a post's account can be changed within its client |
| 4 | Added to Phase 2's changes to the fake |
| 5 | (i) no longer applies: there is no legacy token path. (ii) added as an assert in the test of a moved account |
| 6 | Fixed in Phase 1 |
| 7 | Taken: there are no `legacy-` connections |
| 8 | Fixed: the ads side's cursor loop |
| 9 | Fixed: falls back to the `name` from `/me` |
| 10 | `created` and `ig_state` are left out; `ig_client` is read by the page; `stale` gets an assert |
| 11 | Added to Phases 3 and 4 |
