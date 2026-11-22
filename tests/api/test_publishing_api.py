"""Publicações over the API (docs/publishing-spec.md): off without the Instagram app; an
admin connects a portfolio through Meta's login and says which client each of its
Instagram accounts is for; a post is one JPEG and a caption, published now or at its
time; the image is public only while Instagram fetches it."""

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

import pytest

from fakeinstagram import BUSINESS_ID, IG_ID, jpeg, mp4
from pauta.publishing import MOVED, NO_ACCOUNT_POST, NO_PROFILE, Posts, Publisher
from softpasskey import call


@pytest.fixture()
def ig(ig_on):
    return ig_on


def follow(url, cookie=None):
    """One GET without following the redirect: (status, Location)."""

    class Stop(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    req = urllib.request.Request(url, headers={"Cookie": cookie} if cookie else {})
    try:
        with urllib.request.build_opener(Stop).open(req) as r:
            return r.status, ""
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location") or ""


OK = (302, "/#/publicacoes?ig=ok")


def connect(base, admin):
    """The admin's way through Meta's login, as the browser walks it."""
    status, doc, _ = call(f"{base}/api/instagram/connect", {}, admin)
    assert status == 200, doc
    status, back = follow(doc["url"])
    assert status == 302 and back.startswith(f"{base}/api/instagram/callback?")
    # the browser drops the "#_" before asking, and comes without the session cookie
    return follow(back.split("#")[0])


def assign(base, admin, ig_id, client):
    """Say which client an account is for, as an admin does on the panel."""
    return call(f"{base}/api/instagram/accounts/{ig_id}", {"client": client}, admin, "PATCH")


def upload(base, cookie, raw=None):
    req = urllib.request.Request(
        f"{base}/api/posts/media",
        data=jpeg() if raw is None else raw,
        headers={"Content-Type": "image/jpeg", "Cookie": cookie},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def get(url, cookie=None):
    req = urllib.request.Request(url, headers={"Cookie": cookie} if cookie else {})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


@pytest.fixture()
def linked(team):
    """Renato (admin), Piero (member) and a client with a connected Instagram account."""
    base, nato, piero, _ = team
    client = call(f"{base}/api/clients", {"name": "Du7"}, nato)[1]["id"]
    assert connect(base, nato) == OK
    assert assign(base, nato, IG_ID, client)[0] == 200
    return base, nato, piero, client


def new_post(base, cookie, client, ig_id=IG_ID, **over):
    status, media = upload(base, cookie)
    assert status == 200, media
    body = {"ig_id": ig_id, "media": media["media"], "caption": "Bom dia! #du7", **over}
    status, post, _ = call(f"{base}/api/posts", body, cookie)
    assert status != 200 or post["client"] == client  # the account says whom it is for
    return status, post


def test_off_without_the_instagram_app(team, ig, store):
    base, nato, _piero, _ = team
    ig.secret_file.unlink()
    assert call(f"{base}/api/boot", cookie=nato)[1]["publishing"] == {"enabled": False}
    assert call(f"{base}/api/publishing", cookie=nato)[1] == {
        "enabled": False,
        "connections": [],
        "accounts": [],
        "posts": [],
    }
    for path, body, method in (
        ("/api/instagram/connect", {}, "POST"),
        (f"/api/instagram/accounts/{IG_ID}", {"client": None}, "PATCH"),
        (f"/api/instagram/accounts/{IG_ID}", None, "DELETE"),
        (f"/api/instagram/connections/{BUSINESS_ID}", None, "DELETE"),
        ("/api/posts", {"ig_id": IG_ID}, "POST"),
        ("/api/posts/1/publish", {}, "POST"),
    ):
        status, doc, _ = call(f"{base}{path}", body, nato, method)
        assert (status, doc["error"]) == (404, "as publicações não estão ligadas neste servidor")
    assert upload(base, nato)[0] == 404


def test_an_admin_connects_a_portfolio_and_assigns_its_accounts(team, fake_ig, ig):
    base, nato, piero, _ = team
    assert call(f"{base}/api/boot", cookie=piero)[1]["publishing"] == {"enabled": True}
    du7 = call(f"{base}/api/clients", {"name": "Du7 Tech", "instagram": "@du7dev"}, nato)[1]
    call(f"{base}/api/clients", {"name": "Pauta", "instagram": "@pautacc"}, nato)
    call(f"{base}/api/clients", {"name": "Outra Pauta", "instagram": "pautacc"}, nato)
    call(f"{base}/api/clients", {"name": "Sem arroba"}, nato)
    fake_ig.accounts = [
        {"id": "17841000000000001", "username": "du7dev"},
        {"id": "17841000000000002", "username": "pautacc"},
        {"id": "17841000000000003", "username": ""},
    ]
    # the connection is the team's to make, by an admin; a stranger gets nothing
    assert call(f"{base}/api/instagram/connect", {}, piero)[0] == 403
    assert call(f"{base}/api/instagram/connect", {})[0] == 401
    assert call(f"{base}/api/publishing")[0] == 401

    # cancelled in Meta's dialog, then a callback nobody started
    fake_ig.deny = True
    assert connect(base, nato) == (302, "/#/publicacoes?ig=erro&motivo=cancelado")
    fake_ig.deny = False
    status, back = follow(f"{base}/api/instagram/callback?code=x&state={'s' * 43}")
    assert (status, back) == (302, "/#/publicacoes?ig=erro&motivo=vencido")

    # one login: the portfolio, and every account of it, none of them anybody's yet
    assert connect(base, nato) == OK
    doc = call(f"{base}/api/publishing", cookie=piero)[1]
    (conn,) = doc["connections"]
    assert (conn["business_id"], conn["business_name"]) == (BUSINESS_ID, "Du7 Portfólio")
    assert (conn["state"], conn["by_name"], conn["accounts"]) == ("ok", "Renato Lima", 3)
    assert all(a["client"] is None and a["state"] == "ok" for a in doc["accounts"])
    by = {a["username"]: a for a in doc["accounts"]}
    # the suggestion: the one client whose @ is the account's
    assert by["du7dev"]["match"] == {"id": du7["id"], "name": "Du7 Tech"}
    assert by["pautacc"]["match"] is None  # two clients say @pautacc
    assert by[""]["match"] is None  # no handle is nobody's, not every blank cadastro's
    assert "token" not in json.dumps(doc)

    # saying whose an account is, is an admin's too
    first = by["du7dev"]["ig_id"]
    assert assign(base, piero, first, du7["id"])[0] == 403
    status, doc, _ = assign(base, nato, first, du7["id"])
    assert status == 200
    assert {a["username"]: a["client_name"] for a in doc["accounts"]}["du7dev"] == "Du7 Tech"
    for bad in ({}, {"client": "1"}, {"client": True}):
        status, err, _ = call(f"{base}/api/instagram/accounts/{first}", bad, nato, "PATCH")
        assert status == 400 and err["error"].startswith("informe o cliente"), bad
    assert assign(base, nato, "17841000000000099", du7["id"])[0] == 404
    assert assign(base, nato, first, 999)[0] == 404
    status, doc, _ = assign(base, nato, first, None)
    assert status == 200 and all(a["client"] is None for a in doc["accounts"])
    assert assign(base, nato, first, du7["id"])[0] == 200

    # only an account that is not connected is removed; disconnecting is the admin's
    account, connection = (
        f"/api/instagram/accounts/{first}",
        f"/api/instagram/connections/{BUSINESS_ID}",
    )
    assert call(f"{base}{account}", cookie=nato, method="DELETE")[0] == 400
    assert call(f"{base}{connection}", cookie=piero, method="DELETE")[0] == 403
    status, doc, _ = call(f"{base}{connection}", cookie=nato, method="DELETE")
    assert status == 200 and doc["connections"] == [] and ig.expires_in(BUSINESS_ID) is None
    kept = {a["username"]: (a["client"], a["state"]) for a in doc["accounts"]}
    assert kept["du7dev"] == (du7["id"], "")  # still listed, still its client's, not connected
    assert call(f"{base}{connection}", cookie=nato, method="DELETE")[0] == 404
    assert call(f"{base}{account}", cookie=piero, method="DELETE")[0] == 403
    status, doc, _ = call(f"{base}{account}", cookie=nato, method="DELETE")
    assert status == 200 and len(doc["accounts"]) == 2
    assert call(f"{base}{account}", cookie=nato, method="DELETE")[0] == 404


def test_a_member_publishes_now_and_the_image_is_public_only_meanwhile(linked, fake_ig):
    base, _nato, piero, client = linked
    status, post = new_post(base, piero, client, alt_text="O logo da Du7")
    assert status == 200 and (post["status"], post["by_name"]) == ("draft", "Piero")
    assert "container" not in post
    token = post["media"]
    # the team sees the image; nobody else does, and not at the public address either
    status, headers, raw = get(f"{base}/api/posts/media/{token}", piero)
    assert (status, headers["Content-Type"], raw) == (200, "image/jpeg", jpeg())
    assert get(f"{base}/api/posts/media/{token}")[0] == 401
    assert get(f"{base}/api/media/{token}.jpg")[0] == 404

    status, out, _ = call(f"{base}/api/posts/{post['id']}/publish", {}, piero)
    assert status == 200 and out["status"] == "published", out
    assert out["permalink"] == f"https://www.instagram.com/p/{out['media_id']}/"
    assert out["published_at"] and out["error"] == ""
    # Instagram fetched the image itself, from the app's address, while the post was going out
    (fetch,) = fake_ig.fetched
    assert fetch["url"] == f"{base}/api/media/{token}.jpg"
    assert (fetch["status"], fetch["type"], fetch["magic"]) == (200, "image/jpeg", b"\xff\xd8\xff")
    (sent,) = fake_ig.published
    assert (sent["ig_id"], sent["caption"]) == (IG_ID, "Bom dia! #du7")
    assert sent["alt_text"] == "O logo da Du7"
    assert get(f"{base}/api/media/{token}.jpg")[0] == 404  # closed again

    # out is out: no second publish, no edit; removing it here leaves Instagram alone
    status, doc, _ = call(f"{base}/api/posts/{post['id']}/publish", {}, piero)
    assert (status, doc["error"]) == (400, "esta publicação já saiu ou está saindo")
    assert call(f"{base}/api/posts/{post['id']}", {"caption": "x"}, piero, method="PATCH")[0] == 400
    assert len(fake_ig.published) == 1
    assert call(f"{base}/api/posts/{post['id']}", cookie=piero, method="DELETE")[0] == 200
    assert call(f"{base}/api/publishing", cookie=piero)[1]["posts"] == []
    assert get(f"{base}/api/posts/media/{token}", piero)[0] == 404


def test_what_the_upload_and_the_post_refuse(linked):
    base, nato, piero, client = linked
    assert upload(base, piero, b"\x89PNG\r\n\x1a\n" + bytes(64)) == (
        400,
        {"error": "a imagem precisa ser JPEG"},
    )
    status, doc = upload(base, piero, jpeg(1080, 1920))
    assert status == 400 and "4:5" in doc["error"]
    status, doc = new_post(base, piero, client, caption="#a " * 31)
    assert (status, doc["error"]) == (400, "a legenda tem mais de 30 hashtags")
    status, doc = new_post(base, piero, client, status="scheduled")
    assert (status, doc["error"]) == (400, "escolha quando publicar")
    status, doc = new_post(base, piero, client, ig_id="17841000000000009")  # no such account
    assert (status, doc["error"]) == (400, NO_ACCOUNT_POST)
    # a draft is its author's or an admin's to remove
    _, post = new_post(base, nato, client)
    status, doc, _ = call(f"{base}/api/posts/{post['id']}", cookie=piero, method="DELETE")
    assert (status, doc["error"]) == (403, "só quem criou ou um administrador pode excluir")
    assert call(f"{base}/api/posts/{post['id']}", cookie=nato, method="DELETE")[0] == 200
    assert call(f"{base}/api/posts/999/publish", {}, piero)[0] == 404


def test_a_refusal_is_the_posts_state_and_it_can_go_again(linked, fake_ig, store):
    base, nato, piero, client = linked
    _, post = new_post(base, piero, client)
    fake_ig.at_limit = True
    status, out, _ = call(f"{base}/api/posts/{post['id']}/publish", {}, piero)
    assert status == 200 and out["status"] == "failed"
    assert out["error"] == (
        "este perfil atingiu o limite de publicações do Instagram nas últimas 24 horas"
    )
    assert fake_ig.published == []
    # a slow container is waited for; the second try goes out
    fake_ig.at_limit, fake_ig.not_ready = False, 3
    status, out, _ = call(f"{base}/api/posts/{post['id']}/publish", {}, piero)
    assert out["status"] == "published" and len(fake_ig.published) == 1

    # a token Instagram no longer takes marks the connection, for everyone to see
    _, post = new_post(base, piero, client)
    fake_ig.revoked = True
    out = call(f"{base}/api/posts/{post['id']}/publish", {}, piero)[1]
    assert out["status"] == "failed" and "conecte o perfil de novo" in out["error"]
    doc = call(f"{base}/api/publishing", cookie=nato)[1]
    assert doc["connections"][0]["state"] == "revoked"
    assert doc["posts"][0]["blocked"] == NO_PROFILE
    status, out, _ = call(f"{base}/api/posts/{post['id']}/publish", {}, piero)
    assert (status, out["error"]) == (400, "conecte o Instagram deste cliente primeiro")
    # connecting again clears it, and the failed post is still there to send
    fake_ig.revoked = False
    assert connect(base, nato) == OK
    assert call(f"{base}/api/publishing", cookie=nato)[1]["connections"][0]["state"] == "ok"
    out = call(f"{base}/api/posts/{post['id']}/publish", {}, piero)[1]
    assert out["status"] == "published"


def test_a_scheduled_post_leaves_at_its_time(linked, fake_ig, store, ig):
    base, _nato, piero, client = linked
    soon = datetime.now(UTC) + timedelta(hours=2)
    status, post = new_post(
        base, piero, client, status="scheduled", due=soon.isoformat().replace("+00:00", "Z")
    )
    assert status == 200 and post["status"] == "scheduled"
    assert post["due"] == soon.strftime("%Y-%m-%d %H:%M:%S")
    clock = {"now": datetime.now(UTC)}
    pub = Publisher(Posts(store), ig, base, clock=lambda: clock["now"])
    assert pub.tick() == [] and fake_ig.published == []  # not yet
    # moved an hour later, by its author
    later = soon + timedelta(hours=1)
    body = {"due": later.isoformat().replace("+00:00", "Z"), "caption": "Boa tarde!"}
    assert call(f"{base}/api/posts/{post['id']}", body, piero, method="PATCH")[0] == 200
    clock["now"] = soon + timedelta(minutes=1)
    assert pub.tick() == []
    clock["now"] = later + timedelta(seconds=5)
    (out,) = pub.tick()
    assert out["status"] == "published" and fake_ig.published[0]["caption"] == "Boa tarde!"
    assert pub.tick() == [] and len(fake_ig.published) == 1  # once

    # a portfolio disconnected after scheduling: the post is left as it is, and at its time
    # it fails with why
    _, second = new_post(
        base, piero, client, status="scheduled", due=later.isoformat().replace("+00:00", "Z")
    )
    assert Posts(store).remove_connection(BUSINESS_ID)
    listed = call(f"{base}/api/publishing", cookie=piero)[1]["posts"][0]
    assert (listed["id"], listed["status"], listed["blocked"]) == (
        second["id"],
        "scheduled",
        NO_PROFILE,
    )
    (out,) = pub.tick()
    assert (out["id"], out["status"], out["error"]) == (second["id"], "failed", NO_PROFILE)
    assert len(fake_ig.published) == 1


# ---- Stories and Reels ---------------------------------------------------------------------


def send(base, cookie, raw, ctype="image/jpeg", query=""):
    req = urllib.request.Request(
        f"{base}/api/posts/media{query}",
        data=raw,
        headers={"Content-Type": ctype, "Cookie": cookie},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def part(url, cookie, asked):
    req = urllib.request.Request(url, headers={"Cookie": cookie, "Range": asked})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.headers.get("Content-Range"), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Range"), e.read()


def a_minute_later(store, pid=None, **also):
    """Nobody looked at the waiting video for a minute (and, with `started`, it began then)."""
    sets = ", ".join(
        ["updated=datetime('now','-61 seconds')", *(f"{k}={v}" for k, v in also.items())]
    )
    with store.db() as db:
        db.execute(f"UPDATE post SET {sets} WHERE ? IS NULL OR id=?", (pid, pid))


def a_reel(base, cookie, client, raw=None, **over):
    status, media = send(base, cookie, mp4(30) if raw is None else raw, "video/mp4")
    assert status == 200, media
    body = {"ig_id": IG_ID, "media": media["media"], "kind": "reel", "caption": "Novo vídeo"}
    status, post, _ = call(f"{base}/api/posts", {**body, **over}, cookie)
    assert status == 200 and post["client"] == client, post
    return post


def test_a_story_is_a_tall_picture_and_no_caption(linked, fake_ig):
    base, _nato, piero, client = linked
    status, doc = send(base, piero, jpeg(1080, 1350), query="?kind=story")
    assert status == 400 and "9:16" in doc["error"]
    assert send(base, piero, jpeg(), query="?kind=carousel")[0] == 400
    status, media = send(base, piero, jpeg(1080, 1920), query="?kind=story")
    assert status == 200 and media["media_type"] == "image"
    body = {"ig_id": IG_ID, "media": media["media"], "kind": "story", "caption": "não vai"}
    status, post, _ = call(f"{base}/api/posts", body, piero)
    assert status == 200 and (post["kind"], post["caption"]) == ("story", "")
    status, out, _ = call(f"{base}/api/posts/{post['id']}/publish", {}, piero)
    assert status == 200 and out["status"] == "published", out
    (sent,) = fake_ig.published
    assert (sent["kind"], sent["video"], sent["caption"]) == ("STORIES", False, "")


def test_a_reel_is_a_video_published_when_instagram_is_done(linked, fake_ig, store, ig):
    base, _nato, piero, client = linked
    raw = mp4(30, pad=600_000)
    post = a_reel(base, piero, client, raw)
    assert (post["kind"], post["media_type"], post["status"]) == ("reel", "video", "draft")
    token = post["media"]
    # the team plays it: all of it, or the part a player asks for; nobody else gets any
    watch = f"{base}/api/posts/media/{token}"
    status, headers, body = get(watch, piero)
    assert (status, headers["Content-Type"], headers["Accept-Ranges"]) == (
        200,
        "video/mp4",
        "bytes",
    )
    assert body == raw
    size = len(raw)
    assert part(watch, piero, "bytes=0-99") == (206, f"bytes 0-99/{size}", raw[:100])
    assert part(watch, piero, "bytes=100-") == (206, f"bytes 100-{size - 1}/{size}", raw[100:])
    assert part(watch, piero, "bytes=-50") == (
        206,
        f"bytes {size - 50}-{size - 1}/{size}",
        raw[-50:],
    )
    assert part(watch, piero, f"bytes=5-{size * 2}")[1] == f"bytes 5-{size - 1}/{size}"
    assert part(watch, piero, f"bytes={size}-") == (416, f"bytes */{size}", b"")
    assert part(watch, piero, "bytes=-")[0] == 200 and part(watch, piero, "lines=1-2")[0] == 200
    assert get(watch)[0] == 401 and get(f"{base}/api/media/{token}.mp4")[0] == 404

    # Publicar agora: Instagram has it, and the answer does not wait for it
    fake_ig.not_ready = 2
    status, out, _ = call(f"{base}/api/posts/{post['id']}/publish", {}, piero)
    assert status == 200 and out["status"] == "publishing" and "container" not in out
    (fetch,) = fake_ig.fetched
    assert fetch["url"] == f"{base}/api/media/{token}.mp4"
    assert (fetch["status"], fetch["type"], fetch["video"]) == (200, "video/mp4", True)
    assert fake_ig.published == []
    # public while it is going out, under its own name only
    assert get(f"{base}/api/media/{token}.mp4")[0] == 200
    assert get(f"{base}/api/media/{token}.mov")[0] == 404
    assert get(f"{base}/api/media/{token}.jpg")[0] == 404
    status, doc, _ = call(f"{base}/api/posts/{post['id']}/publish", {}, piero)
    assert (status, doc["error"]) == (400, "esta publicação já saiu ou está saindo")
    status, doc, _ = call(f"{base}/api/posts/{post['id']}", cookie=piero, method="DELETE")
    assert status == 400 and "saindo agora" in doc["error"]

    # the publisher looks once a minute, and publishes when Instagram says it is ready
    pub = Publisher(Posts(store), ig, base)
    assert pub.tick() == []  # looked at a moment ago
    for _ in range(2):
        a_minute_later(store)
        (seen,) = pub.tick()
        assert seen["status"] == "publishing" and fake_ig.published == []
        assert pub.tick() == []
    a_minute_later(store)
    (done,) = pub.tick()
    assert done["status"] == "published" and done["permalink"].startswith("https://www.instagram")
    (sent,) = fake_ig.published
    assert (sent["kind"], sent["video"], sent["share_to_feed"]) == ("REELS", True, "true")
    assert sent["caption"] == "Novo vídeo"
    # out: closed again, and the video itself is gone from the server (it stays on the list)
    assert get(f"{base}/api/media/{token}.mp4")[0] == 404 and get(watch, piero)[0] == 404
    (listed,) = call(f"{base}/api/publishing", cookie=piero)[1]["posts"]
    assert (listed["status"], listed["kind"], listed["media_type"]) == (
        "published",
        "reel",
        "video",
    )
    assert pub.tick() == [] and len(fake_ig.published) == 1


def test_a_video_story_goes_the_same_way(linked, fake_ig, store, ig):
    base, _nato, piero, client = linked
    post = a_reel(base, piero, client, mp4(20), kind="story")
    assert (post["kind"], post["caption"]) == ("story", "")
    assert call(f"{base}/api/posts/{post['id']}/publish", {}, piero)[1]["status"] == "publishing"
    a_minute_later(store)
    (done,) = Publisher(Posts(store), ig, base).tick()
    assert done["status"] == "published"
    assert (fake_ig.published[0]["kind"], fake_ig.published[0]["video"]) == ("STORIES", True)


def test_a_video_that_does_not_come_out_fails_and_can_go_again(linked, fake_ig, store, ig):
    base, _nato, piero, client = linked
    post = a_reel(base, piero, client)
    pub = Publisher(Posts(store), ig, base)
    go = f"{base}/api/posts/{post['id']}/publish"
    watch = f"{base}/api/posts/media/{post['media']}"

    def ends(why: str):
        (out,) = pub.tick()
        assert out["status"] == "failed" and why in out["error"], out
        assert get(watch, piero)[0] == 200 and fake_ig.published == []  # still here to resend

    # Instagram cannot prepare it
    fake_ig.container_error = True
    assert call(go, {}, piero)[1]["status"] == "publishing"
    a_minute_later(store)
    ends("não conseguiu preparar o vídeo")
    fake_ig.container_error = False
    # Instagram never finishes
    fake_ig.not_ready = 99
    assert call(go, {}, piero)[1]["status"] == "publishing"
    a_minute_later(store, started="datetime('now','-16 minutes')")
    ends("demorou demais para preparar o vídeo")
    # the connection is lost while it waits
    assert call(go, {}, piero)[1]["status"] == "publishing"
    Posts(store).set_connection(BUSINESS_ID, state="revoked")
    a_minute_later(store)
    ends("conecte o Instagram")
    Posts(store).set_connection(BUSINESS_ID, state="ok")
    # Instagram is down for one look: the reason is on the post
    assert call(go, {}, piero)[1]["status"] == "publishing"
    fake_ig.down = True
    a_minute_later(store)
    (out,) = pub.tick()
    assert out["status"] == "failed" and out["error"]
    fake_ig.down = False
    # and then it goes
    fake_ig.not_ready = 0
    assert call(go, {}, piero)[1]["status"] == "publishing"
    a_minute_later(store)
    (out,) = pub.tick()
    assert out["status"] == "published" and len(fake_ig.published) == 1


def test_what_the_video_upload_and_its_post_refuse(linked, monkeypatch):
    base, _nato, piero, client = linked
    assert send(base, piero, jpeg(), "video/mp4") == (
        400,
        {"error": "o vídeo precisa ser MP4 ou MOV"},
    )
    status, doc = send(base, piero, mp4(2), "video/quicktime")
    assert status == 400 and "3 segundos" in doc["error"]
    status, doc = send(base, piero, mp4(16 * 60), "video/mp4")
    assert status == 400 and "15 minutos" in doc["error"]
    # a video sent as a picture is not one, whatever its name
    assert send(base, piero, mp4(30))[1] == {"error": "a imagem precisa ser JPEG"}
    limits = call(f"{base}/api/publishing", cookie=piero)[1]["limits"]
    assert limits == {"image_mb": 8, "video_mb": 300}
    status, media = send(base, piero, mp4(90), "video/mp4")
    assert status == 200 and media["seconds"] == 90
    body = {"ig_id": IG_ID, "media": media["media"]}
    for kind, why in (("feed", "Reel ou como Story"), ("story", "60 segundos")):
        status, doc, _ = call(f"{base}/api/posts", {**body, "kind": kind}, piero)
        assert status == 400 and why in doc["error"], doc
    assert call(f"{base}/api/posts", {**body, "kind": "reel"}, piero)[0] == 200
    monkeypatch.setattr("pauta.routes.publishing.MAX_VIDEO", 1000)
    status, doc = send(base, piero, mp4(30, pad=2000), "video/mp4")
    assert status == 413 and "o vídeo passa de" in doc["error"]


# ---- several accounts, whose they are, and what a change of that does to a post ------------


def z(when: datetime) -> str:
    return when.isoformat().replace("+00:00", "Z")


def test_one_client_two_accounts(team, fake_ig):
    base, nato, piero, _ = team
    client = call(f"{base}/api/clients", {"name": "Du7"}, nato)[1]["id"]
    fake_ig.accounts = [
        {"id": "17841000000000001", "username": "du7dev"},
        {"id": "17841000000000002", "username": "pautacc"},
    ]
    first, second = (a["id"] for a in fake_ig.accounts)
    assert connect(base, nato) == OK
    assert assign(base, nato, first, client)[0] == assign(base, nato, second, client)[0] == 200
    for ig_id, handle in ((second, "pautacc"), (first, "du7dev")):
        status, post = new_post(base, piero, client, ig_id=ig_id)
        assert status == 200 and (post["ig_id"], post["ig_username"]) == (ig_id, handle)
        out = call(f"{base}/api/posts/{post['id']}/publish", {}, piero)[1]
        assert out["status"] == "published", out
    # each went to the account it was made for
    assert [sent["ig_id"] for sent in fake_ig.published] == [second, first]


def test_a_post_whose_account_moved_is_refused_and_goes_out_when_it_is_back(
    linked, fake_ig, store, ig
):
    base, nato, piero, client = linked
    other = call(f"{base}/api/clients", {"name": "Outro"}, nato)[1]["id"]
    soon = datetime.now(UTC) + timedelta(hours=2)
    _, early = new_post(base, piero, client, status="scheduled", due=z(soon))
    _, late = new_post(base, piero, client, status="scheduled", due=z(soon + timedelta(hours=1)))
    _, draft = new_post(base, piero, client)
    reel = a_reel(base, piero, client)
    fake_ig.not_ready = 9  # Instagram is still preparing the video
    assert call(f"{base}/api/posts/{reel['id']}/publish", {}, piero)[1]["status"] == "publishing"

    assert assign(base, nato, IG_ID, other)[0] == 200  # the account is another client's now
    listed = {p["id"]: p for p in call(f"{base}/api/publishing", cookie=piero)[1]["posts"]}
    assert listed[early["id"]]["status"] == listed[late["id"]]["status"] == "scheduled"
    assert listed[draft["id"]]["blocked"] == listed[late["id"]]["blocked"] == MOVED
    body = {"status": "scheduled", "due": z(soon)}
    status, err, _ = call(f"{base}/api/posts/{draft['id']}", body, piero, "PATCH")
    assert (status, err["error"]) == (400, MOVED)
    status, err, _ = call(f"{base}/api/posts/{draft['id']}/publish", {}, piero)
    assert (status, err["error"]) == (400, MOVED)

    clock = {"now": soon + timedelta(seconds=5)}
    pub = Publisher(Posts(store), ig, base, clock=lambda: clock["now"])
    a_minute_later(store)
    ended = {p["id"]: p for p in pub.tick()}
    # the one whose time came, and the video that was waiting at Instagram: failed, with why
    assert set(ended) == {early["id"], reel["id"]}
    assert all((p["status"], p["error"]) == ("failed", MOVED) for p in ended.values())
    assert fake_ig.published == []

    assert assign(base, nato, IG_ID, client)[0] == 200  # put back before the other's time
    clock["now"] = soon + timedelta(hours=1, seconds=5)
    (out,) = pub.tick()
    assert (out["id"], out["status"]) == (late["id"], "published")
    assert len(fake_ig.published) == 1


def test_a_disconnect_keeps_the_accounts_and_their_clients(linked, fake_ig, store, ig):
    base, nato, piero, client = linked
    soon = datetime.now(UTC) + timedelta(hours=2)
    _, post = new_post(base, piero, client, status="scheduled", due=z(soon))
    connection = f"{base}/api/instagram/connections/{BUSINESS_ID}"
    status, doc, _ = call(connection, cookie=nato, method="DELETE")
    assert status == 200 and doc["connections"] == []
    (account,) = doc["accounts"]
    assert (account["client"], account["business_id"], account["state"]) == (client, "", "")
    (listed,) = doc["posts"]  # no post changed: it says why it will not go out
    assert (listed["status"], listed["blocked"]) == ("scheduled", NO_PROFILE)

    assert connect(base, nato) == OK  # the next login finds the account with its client
    doc = call(f"{base}/api/publishing", cookie=piero)[1]
    assert (doc["accounts"][0]["client"], doc["accounts"][0]["state"]) == (client, "ok")
    assert doc["posts"][0]["blocked"] == ""
    pub = Publisher(Posts(store), ig, base, clock=lambda: soon + timedelta(seconds=5))
    (out,) = pub.tick()
    assert (out["id"], out["status"]) == (post["id"], "published")
