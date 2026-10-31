"""The move to a new domain over HTTP (decision 4): the old address offers a one-time link,
the new one turns it into a passkey for the same account. An admin can make the link for
someone else."""

import pytest

from pauta.auth import Auth
from softpasskey import ORIGIN, SoftPasskey, call, start

NEW, OLD = "https://pauta.cc", "https://pauta.example"


@pytest.fixture()
def moving(store):
    auth = Auth(store, enabled=True, rp_id="pauta.cc,pauta.example", origins=[NEW, OLD])
    httpd, base = start(store, auth)
    yield base, auth
    httpd.shutdown()
    httpd.server_close()


def on(origin, cookie=None):
    """Headers of a page open on `origin` (browsers send Origin on every write)."""
    return {"headers": {"Origin": origin}, "cookie": cookie}


def ceremony(base, kind, body, key, origin):
    _, opts, _ = call(f"{base}/api/passkey/{kind}/options", body, **on(origin))
    if "flow" not in opts:
        return 400, opts, ""
    cred = key.create(opts["options"]) if kind == "register" else key.get(opts["options"], "")
    status, me, headers = call(
        f"{base}/api/passkey/{kind}/verify",
        {"flow": opts["flow"], "credential": cred},
        **on(origin),
    )
    return status, me, (headers.get("Set-Cookie") or "").split(";")[0]


def test_moving_from_the_old_address(moving):
    base, auth = moving
    token, _ = auth.create_invite(admin=True)
    old_key = SoftPasskey("pauta.example", OLD)
    status, me, old_cookie = ceremony(
        base, "register", {"invite": token, "name": "Renato"}, old_key, OLD
    )
    assert status == 200

    # the old address says where Pauta went; the new one knows it's home
    me = call(f"{base}/api/me", **on(OLD, old_cookie))[1]
    assert me["move"] == {"to": "pauta.cc", "url": NEW, "here": False, "done": False}
    assert call(f"{base}/api/me", **on(NEW))[1]["move"]["here"] is True
    assert call(f"{base}/api/boot", **on(OLD, old_cookie))[1]["me"]["move"]["done"] is False

    # the link is only made on the old address, for someone signed in
    assert call(f"{base}/api/move", {}, **on(OLD))[0] == 401
    status, err, _ = call(f"{base}/api/move", {}, **on(NEW, old_cookie))
    assert status == 400 and "já está em pauta.cc" in err["error"]
    status, link, _ = call(f"{base}/api/move", {}, **on(OLD, old_cookie))
    assert status == 200 and link["url"].startswith(f"{NEW}/#/mudar/")
    mtoken = link["url"].rsplit("/", 1)[1]
    assert call(f"{base}/api/move/{mtoken}")[1] == {"name": "Renato", "to": "pauta.cc"}

    # opened on the wrong address, the link says where to go
    status, err, _ = call(f"{base}/api/passkey/register/options", {"move": mtoken}, **on(OLD))
    assert status == 400 and "pauta.cc" in err["error"]

    new_key = SoftPasskey("pauta.cc", NEW)
    status, me, new_cookie = ceremony(base, "register", {"move": mtoken}, new_key, NEW)
    assert status == 200 and me["account"] == 1 and me["is_admin"] and new_cookie
    assert call(f"{base}/api/me", **on(NEW, new_cookie))[1]["move"]["done"] is True
    members = call(f"{base}/api/members", **on(NEW, new_cookie))[1]
    assert members[0]["domains"] == ["pauta.cc", "pauta.example"]

    # used up; and from now on the new passkey signs in on the new address
    assert call(f"{base}/api/move/{mtoken}")[0] == 404
    assert ceremony(base, "register", {"move": mtoken}, SoftPasskey("pauta.cc", NEW), NEW)[0] == 400
    status, me, _ = ceremony(base, "login", {}, new_key, NEW)
    assert status == 200 and me["name"] == "Renato"
    assert ceremony(base, "login", {}, old_key, NEW)[0] == 400  # the old one doesn't, there
    assert ceremony(base, "login", {}, old_key, OLD)[0] == 200  # but still does at home


def test_no_move_without_a_second_domain(team):
    base, nato, _piero, _key = team
    assert call(f"{base}/api/me", cookie=nato)[1]["move"] is None
    status, err, _ = call(f"{base}/api/move", {}, cookie=nato)
    assert status == 400 and "não está mudando" in err["error"]
    assert call(f"{base}/api/move/{'x' * 32}")[0] == 404


def test_an_admin_sends_someone_their_link(moving):
    base, auth = moving
    token, _ = auth.create_invite(admin=True)
    _, _, admin = ceremony(
        base, "register", {"invite": token, "name": "Edu"}, SoftPasskey("pauta.example", OLD), OLD
    )
    token, _ = auth.create_invite()
    _, piero, piero_cookie = ceremony(
        base, "register", {"invite": token, "name": "Piero"}, SoftPasskey("pauta.example", OLD), OLD
    )

    # admins only, for a real, active person
    assert (
        call(f"{base}/api/members/{piero['account']}/move", {}, **on(OLD, piero_cookie))[0] == 403
    )
    assert call(f"{base}/api/members/99/move", {}, **on(OLD, admin))[0] == 400

    # made on either address, it always points at the new one
    status, link, _ = call(f"{base}/api/members/{piero['account']}/move", {}, **on(OLD, admin))
    assert status == 200 and link["to"] == "pauta.cc" and link["url"].startswith(f"{NEW}/#/mudar/")
    mtoken = link["url"].rsplit("/", 1)[1]
    assert call(f"{base}/api/move/{mtoken}")[1] == {"name": "Piero", "to": "pauta.cc"}

    # Piero taps it in WhatsApp: no cookie on the new address, just a passkey
    status, me, cookie = ceremony(
        base, "register", {"move": mtoken}, SoftPasskey("pauta.cc", NEW), NEW
    )
    assert status == 200 and me["account"] == piero["account"] and not me["is_admin"] and cookie
    assert call(f"{base}/api/move/{mtoken}")[0] == 404


def test_admin_links_outlive_the_move(team, store):
    """With one domain the same link is the way back in after a lost phone."""
    base, nato, _piero, _key = team
    status, link, _ = call(f"{base}/api/members/2/move", {}, cookie=nato)
    assert status == 200 and link["url"].startswith(f"{ORIGIN}/#/mudar/")
    off = Auth(store, enabled=False)
    httpd, open_base = start(store, off)
    try:
        assert call(f"{open_base}/api/members/2/move", {})[0] == 400
    finally:
        httpd.shutdown()
        httpd.server_close()
