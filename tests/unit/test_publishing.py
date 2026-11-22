"""Publicações' own rules (docs/publishing-spec.md): the image and caption checks, the
posts' states, and the Instagram client against the fake: connect, renew, publish, and what
each refusal becomes."""

import json
import logging
import sqlite3
import stat
import struct
from datetime import UTC, datetime, timedelta

import pytest

from fakeinstagram import BUSINESS_ID, IG_ID, SYSTEM_USER, USERNAME, jpeg, mp4
from pauta import instagram, publishing
from pauta.db import SCHEMA_VERSION, Invalid, NotFound, Store
from pauta.instagram import InstagramError, handle
from pauta.publishing import Posts, Publisher, publish

ORIGIN = "http://127.0.0.1:9"  # nothing listens: only tests that never fetch use it


@pytest.fixture()
def posts(store):
    return Posts(store)


@pytest.fixture()
def client(store):
    return store.save_client({"name": "Du7"})["id"]


PORTFOLIO = {"business_id": BUSINESS_ID, "business_name": "Du7 Portfólio"}
TWO = [
    {"ig_id": "17841000000000001", "username": "du7dev"},
    {"ig_id": "17841000000000002", "username": "pautacc"},
]


def login(ig, fake_ig, by=None):
    """The way through Meta's login, as the callback walks it: what `finish` gives."""
    import urllib.parse
    import urllib.request

    url = ig.start(by)
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert "prompt" not in query  # a session already open at Meta is used as it is
    state = query["state"][0]

    class Stop(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    try:
        urllib.request.build_opener(Stop).open(url)
    except urllib.error.HTTPError as e:
        back = e.headers["Location"]
    q = urllib.parse.parse_qs(urllib.parse.urlparse(back).query)
    assert q["state"] == [state] and back.endswith("#_=_")
    assert ig.take_state(state) == by
    return ig.finish(q["code"][0])


def connect(ig, fake_ig, posts, client, by=None):
    """What the callback does and then what an admin does: the login's portfolio and
    accounts are saved, and the first account is given to the client. The connection."""
    portfolio, accounts, expires = login(ig, fake_ig, by)
    posts.save_connection(portfolio, accounts, expires, by)
    posts.assign(accounts[0]["ig_id"], client, by)
    return next(n for n in posts.connections() if n["business_id"] == portfolio["business_id"])


def an_account(posts, client, connected=True):
    """The client's Instagram account without a login: for what never calls Instagram."""
    posts.save_connection(PORTFOLIO, [{"ig_id": IG_ID, "username": USERNAME}], None, None)
    posts.assign(IG_ID, client, None)
    if not connected:
        posts.remove_connection(BUSINESS_ID)


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
    conn = connect(ig_on, fake_ig, posts, client)
    assert (conn["business_id"], conn["business_name"]) == (BUSINESS_ID, "Du7 Portfólio")
    assert (conn["state"], conn["accounts"]) == ("ok", 1)
    (account,) = posts.accounts()
    assert (account["ig_id"], account["username"], account["state"]) == (IG_ID, USERNAME, "ok")
    assert account["client_name"] == "Du7"
    # a system-user token of a "never" configuration: no date to show, nothing to renew
    assert conn["expires"] is None and ig_on.expires_in(BUSINESS_ID) == timedelta.max
    kept = json.loads(ig_on.tokens_file.read_text())
    key = f"biz-{BUSINESS_ID}"  # one token for the portfolio, however many accounts
    assert set(kept) == {key} and kept[key]["token"] in fake_ig.tokens
    assert kept[key]["expires"] is None
    assert stat.S_IMODE(ig_on.tokens_file.stat().st_mode) == 0o600
    with store.db() as db:  # nothing of the token in the database
        dump = "\n".join(db.iterdump())
    assert kept[key]["token"] not in dump
    assert fake_ig.bad_proof == 0  # every call carried the app secret's proof
    ig_on.forget(BUSINESS_ID)
    assert ig_on.expires_in(BUSINESS_ID) is None


def test_a_state_is_used_once_and_a_code_too(ig_on, fake_ig, posts, client):
    ig_on.at(ORIGIN)
    with pytest.raises(InstagramError, match="venceu") as e:
        ig_on.take_state("nope")
    assert e.value.step == "state"
    with pytest.raises(InstagramError, match="não aceitou este pedido") as e:
        ig_on.finish("made-up-code")
    assert e.value.step == "code" and e.value.status == 400


def test_an_empty_login_brings_no_account(ig_on, fake_ig, posts, client):
    ig_on.at(ORIGIN)
    fake_ig.accounts = []  # the person shared no Instagram account
    with pytest.raises(InstagramError, match="nenhuma conta do Instagram") as e:
        connect(ig_on, fake_ig, posts, client)
    assert e.value.step == "me" and posts.connections() == [] and posts.accounts() == []
    assert not ig_on.tokens_file.exists()  # no token kept for a login that didn't count


def test_a_login_gives_the_portfolio_and_all_its_accounts(ig_on, fake_ig):
    """The token is the portfolio's system user, so it carries every account the business
    shared with the app, not only the one ticked on Meta's last screen."""
    ig_on.at(ORIGIN)
    fake_ig.accounts = [{"id": a["ig_id"], "username": a["username"]} for a in TWO]
    old = {a["ig_id"]: {"token": "from before connections"} for a in TWO}
    ig_on.tokens_file.write_text(json.dumps({**old, "999": {"token": "nobody's here"}}))
    portfolio, accounts, expires = login(ig_on, fake_ig)
    assert portfolio == PORTFOLIO and accounts == TWO and expires is None
    kept = json.loads(ig_on.tokens_file.read_text())
    # one token for the portfolio; the per-account ones it replaces are gone
    assert set(kept) == {f"biz-{BUSINESS_ID}", "999"}
    fake_ig.no_business_name = True  # the portfolio's name is a nicety
    assert login(ig_on, fake_ig)[0]["business_name"] == "Pauta System User"


def test_a_long_list_of_accounts_is_read_to_its_end(ig_on, fake_ig, monkeypatch):
    ig_on.at(ORIGIN)
    fake_ig.accounts = [{"id": str(17841000000000000 + i), "username": f"c{i}"} for i in range(230)]
    _, accounts, _ = login(ig_on, fake_ig)
    assert [a["username"] for a in accounts] == [f"c{i}" for i in range(230)]
    assert fake_ig.pages == 3  # a hundred at a time, by the cursor
    before = ig_on.tokens_file.read_text()
    # half a list would disconnect the accounts it missed: a page that fails is no login
    fake_ig.fail_page = 2
    with pytest.raises(InstagramError, match="não deu para falar") as e:
        login(ig_on, fake_ig)
    assert e.value.step == "accounts" and ig_on.tokens_file.read_text() == before
    fake_ig.fail_page = None
    monkeypatch.setattr(instagram, "ACCOUNT_PAGES", 1)  # and so is a list that does not end
    with pytest.raises(InstagramError, match="não deu para falar") as e:
        login(ig_on, fake_ig)
    assert e.value.step == "accounts" and ig_on.tokens_file.read_text() == before


def test_a_login_without_a_portfolio_id_is_keyed_by_its_system_user(ig_on, fake_ig):
    ig_on.at(ORIGIN)
    fake_ig.business_id = None
    portfolio, _, _ = login(ig_on, fake_ig)
    assert portfolio == {"business_id": SYSTEM_USER, "business_name": "Pauta System User"}
    assert set(json.loads(ig_on.tokens_file.read_text())) == {f"biz-{SYSTEM_USER}"}


def test_an_at_is_read_however_it_was_written():
    assert handle("@pautacc") == handle("pautacc") == "pautacc"
    assert handle("https://www.instagram.com/pautacc/") == "pautacc"
    assert handle(" Pauta.CC ") == "pauta.cc"
    assert handle("") == handle(None) == handle("not a handle!") == ""


def test_refusals_become_reasons_a_person_can_act_on(ig_on, fake_ig, posts, client):
    ig_on.at(ORIGIN)
    connect(ig_on, fake_ig, posts, client)
    fake_ig.fail_fetch = True
    with pytest.raises(InstagramError, match="não conseguiu baixar a imagem"):
        ig_on.create_container(BUSINESS_ID, IG_ID, "http://127.0.0.1:9/x.jpg", "oi")
    fake_ig.fail_fetch, fake_ig.not_professional = False, True
    with pytest.raises(InstagramError, match="precisa ser profissional"):
        ig_on.create_container(BUSINESS_ID, IG_ID, "http://127.0.0.1:9/x.jpg", "oi")
    fake_ig.not_professional = False
    fake_ig.revoked = True
    with pytest.raises(InstagramError, match="conecte o perfil de novo") as e:
        ig_on.create_container(BUSINESS_ID, IG_ID, "http://127.0.0.1:9/x.jpg", "oi")
    assert e.value.revoked and e.value.code == 190
    fake_ig.revoked, fake_ig.down = False, True
    with pytest.raises(InstagramError, match="não deu para falar") as e:
        ig_on.publish(BUSINESS_ID, IG_ID, "1")
    assert e.value.status == 503
    ig_on.forget(BUSINESS_ID)
    with pytest.raises(InstagramError, match="conecte o perfil de novo") as e:
        ig_on.publish(BUSINESS_ID, IG_ID, "1")
    assert e.value.revoked and e.value.step == "token"


# ---- posts ---------------------------------------------------------------------------------------


def draft(posts, client, **over):
    """A feed post for the client's account (`an_account` or `connect` first)."""
    media = posts.keep_media(jpeg())
    assert (media["width"], media["height"]) == (1080, 1350)
    post = posts.create({"ig_id": IG_ID, "media": media["media"], "caption": "Oi", **over}, None)
    assert post["client"] == client  # the account says whom a post is for
    return post


def test_a_draft_needs_an_account_with_a_client_and_an_image(posts, client):
    an_account(posts, client)
    p = draft(posts, client)
    assert (p["status"], p["due"], p["caption"], p["client_name"]) == ("draft", None, "Oi", "Du7")
    assert (p["ig_id"], p["ig_username"], p["blocked"]) == (IG_ID, USERNAME, "")
    assert (p["width"], p["height"]) == (1080, 1350)
    assert posts.media_path(p["media"]).read_bytes() == jpeg()
    with pytest.raises(Invalid, match="envie o arquivo de novo"):
        posts.create({"ig_id": IG_ID, "media": p["media"]}, None)  # one image, one post
    with pytest.raises(Invalid, match="envie o arquivo de novo"):
        posts.create({"ig_id": IG_ID, "media": "x" * 43}, None)
    fresh = posts.keep_media(jpeg())["media"]
    for nobody in ({}, {"ig_id": "17841000000000009"}, {"client": client}):
        with pytest.raises(Invalid, match="escolha a conta do Instagram"):
            posts.create({"media": fresh, **nobody}, None)
    posts.assign(IG_ID, None, None)  # an account with no client is nobody's yet
    with pytest.raises(Invalid, match="escolha a conta do Instagram"):
        posts.create({"ig_id": IG_ID, "media": fresh}, None)
    assert posts.media_path("../../etc/passwd") is None


def test_scheduling_needs_a_connected_account_and_a_moment(ig_on, fake_ig, posts, client):
    ig_on.at(ORIGIN)
    an_account(posts, client, connected=False)
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
    # disconnecting changes no post: it stays scheduled and says why it will not go out
    q = draft(posts, client, status="scheduled", due="2030-01-01T10:00:00Z")
    assert posts.remove_connection(BUSINESS_ID) and not posts.remove_connection(BUSINESS_ID)
    q = posts.post(q["id"])
    assert (q["status"], q["blocked"]) == ("scheduled", publishing.NO_PROFILE)
    (account,) = posts.accounts()  # and the account keeps its client for the next login
    assert (account["client"], account["business_id"], account["state"]) == (client, "", "")


def test_deleting_a_post_takes_its_image_and_orphans_are_swept(posts, client):
    an_account(posts, client)
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
    an_account(posts, client)
    p = draft(posts, client)
    assert posts.claim(p["id"])
    assert posts.fail_stuck() == 0  # it only just started
    assert posts.fail_stuck(older_than=-1) == 1
    p = posts.post(p["id"])
    assert p["status"] == "failed" and "confira no Instagram" in p["error"]


def test_publish_refuses_before_sending_what_a_person_can_fix(ig_on, fake_ig, posts, client):
    ig_on.at(ORIGIN)
    an_account(posts, client, connected=False)
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
    assert posts.connections()[0]["state"] == "ok"  # never expires
    fake_ig.expires_in = 3600
    assert connect(ig_on, fake_ig, posts, client)["expires"] is not None
    clock["now"] += timedelta(hours=7)  # past the hour it had, and due for the chores again
    pub.tick()
    n = posts.connections()[0]
    assert n["state"] == "expired" and n["error"] == "a conexão venceu"
    fake_ig.expires_in = None
    assert connect(ig_on, fake_ig, posts, client)["state"] == "ok"  # connecting again mends it
    ig_on.forget(BUSINESS_ID)
    clock["now"] += timedelta(hours=7)
    pub.tick()
    assert posts.connections()[0]["state"] == "expired"


# ---- kinds and video -----------------------------------------------------------------------


def reader(raw: bytes):
    """What the upload route hands keep_video: the next bytes of the body, on request."""
    left = [raw]

    def read(n: int) -> bytes:
        chunk, left[0] = left[0][:n], left[0][n:]
        return chunk

    return read


def video(posts, client, kind="reel", seconds=30, **over):
    raw = mp4(seconds)
    media = posts.keep_video(reader(raw), len(raw), "mp4")
    assert (media["media_type"], media["seconds"], media["bytes"]) == ("video", seconds, len(raw))
    body = {"ig_id": IG_ID, "media": media["media"], "caption": "Oi", "kind": kind, **over}
    post = posts.create(body, None)
    assert post["client"] == client
    return post


def test_a_videos_length_comes_from_its_own_header(tmp_path):
    path = tmp_path / "v.mp4"
    big = struct.pack(">I4sQ", 1, b"mdat", 16 + 40) + bytes(40)  # a box with a 64-bit size
    good = (
        (mp4(10), 10),
        (mp4(42.5, pad=5000, moov_last=True), 42.5),  # the index at the end, as phones write it
        (mp4(900, wide=True), 900),
        (mp4(7)[:28] + big + mp4(7)[28:], 7),
    )
    for raw, seconds in good:
        path.write_bytes(raw)
        assert publishing.video_seconds(path) == seconds
    to_the_end = struct.pack(">I4s", 0, b"mdat") + bytes(64)  # size 0: the rest of the file
    bad = (
        jpeg(),
        b"",
        mp4()[:40],  # cut short
        mp4()[28:],  # no `ftyp` first
        mp4().replace(b"mvhd", b"free"),  # an index that says nothing of time
        mp4().replace(b"moov", b"free"),
        mp4()[:28] + to_the_end,
        mp4()[:28] + struct.pack(">I4s", 4, b"moov"),  # a box smaller than its own header
        mp4()[:28] + struct.pack(">I4s", 8 + publishing.MOOV_MAX + 1, b"moov"),
    )
    for raw in bad:
        path.write_bytes(raw)
        with pytest.raises(Invalid, match="MP4 ou MOV"):
            publishing.video_seconds(path)
    zero = mp4(5).replace(struct.pack(">II", 1000, 5000), struct.pack(">II", 0, 5000))
    path.write_bytes(zero)  # no time scale: no length
    with pytest.raises(Invalid, match="MP4 ou MOV"):
        publishing.video_seconds(path)


def test_instagrams_rules_by_kind():
    assert publishing.check_image(jpeg(1080, 1920), "story") == (1080, 1920)
    with pytest.raises(Invalid, match="9:16"):
        publishing.check_image(jpeg(1080, 1350), "story")
    assert publishing.clean_kind(None) == "feed" and publishing.clean_kind("reel") == "reel"
    with pytest.raises(Invalid, match="Story ou é um Reel"):
        publishing.clean_kind("carousel")
    mb = 1024 * 1024
    publishing.check_video(3, mb, "story")
    publishing.check_video(60, 100 * mb, "story")
    publishing.check_video(15 * 60, 300 * mb, "reel")
    for seconds, size, kind, why in (
        (30, mb, "feed", "Reel ou como Story"),
        (2.9, mb, "reel", "pelo menos 3 segundos"),
        (61, mb, "story", "Story tem no máximo 60 segundos"),
        (30, 100 * mb + 1, "story", "Story tem no máximo 100 MB"),
        (15 * 60 + 1, mb, "reel", "Reel tem no máximo 15 minutos"),
        (30, 300 * mb + 1, "reel", "Reel tem no máximo 300 MB"),
    ):
        with pytest.raises(Invalid, match=why):
            publishing.check_video(seconds, size, kind)


def test_what_a_post_keeps_by_kind(posts, client):
    an_account(posts, client)
    tall = posts.keep_media(jpeg(1080, 1920), "story")
    body = {"ig_id": IG_ID, "media": tall["media"], "kind": "story"}
    story = posts.create({**body, "caption": "ninguém vê", "alt_text": "nem isto"}, None)
    assert (story["kind"], story["media_type"]) == ("story", "image")
    assert (story["caption"], story["alt_text"]) == ("", "")  # a Story has neither
    assert posts.update(story["id"], {"caption": "de novo", "alt_text": "x"})["caption"] == ""
    reel = video(posts, client, alt_text="só imagem do feed tem")
    assert (reel["kind"], reel["media_type"], reel["caption"]) == ("reel", "video", "Oi")
    assert (reel["alt_text"], reel["width"], reel["height"]) == ("", 0, 0)
    assert posts.update(reel["id"], {"alt_text": "x"})["alt_text"] == ""
    assert posts.media_path(reel["media"]).suffix == ".mp4"
    assert video(posts, client, kind="story", seconds=45)["kind"] == "story"
    assert draft(posts, client)["kind"] == "feed"  # what every post was before

    feed_picture = posts.keep_media(jpeg())["media"]
    for over, why in (
        ({"media": feed_picture, "kind": "reel"}, "um Reel precisa de um vídeo"),
        ({"media": feed_picture, "kind": "story"}, "9:16"),  # sent as a feed picture
        ({"media": feed_picture, "kind": "carousel"}, "Story ou é um Reel"),
    ):
        with pytest.raises(Invalid, match=why):
            posts.create({"ig_id": IG_ID, **over}, None)
    with pytest.raises(Invalid, match="Reel ou como Story"):
        video(posts, client, kind="feed")
    with pytest.raises(Invalid, match="60 segundos"):
        video(posts, client, kind="story", seconds=90)


def test_a_video_goes_straight_to_the_disk_or_is_not_kept(posts, monkeypatch):
    def kept() -> list[str]:
        return sorted(p.name for p in posts.media_dir.iterdir()) if posts.media_dir.is_dir() else []

    raw = mp4(20, pad=700_000)  # more than one read of it
    media = posts.keep_video(reader(raw), len(raw), "mov")
    assert posts.media_path(media["media"]).read_bytes() == raw
    assert kept() == [f"{media['media']}.mov"]
    for body, length, ext, why in (
        (raw[:1000], len(raw), "mp4", "parou no meio"),  # the upload stopped
        (jpeg(), len(jpeg()), "mp4", "MP4 ou MOV"),
        (mp4(2), len(mp4(2)), "mp4", "3 segundos"),
        (mp4(16 * 60), len(mp4(16 * 60)), "mp4", "15 minutos"),
        (raw, len(raw), "jpg", "300 MB"),  # not a video's name
        (raw, 0, "mp4", "300 MB"),
    ):
        with pytest.raises(Invalid, match=why):
            posts.keep_video(reader(body), length, ext)
    monkeypatch.setattr(publishing, "MAX_VIDEO", len(raw) - 1)
    with pytest.raises(Invalid, match="passa de"):
        posts.keep_video(reader(raw), len(raw), "mp4")
    assert kept() == [f"{media['media']}.mov"]  # nothing half-written stays
    # what a died upload left, and a video no post took, go with the other orphans
    (posts.media_dir / ".dead.123.tmp").write_bytes(b"x")
    assert posts.sweep_media(older_than=3600) == 0
    assert posts.sweep_media(older_than=-1) == 2 and kept() == []


def test_what_instagram_is_asked_for_each_kind(ig_on, fake_ig, posts, client):
    """Against the fake, which refuses what the real one does: a caption on a Story, a Reel
    that is a picture, a video with no kind."""
    ig_on.at(ORIGIN)
    connect(ig_on, fake_ig, posts, client)
    fake_ig.fail_fetch = True  # nothing listens at ORIGIN; the form is what is looked at here
    sent = []
    real = ig_on._post

    def spy(url, form, token=""):
        sent.append({k: v for k, v in form.items() if k != "appsecret_proof"})
        return real(url, form, token)

    ig_on._post = spy
    for args in (
        (f"{ORIGIN}/u.jpg", "Oi", "alt"),
        (f"{ORIGIN}/u.jpg", "Oi", "alt", "story"),
        (f"{ORIGIN}/u.mp4", "Oi", "alt", "story", True),
        (f"{ORIGIN}/u.mp4", "Oi", "alt", "reel", True),
    ):
        with pytest.raises(InstagramError, match="baixar"):
            ig_on.create_container(BUSINESS_ID, IG_ID, *args)
    jpg, clip = f"{ORIGIN}/u.jpg", f"{ORIGIN}/u.mp4"
    assert sent == [
        {"image_url": jpg, "caption": "Oi", "alt_text": "alt"},
        {"image_url": jpg, "media_type": "STORIES"},
        {"video_url": clip, "media_type": "STORIES"},
        {"video_url": clip, "caption": "Oi", "media_type": "REELS", "share_to_feed": "true"},
    ]


def test_a_video_waits_longer_before_it_counts_as_died(posts, client):
    an_account(posts, client)
    picture, reel = draft(posts, client), video(posts, client)
    assert posts.claim(picture["id"]) and posts.claim(reel["id"])
    with posts.store.db() as db:
        db.execute("UPDATE post SET started=datetime('now','-11 minutes')")
    assert posts.fail_stuck() == 1  # the picture: ten minutes is long for one
    assert posts.post(picture["id"])["status"] == "failed"
    assert posts.post(reel["id"])["status"] == "publishing"
    with posts.store.db() as db:
        db.execute("UPDATE post SET started=datetime('now','-31 minutes')")
    assert posts.fail_stuck() == 1
    assert "confira no Instagram" in posts.post(reel["id"])["error"]
    # nothing to look at: a post that is not waiting comes back as it is
    assert publishing.advance(posts, None, picture["id"])["status"] == "failed"


# ---- a portfolio's accounts, the client each is for, and whether a post can go out ----------


def test_an_account_goes_to_a_client_by_hand_and_can_move(store, posts, client, caplog):
    other = store.save_client({"name": "Outro"})["id"]
    posts.save_connection(PORTFOLIO, TWO, None, None)
    first = TWO[0]["ig_id"]
    assert [a["client"] for a in posts.accounts()] == [None, None]  # a login assigns nothing
    with caplog.at_level(logging.INFO, logger="pauta"):
        assert posts.assign(first, client, 7)["client_name"] == "Du7"
    said = [json.loads(r.getMessage()) for r in caplog.records]
    assert {"event": "ig_account_assigned", "account": 7, "ig": first, "client": client} in said
    media = posts.keep_media(jpeg())["media"]
    when = {"status": "scheduled", "due": "2030-01-01T10:00:00Z"}
    p = posts.create({"ig_id": first, "media": media, **when}, None)
    assert posts.assign(first, other, None)["client"] == other  # to another client
    assert posts.assign(first, None, None)["client"] is None  # to nobody
    now = posts.post(p["id"])  # and no post changed with it
    assert (now["status"], now["client"], now["ig_id"]) == ("scheduled", client, first)
    with pytest.raises(NotFound, match="conta do Instagram não encontrada"):
        posts.assign("1", client, None)
    with pytest.raises(NotFound, match="cliente não encontrado"):
        posts.assign(first, 999, None)


def test_why_a_post_cannot_go_out(store, posts, client):
    other = store.save_client({"name": "Outro"})["id"]
    posts.save_connection(PORTFOLIO, TWO, None, None)
    first = TWO[0]["ig_id"]
    posts.assign(first, client, None)
    p = posts.create({"ig_id": first, "media": posts.keep_media(jpeg())["media"]}, None)

    def blocked() -> str:
        return posts.post(p["id"])["blocked"]

    def schedule():
        return posts.update(p["id"], {"status": "scheduled", "due": "2030-01-01T10:00:00Z"})

    assert blocked() == ""
    for client_now in (other, None):  # another client's, or nobody's
        posts.assign(first, client_now, None)
        assert blocked() == publishing.MOVED
        with pytest.raises(Invalid, match="não é mais deste cliente"):
            schedule()
    posts.assign(first, client, None)
    posts.set_connection(BUSINESS_ID, state="revoked")
    assert blocked() == publishing.NO_PROFILE
    posts.set_connection(BUSINESS_ID, state="ok")
    assert blocked() == "" and schedule()["status"] == "scheduled"
    posts.remove_connection(BUSINESS_ID)  # no post changes: it says why instead
    now = posts.post(p["id"])
    assert (now["status"], now["blocked"]) == ("scheduled", publishing.NO_PROFILE)
    posts.remove_account(first, None)
    assert blocked() == publishing.NO_ACCOUNT_POST
    with posts.store.db() as db:
        db.execute("UPDATE post SET ig_id=''")  # as the upgrade leaves a post with no profile
    assert blocked() == publishing.NO_ACCOUNT_POST
    with pytest.raises(Invalid, match="escolha a conta do Instagram"):
        schedule()
    with posts.store.db() as db:
        db.execute("UPDATE post SET status='published'")
    assert blocked() == ""  # out is out


def test_a_posts_account_changes_only_within_its_client(store, posts, client):
    other = store.save_client({"name": "Outro"})["id"]
    third = {"ig_id": "17841000000000003", "username": "outro"}
    posts.save_connection(PORTFOLIO, [*TWO, third], None, None)
    first, second = (a["ig_id"] for a in TWO)
    posts.assign(first, client, None)
    posts.assign(second, client, None)
    posts.assign(third["ig_id"], other, None)
    p = posts.create({"ig_id": first, "media": posts.keep_media(jpeg())["media"]}, None)
    moved = posts.update(p["id"], {"ig_id": second})
    assert (moved["ig_id"], moved["ig_username"], moved["client"]) == (second, "pautacc", client)
    with pytest.raises(Invalid, match="não é mais deste cliente"):
        posts.update(p["id"], {"ig_id": third["ig_id"]})
    with pytest.raises(Invalid, match="escolha a conta do Instagram"):
        posts.update(p["id"], {"ig_id": "1"})
    assert posts.update(p["id"], {"ig_id": "", "caption": "Novo"})["ig_id"] == second
    assert posts.update(p["id"], {"caption": "De novo"})["ig_id"] == second


def test_an_account_a_login_no_longer_lists_is_not_connected(posts, client):
    posts.save_connection(PORTFOLIO, TWO, None, None)
    first, second = (a["ig_id"] for a in TWO)
    posts.assign(second, client, None)
    posts.save_connection(PORTFOLIO, TWO[:1], None, None)  # the next login: one of the two
    a, b = posts.account(first), posts.account(second)
    assert (a["business_id"], a["state"]) == (BUSINESS_ID, "ok")
    # the new token does not reach it: not connected, and still its client's
    assert (b["business_id"], b["state"], b["client"]) == ("", "", client)
    posts.save_connection(PORTFOLIO, TWO, None, None)  # listed again
    b = posts.account(second)
    assert (b["state"], b["client"]) == ("ok", client)


def test_the_last_login_takes_the_account(posts, client):
    first = TWO[0]["ig_id"]
    posts.save_connection(PORTFOLIO, TWO[:1], None, None)
    posts.assign(first, client, None)
    theirs = {"business_id": "3351000000000852", "business_name": "Do cliente"}
    posts.save_connection(theirs, TWO[:1], None, None)
    a = posts.account(first)
    assert (a["business_id"], a["client"]) == (theirs["business_id"], client)
    assert [(n["business_name"], n["accounts"]) for n in posts.connections()] == [
        ("Du7 Portfólio", 0),
        ("Do cliente", 1),
    ]


def test_only_an_unconnected_account_is_removed(posts, client):
    an_account(posts, client)
    p = draft(posts, client)
    with pytest.raises(Invalid, match="desconecte o portfólio"):
        posts.remove_account(IG_ID, None)
    with pytest.raises(NotFound):
        posts.remove_account("1", None)
    posts.remove_connection(BUSINESS_ID)
    posts.remove_account(IG_ID, None)
    assert posts.accounts() == []
    now = posts.post(p["id"])  # the post stays, with nowhere to go
    assert (now["ig_id"], now["ig_username"]) == (IG_ID, None)
    assert now["blocked"] == publishing.NO_ACCOUNT_POST


# ---- the upgrade to a portfolio's accounts (schema 17) ----------------------------------------


def v16_file(path):
    """The file as the release before schema 17 left it: two clients with a connected
    profile each, a third with none, and a post for each of the three."""
    store = Store(path)
    ids = [store.save_client({"name": name})["id"] for name in ("Um", "Dois", "Três")]
    conn = sqlite3.connect(path)
    conn.executescript(
        "DROP TABLE ig_account; DROP TABLE ig_connection; "
        "ALTER TABLE post DROP COLUMN ig_id; UPDATE meta SET value='16' WHERE key='schema';"
    )
    for cid, ig_id, name in ((ids[0], "17841400000000001", "um"), (ids[1], "178414002", "dois")):
        conn.execute(
            "INSERT INTO ig_profile(client, ig_id, username) VALUES (?,?,?)", (cid, ig_id, name)
        )
    for cid in ids:
        conn.execute("INSERT INTO post(client, media) VALUES (?, ?)", (cid, f"m{cid}"))
    conn.commit()
    conn.close()
    return ids


def rows(path, sql):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_the_upgrade_keeps_each_profiles_client_and_each_posts_account(tmp_path):
    path = tmp_path / "old.db"
    one, two, three = v16_file(path)
    Store(path)
    assert rows(path, "SELECT ig_id, username, business_id, client FROM ig_account ORDER BY 2") == [
        ("178414002", "dois", "", two),
        ("17841400000000001", "um", "", one),
    ]
    assert rows(path, "SELECT COUNT(*) FROM ig_connection") == [(0,)]  # the owner logs in once
    assert rows(path, "SELECT client, ig_id FROM post ORDER BY client") == [
        (one, "17841400000000001"),
        (two, "178414002"),
        (three, ""),  # its client had no profile: the post has no account
    ]
    # the release before this one publishes through these rows: now it sends nothing
    assert rows(path, "SELECT DISTINCT state FROM ig_profile") == [("expired",)]
    assert rows(path, "SELECT value FROM meta WHERE key='schema'") == [(str(SCHEMA_VERSION),)]


def test_the_upgrade_happens_once(tmp_path):
    path = tmp_path / "old.db"
    v16_file(path)
    Store(path)
    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM ig_account WHERE username='um'")
    conn.commit()
    conn.close()
    Store(path)  # a later start: what an admin removed is not copied back
    assert rows(path, "SELECT username FROM ig_account") == [("dois",)]


def test_an_upgrade_that_fails_leaves_the_file_as_it_was(tmp_path):
    path = tmp_path / "old.db"
    v16_file(path)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TRIGGER t BEFORE UPDATE ON ig_profile BEGIN SELECT RAISE(ABORT, 'no'); END"
    )
    conn.commit()
    conn.close()
    with pytest.raises(sqlite3.IntegrityError):
        Store(path)
    assert "ig_id" not in {r[1] for r in rows(path, "PRAGMA table_info(post)")}
    assert rows(path, "SELECT COUNT(*) FROM ig_account") == [(0,)]
    assert rows(path, "SELECT DISTINCT state FROM ig_profile") == [("ok",)]
    conn = sqlite3.connect(path)
    conn.execute("DROP TRIGGER t")
    conn.commit()
    conn.close()
    Store(path)  # the next start does all of it
    assert len(rows(path, "SELECT 1 FROM ig_account")) == 2
    assert rows(path, "SELECT DISTINCT state FROM ig_profile") == [("expired",)]


def test_the_export_has_the_connections_and_the_accounts(store):
    assert store.table("ig_connection") == [] and store.table("ig_account") == []
    with pytest.raises(Invalid):
        store.table("ig_profile")
