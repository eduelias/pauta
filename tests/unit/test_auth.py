"""Sessions, invites, passkey flows and account settings, without HTTP."""

import sqlite3
import time

import pytest

from pauta import auth as auth_mod
from pauta.auth import COOKIE, Auth, AuthError, device_label
from pauta.db import SCHEMA_VERSION, STARTS, Invalid, NotFound, Store
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


def test_only_a_known_auth_mode_starts(store, monkeypatch):
    for word in ("", "open"):
        monkeypatch.setenv("PAUTA_AUTH", word)
        assert not Auth(store).enabled
    for word in ("passkey", "Passkeys", " passkeys", "on", "1"):
        monkeypatch.setenv("PAUTA_AUTH", word)
        with pytest.raises(RuntimeError, match="PAUTA_AUTH"):
            Auth(store)
    assert Auth(store, enabled=True).enabled  # the CLI's own commands don't read it


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
    auth.rename(aid, "x" * 39 + " y")  # the cut at 40 falls after a space
    assert store.members()[0]["name"] == "x" * 39
    with pytest.raises(AuthError):
        auth.rename(aid, "   ")
    for bad in ("nope", "a@b", "a b@c.d", "x@" + "y" * 260 + ".com"):
        with pytest.raises(AuthError, match="e-mail"):
            auth.set_email(aid, bad)
    auth.set_email(aid, " ana@example.com ")
    assert len(store.members()[0]["avatar"]) == 64
    auth.set_email(aid, "")
    assert store.members()[0]["avatar"] == ""


def test_whatsapp_is_free_text_like_a_clients(store, auth):
    aid = add_account(store)
    auth.set_whatsapp(aid, "  +55 (11)\t 9 0000-0000 \x07 ")
    assert auth.viewer_for(_account(store, aid))["whatsapp"] == "+55 (11) 9 0000-0000"
    auth.set_whatsapp(aid, "1" * 60)
    assert len(auth.viewer_for(_account(store, aid))["whatsapp"]) == 40
    auth.set_whatsapp(aid, None)
    assert auth.viewer_for(_account(store, aid))["whatsapp"] == ""
    assert auth_mod.OPEN_VIEWER["whatsapp"] == ""


def _account(store, aid):
    with store.db() as conn:
        return dict(conn.execute("SELECT * FROM account WHERE id=?", (aid,)).fetchone())


@pytest.mark.parametrize(
    ("ua", "transports", "label"),
    [
        ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)", "internal", "iPhone"),
        ("Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X)", "internal,hybrid", "iPad"),
        ("Mozilla/5.0 (Linux; Android 15; Pixel 9)", "internal", "Android"),
        ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", "internal", "Mac"),
        ("Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "", "Windows"),
        ("Mozilla/5.0 (X11; CrOS x86_64 14541.0.0)", "internal", "Chromebook"),
        ("Mozilla/5.0 (X11; Linux x86_64)", "internal", "Linux"),
        ("Mozilla/5.0 (Macintosh)", "hybrid", "Celular (pelo QR)"),  # a phone answered the QR
        ("Mozilla/5.0 (Windows NT 10.0)", "usb,nfc", "Chave de segurança"),
        ("", "", "Este aparelho"),
        (None, None, "Este aparelho"),
    ],
)
def test_a_passkeys_first_label_comes_from_the_device(ua, transports, label):
    assert device_label(ua, transports) == label


def test_passkeys_are_listed_labelled_and_removed_while_one_stays(store, auth):
    token, _ = auth.create_invite()
    opts = auth.register_options(invite=token, name="Ana")
    phone = SoftPasskey()
    acc = auth.register_verify(
        opts["flow"], phone.create(opts["options"]), user_agent="Mozilla/5.0 (iPhone; ...)"
    )
    opts = auth.register_options(account=acc)
    auth.register_verify(opts["flow"], SoftPasskey().create(opts["options"]))
    keys = auth.passkeys(acc["id"])
    assert [k["label"] for k in keys] == ["iPhone", "Este aparelho"]
    assert set(keys[0]) == {"id", "label", "transports", "rp_id", "created", "last_used"}
    assert keys[0]["transports"] == "internal" and keys[0]["last_used"] is None
    assert auth.passkeys(None) == []  # open mode

    auth.relabel_passkey(acc["id"], keys[1]["id"], "  Mac\u200b do   trabalho " + "x" * 50)
    assert auth.passkeys(acc["id"])[1]["label"].startswith("Mac do trabalho x")
    assert len(auth.passkeys(acc["id"])[1]["label"]) == 40
    with pytest.raises(NotFound):
        auth.relabel_passkey(acc["id"], "nope", "x")
    for bad in (None, 5, ["Mac"], {"label": "Mac"}):
        with pytest.raises(AuthError, match="nome inválido"):  # JSON that isn't a string
            auth.relabel_passkey(acc["id"], keys[1]["id"], bad)
    assert auth.passkeys(acc["id"])[1]["label"].startswith("Mac do trabalho x")
    other = add_account(store, "Bia")
    with pytest.raises(NotFound):  # someone else's passkey is not found, not forbidden
        auth.relabel_passkey(other, keys[0]["id"], "x")
    with pytest.raises(NotFound):
        auth.remove_passkey(other, keys[0]["id"])

    cookie = cookie_value(auth.make_cookie(acc["id"], secure=False))
    assert auth.account_from_cookie(cookie)["id"] == acc["id"]
    auth.remove_passkey(acc["id"], keys[0]["id"])
    assert [k["label"][:3] for k in auth.passkeys(acc["id"])] == ["Mac"]
    assert auth.account_from_cookie(cookie) is None  # every session ended with it
    cookie = cookie_value(auth.make_cookie(acc["id"], secure=False))
    with pytest.raises(AuthError, match="única passkey"):
        auth.remove_passkey(acc["id"], keys[1]["id"])
    assert auth.account_from_cookie(cookie)["id"] == acc["id"]  # a refusal ends nothing
    assert store.members()[0]["passkeys"] == 1


