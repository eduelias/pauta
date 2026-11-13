# App Review for Publicações: what it takes to drop the tester step

- **Why this exists:** while the publishing app is unpublished, only accounts with a role on
  it can be used, so every client's Instagram profile has to be invited as an **Instagram
  Tester** and accept that invitation. That is fine for the owner's own profiles and
  unacceptable for Piero's clients. The way out is App Review and Advanced Access.
- **Status, 2026-11-13:** the app's required settings are complete (Meta's Publish page now
  says so). Nothing has been submitted, and the one irreversible step has not been taken.
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

## What is left, in order

1. **Become a Tech Provider.** Meta's dialog: "This option is for businesses that need to
   access business data owned by other business portfolios". **It cannot be reversed.** It
   is the gate to submitting App Review at all, and it brings two obligations: business
   verification of the entity, and the full data-usage questionnaire. This is the owner's
   decision to make, not a setting to flip.
2. **Business verification.** Du7 Technology Services already shows "Business verification
   complete" on the app-creation screen, so this may be satisfied; confirm after step 1.
3. **Request Advanced Access** for `instagram_basic` and `instagram_content_publish`, from
   the use case's Permissions and features table.
4. **Answer the data questions** (usage, handling, protection) and submit, with a screencast.
5. **Publish the app** once the review passes.

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
