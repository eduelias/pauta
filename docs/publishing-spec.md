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
| Connect | An admin picks a client and clicks **Conectar Instagram**. Instagram's login opens; whoever is signed in there approves; the profile (professional, public) is now that client's. One profile serves one client |
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
- Images: `<db>.media/<token>.jpg`, removed with their post; one nobody attached to a post
  goes after a day.
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

Publishing to a profile the app's own people do not manage needs **Advanced Access** for
`instagram_content_publish` and `instagram_basic`: App Review with a screencast, and Business
Verification. That is the gate between this beta and a client of Piero's. Until then every
profile is one added by hand to the app's roles.

## Not built, and why

| | |
|---|---|
| The client's approval on a link | The step agencies lose hours on. The public report link (decision 12) is the pattern. Next, if the beta is kept |
| AI drafts for caption and art | Cents per post; needs the brand kit first. Since June 2026 Instagram takes `is_ai_generated` on the container: generated art must send it |
| A calendar view | The list by state is enough for one profile |
| Carousels, Reels, Stories, Facebook Pages | One image to the feed proves the path; each of the others is its own container type |
| The tab on the phone | The phone's bar has five fixed slots. The screens work on a phone at `/#/publicacoes`; the bar waits for a decision on which slot gives way |
| Usage events, `/metrics` | Decision 11's table is the owner's to extend |
| A post created in Pauta and deleted on Instagram | Pauta is not told. "Tirar da lista" removes it here only |

## Limits worth knowing

Instagram counts posts made through the API per profile per 24 hours; its own docs say 100
in one place and 50 in another, and the endpoint `content_publishing_limit` is what counts
(`Instagram.quota`). Containers expire after a day. Images must be sRGB JPEG. A caption's
links are not clickable on Instagram, and addresses should be plain ASCII.
