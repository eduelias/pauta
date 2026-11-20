"""The fixes from the October 2026 security review: one test per way in that was closed."""

import contextlib
import json
import os
import socket
import sqlite3
import threading
import time
from urllib.parse import urlparse

import pytest

from fakemeta import fetch
from pauta import server as server_mod
from pauta.auth import Auth, AuthError
from pauta.db import SCHEMA_VERSION, Invalid, Store
from pauta.ratelimit import RateLimiter
from softpasskey import ORIGIN, RP_ID, SoftPasskey, call, join, login, start


@contextlib.contextmanager
def raw(path):
    """A plain connection that is committed and closed: sqlite3's own `with` only commits."""
    conn = sqlite3.connect(path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def send_raw(base, data: bytes, wait: float = 5) -> bytes:
    u = urlparse(base)
    with socket.create_connection((u.hostname, u.port), timeout=wait) as s:
        s.sendall(data)
        out = b""
        while chunk := s.recv(4096):
            out += chunk
    return out


# ---- sessions ------------------------------------------------------------------------------


def test_the_signing_key_is_not_in_the_database(store, auth):
    key = f"{store.path}.session-key"
    assert os.stat(key).st_mode & 0o777 == 0o600
    with raw(store.path) as db:
        assert not db.execute("SELECT 1 FROM meta WHERE key='session_secret'").fetchone()


def test_an_old_database_loses_its_key_and_everyone_signs_in_again(tmp_path):
    db = tmp_path / "pauta.db"
    Store(db)
    with raw(db) as conn:  # how 1.2 kept it
        conn.execute("INSERT INTO meta(key, value) VALUES ('session_secret', 'old-secret')")
    a = Auth(Store(db), enabled=True)
    assert a.secret != b"old-secret"
    with raw(db) as conn:
        assert not conn.execute("SELECT 1 FROM meta WHERE key='session_secret'").fetchone()


def test_a_damaged_key_file_stops_the_app(tmp_path):
    store = Store(tmp_path / "pauta.db")
    (tmp_path / "pauta.db.session-key").write_text("short\n")
    with pytest.raises(RuntimeError, match="too short"):
        Auth(store, enabled=True)


def test_logout_ends_the_session_on_every_device(team):
    base, nato, piero, _ = team
    assert call(f"{base}/api/requests", cookie=piero)[0] == 200
    status, _, headers = call(f"{base}/api/logout", {}, piero)
    assert status == 200 and "Max-Age=0" in headers["Set-Cookie"]
    assert call(f"{base}/api/requests", cookie=piero)[0] == 401  # a copied cookie is dead too
    assert call(f"{base}/api/requests", cookie=nato)[0] == 200


def test_reenabling_an_account_doesnt_revive_old_sessions(team):
    base, nato, piero, _ = team
    pid = call(f"{base}/api/me", cookie=piero)[1]["account"]
    for disabled in (True, False):
        status, _, _ = call(f"{base}/api/members/{pid}", {"disabled": disabled}, nato, "PATCH")
        assert status == 200
    assert call(f"{base}/api/requests", cookie=piero)[0] == 401


# ---- invites and passkeys ------------------------------------------------------------------


def test_a_single_use_invite_cant_be_raced(auth, store):
    token, _ = auth.create_invite(admin=True)
    tries = []
    for i in range(8):
        key = SoftPasskey()
        opts = auth.register_options(invite=token, name=f"Pessoa {i}")
        tries.append((opts["flow"], key.create(opts["options"])))
    joined, refused = [], []

    def go(flow, cred):
        try:
            joined.append(auth.register_verify(flow, cred))
        except AuthError:
            refused.append(flow)

    threads = [threading.Thread(target=go, args=t) for t in tries]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(joined) == 1 and len(refused) == 7
    with store.db() as db:
        assert db.execute("SELECT COUNT(*) FROM account").fetchone()[0] == 1
        assert tuple(db.execute("SELECT uses, max_uses FROM invite").fetchone()) == (1, 1)


class NoUserVerification(SoftPasskey):
    """A security key without a PIN: presence only."""

    def _auth_data(self, flags, attested=b""):
        return super()._auth_data(flags & ~0x04, attested)


def test_a_passkey_must_verify_the_person(site):
    base, auth, _ = site
    token, _ = auth.create_invite()
    status, doc, _ = join(base, token, "Ana", NoUserVerification())
    assert status == 400 and "não aceita" in doc["error"]
    token, _ = auth.create_invite()
    key = SoftPasskey()
    assert join(base, token, "Ana", key)[0] == 200
    lazy = NoUserVerification()
    lazy.key, lazy.cred_id, lazy.count = key.key, key.cred_id, key.count
    assert login(base, lazy)[0] == 400
    assert login(base, key)[0] == 200


@pytest.mark.parametrize("credential", [[1], "x", 7, None])
def test_malformed_passkey_answers_are_400_not_500(site, credential):
    base, _, _ = site
    for step in ("login", "register"):
        if step == "login":
            flow = call(f"{base}/api/passkey/login/options", {})[1]["flow"]
        else:
            token, _ = site[1].create_invite()
            body = {"invite": token, "name": "Ana"}
            flow = call(f"{base}/api/passkey/register/options", body)[1]["flow"]
        body = {"flow": flow, "credential": credential}
        assert call(f"{base}/api/passkey/{step}/verify", body)[0] == 400


# ---- admins and members --------------------------------------------------------------------


def test_admin_flags_must_be_true_or_false(team):
    base, nato, _, _ = team
    rid = call(f"{base}/api/me", cookie=nato)[1]["account"]
    for bad in (0, "0", "false", 1):
        status, doc, _ = call(f"{base}/api/members/{rid}", {"is_admin": bad}, nato, "PATCH")
        assert status == 400, bad
    assert call(f"{base}/api/me", cookie=nato)[1]["is_admin"]


def test_the_team_always_keeps_an_active_admin(store, auth):
    with store.db() as db:
        a = db.execute("INSERT INTO account(name, handle, is_admin) VALUES ('A','a',1)").lastrowid
        b = db.execute("INSERT INTO account(name, handle, is_admin) VALUES ('B','b',1)").lastrowid
    auth.set_member(b, is_admin=False, by=a)  # two admins: fine
    with pytest.raises(AuthError, match="pelo menos um"):
        auth.set_member(a, is_admin=False, by=b)  # b isn't admin any more, but the rule holds
    auth.set_member(b, is_admin=True, by=a)
    auth.set_member(a, disabled=True, by=b)
    with pytest.raises(AuthError, match="pelo menos um"):
        auth.set_member(b, is_admin=False, by=None)  # the CLI or a bug: still refused
    assert [m["is_admin"] for m in store.members() if m["id"] == b] == [1]


@pytest.mark.parametrize("change", [{"disabled": True}, {"is_admin": False}])
def test_links_end_when_the_admin_behind_them_is_disabled_or_demoted(team, change):
    base, nato, piero, _ = team
    token = call(f"{base}/api/invite", {"admin": True}, nato)[1]["path"].rsplit("/", 1)[1]
    _, ana, ana_cookie = join(base, token, "Ana", SoftPasskey())
    pid = call(f"{base}/api/me", cookie=piero)[1]["account"]
    invite = call(f"{base}/api/invite", {"admin": True, "uses": 5}, ana_cookie)[1]["path"]
    links = [f"{base}/api/invite/{invite.rsplit('/', 1)[1]}"]  # one she made, to join
    for member, by in ((pid, ana_cookie), (ana["account"], nato)):  # made by her, made for her
        url = call(f"{base}/api/members/{member}/move", {}, by)[1]["url"]
        links.append(f"{base}/api/move/{url.rsplit('/', 1)[1]}")
    kept = call(f"{base}/api/members/{pid}/move", {}, nato)[1]["url"].rsplit("/", 1)[1]
    assert [call(link)[0] for link in links] == [200, 200, 200]
    assert call(f"{base}/api/members/{ana['account']}", change, nato, "PATCH")[0] == 200
    assert [call(link)[0] for link in links] == [404, 404, 404]
    assert call(f"{base}/api/move/{kept}")[0] == 200  # nobody else's links are touched


def test_export_is_for_admins(team):
    base, nato, piero, _ = team
    assert call(f"{base}/api/export", cookie=piero)[0] == 403
    assert call(f"{base}/api/export", cookie=nato)[0] == 200


def test_nobody_can_look_like_someone_else(team, site):
    base, nato, piero, _ = team
    _, _, store = site
    for name in ("Renato Lima", "renato  lima", "Renáto Lima", "Renato​ Lima"):
        status, doc, _ = call(f"{base}/api/me", {"name": name}, piero, "PATCH")
        assert status == 400 and "nome" in doc["error"], name
    assert call(f"{base}/api/me", {"name": "Renato Lima"}, nato, "PATCH")[0] == 200  # own
    call(f"{base}/api/me", {"email": "Nato@Example.com"}, nato, "PATCH")
    status, doc, _ = call(f"{base}/api/me", {"email": "nato@example.com"}, piero, "PATCH")
    assert status == 400 and "e-mail" in doc["error"]
    status, me, _ = call(f"{base}/api/me", {"name": "Pi‮ero\x07"}, piero, "PATCH")
    assert status == 200 and me["name"] == "Piero"
    # and a new person can't join under a teammate's name
    token, _ = site[1].create_invite()
    status, doc, _ = join(base, token, "RENATO LIMA", SoftPasskey())
    assert status == 400 and "nome" in doc["error"]


def test_invite_options_are_checked(team):
    base, nato, _, _ = team
    for bad in ("abc", 1.5, True, [1]):
        assert call(f"{base}/api/invite", {"uses": bad}, nato)[0] == 400
    status, inv, _ = call(f"{base}/api/invite", {"admin": "yes", "uses": 2}, nato)
    token = inv["path"].rsplit("/", 1)[1]
    assert status == 200 and call(f"{base}/api/invite/{token}")[1]["admin"] is False


# ---- data ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "link", ["javascript:alert(1)", " JavaScript:x", "java\tscript:x", "data:text/html,x"]
)
def test_links_that_run_code_are_refused(store, link):
    for field in ("ads_page", "instagram"):
        with pytest.raises(Invalid, match="link"):
            store.save_client({"name": "Loja", field: link})
    c = store.save_client({"name": "Loja", "ads_page": "Biblioteca: ver no Drive"})
    assert c["ads_page"] == "Biblioteca: ver no Drive"


