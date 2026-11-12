"""Publicações over the API (docs/publishing-spec.md): off without the Instagram app; an
admin connects a client's profile through Instagram's login; a post is one JPEG and a
caption, published now or at its time; the image is public only while Instagram fetches it."""

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

import pytest

from fakeinstagram import IG_ID, USERNAME, jpeg
from pauta.publishing import Posts, Publisher
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


def connect(base, admin, client):
    """The admin's way through Instagram's login, as the browser walks it."""
    status, doc, _ = call(f"{base}/api/clients/{client}/instagram", {}, admin)
    assert status == 200, doc
    status, back = follow(doc["url"])
    assert status == 302 and back.startswith(f"{base}/api/instagram/callback?")
    # the browser drops the "#_" before asking, and comes without the session cookie
    return follow(back.split("#")[0])


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
    """Renato (admin), Piero (member) and a client with its Instagram connected."""
    base, nato, piero, _ = team
    client = call(f"{base}/api/clients", {"name": "Du7"}, nato)[1]["id"]
    assert connect(base, nato, client) == (302, "/#/publicacoes?ig=ok")
    return base, nato, piero, client


def new_post(base, cookie, client, **over):
    status, media = upload(base, cookie)
    assert status == 200, media
    body = {"client": client, "media": media["media"], "caption": "Bom dia! #du7", **over}
    status, post, _ = call(f"{base}/api/posts", body, cookie)
    return status, post


def test_off_without_the_instagram_app(team, ig, store):
    base, nato, _piero, _ = team
    ig.secret_file.unlink()
    assert call(f"{base}/api/boot", cookie=nato)[1]["publishing"] == {"enabled": False}
    assert call(f"{base}/api/publishing", cookie=nato)[1] == {
        "enabled": False,
        "profiles": [],
        "posts": [],
    }
    client = call(f"{base}/api/clients", {"name": "Du7"}, nato)[1]["id"]
    for path, body in (
        (f"/api/clients/{client}/instagram", {}),
        ("/api/posts", {"client": client}),
        ("/api/posts/1/publish", {}),
    ):
        status, doc, _ = call(f"{base}{path}", body, nato)
        assert (status, doc["error"]) == (404, "as publicações não estão ligadas neste servidor")
    assert upload(base, nato)[0] == 404


def test_an_admin_connects_a_clients_profile(team, fake_ig, ig):
    base, nato, piero, _ = team
    assert call(f"{base}/api/boot", cookie=piero)[1]["publishing"] == {"enabled": True}
    client = call(f"{base}/api/clients", {"name": "Du7"}, nato)[1]["id"]
    # the profile is the team's to connect, by an admin; a stranger gets nothing
    assert call(f"{base}/api/clients/{client}/instagram", {}, piero)[0] == 403
    assert call(f"{base}/api/clients/{client}/instagram", {})[0] == 401
    assert call(f"{base}/api/clients/999/instagram", {}, nato)[0] == 404
    assert call(f"{base}/api/publishing")[0] == 401

    # cancelled in Instagram's dialog, then a callback nobody started
    fake_ig.deny = True
    assert connect(base, nato, client) == (302, "/#/publicacoes?ig=erro&motivo=cancelado")
    fake_ig.deny = False
    status, back = follow(f"{base}/api/instagram/callback?code=x&state={'s' * 43}")
    assert (status, back) == (302, "/#/publicacoes?ig=erro&motivo=vencido")

    assert connect(base, nato, client) == (302, "/#/publicacoes?ig=ok")
    doc = call(f"{base}/api/publishing", cookie=piero)[1]
    (profile,) = doc["profiles"]
    assert (profile["client"], profile["ig_id"], profile["username"]) == (client, IG_ID, USERNAME)
    assert (profile["state"], profile["by_name"]) == ("ok", "Renato Lima")
    assert "token" not in json.dumps(doc)

    # the same profile for a second client is refused, and the first stays as it was
    other = call(f"{base}/api/clients", {"name": "Outro"}, nato)[1]["id"]
    assert connect(base, nato, other) == (302, "/#/publicacoes?ig=erro&motivo=perfil")
    assert len(call(f"{base}/api/publishing", cookie=nato)[1]["profiles"]) == 1
    assert ig.expires_in(IG_ID) is not None  # the first client's connection still works

    # disconnecting is the admin's too
    assert call(f"{base}/api/clients/{client}/instagram", cookie=piero, method="DELETE")[0] == 403
    status, doc, _ = call(f"{base}/api/clients/{client}/instagram", cookie=nato, method="DELETE")
    assert status == 200 and doc["profiles"] == [] and ig.expires_in(IG_ID) is None
    assert call(f"{base}/api/clients/{client}/instagram", cookie=nato, method="DELETE")[0] == 404


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
    status, doc = new_post(base, piero, 999)
    assert status == 404
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

    # a token Instagram no longer takes marks the profile, for everyone to see
    _, post = new_post(base, piero, client)
    fake_ig.revoked = True
    out = call(f"{base}/api/posts/{post['id']}/publish", {}, piero)[1]
    assert out["status"] == "failed" and "conecte o perfil de novo" in out["error"]
    doc = call(f"{base}/api/publishing", cookie=nato)[1]
    assert doc["profiles"][0]["state"] == "revoked"
    status, out, _ = call(f"{base}/api/posts/{post['id']}/publish", {}, piero)
    assert (status, out["error"]) == (400, "conecte o Instagram deste cliente primeiro")
    # connecting again clears it, and the failed post is still there to send
    fake_ig.revoked = False
    assert connect(base, nato, client) == (302, "/#/publicacoes?ig=ok")
    assert call(f"{base}/api/publishing", cookie=nato)[1]["profiles"][0]["state"] == "ok"
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

    # a profile disconnected after scheduling: the post waits as a draft, nothing is sent
    _, second = new_post(
        base, piero, client, status="scheduled", due=later.isoformat().replace("+00:00", "Z")
    )
    Posts(store).remove_profile(client)
    assert pub.tick() == []
    assert call(f"{base}/api/publishing", cookie=piero)[1]["posts"][0]["status"] == "draft"
    assert second["id"] and len(fake_ig.published) == 1
