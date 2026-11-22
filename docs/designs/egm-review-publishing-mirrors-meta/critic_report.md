# Stage 7: critic review

Target: the feature specification of `docs/designs/2026-11-22_publishing-mirrors-meta.md`
(lines 1-205 of the version revised after stage 6), reviewed on 2026-11-22 by three
reviewers: design, structure and style.

## Style

**Result: no Blocker, 10 Major, 5 Nit.** The text has no promotional wording and most
claims carry numbers. The findings are mostly about undefined Meta terms, figurative verbs
used in place of technical ones, and a few claims worded more strongly than their evidence.

### Major

- **S1 (14-20, 30, 60). Meta's terms are never defined:** business portfolio, token, system
  user. Add a definition of each after the opening paragraph.
- **S2 (79-81, goal 5). Jargon, and the second sentence repeats the first less clearly.**
  "Additive" is unexplained; "it" and "there" have no clear antecedent.
- **S3 (55-56, 58-65). The claim is wider than the evidence.** Only the first two rows of
  the table report a check against tokens; say so, and rename the column.
- **S4 (138, 153, 192, 198). "Asks first" does not say who asks whom.** Use "Pauta asks the
  admin to confirm before saving".
- **S5 (123-130, 143). "Moment" and "at once" are ambiguous** (they read as "briefly" and
  "one at a time"). Use "date and time" and "immediately".
- **S6 (143-144). "Moved" covers two events and "says so" is vague;** one Why cell is two
  noun phrases.
- **S7 (191). An unsupported superlative with an ambiguous referent:** "the manual step
  whose error is the worst one here".
- **S8 (157-160). A forward reference to Phase 5 and unexplained Meta review terms.**
- **S9 (136). "Shares" and "may not" are ambiguous.**
- **S10 (22-24). The "shape" metaphor and "these things".**

### Nit

- **S11.** "By itself" used for "automatically" (32, 81, 129-130, 137).
- **S12.** Figurative verbs for data relations: "brings", "carries", "names", "the last
  login wins" (31, 61, 116-118, 140).
- **S13.** Planned work stated in the present tense (202-203).
- **S14.** Judgments stated before their evidence: "stored in the wrong place", "cheap today
  and expensive later" (45, 49).
- **S15.** Fragments and idioms: "does the job", "a slip on a chooser", "the journal",
  "True today as well", "Meta pages the list", "its own piece of work".

## Structure

**Verdict: no Blocker, 3 Major, 10 Nit.** Every part the feature-spec standard requires is
present and the heading hierarchy is sound; the Majors are places where a goal, the model
and the risks table do not line up.

| Goal | Model | Alternatives | Risks |
|---|---|---|---|
| 1. Several accounts per client | covered | A | covered |
| 2. One login per portfolio, admin assigns | covered | A, C, I | covered |
| 3. A post belongs to an account | covered | A, D | the no-account state is undefined (M2) |
| 4. Upgrade keeps everything, one login | covered | F | the window before the login is missing (M1) |
| 5. Additive, rollback publishes nothing | covered | none (M3) | covered |

### Major

- **M1 (77-78 against 172-176, 196-204). Goal 4 is unconditional, the upgrade section
  contradicts it, and the Risks table omits the case.** A post that comes due before the
  owner's login fails and is sent again by hand: a second manual step with a dated
  deadline, stated only in the model section.
- **M2 (112-117, 167). The model never says a post can have no account, yet the plan builds
  that state** (a post whose client has no profile at the upgrade; a post made in the older
  release during a rollback). Add it to the upgrade step and as a rule.
- **M3 (79-81, 168-170, 180-192, 202). Goal 5 has no alternative and no stated reason.**
  Leaving `ig_profile` untouched so the older release keeps publishing is neither named nor
  rejected, and the spec never says why publishing nothing is the wanted outcome.

### Nit

- **N1.** Review-finding labels (A1, B3) collide with the alternatives' letters and name no
  file.
- **N2.** Problem reason 3 (state and token in the wrong place) has no goal.
- **N3.** The behaviour of an account that left the portfolio is specified in Non-goals and
  Risks, not in the model.
