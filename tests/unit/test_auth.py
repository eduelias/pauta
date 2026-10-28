"""Sessions, invites, passkey flows and account settings, without HTTP."""

import time

import pytest

from pauta import auth as auth_mod
from pauta.auth import COOKIE, Auth, AuthError
from pauta.db import Store
from softpasskey import SoftPasskey


def add_account(store, name="Ana", **cols):
    fields = {"name": name, "handle": f"h-{name}", **cols}
    with store.db() as conn:
        keys = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        return conn.execute(
            f"INSERT INTO account({keys}) VALUES ({marks})", tuple(fields.values())
        ).lastrowid


def cookie_value(set_cookie: str) -> str:
    return set_cookie.split(";")[0]


# ---- configuration -------------------------------------------------------------------------


def test_configuration_from_the_environment(store, monkeypatch):
    monkeypatch.setenv("PAUTA_AUTH", "passkeys")
    monkeypatch.setenv("PAUTA_RP_ID", "pauta.example")
    monkeypatch.setenv("PAUTA_ORIGIN", "https://pauta.example, https://alt.example ,")
    a = Auth(store)
    assert a.enabled and a.rp_id == "pauta.example"
    assert a.origins == ["https://pauta.example", "https://alt.example"]


def test_defaults_are_local_and_open(store, monkeypatch):
    for k in ("PAUTA_AUTH", "PAUTA_RP_ID", "PAUTA_ORIGIN"):
        monkeypatch.delenv(k, raising=False)
    a = Auth(store)
    assert not a.enabled and a.rp_id == "localhost" and a.origins == auth_mod.DEV_ORIGINS
    viewer = a.viewer(None)
    assert viewer["logged_in"] and viewer["is_admin"] and viewer["account"] is None


# ---- sessions ------------------------------------------------------------------------------


def test_cookie_round_trip_and_survives_a_restart(store, auth, tmp_path):
    aid = add_account(store)
    header = auth.make_cookie(aid, secure=True)
    assert "HttpOnly" in header and "SameSite=Strict" in header and header.endswith("Secure")
    assert "Secure" not in auth.make_cookie(aid, secure=False)
    cookie = cookie_value(header)
    assert auth.account_from_cookie(f"other=1; {cookie}")["id"] == aid
    again = Auth(Store(store.path), enabled=True)  # same DB: same signing secret
    assert again.account_from_cookie(cookie)["id"] == aid
    elsewhere = Auth(Store(tmp_path / "other.db"), enabled=True)
    assert elsewhere.account_from_cookie(cookie) is None


@pytest.mark.parametrize(
    "mangle",
    [
        lambda v: v[:-2] + "xx",  # signature
        lambda v: "9" + v,  # account id
        lambda v: v.replace("|", "", 1),  # shape
        lambda v: "",
    ],
)
def test_tampered_cookies_are_refused(store, auth, mangle):
    aid = add_account(store)
    value = cookie_value(auth.make_cookie(aid, secure=False)).split("=", 1)[1]
    assert auth.account_from_cookie(f"{COOKIE}={mangle(value)}") is None


def test_expired_and_disabled_sessions_end(store, auth, monkeypatch):
    aid = add_account(store)
    cookie = cookie_value(auth.make_cookie(aid, secure=False))
    later = time.time() + auth_mod.SESSION_DAYS * 86400 + 60
    monkeypatch.setattr(auth_mod.time, "time", lambda: later)
    assert auth.account_from_cookie(cookie) is None
    monkeypatch.undo()
    with store.db() as conn:
        conn.execute("UPDATE account SET disabled=1 WHERE id=?", (aid,))
    assert auth.account_from_cookie(cookie) is None
    assert auth.account_from_cookie(None) is None
    assert Auth.clear_cookie(secure=True).startswith(f"{COOKIE}=; Path=/; Max-Age=0")


def test_viewer_for_an_account(store, auth):
    aid = add_account(store, email="ana@example.com", is_admin=1)
    me = auth.viewer(cookie_value(auth.make_cookie(aid, secure=False)))
    assert me["logged_in"] and me["is_admin"] and me["name"] == "Ana"
    assert len(me["avatar"]) == 64 and me["email"] == "ana@example.com"
    assert auth.viewer("") == {**auth.viewer_for(None), "auth": True}


# ---- invites -------------------------------------------------------------------------------


def test_invites(store, auth):
    by = add_account(store, "Renato")
    token, expires = auth.create_invite(admin=True, uses=50, created_by=by)
    assert expires > time.time() + 6 * 86400
    info = auth.invite_info(token)
    assert info["admin"] and info["uses_left"] == 20 and info["invited_by"] == "Renato"
    assert auth.invite_info("nope") is None and auth.invite_info("") is None
    old, _ = auth.create_invite(days=-1)
    assert auth.invite_info(old) is None
    with store.db() as conn:  # only the hash is stored
        assert not conn.execute("SELECT 1 FROM invite WHERE token_hash=?", (token,)).fetchone()


def test_registration_needs_a_valid_invite_and_a_name(auth):
    with pytest.raises(AuthError, match="convite"):
        auth.register_options(invite="nope", name="Ana")
    token, _ = auth.create_invite()
    with pytest.raises(AuthError, match="nome"):
        auth.register_options(invite=token, name="   ")
    opts = auth.register_options(invite=token, name="  Ana   Lima ")
    assert opts["options"]["user"]["name"] == "Ana Lima"
    assert opts["options"]["authenticatorSelection"]["residentKey"] == "required"


