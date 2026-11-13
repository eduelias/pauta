"""Publicações' own rules (docs/publishing-spec.md): the image and caption checks, the
posts' states, and the Instagram client against the fake: connect, renew, publish, and what
each refusal becomes."""

import json
import stat
from datetime import UTC, datetime, timedelta

import pytest

from fakeinstagram import IG_ID, USERNAME, jpeg
from pauta import instagram, publishing
from pauta.db import Invalid, NotFound
from pauta.instagram import InstagramError
from pauta.publishing import Posts, Publisher, publish

ORIGIN = "http://127.0.0.1:9"  # nothing listens: only tests that never fetch use it


@pytest.fixture()
def posts(store):
    return Posts(store)


@pytest.fixture()
def client(store):
    return store.save_client({"name": "Du7"})["id"]


def connect(ig, fake_ig, posts, client, by=None):
    """What the callback does: the dialog's code, exchanged, saved for the client."""
    import urllib.parse
    import urllib.request

    url = ig.start(client, by)
    state = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]

    class Stop(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    try:
        urllib.request.build_opener(Stop).open(url)
    except urllib.error.HTTPError as e:
        back = e.headers["Location"]
    q = urllib.parse.parse_qs(urllib.parse.urlparse(back).query)
    assert q["state"] == [state] and back.endswith("#_=_")
    assert ig.take_state(state) == (client, by)
    who, expires = ig.finish(q["code"][0])
    return posts.save_profile(client, who, expires, by)


# ---- the image and the caption ---------------------------------------------------------------


def test_a_jpegs_size_comes_from_its_frame_header():
    assert publishing.jpeg_size(jpeg(1080, 1350)) == (1080, 1350)
    assert publishing.jpeg_size(jpeg(1440, 754)) == (1440, 754)
    with pytest.raises(Invalid, match="precisa ser JPEG"):
        publishing.jpeg_size(b"\x89PNG\r\n\x1a\n" + bytes(40))
    with pytest.raises(Invalid, match="tamanho da imagem"):
        publishing.jpeg_size(b"\xff\xd8\xff\xe0\x00\x10" + bytes(14))  # no frame header


def test_instagrams_rules_for_an_image():
    assert publishing.check_image(jpeg(1080, 1350)) == (1080, 1350)  # 4:5
    assert publishing.check_image(jpeg(1080, 566)) == (1080, 566)  # 1.91:1
    assert publishing.check_image(jpeg(1080, 1080)) == (1080, 1080)
    with pytest.raises(Invalid, match="4:5"):
        publishing.check_image(jpeg(1080, 1920))  # a story's shape
    with pytest.raises(Invalid, match="4:5"):
        publishing.check_image(jpeg(1600, 600))
    with pytest.raises(Invalid, match="320 px"):
        publishing.check_image(jpeg(300, 300))
    with pytest.raises(Invalid, match="8 MB"):
        publishing.check_image(jpeg(pad=publishing.MAX_IMAGE))
    with pytest.raises(Invalid, match="envie uma imagem"):
        publishing.check_image(b"")


def test_caption_limits_are_instagrams():
    assert publishing.clean_caption("  Olá\r\nmundo \x00 ") == "Olá\nmundo"
    assert publishing.clean_caption("#a " * 30).count("#") == 30
    with pytest.raises(Invalid, match="30 hashtags"):
        publishing.clean_caption("#a " * 31)
    with pytest.raises(Invalid, match="20 perfis"):
        publishing.clean_caption(" ".join(f"@p{i}" for i in range(21)))
    with pytest.raises(Invalid, match="2200"):
        publishing.clean_caption("x" * 2201)
    # an e-mail is not a mention, a # inside a word not a hashtag
    assert publishing.clean_caption("fale@du7.dev c#") == "fale@du7.dev c#"


def test_a_moment_is_kept_in_utc():
    assert publishing.clean_due("2026-11-13T09:30:00-03:00") == "2026-11-13 12:30:00"
    assert publishing.clean_due("2026-11-13T12:30:00.000Z") == "2026-11-13 12:30:00"
    assert publishing.clean_due("") is None
    with pytest.raises(Invalid, match="data de publicação"):
        publishing.clean_due("amanhã")


# ---- the Instagram client ----------------------------------------------------------------------


def test_off_without_the_app_id_the_configuration_or_the_secret(store, ig_on):
    assert ig_on.enabled
    assert not instagram.Instagram(store.path).enabled  # no app id
    assert not instagram.Instagram(store.path, app_id="1").enabled  # no configuration
    ig_on.secret_file.unlink()
    assert not ig_on.enabled


def test_connecting_keeps_the_token_out_of_the_database(store, ig_on, fake_ig, posts, client):
    ig_on.at(ORIGIN)
    profile = connect(ig_on, fake_ig, posts, client)
    assert (profile["ig_id"], profile["username"], profile["state"]) == (IG_ID, USERNAME, "ok")
    assert profile["client_name"] == "Du7"
    # a system-user token of a "never" configuration: no date to show, nothing to renew
    assert profile["expires"] is None and ig_on.expires_in(IG_ID) == timedelta.max
    kept = json.loads(ig_on.tokens_file.read_text())
    assert set(kept) == {IG_ID} and kept[IG_ID]["token"] in fake_ig.tokens
    assert kept[IG_ID]["expires"] is None
    assert stat.S_IMODE(ig_on.tokens_file.stat().st_mode) == 0o600
    with store.db() as db:  # nothing of the token in the database
        dump = "\n".join(db.iterdump())
    assert kept[IG_ID]["token"] not in dump
    assert fake_ig.bad_proof == 0  # every call carried the app secret's proof
    ig_on.forget(IG_ID)
    assert ig_on.expires_in(IG_ID) is None


def test_a_state_is_used_once_and_a_code_too(ig_on, fake_ig, posts, client):
    ig_on.at(ORIGIN)
    with pytest.raises(InstagramError, match="venceu") as e:
        ig_on.take_state("nope")
    assert e.value.step == "state"
    with pytest.raises(InstagramError, match="não aceitou este pedido") as e:
        ig_on.finish("made-up-code")
    assert e.value.step == "code" and e.value.status == 400


def test_the_login_must_bring_exactly_one_profile(ig_on, fake_ig, posts, client):
    ig_on.at(ORIGIN)
    fake_ig.accounts = []  # the person shared no Instagram account
    with pytest.raises(InstagramError, match="nenhum perfil do Instagram") as e:
        connect(ig_on, fake_ig, posts, client)
    assert e.value.step == "me" and posts.profile(client) is None
    fake_ig.accounts = [{"id": "1", "username": "a"}, {"id": "2", "username": "b"}]
    with pytest.raises(InstagramError, match="mais de um perfil"):
        connect(ig_on, fake_ig, posts, client)
    assert posts.profile(client) is None and json.loads("{}") == {}
    assert not ig_on.tokens_file.exists()  # no token was kept for a login that didn't count


def test_one_profile_serves_one_client(store, ig_on, fake_ig, posts, client):
    ig_on.at(ORIGIN)
    connect(ig_on, fake_ig, posts, client)
    other = store.save_client({"name": "Outro"})["id"]
    with pytest.raises(Invalid, match="já está ligado a Du7"):
        connect(ig_on, fake_ig, posts, other)
    with pytest.raises(NotFound):
        posts.save_profile(999, {"ig_id": "1"}, None, None)


def test_refusals_become_reasons_a_person_can_act_on(ig_on, fake_ig, posts, client):
    ig_on.at(ORIGIN)
    connect(ig_on, fake_ig, posts, client)
    fake_ig.fail_fetch = True
    with pytest.raises(InstagramError, match="não conseguiu baixar a imagem"):
        ig_on.create_container(IG_ID, "http://127.0.0.1:9/x.jpg", "oi")
    fake_ig.fail_fetch, fake_ig.not_professional = False, True
    with pytest.raises(InstagramError, match="precisa ser profissional"):
        ig_on.create_container(IG_ID, "http://127.0.0.1:9/x.jpg", "oi")
    fake_ig.not_professional = False
    fake_ig.revoked = True
    with pytest.raises(InstagramError, match="conecte o perfil de novo") as e:
        ig_on.create_container(IG_ID, "http://127.0.0.1:9/x.jpg", "oi")
    assert e.value.revoked and e.value.code == 190
    fake_ig.revoked, fake_ig.down = False, True
    with pytest.raises(InstagramError, match="não deu para falar") as e:
        ig_on.publish(IG_ID, "1")
    assert e.value.status == 503
    ig_on.forget(IG_ID)
    with pytest.raises(InstagramError, match="conecte o perfil de novo") as e:
        ig_on.publish(IG_ID, "1")
    assert e.value.revoked and e.value.step == "token"


# ---- posts ---------------------------------------------------------------------------------------


def draft(posts, client, **over):
    media = posts.keep_media(jpeg())
    assert (media["width"], media["height"]) == (1080, 1350)
    return posts.create({"client": client, "media": media["media"], "caption": "Oi", **over}, None)


def test_a_draft_needs_only_a_client_and_an_image(posts, client):
    p = draft(posts, client)
    assert (p["status"], p["due"], p["caption"], p["client_name"]) == ("draft", None, "Oi", "Du7")
    assert (p["width"], p["height"]) == (1080, 1350)
    assert posts.media_path(p["media"]).read_bytes() == jpeg()
    with pytest.raises(Invalid, match="envie a imagem de novo"):
        posts.create({"client": client, "media": p["media"]}, None)  # one image, one post
    with pytest.raises(Invalid, match="envie a imagem de novo"):
        posts.create({"client": client, "media": "x" * 43}, None)
    with pytest.raises(Invalid, match="escolha o cliente"):
        posts.create({"media": p["media"]}, None)
    assert posts.media_path("../../etc/passwd") is None


def test_scheduling_needs_a_connected_profile_and_a_moment(ig_on, fake_ig, posts, client):
    ig_on.at(ORIGIN)
    with pytest.raises(Invalid, match="conecte o Instagram"):
        draft(posts, client, status="scheduled", due="2030-01-01T10:00:00Z")
    connect(ig_on, fake_ig, posts, client)
    with pytest.raises(Invalid, match="escolha quando"):
        draft(posts, client, status="scheduled")
    p = draft(posts, client, status="scheduled", due="2030-01-01T10:00:00Z")
    assert (p["status"], p["due"]) == ("scheduled", "2030-01-01 10:00:00")
    assert p["ig_username"] == USERNAME
    assert posts.due("2029-12-31 23:59:59") == [] and posts.due("2030-01-01 10:00:00") == [p["id"]]
    # back to a draft; the caption changes; a published one no longer does
    p = posts.update(p["id"], {"status": "draft", "caption": "Novo"})
    assert (p["status"], p["caption"]) == ("draft", "Novo")
    assert posts.claim(p["id"]) and not posts.claim(p["id"])  # taken once
    with pytest.raises(Invalid, match="já saiu ou está saindo"):
        posts.update(p["id"], {"caption": "tarde"})
    with pytest.raises(Invalid, match="está saindo agora"):
        posts.delete(p["id"])
    # disconnecting sends what was scheduled back to drafts
    q = draft(posts, client, status="scheduled", due="2030-01-01T10:00:00Z")
    assert posts.remove_profile(client)["ig_id"] == IG_ID and posts.remove_profile(client) is None
    assert posts.post(q["id"])["status"] == "draft"


def test_deleting_a_post_takes_its_image_and_orphans_are_swept(posts, client):
    p = draft(posts, client)
    path = posts.media_path(p["media"])
    posts.delete(p["id"])
    assert not path.exists()
    with pytest.raises(NotFound):
        posts.post(p["id"])
    orphan = posts.keep_media(jpeg())["media"]
    kept = draft(posts, client)
    assert posts.sweep_media(older_than=3600) == 0  # fresh: someone may still be typing
    assert posts.sweep_media(older_than=-1) == 1
    assert posts.media_path(orphan) is None and posts.media_path(kept["media"])


def test_a_post_left_publishing_is_marked_unsure_not_retried(posts, client):
    p = draft(posts, client)
    assert posts.claim(p["id"])
    assert posts.fail_stuck() == 0  # it only just started
    assert posts.fail_stuck(older_than=-1) == 1
    p = posts.post(p["id"])
    assert p["status"] == "failed" and "confira no Instagram" in p["error"]


def test_publish_refuses_before_sending_what_a_person_can_fix(ig_on, fake_ig, posts, client):
    ig_on.at(ORIGIN)
    p = draft(posts, client)
    with pytest.raises(Invalid, match="conecte o Instagram"):
        publish(posts, ig_on, p["id"], ORIGIN)
    assert posts.post(p["id"])["status"] == "draft" and fake_ig.calls == []


def test_the_publisher_says_when_a_connection_lapsed(ig_on, fake_ig, posts, client):
    """A token that doesn't expire is left alone; one that does (a 60-day configuration) is
    said to have lapsed once it has, and one that is gone from the file too."""
    ig_on.at(ORIGIN)
    connect(ig_on, fake_ig, posts, client)
    clock = {"now": datetime.now(UTC)}
    pub = Publisher(posts, ig_on, ORIGIN, clock=lambda: clock["now"])
    clock["now"] += timedelta(days=400)
    pub.tick()
    assert posts.profile(client)["state"] == "ok"  # never expires
    fake_ig.expires_in = 3600
    assert connect(ig_on, fake_ig, posts, client)["expires"] is not None
    clock["now"] += timedelta(hours=7)  # past the hour it had, and due for the chores again
    pub.tick()
    p = posts.profile(client)
    assert p["state"] == "expired" and p["error"] == "a conexão venceu"