def test_a_passkey_for_a_domain_pauta_left_is_not_the_one_that_stays(store, auth):
    """After a move (decision 4) the old domain's passkeys linger on the account. They don't
    sign in anywhere any more, so they can't count as "another one" when the person removes
    the real last passkey; a leftover itself goes as long as a real one stays."""
    token, _ = auth.create_invite()
    opts = auth.register_options(invite=token, name="Ana")
    acc = auth.register_verify(opts["flow"], SoftPasskey().create(opts["options"]))
    for _ in range(2):
        opts = auth.register_options(account=acc)
        auth.register_verify(opts["flow"], SoftPasskey().create(opts["options"]))
    real, old1, old2 = [k["id"] for k in auth.passkeys(acc["id"])]
    with store.db() as db:
        db.execute("UPDATE passkey SET rp_id='pauta.example'")  # all from the domain we left
    for k in (real, old1, old2):
        with pytest.raises(AuthError, match="única passkey"):  # none would sign in after
            auth.remove_passkey(acc["id"], k)
    with store.db() as db:
        db.execute("UPDATE passkey SET rp_id='' WHERE id=?", (real,))  # as 1.5 made them
    with pytest.raises(AuthError, match="única passkey"):
        auth.remove_passkey(acc["id"], real)  # two would be left, neither of them usable
    auth.remove_passkey(acc["id"], old1)  # the leftovers go while the real one stays
    auth.remove_passkey(acc["id"], old2)
    assert [k["id"] for k in auth.passkeys(acc["id"])] == [real]
    with pytest.raises(AuthError, match="única passkey"):
        auth.remove_passkey(acc["id"], real)
    opts = auth.register_options(account=acc)
    auth.register_verify(opts["flow"], SoftPasskey().create(opts["options"]))  # on localhost
    auth.remove_passkey(acc["id"], real)
    assert [k["rp_id"] for k in auth.passkeys(acc["id"])] == ["localhost"]


def test_start_screen_is_one_of_the_screens_or_the_painel(store, auth):
    aid = add_account(store)
    assert auth.viewer_for(_account(store, aid))["start"] == ""  # the Painel, as always
    for screen in STARTS:
        auth.set_start(aid, f" {screen} ")
        assert auth.viewer_for(_account(store, aid))["start"] == screen
    for bad in ("painel", "configuracoes", "pedido/7", "Quadro", ["quadro"], 7):
        with pytest.raises(Invalid, match="valor inválido"):
            auth.set_start(aid, bad)
    assert auth.viewer_for(_account(store, aid))["start"] == STARTS[-1]  # a refusal changes nothing
    for painel in ("", None):
        auth.set_start(aid, "quadro")
        auth.set_start(aid, painel)
        assert auth.viewer_for(_account(store, aid))["start"] == ""
    assert auth_mod.OPEN_VIEWER["start"] == ""  # local mode has no accounts to keep it on
    assert auth.viewer_for(None)["start"] == ""


def test_schema_v14_gains_the_start_screen(tmp_path):
    """v15 adds the screen a person opens the app on; a v14 database (1.13.1) gets the
    column on open, every account on the Painel as before."""
    store = Store(tmp_path / "old.db")
    aid = add_account(store)
    conn = sqlite3.connect(tmp_path / "old.db")
    conn.executescript(
        "ALTER TABLE account DROP COLUMN start; UPDATE meta SET value='14' WHERE key='schema';"
    )
    conn.commit()
    conn.close()
    store = Store(tmp_path / "old.db")
    with store.db() as db:
        version = db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0]
        assert version == str(SCHEMA_VERSION)
    assert _account(store, aid)["start"] == ""
    Auth(store, enabled=True, rp_id="localhost", origins=["http://localhost"]).set_start(
        aid, "quadro"
    )
    assert _account(store, aid)["start"] == "quadro"