def test_first_account_is_admin_and_invites_count_down(auth):
    token, _ = auth.create_invite(uses=2)
    accounts = []
    for name in ("Primeira", "Segunda"):
        opts = auth.register_options(invite=token, name=name)
        accounts.append(auth.register_verify(opts["flow"], SoftPasskey().create(opts["options"])))
    assert [a["is_admin"] for a in accounts] == [1, 0]
    assert auth.invite_info(token) is None  # both uses spent


def test_invite_used_up_between_options_and_verify(auth):
    token, _ = auth.create_invite()
    a = auth.register_options(invite=token, name="A")
    b = auth.register_options(invite=token, name="B")
    auth.register_verify(a["flow"], SoftPasskey().create(a["options"]))
    with pytest.raises(AuthError, match="convite"):
        auth.register_verify(b["flow"], SoftPasskey().create(b["options"]))


def test_adding_a_second_device(store, auth):
    token, _ = auth.create_invite()
    opts = auth.register_options(invite=token, name="Ana")
    first = SoftPasskey()
    acc = auth.register_verify(opts["flow"], first.create(opts["options"]))
    opts = auth.register_options(account=acc)
    excluded = [c["id"] for c in opts["options"]["excludeCredentials"]]
    assert len(excluded) == 1  # the browser won't make a duplicate on the same device
    auth.register_verify(opts["flow"], SoftPasskey().create(opts["options"]))
    assert store.members()[0]["passkeys"] == 2


# ---- flows and login -----------------------------------------------------------------------


def test_flows_are_single_use_kind_bound_and_expire(auth, monkeypatch):
    fid = auth.login_options()["flow"]
    with pytest.raises(AuthError):
        auth._take_flow(fid, "register")  # wrong kind; and it is now spent
    with pytest.raises(AuthError):
        auth._take_flow(fid, "login")
    fid = auth.login_options()["flow"]
    later = time.time() + auth_mod.FLOW_SECONDS + 1
    monkeypatch.setattr(auth_mod.time, "time", lambda: later)
    with pytest.raises(AuthError, match="expirou"):
        auth._take_flow(fid, "login")


def test_login(store, auth):
    token, _ = auth.create_invite()
    opts = auth.register_options(invite=token, name="Ana")
    key = SoftPasskey()
    acc = auth.register_verify(opts["flow"], key.create(opts["options"]))
    opts = auth.login_options()
    assert auth.login_verify(opts["flow"], key.get(opts["options"], ""))["id"] == acc["id"]
    assert store.members()[0]["last_seen"]
    opts = auth.login_options()
    with pytest.raises(AuthError, match="cadastrada"):
        auth.login_verify(opts["flow"], SoftPasskey().get(opts["options"], ""))
    opts = auth.login_options()
    bad = key.get(opts["options"], "")
    bad["response"]["signature"] = bad["response"]["signature"][::-1]
    with pytest.raises(AuthError, match="não aceita"):
        auth.login_verify(opts["flow"], bad)
    with store.db() as conn:
        conn.execute("UPDATE account SET disabled=1")
    opts = auth.login_options()
    with pytest.raises(AuthError, match="desativada"):
        auth.login_verify(opts["flow"], key.get(opts["options"], ""))


def test_garbage_registration_is_refused(auth):
    token, _ = auth.create_invite()
    opts = auth.register_options(invite=token, name="Ana")
    with pytest.raises(AuthError, match="não aceita"):
        auth.register_verify(opts["flow"], {"id": "x", "response": {}})


# ---- account settings ------------------------------------------------------------------------


def test_member_admin_rules(store, auth):
    admin, other = add_account(store, "Admin", is_admin=1), add_account(store, "Other")
    with pytest.raises(AuthError, match="si mesmo"):
        auth.set_member(admin, disabled=True, by=admin)
    with pytest.raises(AuthError, match="si mesmo"):
        auth.set_member(admin, is_admin=False, by=admin)
    with pytest.raises(AuthError, match="não encontrada"):
        auth.set_member(999, disabled=True, by=admin)
    auth.set_member(other, is_admin=True, by=admin)
    auth.set_member(other, disabled=True, by=admin)
    row = next(m for m in store.members() if m["id"] == other)
    assert row["is_admin"] == 1 and row["disabled"] == 1


def test_rename_and_email(store, auth):
    aid = add_account(store)
    auth.rename(aid, "  Ana   Paula " + "x" * 60)
    name = store.members()[0]["name"]
    assert name.startswith("Ana Paula x") and len(name) == 40
    with pytest.raises(AuthError):
        auth.rename(aid, "   ")
    for bad in ("nope", "a@b", "a b@c.d", "x@" + "y" * 260 + ".com"):
        with pytest.raises(AuthError, match="e-mail"):
            auth.set_email(aid, bad)
    auth.set_email(aid, " ana@example.com ")
    assert len(store.members()[0]["avatar"]) == 64
    auth.set_email(aid, "")
    assert store.members()[0]["avatar"] == ""
