# Publicações: posts for a client's Instagram (beta, acceptance only)

- **Status:** a first cut built on 2026-11-12 to be tried on acceptance with the owner's own
  profile (@du7dev) as the client. Off everywhere the Instagram app is not configured, so
  production does not show it. Not a decision record yet: it becomes one (and amends
  decision 8's "Pauta only reads") if the trial says the module is worth keeping.
- **Where it came from:** the owner asked what KingHost does for "daily posting" and whether
  Pauta could do something alike for less. KingHost sells the Etus scheduler (Locaweb
  group) at R$ 15,90 to 27,90 per profile per month: the customer writes, the tool
  publishes. Pauta cannot win as a cheaper clone of that. What nobody sells between those
  tools and a R$ 1.000 freelancer is the content with a review step. So the order agreed
  was: calendar, drafts and client approval first, automatic publishing second. The owner
  then asked to try publishing first, on acceptance, with his own profile: the riskiest
  unknown is Meta's side, and one's own profile needs no App Review.

## What the beta does

| | |
|---|---|
| Connect | An admin picks a client and clicks **Conectar Instagram**. Meta's login opens; the profile shared there becomes that client's. One profile serves one client, and the client's own `@` (its record) says which profile is which |
| Formats | A picture for the feed, a Story (a picture or a video) or a Reel: see "Stories and Reels" below |
| Compose | **Nova publicação**: the client, one image, the caption (2.200 characters, 30 hashtags, 20 mentions, Instagram's limits), an optional description of the image, an optional moment |
| The image | Any picture the browser can open. The form turns it into a JPEG at most 1440 px wide and refuses a proportion outside 4:5 to 1,91:1 before anything is sent. The server checks again (JPEG, 8 MB, proportion, 320 px) by reading the file's own header |
| Publish | **Publicar agora** waits for Instagram (a few seconds) and says how it ended. **Agendar** keeps the post; a background thread publishes what is due, every 20 seconds |
| States | rascunho, agendada, saindo, publicada (with the link to the post), falhou (with the reason, and the post still there to send again) |
| Who | Members create, schedule, publish and delete their own; admins connect and disconnect profiles and delete anyone's |

## A second integration, on purpose

`meta.py` reads ad accounts with `ads_read` through Facebook Login for Business and never
writes. Publishing writes to a client's public profile. They share nothing:

| | Campanhas (`meta.py`) | Publicações (`instagram.py`) |
|---|---|---|
| Meta app | **Pauta** (production), **Pauta (acc)** (its test version) | Its own: **Pauta Publicações (acc)** on acceptance |
| Login | Facebook Login for Business, a system user per ads portfolio | The same dialog with another configuration ("Unified Login"): the asset is an Instagram account, and the person may sign in with Instagram itself |
| Ids and secret | `PAUTA_META_APP_ID`, `PAUTA_META_CONFIG_ID`, `<db>.meta-secret` | `PAUTA_IG_APP_ID`, `PAUTA_IG_CONFIG_ID`, `<db>.ig-secret` |
| Tokens | `<db>.meta-token.<business>`, never expire | `<db>.ig-tokens`, one per profile, never expire (the configuration says so) |
| Permissions | `ads_read` | `instagram_basic`, `instagram_content_publish`, nothing else |
| Belongs to | The team (a portfolio) | A client (a profile) |
| A Facebook Page | Not involved | Not needed |

**Why not "Instagram Login", as first built.** The first cut used the Instagram API with
Instagram Login (its own Instagram app id, `graph.instagram.com`, 60-day tokens). Creating
the app on 2026-11-13 showed that Meta no longer offers it: "API setup with Instagram login
is not available for newer apps. Your app uses API setup with Unified login instead."
Existing apps keep it with no end date announced; a new one cannot have it. Two more things
the dashboard taught: a test version of the ads app (**Pauta (acc)**) offers no other
product, so publishing needed an app of its own anyway; and Meta's template configuration
for Unified Login asks for `ads_management`, `ads_read`, messages and comments too. Pauta's
configuration was made by hand with the two publishing permissions only, and the dashboard
accepts it ("Instagram Login Compatible").

A policy action against one cannot take the other down, and either can be switched off by
removing its two settings.

## How a post goes out

Instagram's API has no scheduling and takes no upload: the app keeps the post, and at the
moment asks Instagram to fetch the image from a public address.

1. The post is **claimed** (`publishing`) in one UPDATE. Two taps, or a tap and the
   scheduler, cannot both get it.
2. `POST /{ig-id}/media` with `image_url` and the caption gives a container. The address is
   `/api/media/<token>.jpg`: unguessable, and it answers **only while that post is
   `publishing`**. A draft's image is never public.
3. The container's `status_code` is read until `FINISHED` (an image is ready at once; a slow
   one gets 40 seconds).
4. `POST /{ig-id}/media_publish`, then the permalink.

A refusal from Instagram is the post's state (`failed`, with a reason a person can act on:
the daily limit, the image could not be fetched, the profile was restricted, connect
again). A token Instagram no longer takes marks the profile, and every screen says
"conecte de novo". A post found `publishing` ten minutes after it started (the server died
between steps 2 and 4) is marked failed with "confira no Instagram antes de publicar de
novo": whether it went out is not known, and a blind retry could post it twice.

