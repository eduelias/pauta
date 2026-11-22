# Consolidated review: Publicações follows Meta's model

Document reviewed: [`../2026-11-22_publishing-mirrors-meta.md`](../2026-11-22_publishing-mirrors-meta.md).
Date: 2026-11-22. No code was changed by this review.

## How it was reviewed

| Stage | Reviewers | Report | Blocker | Major | Nit |
|---|---|---|---|---|---|
| 5. Initial zoom-out | zoom-out, inventive catalyst | [`zoom_out_report.md`](zoom_out_report.md) | 1 | 11 | 7 |
| 6. Comprehension | comprehension | [`comprehension_report.md`](comprehension_report.md) | 0 | 5 | 9 |
| 7. Critic | design, structure, style | [`critic_report.md`](critic_report.md) | 0 | 19 | 22 |
| 8. Intermediate zoom-out | zoom-out | [`intermediate_zoom_out_report.md`](intermediate_zoom_out_report.md) | 0 | 1 | 7 |
| 9. Implementation readiness | readiness, codebase details, style | [`implementation_readiness_report.md`](implementation_readiness_report.md) | 4 | 27 | 22 |
| Ponytail review | one independent reviewer | [`ponytail_review.md`](ponytail_review.md) | 1 must fix | 6 should fix | 4 nice to have |

Ten Elephant-Goldfish reviewers in five stages, run in order, plus one Ponytail reviewer.
The document was revised after each stage, so each stage read the version the stage before
it had changed. The four Blockers of stage 9 are two findings, each raised by two
reviewers.

**What was not done:** the plan was revised after stage 9 and that last revision has not
been read by a reviewer. Nothing in the plan has been run: the claims about `sqlite3`'s
transactions, about Meta's paging and about the real Graph API's answers come from reading
code and documentation, apart from the one check of `/me` and of the account list against
the two tokens on acceptance.

## Verdict

**The model stands.** No reviewer asked for a different one, and three checked its claims
about the existing code and found them accurate. The reviews changed the transitions around
it and the order of the work:

1. **The upgrade is smaller.** The first draft kept the old tokens working through a
   special kind of connection. Two reviewers and the Ponytail review found it was about 60
   lines for two test accounts and that it re-created removed connections at every start.
   It is gone: the upgrade copies rows once, in one transaction, and the owner logs in once.
2. **A rollback cannot publish on the wrong account.** The older release sends by client
   and ignores the new column. The upgrade now marks the old rows so that release refuses
   until someone connects again there.
3. **Nothing changes a post behind a person's back.** Reassigning an account or
   disconnecting a portfolio no longer turns scheduled posts into drafts. One rule decides
   whether a post can go out, the server computes it, and the list shows it.
4. **A disconnect keeps the assignments**, as the ads side does, and an admin can remove an
   account that is not connected, so that an Instagram account's record can still be
   deleted.
5. **The work is three commits, not five.** The first plan's middle phases could not each
   pass the checks, because the page depends on the server change. They are one phase now.

## Consolidated findings and what was done

🔴 Blocker, 🟡 Major, 🟢 Nit. The source column gives the report and the finding's label
there. "Resolved" means the document as it now stands answers the finding.