def test_hidden_characters_are_dropped(store):
    c = store.save_client({"name": "Lo‮ja\x00", "notes": "a\tb\nc⁦d\x1b"})
    assert c["name"] == "Loja" and c["notes"] == "a\tb\ncd"


def test_huge_ids_are_400_not_500(team):
    base, _, piero, _ = team
    cid = call(f"{base}/api/clients", {"name": "Loja"}, piero)[1]["id"]
    for field, value in (("client", "9" * 30), ("client", -1), ("assignee", 2**40)):
        body = {"client": cid, "what": "x", field: value}
        assert call(f"{base}/api/requests", body, piero)[0] == 400, field


def test_schema_v3_gets_session_generations(tmp_path):
    path = tmp_path / "old.db"
    with raw(path) as db:
        db.execute(
            "CREATE TABLE account (id INTEGER PRIMARY KEY, name TEXT NOT NULL, "
            "handle TEXT NOT NULL UNIQUE, email TEXT NOT NULL DEFAULT '', "
            "is_admin INTEGER NOT NULL DEFAULT 0, disabled INTEGER NOT NULL DEFAULT 0, "
            "created TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        db.execute("INSERT INTO account(name, handle) VALUES ('Ana', 'h')")
    store = Store(path)
    with store.db() as db:
        assert db.execute("SELECT session_gen FROM account").fetchone()[0] == 0
        assert db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0] == str(
            SCHEMA_VERSION
        )


