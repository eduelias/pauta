# Stage 8: intermediate zoom-out review

Target: `docs/designs/2026-11-22_publishing-mirrors-meta.md` (lines 1-584, the version
revised after stage 7), reviewed on 2026-11-22 against the zoom-out standard, with the
earlier reports in hand. The pass looked at what was added in answer to them.

**Verdict: no Blocker, 1 Major, 7 Nit.** The remedies mostly made the design simpler, not
heavier. The one Major is the "não veio no último login" state, which duplicates "not
connected" and leaves a gap in the remove-account remedy.

## Are the first pass's findings resolved?

Resolved in the document as it stands: A1 (no `legacy-` connections), A2/B1 (the copy runs
once, in one transaction), A3/B5 (no cascade; a disconnect keeps the client), A4/B6 (the
review texts and the confirm), A5/B2 (goal 5 and the `expired` marking), A6 (the export),
A7, A8, A9, A11, B3 (`assign` changes no post), B4 (`update` takes `ig_id`; `ready` is the
one check), B8.

Not resolved, or closed another way: A10 is half open (`ig_connection` is itself the record
while `meta_connection` mirrors token files; not stated); B7 is declined on purpose as a
non-goal, which the reviewer counts as closed by decision; the one-time upgrade block that
replaced the `legacy-` path has no stated end.

## Findings

1. **Major. "Não veio no último login" is a third account state that duplicates "not
   connected".** After a login the only token kept for a portfolio is the new one, and the
   list is what that token reaches: an account the login does not list cannot be published
   to. The design still offers it when composing and lets the post fail at its time, and
   pays for that with a `seen` column, a derived `stale` flag, a label, a rule, a non-goal
   and asserts. It also leaves a gap: `remove_account` refuses while `business_id` is set,
   so an account that left a still-connected portfolio can only be removed by disconnecting
   the whole portfolio, which is the "client who leaves" case. One planned test confuses the
   two states. *Change:* in `save_connection`, set `business_id=''` on that portfolio's
   accounts the login did not list; delete `seen`, `stale`, the label, the rule and the
   non-goal.
2. **Nit. The "can this post go out" rule is written twice, with two wordings:** `ready` on
   the server and `postRow` in the page, and they already differ. *Change:* the server puts
   the reason on each post in `GET /api/publishing` and the page prints it.
3. **Nit. A dedicated error and a 2,100-account test for a portfolio nobody has.** Keep the
   20-page bound; on hitting it raise the ordinary failure; delete `TOO_MANY` and the case.
4. **Nit. One change of a chooser can raise two dialogs in a row.** Ask one question, the
   first that applies.
5. **Nit. The one-time upgrade block has no end, and it writes a string nobody reads.** Say
   that the change which drops `ig_profile` also deletes the block and its tests; reduce
   the last statement to `SET state='expired'`.
6. **Nit. Rollback notes and a dated deadline sit where they inform nobody.** Cut the
   changelog entry to what changed plus "connect once on acceptance"; keep the rollback
   note in the design only, without the second-rollback sentence; state the deadline once.
7. **Nit. Phase 4 steps 1 and 3 interleave two handlers.** Move the remove button's
   sentences to the click listener's step.
8. **Nit. The rest of A10:** one clause saying the row is the record and the token file
   only holds the token.

## Additions the reviewer would leave as they are

The upgrade as one transaction that marks `ig_profile` rows `expired`; no post changing on
reassignment or disconnect (a net removal, matching decision 8's "statuses derived, never
stored"); changing a post's account within its client; "a post may have no account"; and
removing an unconnected account (the largest new surface, justified by the deletion promise
in `app-review.md`; finding 1 makes it sufficient).

Outside the pass's focus: `ig_connection.expires`, the `expired` state and the chores check
are carried over for a token that the code and the spec both say never expires.
