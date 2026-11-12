# Publicações: posts for a client's Instagram (beta, acceptance only)

- **Status:** a first cut built on 2026-11-12 to be tried on acceptance with the owner's own
  profile (@du7.dev) as the client. Off everywhere the Instagram app is not configured, so
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
| Login | Facebook Login for Business, a system user per portfolio | Instagram API with Instagram Login, one login per profile |
| Ids and secret | `PAUTA_META_APP_ID`, `PAUTA_META_CONFIG_ID`, `<db>.meta-secret` | `PAUTA_IG_APP_ID` (the *Instagram* app id), `<db>.ig-secret` |
| Tokens | `<db>.meta-token.<business>`, never expire | `<db>.ig-tokens`, 60 days, renewed by the publisher while valid |
| Permissions | `ads_read` | `instagram_business_basic`, `instagram_business_content_publish` |
| Belongs to | The team (a portfolio) | A client (a profile) |
| A Facebook Page | Not involved | Not needed |

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

Meta's side, once, in the test app **Pauta (acc)** (App ID `1438754228470933`):

1. Add the **Instagram** product; in *API setup with Instagram login* → *Set up Instagram
   business login* → *Business login settings*, add the redirect URI
   `https://acc.pauta.cc/api/instagram/callback` and note the **Instagram app id** and
   **Instagram app secret** (they are not the Facebook ones).
2. In *Generate access tokens*, add the profile. It must be professional and public. The app
   stays in development mode: a profile of a person with a role on the app, added there,
   needs no App Review.

du7's side: a drop-in `pauta-acc.service.d/instagram.conf` with
`Environment=PAUTA_IG_APP_ID=…`, and `/var/lib/pauta-acc/pauta.db.ig-secret` (owner
`pauta-acc`, mode 600) rendered from the 1Password item "pauta-acc instagram app secret"
(Du7 Tech). `PAUTA_ORIGIN` is already there. Then `sudo systemctl restart pauta-acc`; the
journal says `publisher_started` and the Publicações tab appears.

## What it would take for other people's profiles

Publishing to a profile the app's own people do not manage needs **Advanced Access** for
`instagram_business_content_publish`: App Review with a screencast, and Business
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
