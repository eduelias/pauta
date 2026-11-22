# App Review for Publicações: what it takes to drop the tester step

- **Why this exists:** while the publishing app is unpublished, only accounts with a role on
  it can be used, so every client's Instagram profile has to be invited as an **Instagram
  Tester** and accept that invitation. That is fine for the owner's own profiles and
  unacceptable for Piero's clients. The way out is App Review and Advanced Access.
- **Status, 2026-11-13:** four of the submission's five sections are green — Verification,
  App settings, Data handling and Reviewer instructions. Only **Allowed usage** is open, and
  everything left in it is the owner's to do or Meta's to catch up on. Nothing has been
  submitted yet.
- **Status, 2026-11-22:** the screencast is recorded and uploaded under both permissions,
  and both descriptions at Meta say what the code now does. What is left in **Allowed
  usage** is the three agreements, then Submit: both are the owner's.
- **The app:** Pauta Publicações (acc), App ID `29400025989594205`, in the Du7 Technology
  Services portfolio. Permissions `instagram_basic` and `instagram_content_publish`, both at
  "Ready for testing" (Standard Access).

## Done

| | |
|---|---|
| Privacy policy URL | `https://www.pauta.cc/privacidade.html` |
| Terms of Service URL | `https://www.pauta.cc/termos.html` |
| User data deletion | Instructions URL, the same privacy page (it carries the LGPD rights section and the deletion/retention promise) |
| Category | Business and pages |
| Contact e-mail | the owner's |
| App icon | the brand mark on its gradient, 1024 square |
| Tech Provider | declared, 2026-11-13 |
| Business verification | complete (Du7 Technology Services) |

## What is left, in order

The declaration added a **Review** section to the dashboard (Testing, Verification, App
Review) and opened a submission that already lists what will be reviewed:
`instagram_content_publish`, `instagram_basic` and `public_profile`, each "In 1 use case".

1. **The screencasts.** Done on 2026-11-22: one recording per the script below, uploaded
   under each of `instagram_content_publish` and `instagram_basic` (see "The recording").
2. **The three "agree to allowed usage" checkboxes**, one per permission. They are legal
   undertakings about how Du7 will use the data, so the owner ticks them.
3. **The API test calls** to register themselves, which is Meta's side (see below).
4. **Submit**, then wait. Meta may come back with questions, and may ask for access — see
   the note on reviewer access below.
5. **Publish the app** once the review passes.

## The submission, as it stands

Meta opened a submission (`submission_id` 29402866305976840) with five sections. Verification
and App settings are green. **Allowed usage** now has both written descriptions saved (the
texts below). What is left inside it, per permission:

| | `instagram_content_publish` | `instagram_basic` | `public_profile` |
|---|---|---|---|
| Description | done | done | not asked |
| Screencast | uploaded 2026-11-22 | uploaded 2026-11-22 | not asked |
| API test calls | completed | completed | none required |
| Agree to allowed usage | **owner** | **owner** | **owner** |

On the API test calls: the acceptance unit on du7 runs with
`PAUTA_IG_APP_ID=29400025989594205`, which is this app, so today's real connect and the two
real publishes were made against the app under review and will be attributed to it. Review →
Testing repeats that the data takes up to 24 h to appear, and that each test stays valid for
30 days. Nothing to do but wait; if it is still zero tomorrow, make one fresh call from the
Graph API Explorer with the app's own token.

Reviewer instructions, saved today, tell Meta three things: that Facebook Login for Business
is used only to connect a client's Instagram account and never to sign anyone in to Pauta,
that the test site is `https://acc.pauta.cc/`, and that Pauta has no passwords — a reviewer
account is issued on request as an invitation link that creates a passkey in their own
browser. **That promise is live**: if Meta writes to the app's contact address asking for
access, the invitation has to go out, or the review fails on "could not access the app".

### The reviewer invitation, ready to send

Made on 2026-11-13 and waiting in 1Password, **Du7 Tech → "Pauta acc reviewer invite"**. It
is an **admin** invitation, 2 uses, valid until **2027-02-11**, for `https://acc.pauta.cc/`.
Send it only if Meta asks for access, and only to the address they write from.

- **Why admin.** Connecting and disconnecting a client's Instagram profile is an admin-only
  route, and that is exactly what the reviewer has to exercise. A member account would let
  them see Publicações but not reach the permission under review.
- **Why that is safe.** Acceptance carries demo data only, runs as its own user with
  `ProtectHome=yes`, and cannot reach production's database. The only real things in it are
  the owner's own two Instagram profiles, `@du7dev` and `@pautacc`, both connected, with one
  published post each and a live permalink. A reviewer therefore lands on a module that
  already works rather than an empty screen.