| # | Priority | Finding | Sources | Outcome |
|---|---|---|---|---|
| 1 | 🔴 | The upgrade's copy ran at every start and undid takeovers and disconnects | zoom-out A2, B1; Ponytail 1 | Resolved: it runs once, guarded by the `post.ig_id` column |
| 2 | 🔴 | Phases 2, 3 and 4 could not each pass `make check` | readiness R-B1, R-B2; codebase C-B1 | Resolved: one phase and one commit for the client, the store, the routes and the page |
| 3 | 🔴 | "`ig_id` stays in the request's path" was false for three of six methods | codebase C-B2; readiness R-M1 | Resolved: the six signatures are listed |
| 4 | 🟡 | The `legacy-` path was permanent code for two test accounts | zoom-out A1; Ponytail 7 | Resolved: removed (alternative 6) |
| 5 | 🟡 | A rollback could fail every post, or publish on an account that changed client | zoom-out A5, B2; critic D5; Ponytail 2 | Resolved: the upgrade marks `ig_profile` rows `expired`; the remaining case (wrong account of the right client after a deliberate reconnect) is in the Risks table with its instruction |
| 6 | 🟡 | The guard column could commit before the copy | critic D4 | Resolved: one explicit transaction, and a test that forces a failure |
| 7 | 🟡 | A disconnect deleted every assignment | zoom-out A3, B5 | Resolved: no cascade; accounts keep their clients |
| 8 | 🟡 | No way was left to delete an Instagram account's record | critic D3 | Resolved: an admin removes an account that is not connected; `ig_profile` is dropped by the change that takes the beta to production |
| 9 | 🟡 | Reassigning unscheduled every post of the account, with no way back | zoom-out B3 | Resolved: no post changes; the check at scheduling and at sending decides |
| 10 | 🟡 | A post that could not go out could still be scheduled, failed with the wrong reason, and had no way out | zoom-out B4; Ponytail 3; critic M2 | Resolved: one check (`why_not`) with three messages; a post's account can be changed within its client; "a post may have no account" is a stated rule |
| 11 | 🟡 | The rule was written twice, on the server and in the page | intermediate zoom-out 2 | Resolved: the server puts the reason on each post and the page prints it |
| 12 | 🟡 | A scheduled post on an unconnected account looked healthy | critic D2 | Resolved: the same reason shows on the list from the moment it is true |
| 13 | 🟡 | The guard against a wrong assignment missed the likeliest slip | zoom-out B6; critic D1 | Resolved: one question before moving an assigned account, or else before contradicting the handle on a client's record |
| 14 | 🟡 | The text saved with Meta for `instagram_basic` would become untrue | zoom-out A4, B6; critic N4 | Resolved: the new text is in Phase 3 and the owner saves it in Meta's dashboard |
| 15 | 🟡 | An extra account state ("did not come with the last login") duplicated "not connected" and blocked removal | intermediate zoom-out 1 | Resolved: such an account becomes not connected; the column, the flag and the label are gone |
| 16 | 🟡 | Existing tests the change breaks were not listed, and three new tests needed a server | readiness R-M2; codebase C-M1, C-M2 | Resolved: each is listed with what it becomes; the publishing ones are API tests |
| 17 | 🟡 | The fake Instagram could not tell two accounts apart | Ponytail 4 | Resolved: it records the account of the request's path |
| 18 | 🟡 | The connection's id was not sanitised and could be missing | readiness R-M4; codebase C-M6 | Resolved: digits only, as the ads side; with none the login fails and nothing is stored |
| 19 | 🟡 | The edit form could silently move a post to another account | readiness R-M5; codebase C-M8 | Resolved: a placeholder when the post's account is not in the list; the save sends the account only when chosen |
| 20 | 🟡 | Panel texts, hooks, route preconditions and input checks were left to the implementer | readiness R-M6, R-M7; codebase C-M5, C-M7 | Resolved: a table of texts and attributes; the routes' guard, body rule and messages |
| 21 | 🟡 | The post's life, the roles, Meta's terms and the word "account" were unexplained or ambiguous | comprehension 2, 3; style S1, S4 to S10; plan style 8 | Resolved in the text |
| 22 | 🟡 | Goals, model and risks did not line up (the window before the owner's login; goal 5 with no alternative) | critic M1, M3 | Resolved: a risk row and alternatives 11 and 12 |
| 23 | 🟡 | Paging followed an address from an answer | zoom-out A8; Ponytail 8; readiness R-N1 | Resolved: the cursor loop and stop rule of `Meta._pages` |
| 24 | 🟢 | The export listed the frozen table and not the new ones | zoom-out A6; Ponytail 6 | Resolved, with a test |
| 25 | 🟢 | A 17-digit Instagram id passed through `Number()` in the page | Ponytail 11 | Resolved |
| 26 | 🟢 | A dedicated error and a 2,100-account test for a portfolio nobody has | intermediate zoom-out 3 | Resolved: removed; the bound is tested by patching it to 1 |
| 27 | 🟢 | Two confirmation questions could follow one choice | intermediate zoom-out 4 | Resolved: one at most |
| 28 | 🟢 | Wording, sources, citations, counts, stale text in other documents | the Nits of every report | Resolved in the text or listed in Phase 3 |

## Declined, with the reason

| Finding | Why it was not taken |
|---|---|
| Re-read each portfolio's accounts in the background (zoom-out B7) | A non-goal: a removed account, a renamed one and a revoked token are learned at a login or when a post fails, as today. The second zoom-out pass counted it closed by decision |
| Start the login from a client and suggest that client (critic D6) | Alternative 10: it needs a stored hint or an assignment at the login, which is the automatic assignment the rules exclude |
| Drop `expires`, the `expired` state and the chores check, for a token that does not lapse (intermediate zoom-out, outside its focus) | Kept as they are today: a login configuration other than "never" gives a token that does lapse, and an existing test covers it |

## Left for the owner

1. **Whether to build it.** The design answers "a client can have several Instagram
   accounts" before any client has asked for one. Alternative 12 says why now.
2. **One login on acceptance after the upgrade**, before the next scheduled post's time, and
   a yes for each test post.
3. **Saving the new `instagram_basic` text in Meta's dashboard** before the review is
   submitted.
