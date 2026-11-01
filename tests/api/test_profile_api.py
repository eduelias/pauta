"""Perfil over HTTP (decision 10): what a person may change about themselves, their passkeys
(label, remove while one stays, a link for a new phone), and what teammates never see."""

import json
import time

from pauta.auth import MOVE_SECONDS, Auth
from softpasskey import ORIGIN, SoftPasskey, call, join, login, start


def register_more(base, cookie, key):
    """A second passkey for the signed-in account, like "Adicionar passkey neste aparelho"."""
    _, opts, _ = call(f"{base}/api/passkey/register/options", {}, cookie)
    body = {"flow": opts["flow"], "credential": key.create(opts["options"])}
    return call(f"{base}/api/passkey/register/verify", body, cookie)[0]


def test_patch_me_takes_name_email_and_whatsapp(team):
    base, nato, piero, _ = team
    me = call(f"{base}/api/me", {"whatsapp": " +55 11 90000-0000 "}, nato, "PATCH")[1]
    assert me["whatsapp"] == "+55 11 90000-0000" and me["name"] == "Renato Lima"
    me = call(f"{base}/api/me", {"name": "Nato", "email": "r@example.com"}, nato, "PATCH")[1]
    assert (me["name"], me["email"]) == ("Nato", "r@example.com")
    assert me["whatsapp"] == "+55 11 90000-0000"
    assert call(f"{base}/api/me", cookie=nato)[1]["whatsapp"] == "+55 11 90000-0000"
    # the rules the old rename route had: a name, unique in the team; a real e-mail
    status, err, _ = call(f"{base}/api/me", {"name": "  "}, nato, "PATCH")
    assert status == 400 and err["error"] == "digite seu nome"
    status, err, _ = call(f"{base}/api/me", {"name": "piéro"}, nato, "PATCH")
    assert status == 400 and "já tem alguém" in err["error"]
    assert call(f"{base}/api/me", {"email": "nope"}, nato, "PATCH")[0] == 400
    status, me, _ = call(f"{base}/api/me", {"whatsapp": "9" * 60}, piero, "PATCH")
    assert status == 200 and len(me["whatsapp"]) == 40  # free text, cut like a client's
    assert call(f"{base}/api/me", {}, nato, "PATCH")[1]["name"] == "Nato"  # nothing to change


def test_the_number_is_the_persons_only_not_even_an_admins(team):
    base, nato, piero, _ = team
    call(f"{base}/api/me", {"whatsapp": "31600000000"}, piero, "PATCH")
    for cookie in (nato, piero):
        assert "whatsapp" not in json.dumps(call(f"{base}/api/members", cookie=cookie)[1])
        boot = call(f"{base}/api/boot", cookie=cookie)[1]
        assert "31600000000" not in json.dumps(boot["members"])
    assert call(f"{base}/api/me", cookie=piero)[1]["whatsapp"] == "31600000000"
    assert call(f"{base}/api/me", cookie=nato)[1]["whatsapp"] == ""  # the admin sees only his
    export = json.dumps(call(f"{base}/api/export", cookie=nato)[1])
    assert "31600000000" not in export  # the export has no account table either


def test_my_passkeys_label_remove_and_the_last_one_stays(team):
    base, nato, piero, nato_key = team
    keys = call(f"{base}/api/me/passkeys", cookie=nato)[1]
    assert len(keys) == 1 and keys[0]["label"] == "Este aparelho"  # urllib sends no device
    assert set(keys[0]) == {"id", "label", "transports", "rp_id", "created", "last_used"}
    assert "public_key" not in json.dumps(keys)
    first = keys[0]["id"]
    status, err, _ = call(f"{base}/api/me/passkeys/{first}", None, nato, "DELETE")
    assert status == 400 and "única passkey" in err["error"]

    assert register_more(base, nato, SoftPasskey()) == 200
    keys = call(f"{base}/api/me/passkeys", cookie=nato)[1]
    assert len(keys) == 2 and keys[0]["id"] == first
    status, keys, _ = call(f"{base}/api/me/passkeys/{first}", {"label": "iPhone"}, nato, "PATCH")
    assert status == 200 and [k["label"] for k in keys] == ["iPhone", "Este aparelho"]
    for bad in ({}, {"label": None}, {"label": 7}, {"label": ["x"]}):
        status, err, _ = call(f"{base}/api/me/passkeys/{first}", bad, nato, "PATCH")
        assert (status, err["error"]) == (400, "nome inválido"), bad

    # someone else's passkey is not found, for the label and for the removal
    piero_key = call(f"{base}/api/me/passkeys", cookie=piero)[1][0]["id"]
    assert call(f"{base}/api/me/passkeys/{piero_key}", {"label": "x"}, nato, "PATCH")[0] == 404
    assert call(f"{base}/api/me/passkeys/{piero_key}", None, nato, "DELETE")[0] == 404
    assert call(f"{base}/api/me/passkeys/{'x' * 20}", None, nato, "DELETE")[0] == 404
    assert call(f"{base}/api/me/passkeys/{first}", None, piero, "DELETE")[0] == 404
    assert call(f"{base}/api/me/passkeys/{'x' * 20}", None, None, "DELETE")[0] == 401

    # the phone that owns `first` is signed in too; removing its passkey signs it out at
    # once, while the laptop doing the removing gets a fresh cookie in the same answer
    status, _, phone = login(base, nato_key)
    assert status == 200 and phone.startswith("pauta_session=")  # same generation as nato's
    status, keys, headers = call(f"{base}/api/me/passkeys/{first}", None, nato, "DELETE")
    assert status == 200 and [k["label"] for k in keys] == ["Este aparelho"]
    fresh = (headers.get("Set-Cookie") or "").split(";")[0]
    assert fresh.startswith("pauta_session=") and fresh != nato
    assert "HttpOnly" in headers["Set-Cookie"] and "SameSite=Strict" in headers["Set-Cookie"]
    assert call(f"{base}/api/me/passkeys", cookie=phone)[0] == 401
    assert call(f"{base}/api/me/passkeys", cookie=nato)[0] == 401  # the old cookie too
    assert call(f"{base}/api/me", cookie=fresh)[1]["name"] == "Renato Lima"
    assert call(f"{base}/api/me", cookie=piero)[1]["name"] == "Piero"  # nobody else
    nato = fresh
    assert call(f"{base}/api/me/passkeys/{keys[0]['id']}", None, nato, "DELETE")[0] == 400
    members = call(f"{base}/api/members", cookie=piero)[1]
    assert next(m for m in members if m["name"] == "Renato Lima")["passkeys"] == 1
    # the removed passkey no longer signs in
    _, opts, _ = call(f"{base}/api/passkey/login/options", {})
    body = {"flow": opts["flow"], "credential": nato_key.get(opts["options"], "")}
    status, err, _ = call(f"{base}/api/passkey/login/verify", body)
    assert status == 400 and "não está cadastrada" in err["error"]
    # a refused removal (the last one) changes nothing: this cookie still works
    assert call(f"{base}/api/me", cookie=nato)[1]["name"] == "Renato Lima"