- **What they still cannot do.** They cannot run the connect flow against a profile of their
  own, because while the app is unpublished only accounts with a role on it can pass Facebook
  Login for Business. They can press the button and see the dialog. The screencast is what
  shows the rest.
- **To revoke.** Delete the unused row from the `invite` table in
  `/var/lib/pauta-acc/pauta.db` on du7, or let it expire.

One older unused admin invitation for acceptance is still in that table and expires on
2026-11-15. It will lapse on its own; nothing to do unless you want it gone sooner.

### The five data-handling questions

Meta's own warning on the page: "If you are unsure of how to answer any question, we
recommend that you consult with the appropriate legal and data security colleagues in your
organization. Providing incomplete or vague answers may result in loss of platform access."
These are declarations about Du7, so the owner answers them.

1. **Do you have data processors or service providers that will have access to the Platform
   Data?** Evidence for "No": `app.pauta.cc` and `acc.pauta.cc` resolve through a CNAME to
   `du7.sytes.net` → a KPN address, the house connection. Cloudflare holds the DNS records
   with `proxied = false`, so it never sees the traffic, and TLS is a Let's Encrypt
   certificate terminated by Caddy on the Pi. The Instagram id, username and token sit in
   files next to the database on that machine and nowhere else. The answer changes the day a
   backup leaves the house to someone else's computer.
2. **Who is the person or entity responsible for all Platform Data?** The registered legal
   entity, not a product name.
3. **The country where that entity is located.**
4. **Have you given personal data to public authorities under national security requests in
   the past 12 months?**
5. **Which policies do you have for requests from public authorities?** The choices are:
   review of the legality of the request; provisions for challenging unlawful requests; a
   data-minimisation policy; documentation of the requests and the reasoning; none of the
   above; prohibited from answering. Ticking a policy that does not exist in writing is a
   false statement to Meta. "None of the above" is an allowed answer and is the honest one
   for a company that has not written these procedures down.

## Ready to paste

Meta reviews in English. These describe what the code actually does; keep them true if the
code changes.

**`instagram_basic`**

> Pauta is a work-management tool for small marketing agencies in Brazil. An agency records
> one row per client. After a business shares its Instagram professional accounts with our
> app through Facebook Login for Business, we call `/me/assigned_instagram_accounts` and read
> only each account's id and username. We use them for two things: to show the agency which
> accounts it can publish to, so that an administrator assigns each one to the client it
> belongs to, and to ask that administrator to confirm when an account's handle is the one
> recorded for a different client, so a post is not published to the wrong client's profile.
> We do not read or store media, insights, or any other profile data.

This text changed on 2026-11-22, when the username stopped being a condition for
connecting, and was saved in Meta's dashboard the same day.

**`instagram_content_publish`**

> Pauta is a work-management tool used by small marketing agencies in Brazil. An agency
> keeps one record per client. An administrator connects a business portfolio through
> Facebook Login for Business and assigns each of its Instagram professional accounts to
> the client it belongs to. Inside Pauta, an agency member composes a post for one of a
> client's accounts: a feed post (one image, a caption and an optional image description),
> a Story (one image or a short video) or a Reel (one video and a caption). The post is
> saved so it can be reviewed before it goes out. The agency then either publishes it
> straight away or sets a date and time. The Instagram API has no scheduling, so our server
> keeps the post and, at the chosen moment, calls `/{ig-user-id}/media` with `image_url` or
> `video_url` (and `media_type` `STORIES` or `REELS` where that applies) and the caption,
> polls the container until its `status_code` is `FINISHED`, and calls
> `/{ig-user-id}/media_publish`. We then read the permalink so the agency can open the
> published post from our interface. The file is served from an unguessable address on our
> own domain that answers only while that post is being published, and is closed again
> immediately afterwards. Nothing is published unless an agency member created the post in
> Pauta first.

Saved in Meta's dashboard on 2026-11-22, in place of the text that described a single image
only.

## Screencast script

Record one pass, no cuts, showing a real account:

1. Sign in to Pauta and open **Publicações**.
2. Press **Conectar Instagram**. Show Meta's login, the portfolio and the Instagram account
   being selected, and the confirmation screen.
3. Back in Pauta, show the account listed with its `@`, and choose its client: this is
   `instagram_basic` being used.
4. Press **Nova publicação**, choose the client, add the image and caption, and set a time a
   few minutes ahead. Show the post listed as *agendada*.
5. Wait for it to publish by itself. Show it as *publicada* and open **Ver no Instagram** —
   this is `instagram_content_publish`.
6. Press **Desconectar** on the portfolio to show that the agency can revoke it.

### The recording (2026-11-22)

