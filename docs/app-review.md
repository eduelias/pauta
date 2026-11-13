# App Review for Publicações: what it takes to drop the tester step

- **Why this exists:** while the publishing app is unpublished, only accounts with a role on
  it can be used, so every client's Instagram profile has to be invited as an **Instagram
  Tester** and accept that invitation. That is fine for the owner's own profiles and
  unacceptable for Piero's clients. The way out is App Review and Advanced Access.
- **Status, 2026-11-13:** app settings complete, app icon set, and the app is now declared a
  **Tech Provider** (the owner's call; Meta says it cannot be reversed). Business
  verification already shows complete. Nothing has been submitted for review yet.
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

1. **Review → Testing.** Complete the testing requirements Meta lists for the use case.
2. **App Review → Next.** The data-usage, data-handling and data-protection questionnaire.
   These are statements about how Du7 stores and protects client data: the owner answers
   them, not a guess from the code.
3. **The screencast.** One unbroken recording per the script below. It has to be made by
   hand on a real account; nothing automates it.
4. **Submit**, then wait. Meta may come back with questions.
5. **Publish the app** once the review passes.

## The submission, as it stands

Meta opened a submission (`submission_id` 29402866305976840) with five sections. Verification
and App settings are green. **Allowed usage** now has both written descriptions saved (the
texts below). What is left inside it, per permission:

| | `instagram_content_publish` | `instagram_basic` | `public_profile` |
|---|---|---|---|
| Description | done | done | not asked |
| Screencast | **to record** | **to record** | not asked |
| API test calls | 0 of 1 shown; the calls were made today, and Meta says they can take 24 h to appear | same | not asked |
| Agree to allowed usage | **owner** | **owner** | **owner** |

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
> one row per client. After a client's Instagram professional account is shared with our app
> through Facebook Login for Business, we call `/me/assigned_instagram_accounts` and read
> only the account id and username. We use them for two things: to show the agency which
> profile is connected to which client, and to confirm that the shared profile matches the
> handle the agency recorded for that client, so a post cannot be published to the wrong
> client's profile. We do not read or store media, insights, or any other profile data.

**`instagram_content_publish`**

> Inside Pauta, an agency member composes a post for one client: a single image and a
> caption, with an optional image description. The post is saved and can be reviewed before
> it goes out. The agency either publishes it immediately or sets a time. The Instagram API
> has no scheduling, so our server keeps the post and, at that moment, creates a media
> container with `image_url` and the caption, waits for the container to be ready, and calls
> `media_publish`. The image is served from an unguessable address on our own domain that
> answers only while that post is being published, and is closed again immediately after.
> Nothing is published without an agency member creating it first.

## Screencast script

Record one pass, no cuts, showing a real account:

1. Sign in to Pauta and open **Publicações**.
2. Pick a client and press **Conectar Instagram**. Show Meta's login, the portfolio and the
   Instagram account being selected, and the confirmation screen.
3. Back in Pauta, show the client's row listing the connected `@` — this is `instagram_basic`
   being used, and the only thing it is used for.
4. Press **Nova publicação**, choose the client, add the image and caption, and set a time a
   few minutes ahead. Show the post listed as *agendada*.
5. Wait for it to publish by itself. Show it as *publicada* and open **Ver no Instagram** —
   this is `instagram_content_publish`.
6. Press **Desconectar** on the profile to show that the agency can revoke it.

## Notes

- Publishing the app and Advanced Access are different things. Publishing alone leaves
  Standard Access, which covers only the app's own business; Piero's clients are other
  businesses and need Advanced.
- The app icon is still empty. Meta's Publish page does not require it, but a review with a
  blank icon looks unfinished; the brand avatar at `1080×1080` is the right file.
- App domains is empty on purpose. The Business Login redirect is registered separately and
  works; filling it in without checking could break the live connection on acceptance.
- Once Advanced Access is granted, clients connect through their **own** portfolio and their
  own Instagram account. The current arrangement, where both profiles sit inside Du7's
  portfolio, suits the owner's own accounts and should not be the pattern for clients:
  revoking access should stay in the client's hands.