def test_my_own_new_passkey_link(team):
    base, nato, piero, _ = team
    status, link, _ = call(f"{base}/api/me/move", {}, piero)
    assert status == 200 and link["to"] == "localhost"
    assert time.time() + MOVE_SECONDS - 10 < link["expires"] <= time.time() + MOVE_SECONDS
    assert link["url"].startswith(f"{ORIGIN}/#/mudar/")
    token = link["url"].rsplit("/", 1)[1]
    assert call(f"{base}/api/move/{token}")[1] == {"name": "Piero", "to": "localhost"}
    # on the new phone: no cookie, one ceremony, same account, and the link is spent
    _, opts, _ = call(f"{base}/api/passkey/register/options", {"move": token})
    body = {"flow": opts["flow"], "credential": SoftPasskey().create(opts["options"])}
    status, me, headers = call(f"{base}/api/passkey/register/verify", body)
    assert status == 200 and me["name"] == "Piero" and not me["is_admin"]
    assert "pauta_session=" in (headers.get("Set-Cookie") or "")
    assert call(f"{base}/api/move/{token}")[0] == 404
    assert len(call(f"{base}/api/me/passkeys", cookie=piero)[1]) == 2
    assert call(f"{base}/api/me/move", {})[0] == 401


def test_my_own_link_dies_with_my_sessions_an_admins_does_not(team):
    """A self-made link is tied to the session that made it: "Sair em todos os aparelhos"
    (or a logout anywhere) expires it. The admin's 3-day link for the same person stays."""
    base, nato, piero, _ = team
    mine = call(f"{base}/api/me/move", {}, piero)[1]["url"].rsplit("/", 1)[1]
    status, theirs, _ = call(f"{base}/api/members/2/move", {}, nato)
    assert status == 200 and theirs["expires"] > time.time() + 2 * 86400
    theirs = theirs["url"].rsplit("/", 1)[1]
    assert call(f"{base}/api/move/{mine}")[0] == call(f"{base}/api/move/{theirs}")[0] == 200

    assert call(f"{base}/api/logout", {}, piero)[0] == 200
    assert call(f"{base}/api/me/passkeys", cookie=piero)[0] == 401
    assert call(f"{base}/api/move/{mine}")[0] == 404
    assert call(f"{base}/api/move/{theirs}")[1] == {"name": "Piero", "to": "localhost"}
    # nor can the dead link open a ceremony
    status, err, _ = call(f"{base}/api/passkey/register/options", {"move": mine})
    assert status == 400 and "expirou" in err["error"]


def test_open_mode_has_no_passkeys_to_manage(tmp_path):
    store = __import__("pauta.db", fromlist=["Store"]).Store(tmp_path / "pauta.db")
    httpd, base = start(store, Auth(store, enabled=False))
    try:
        assert call(f"{base}/api/me/passkeys")[1] == []
        assert call(f"{base}/api/me/passkeys/{'x' * 20}", {"label": "x"}, None, "PATCH")[0] == 400
        assert call(f"{base}/api/me/passkeys/{'x' * 20}", None, None, "DELETE")[0] == 400
        assert call(f"{base}/api/me/move", {})[0] == 400
        assert call(f"{base}/api/me", {"whatsapp": "1"}, None, "PATCH")[0] == 400
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_a_fresh_join_labels_the_passkey_after_the_browser(site):
    base, auth, _ = site
    token, _ = auth.create_invite(admin=True)
    _, opts, _ = call(f"{base}/api/passkey/register/options", {"invite": token, "name": "Lu"})
    body = {"flow": opts["flow"], "credential": SoftPasskey().create(opts["options"])}
    ua = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Safari/605"}
    status, _, headers = call(f"{base}/api/passkey/register/verify", body, headers=ua)
    cookie = (headers.get("Set-Cookie") or "").split(";")[0]
    assert status == 200
    assert [k["label"] for k in call(f"{base}/api/me/passkeys", cookie=cookie)[1]] == ["iPhone"]
    assert join  # the helper stays the way the other tests sign up