Made on acceptance with the owner's browser, signed in to Facebook as the app's
administrator. It follows the six steps with a feed post to `@du7dev`, scheduled two
minutes ahead and published by the scheduler
(`https://www.instagram.com/p/DgC298ZlNa4/`). What was uploaded is an edit of that one
pass: cropped to the page, the wait for the scheduled minute sped up 16 times, English
captions under the picture because the interface is in Portuguese, 3 min 40 s. The
browser was driven by an assistant, and its "working here" marker shows at the top of the
page throughout; the question Pauta asks before **Desconectar** was answered for it, so
that one question is not in the picture. Acceptance was reconnected straight afterwards.

## Notes

- Publishing the app and Advanced Access are different things. Publishing alone leaves
  Standard Access, which covers only the app's own business; Piero's clients are other
  businesses and need Advanced.
- App domains is empty on purpose. The Business Login redirect is registered separately and
  works; filling it in without checking could break the live connection on acceptance.
- Once Advanced Access is granted, clients connect through their **own** portfolio and their
  own Instagram account. The current arrangement, where both profiles sit inside Du7's
  portfolio, suits the owner's own accounts and should not be the pattern for clients:
  revoking access should stay in the client's hands.

## Live mode, 2026-11-13

The owner pressed **Publish** on Pauta Publicações (acc), and Meta's developer alert
confirms it: the app switched to live mode. What that changed, and what it did not:

- **Changed.** In development mode only accounts holding a role on the app could get
  through Facebook Login at all, which is why every profile had to accept an Instagram
  Tester invitation. Live mode lifts that.
- **Not changed.** All three permissions still read **"Ready for testing"** on the
  permissions page, which is Standard Access, and all three still show 0 API calls.
  Standard Access only returns data for assets inside the app's own business portfolio, so
  a client's Instagram still has to be in the Du7 Technology Services portfolio. Advanced
  Access is what removes that, and it comes only from App Review.
- **Not changed either.** The submission is untouched: Allowed usage is still the one open
  section and Submit is still greyed out. Publishing and submitting are different buttons.
- **Now in force.** The privacy policy, the terms and the deletion instructions on pauta.cc
  are publicly binding, the app appears in people's Business integrations settings, and
  Meta's annual data use checkup starts applying.

### The switch broke nothing

Proved rather than assumed, straight after the switch. A post was composed in Pauta on
acceptance for Du7 Tech (`@du7dev`), scheduled for 14:08 local, and left alone:

| | |
|---|---|
| Due | 13:08:00 UTC (14:08 CET, as the browser sent it) |
| Picked up | 13:08:08 UTC, 8 s later |
| Published | 13:08:19 UTC, 11 s end to end |
| Permalink | `https://www.instagram.com/p/Dfrs91AFH4k/` |

Worth noting for anyone reading the `post` table: `due` and `published_at` are stored in
**UTC** while the form takes local time, so a 14:08 post reads as 13:08 in the database in
winter. That is correct, not a bug.

## The production ads app, prepared for publishing

A second, separate app exists: **Pauta**, App ID `1767206382079558`, in the same portfolio.
It is the **ads** app behind the campaigns integration (use case: measure ad performance
data with Marketing API), it serves `app.pauta.cc`, and it was still unpublished with an
empty settings page. Everything Meta requires before its Publish button works is now filled
in and saved:

| | |
|---|---|
| Privacy policy URL | `https://www.pauta.cc/privacidade.html` |
| Terms of Service URL | `https://www.pauta.cc/termos.html` |
| User data deletion | Data deletion instructions URL, the same privacy page |
| Category | Business and pages |
| App icon | the brand mark on its gradient, 1024 square |
| Platform | Website, site URL `https://app.pauta.cc/` |
| Contact e-mail | already set |

**Published on 2026-11-13**, on the owner's say-so. It is now in live mode, like the
acceptance app.

Checked straight afterwards that nothing broke: the production campaigns page loaded, and a
forced "Atualizar agora" ran a live sync at 14:14:56 across **9 connections and 9 accounts
with `errors: 0`** and 21 insight rows. Existing tokens and connections are untouched by the
mode switch, as expected.

Two things to decide before or after pressing it:

1. **Tech Provider.** This app has still not been declared one, and publishing did not
   change that. Without it, no App Review and so no Advanced Access for `ads_read` against
   other businesses' ad accounts: live mode on its own leaves Standard Access, which covers
   only Du7's own business. The declaration cannot be reversed, which is why it is left to
   the owner.
2. **There is still no production publishing app.** "Pauta Publicações (acc)" is the
   acceptance one, and its redirect points at `acc.pauta.cc`. When publishing goes to
   production it needs either its own app or a second redirect on that one. A client
   approving the connection reads the app's display name on Meta's consent screen, and
   "Pauta Publicações (acc)" is not what they should see.