## Data

- `ig_profile(client, ig_id, username, name, account_type, state, error, expires,
  connected_by, connected_at)`: who, never a token. `post(id, client, caption, alt_text,
  media, width, height, status, due, container, media_id, permalink, error, account,
  created, updated, started, published_at)`. Schema v15, two new tables, nothing else moves.
  Schema v16 adds `kind` and `media_type` to `post`.
- Files: `<db>.media/<token>.<jpg|mp4|mov>`, removed with their post (a video as soon as it
  is published); one nobody attached to a post goes after a day.
- Moments are UTC in the database and the browser's own time on screen.

## Setting it up (acceptance)

Done on 2026-11-13, in Meta's dashboard, as the owner:

1. A new app, **Pauta Publicações (acc)** (App ID `29400025989594205`), use case *Manage
   messaging & content on Instagram*, in the Du7 Technology Services portfolio.
2. *Use cases → Customize → Permissions and features*: `instagram_basic` and
   `instagram_content_publish` added (both "Ready for testing").
3. *Facebook Login for Business → Configurations*: **Pauta publicar no Instagram**
   (`1692317655580950`): General, system-user token, never expires, asset *Instagram
   accounts* (required), those two permissions.
4. *API setup with Unified login*: that configuration selected, redirect URL
   `https://acc.pauta.cc/api/instagram/callback`.
5. *App roles → Roles*: @du7dev as **Instagram Tester**, accepted on Instagram under
   Settings → Apps and websites → Tester Invites. The app is unpublished: only people and
   profiles with a role on it can log in.

du7's side: a drop-in `pauta-acc.service.d/instagram.conf` with
`Environment=PAUTA_IG_APP_ID=…` and `Environment=PAUTA_IG_CONFIG_ID=…`, and
`/var/lib/pauta-acc/pauta.db.ig-secret` (owner `pauta-acc`, mode 600) holding the new app's
**App secret** (App settings → Basic), rendered from the 1Password item "pauta-acc instagram
app secret" (Du7 Tech). `PAUTA_ORIGIN` is already there. Then
`sudo systemctl restart pauta-acc`; the journal says `publisher_started` and the Publicações
tab appears.

**Which profile a login is for.** The token is the portfolio's system user, so it carries
**every** Instagram account the team has ever shared with the app, not only the one ticked
on Meta's last screen. The first client hid this (one account, one profile); the second
exposed it at once. So `finish()` takes the client's own `@` from its record and picks that
account out of the list. Without an `@`: a single account still connects, several are
refused with "escreva o @ deste cliente". With an `@` that nobody shared: refused too, since
connecting the only account on offer would quietly publish one client's posts on another's
profile. For an agency with ten clients in one portfolio, the `@` on the client record is
therefore not decoration: it is what keeps the posts apart.

**What the first connection showed (2026-11-13).** @du7dev sits in the app's own portfolio
(Du7 Technology Services), the case Meta's docs do not promise. Two attempts:

- Signing in **with Instagram** as @du7dev (an Instagram Tester of the app): the sharing
  screens came up, and after "Opslaan" Meta spun for half a minute and answered "Could not
  connect Pauta Publicações (acc)". Nothing reached Pauta.
- Signing in **with Facebook** as the app's admin, who also administers that portfolio: the
  same screens, and the callback arrived. `/me/assigned_instagram_accounts` returned the
  one profile, and the token has no expiry.