- **N4.** The app-review paragraph sits under "What a person sees" and carries an owner step
  that is not a risk row.
- **N5.** "Additive to the database" contradicts the step that rewrites `ig_profile` rows;
  say "additive to the schema".
- **N6.** Waiting until a client needs a second account is argued in the problem section but
  is not in the alternatives table.
- **N7.** Two non-goals give no reason or pointer (the panel staying on Publicações; one
  Meta app).
- **N8.** Raw angle brackets in a table cell (`<cliente>`) are dropped by Markdown renderers.
- **N9.** Quotations carry no source (Meta's documentation; the docstring of
  `meta_disconnect`).
- **N10.** Small asymmetries: a disconnected post shows no line on the list while a moved one
  does; "the last login wins" has no risk row; the schema-number row is a topic, not a risk;
  production is not mentioned in the upgrade section; the code fence has no language tag.

**Outside the audited range:** Phase 5 does not list the "A second integration, on purpose"
table of `publishing-spec.md`, two of whose rows this model makes untrue.

## Design

**Verdict: no Blocker, 6 Major, 7 Nit.** The model is sound and the specification covers
every area the standard asks for. The Majors are failure modes the Risks table omits or
understates, plus one missing alternative. Every checked claim about the existing code
holds except one overstatement (Nit 1).

### Major

- **D1 (137-138, 153, 198). The wrong-client guard misses the most likely slip.** The
  question fires only when one client's record matches the handle. 7 of 15 production
  clients have no usable handle, so their accounts get no suggestion and no question: an
  account moved from client A to B by a slip is then offered as "B (@x)" and a new post for
  B publishes on A's profile. *Change:* ask whenever an already-assigned account is moved to
  a different client, naming both.
- **D2 (143, 153, 155, 172-176). A scheduled post on an unconnected account still looks
  scheduled.** Nothing marks a scheduled post whose portfolio is disconnected, lapsed,
  revoked or not yet connected, and the plan drops `ig_state` from the post query. Posts
  left scheduled also go out after a later reconnect with nobody approving again; this is
  not in the Risks table.
- **D3 (94-96, 139, 178). No way is left to delete an Instagram account's data.** Today a
  disconnect deletes the profile row. After the change a disconnect keeps `ig_account`,
  deleting a client only unassigns it, removing a row is a non-goal, and `ig_profile` is
  kept with no end date, while `app-review.md` records the deletion promise as publicly
  binding.
- **D4 (162-170, 203). "Happens once" is not atomic with the copy.** Python's `sqlite3`
  opens a transaction only before INSERT, UPDATE or DELETE, so the `ALTER` that is the
  guard commits before the copy and the marking. A failure in that window leaves the guard
  set with nothing copied, and a restart will not repair it.
- **D5 (79-81, 168-170, 202). A rollback can publish on the wrong account of the right
  client.** The older release ignores `post.ig_id`. After a rollback and a reconnect of a
  client that was given two accounts, a still-scheduled post goes out on whichever account
  the old `@` match picks. Also: a profile reconnected during a first rollback stays `ok`
  for a second one, and posts made in the older release come back with no account.
- **D6 (74-75, 137, 180-192). Missing alternative: keep the client as a hint in the login.**
  The login could be started from a client and the accounts it newly brings suggested for
  that client. Name it and reject it with a reason, or adopt it.

### Nit

1. "Could not be connected without editing their record" is overstated: a login that brings
   a single account connects whatever the field says; it refuses only when several come.
2. The Meta quotes carry no URLs, and the check covers one portfolio (the app's own, through
   a Facebook identity); a portfolio outside Du7's is untested.
3. A connection can end with no accounts (the last login wins); the specification does not
   say what it shows.
4. A post with an empty `ig_id` is a real state the model text does not name.
5. The row counts have no date or method.
6. "Findings A1, B1..." do not say which report is A and which is B.
7. What happens past 20 pages or when a page fails mid-list is not said (a partial list
   would wrongly mark the rest as not seen); "Instagram's own reason" for an account that
   left the portfolio will likely be a generic refusal.