# ---- HTTP ----------------------------------------------------------------------------------


def test_more_security_headers(site):
    base, _, _ = site
    _, _, headers = call(f"{base}/api/me")
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert "camera=()" in headers["Permissions-Policy"]


@pytest.mark.parametrize("length", ["-1", "abc", "1e3"])
def test_bad_content_length_is_400(site, length):
    base, _, _ = site
    head = (
        f"POST /api/passkey/login/options HTTP/1.0\r\nOrigin: {ORIGIN}\r\n"
        f"Content-Type: application/json\r\nContent-Length: {length}\r\n\r\n{{}}"
    )
    assert send_raw(base, head.encode()).startswith(b"HTTP/1.0 400")


def test_json_means_exactly_json(team):
    base, nato, _, _ = team
    sneaky = {"Content-Type": "text/plain; x=application/json"}
    assert call(f"{base}/api/clients", {"name": "X"}, nato, headers=sneaky)[0] == 415
    ok = {"Content-Type": "Application/JSON; charset=utf-8"}
    assert call(f"{base}/api/clients", {"name": "X"}, nato, headers=ok)[0] == 200


@pytest.fixture()
def tight(store, monkeypatch):
    monkeypatch.setattr(server_mod, "IDLE_SECONDS", 0.3)
    monkeypatch.setattr(server_mod, "MAX_CONNECTIONS", 1)
    httpd, base = start(store, Auth(store, enabled=True, rp_id=RP_ID, origins=[ORIGIN]))
    yield base
    httpd.shutdown()
    httpd.server_close()


