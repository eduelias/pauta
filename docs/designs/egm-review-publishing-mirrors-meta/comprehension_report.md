# Stage 6: comprehension test

The reviewer read `docs/designs/2026-11-22_publishing-mirrors-meta.md` alone (458 lines, the
version revised after stage 5), with no other file and no standard, on 2026-11-22.

**Verdict:** the document is self-contained enough to say back what is being built and why.
No Blocker, 5 Major, 9 Nit.

## What this proposes

**Feature specification (lines 1-185).** Pauta is a marketing team's request queue. Its
Instagram publishing beta ("Publicações") would be reshaped to match the ads side and Meta's
own object model. One Meta login would connect a whole business portfolio (`ig_connection`,
one token) and list every Instagram account in it (`ig_account`, keyed by Instagram's id).
An admin would assign each account to a client by hand, helped by a handle-based suggestion
and a confirmation when the choice contradicts it. A post would name its Instagram account
as well as its client, and go out only while that account is connected and assigned to the
post's client. The upgrade copies each old `ig_profile` row into `ig_account`, stamps each
post with its account, and marks the old rows `expired` so a rolled-back release publishes
nothing; the owner then logs in once.

**Implementation plan (lines 186-458).** Five phases, one commit each: (1) schema 17, two
new tables, the `post.ig_id` column and a one-time copy guarded by the column's absence;
(2) the Instagram client keys its token as `biz-<business_id>` and its login returns the
portfolio plus a paged account list; (3) the `Posts` layer gains connections, accounts,
`assign` and a `ready` check used at scheduling and sending, and routes for connect, assign
and disconnect replace the per-client ones; (4) the page gets a per-portfolio panel with a
client chooser per account, and an account chooser on posts; (5) the spec, the App Review
text and the changelog are rewritten. It ends with a checklist on acceptance: deploy, one
login before 2026-11-23 16:00, one real post per account, and saving the new permission
text in Meta's dashboard.

## How the existing system works, per this document

The ads side ("Campanhas", in production) connects a portfolio once with one token, lists
all its ad accounts, and has an admin assign each to a client; a disconnect keeps those
assignments. The publishing beta runs only on acceptance (2 accounts, 16 posts, 7
scheduled) and connects per client: an admin picks a client and logs in at Meta, and the
code keeps the one portfolio account whose handle matches the client's free-text `@` field.
That account is stored in `ig_profile`, keyed by client, so a client has exactly one. The
same portfolio token is stored once per account, connection state lives per client, a post
knows only its client, and a disconnect deletes the profile row and turns scheduled posts
back to drafts. A background publisher sends scheduled posts when due and only while the
profile's state is `ok`.

Two parts of that paragraph were the reviewer's guesses: the publisher's behaviour, and
"disconnect drafts scheduled posts".

## Findings

### Major

1. **A disconnect unschedules posts, but only the plan says so** (121, 134 against 170,
   308-310, 363, 393-394, 453-454). The rule and the screen row say a disconnect forgets
   the token and keeps the accounts; the plan also turns scheduled posts into drafts, while
   reassigning "changes no post" and the upgrade leaves the 7 posts scheduled. The cases are
   treated differently with no stated reason.
2. **The post lifecycle is never stated** (124, 156, 170, 311-329, 358-361). Draft,
   scheduled, failed, "the claim", "advance", "the publisher's tick" and "container" appear
   without a definition, and the document does not say whether a post that failed with
   `MOVED` or `NO_PROFILE` retries by itself.
3. **"Account" means three things, and one is unmarked** (201, 244-245, 306, 338-340): an ad
   account, an Instagram account, and a Pauta user. The journal event carries no Instagram
   id. The `None` case of `start` is not explained.
4. **"Cannot be posted to" for an account that left the portfolio is ambiguous about who
   refuses** (90-91 against 181, 296-298, 311-315, 400-401). In the plan `stale` only shows
   a label.
5. **A risk mitigation promises tests the plan does not list** (183 against 229-235).

### Nit

6. Roles ("the owner", "admin", "member") are not introduced.
7. Connection states are not enumerated, and "state" also means the OAuth state.
8. "Acceptance", `make acc` and "the file" are assumed.
9. "The journal" is not defined.
10. Whether clearing an account's client triggers the confirmation is unclear.
11. "Changes in three places" does not match what follows.
12. The ads side's assignment is described two ways (28 against 119).
13. Small naming gaps: the text of `NO_PROFILE`; `seen` and `kind` unexplained at first use;
    `conn` is an id in one place and a dict in another; `ready` is a check and a page flag;
    whether the edit chooser filters on an `ok` connection; Portuguese strings not glossed.
14. Goal 5 says "never" where the mechanism says "until".