So the same-portfolio case works, through the Facebook identity. Why the Instagram identity
failed is not known (the tester role, or the portfolio rule); it matters for clients, who
will mostly sign in with Instagram, and is the first thing to test with a profile outside
Du7's portfolio. Because the dialog is opened with `prompt=login`, Meta also asks for the
Facebook password again when switching identities. Meta showed a cookie consent before the
sharing screens ("optional cookies are required to sign in to apps with Facebook and
Instagram").

**The first real post (2026-11-13, 08:45 UTC).** A 1080 × 1350 picture, chosen as PNG and
turned into a 0,2 MB JPEG by the form, saved as a draft and then published from acceptance
to @du7dev. Instagram fetched `/api/media/<token>.jpg` once (a GET, 2 ms), and the whole
publish call took 9,9 seconds: the wait is Instagram preparing the container. The permalink
came back and opens. The scheduler has not published a real post yet.

## What it would take for other people's profiles

`app-review.md` holds the live checklist: what is already set on the app, the irreversible
Tech Provider step, the paste-ready justifications and the screencast script.

Publishing to a profile the app's own people do not manage needs **Advanced Access** for
`instagram_content_publish` and `instagram_basic`: App Review with a screencast, and Business
Verification. That is the gate between this beta and a client of Piero's. Until then every
profile is one added by hand to the app's roles.

## Stories and Reels (built 2026-11-22, on acceptance)

Planned and built the same day, at the owner's request, ahead of Advanced Access: it is on
acceptance only, like the rest of this module. A scheduler that only posts one image to the
feed does not replace the tool it was compared with, which publishes every format. Both
formats go through the permission and the two-step flow the beta already used
(`instagram_content_publish`, a container, then `media_publish`): no new permission, no
second review, and nothing to add to the App Review submission. The form still opens on
**Feed**, so the screencast script in `app-review.md` reads as before.

What Instagram takes, read from Meta's documentation on 2026-11-22:

| | Story, image | Story, video | Reel |
|---|---|---|---|
| Container | `media_type=STORIES`, `image_url` | `media_type=STORIES`, `video_url` | `media_type=REELS`, `video_url` |
| File | sRGB JPEG, 8 MB | MOV or MP4, 100 MB, 3 to 60 s | MOV or MP4, 300 MB, 3 s to 15 min |
| Shape | 9:16 recommended | 9:16 recommended | 9:16 recommended, at most 1920 px wide |
| Caption | none | none | yes |
| Also | user tags | user tags | `thumb_offset` or `cover_url` (JPEG, 8 MB), `share_to_feed`, up to 3 collaborators, `audio_name` |

A video is H264 or HEVC with AAC sound, 23 to 60 frames a second, at most 25 Mbps; Meta's
page also asks for no edit lists and the `moov` atom at the front of the file. Instagram
fetches it from a public address, as it does an image, and then prepares the container: Meta
says to read `status_code` once a minute, for five minutes at most.

**What the API cannot do**, and no code here changes it:

- A Story takes no sticker: no link, no poll, no location.
- A Reel's sound is the file's own. Music from Instagram's library cannot be attached
  ("music tagging is only available for original audio"); neither can filters or shopping tags.
- A Reel cannot be an item of a carousel.

A Reel with library audio, or a Story with a link, is still posted by hand. The form says so
under the file field.

### What was built

| | |
|---|---|
| A post's kind | `post.kind`: `feed`, `story` or `reel`, chosen under **Formato** when the post is made and fixed after. `post.media_type` says whether its file is a picture or a video |
| A Story's picture | Checked against 9:16 (a feed picture against 4:5 to 1,91:1), in the form and again on the server. A Story keeps no caption and no description; a Reel keeps a caption |
| A video comes in as it is | The browser cannot convert a video and du7 does not transcode. The upload goes straight to the disk, a piece at a time (the unit has under 200 MB of memory), with its progress on the form. The server reads the file's own header (`ftyp`, then `moov` → `mvhd`, wherever in the file it is) for the length, and refuses what is not an MP4 or MOV, under 3 seconds, or over what its kind takes |
| What is left to Instagram | The codec, the frame rate, the proportion and where `moov` sits are not checked here: phones write `moov` at the end, and refusing those files would refuse most of them. When Instagram cannot prepare a video the post fails with "confira o formato (MP4 ou MOV, H.264 e AAC)" |
| The preview | A `<video>` reading the uploaded file from `/api/posts/media/<token>` (signed in), which answers byte ranges: a player asks for nothing else, and the page's policy allows no `blob:` addresses |
| The way out | "Publicar agora" on a video answers at once with the post `publishing` ("saindo…"): the container exists and Instagram is fetching. The publisher's tick looks at each such container once a minute and publishes it when it says `FINISHED` (`advance`). `ERROR`, a profile gone meanwhile, or fifteen minutes without an answer fail the post with a reason; nothing went out, so it can be sent again. A video found `publishing` after thirty minutes gets the "confira no Instagram" failure, where a picture gets it after ten |
| The public address | `/api/media/<token>.<jpg|mp4|mov>`, still only while the post is `publishing`, now streamed and range-capable |
| Room | A video is removed from du7 once it is published (the post and its link stay). Unused uploads, and what a died upload left, go after a day with the other orphans |
| A Reel on the grid | Always (`share_to_feed=true`) |

Schema v16: two added columns on `post`, with defaults that make every existing post a
picture for the feed.

### Not in this cut

A Reel's cover (Instagram takes the first frame), keeping a Reel off the profile's grid,
collaborators, user tags, the resumable upload to Meta (the public address is what works
today; it is the fallback if Instagram's fetch of a large file over du7's line proves
unreliable), and a server setting for the largest upload (it is Instagram's 300 MB).

### Still to ask the team

1. How many of the Reels they post use music from Instagram's library? Those cannot go
   through Pauta.
2. Do their Stories carry links or polls? Same answer.
3. Are the clients' profiles Business or Creator accounts? Meta's reference now says
   "professional accounts" for publishing in general, but an older page limited Stories to
   Business accounts: to be tried with a Creator profile. `ig_profile.account_type` already
   records which is which.
4. How long and how heavy is a typical video? That says whether du7's line carries it.
5. Should a Reel stay off the profile's grid sometimes?

### The first real Reel (2026-11-22, 10:44 UTC)

A 6-second 1080 × 1920 test pattern (H.264, AAC, 1,5 MB, MP4 with `moov` at the **end** of
the file, as phones write it), made a draft on acceptance for Du7 Tech (`@du7dev`) and
published with "Publicar agora":

| | |
|---|---|
| Container | 10:44:46 to 10:44:48 UTC: the call that creates it took 2 s |
| Fetched | 10:44:49, one plain GET of the whole file (no byte range), 3 ms on du7's side |
| Published | 10:46:08, at the publisher's first look: 82 s end to end |
| Permalink | `https://www.instagram.com/reel/DgCnuCpDwVB/` |

So Instagram takes a file whose index is at the end, and a short video is ready within the
first minute. The video was removed from du7 at once; the post stays on the list.

### Not tried yet

A Story (picture or video) on the real Instagram, a video from a phone's camera, and a
large one: how du7's line carries 100 MB and more is still unknown.

## Not built, and why

| | |
|---|---|
| The client's approval on a link | The step agencies lose hours on. The public report link (decision 12) is the pattern. Next, if the beta is kept |
| AI drafts for caption and art | Cents per post; needs the brand kit first. Since June 2026 Instagram takes `is_ai_generated` on the container: generated art must send it |
| A calendar view | The list by state is enough for one profile |
| Carousels, Facebook Pages | One image to the feed proves the path; each of the others is its own container type. A carousel takes up to 20 items, cropped to the first one's proportion |
| The tab on the phone | The phone's bar has five fixed slots. The screens work on a phone at `/#/publicacoes`; the bar waits for a decision on which slot gives way |
| Usage events, `/metrics` | Decision 11's table is the owner's to extend |
| A post created in Pauta and deleted on Instagram | Pauta is not told. "Tirar da lista" removes it here only |

## Limits worth knowing

Instagram counts posts made through the API per profile per 24 hours; its own docs say 100
in one place and 50 in another, and the endpoint `content_publishing_limit` is what counts
(`Instagram.quota`). Containers expire after a day. Images must be sRGB JPEG. A caption's
links are not clickable on Instagram, and addresses should be plain ASCII.