def test_a_stalled_body_is_dropped(tight):
    head = (
        f"POST /api/logout HTTP/1.0\r\nOrigin: {ORIGIN}\r\n"
        "Content-Type: application/json\r\nContent-Length: 100\r\n\r\n{"
    )
    start_at = time.monotonic()
    reply = send_raw(tight, head.encode())
    assert reply.startswith(b"HTTP/1.0 408") and time.monotonic() - start_at < 3


def test_a_body_has_a_total_time_however_it_arrives(tight, monkeypatch):
    monkeypatch.setattr(server_mod, "BODY_SECONDS", 0.5)
    head = (
        f"POST /api/logout HTTP/1.0\r\nOrigin: {ORIGIN}\r\n"
        "Content-Type: application/json\r\nContent-Length: 100\r\n\r\n"
    )
    u = urlparse(tight)
    reply = b""
    with socket.create_connection((u.hostname, u.port), timeout=0.1) as s:
        s.sendall(head.encode())
        for _ in range(30):  # a byte every 0.1 s: the connection is never idle
            try:
                reply = s.recv(4096)
                break
            except TimeoutError:
                s.sendall(b" ")
    assert reply.startswith(b"HTTP/1.0 408")


def test_connections_are_capped(tight):
    u = urlparse(tight)
    hog = socket.create_connection((u.hostname, u.port))  # says nothing, holds the one slot
    try:
        time.sleep(0.1)
        assert send_raw(tight, b"GET /healthz HTTP/1.0\r\n\r\n").startswith(b"HTTP/1.0 503")
    finally:
        hog.close()
    time.sleep(0.5)  # the slot is free again
    reply = send_raw(tight, b"GET /healthz HTTP/1.0\r\n\r\n")
    assert reply.startswith(b"HTTP/1.0 200") and json.loads(reply.split(b"\r\n\r\n")[1])


def test_the_meta_callback_is_rate_limited(store, auth):
    """Meta's login lands here without a cookie, guarded by a one-time state alone: guesses
    from one address count against the login bucket."""
    httpd, base = start(store, auth, RateLimiter({"login": (2, 60)}))
    try:
        codes = [fetch(f"{base}/api/meta/callback?code=x&state=forged")[0] for _ in range(3)]
        assert codes == [302, 302, 429]
    finally:
        httpd.shutdown()
        httpd.server_close()
