"""The API over real HTTP: invites, passkeys, clients, requests and their timeline."""

import hashlib
import json
import sqlite3
import urllib.request

from pauta.auth import Auth
from pauta.db import Store
from softpasskey import ORIGIN, SoftPasskey, call, join, login, start


def test_anonymous_sees_nothing(site):
    base, _, _ = site
    assert call(f"{base}/api/me")[1]["logged_in"] is False
    for path in ("/api/requests", "/api/clients", "/api/boot", "/api/members", "/api/export"):
        assert call(f"{base}{path}")[0] == 401
    assert call(f"{base}/api/clients", {"name": "X"})[0] == 401
    with urllib.request.urlopen(f"{base}/") as r:  # the shell is public: it shows the login
        assert r.status == 200 and b"app.js" in r.read()
        assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]


def test_invites_are_single_use_and_admin_only(team, site):
    base, nato, piero, _ = team
    _, auth, _ = site
    assert call(f"{base}/api/invite", {}, piero)[0] == 403
    token, _ = auth.create_invite()
    assert join(base, token, "Ana", SoftPasskey())[0] == 200
    assert join(base, token, "Mallory", SoftPasskey())[0] == 400
    assert call(f"{base}/api/invite/{token}")[0] == 404


def test_login_with_passkey(team):
    base, _, _, nato_key = team
    status, me, cookie = login(base, nato_key)
    assert status == 200 and me["name"] == "Renato Lima" and cookie.startswith("pauta_session=")
    assert call(f"{base}/api/me", cookie=cookie)[1]["logged_in"]
    assert login(base, SoftPasskey())[0] == 400  # unknown passkey


def test_request_flow(team):
    base, nato, piero, _ = team
    status, c, _ = call(
        f"{base}/api/clients",
        {"name": "Clínica Bem Estar", "segment": "Estética", "instagram": "@bemestar"},
        nato,
    )
    assert status == 200 and c["state"] == "Ativo" and c["access"] == "Pendente"
    assert call(f"{base}/api/clients", {"name": "clínica bem estar"}, nato)[0] == 400  # dup
    body = {
        "client": c["id"],
        "kind": "Criar campanha",
        "what": "Limpeza de pele -20%",
        "budget": "1.500,00",
        "due": "2026-11-05",
        "priority": "Alta",
        "creatives_url": "drive.google.com/x",
    }
    status, r, _ = call(f"{base}/api/requests", body, nato)
    assert status == 200 and r["status"] == "todo" and r["budget"] == 1500.0
    assert r["creatives_url"] == "https://drive.google.com/x"
    assert r["created_by_name"] == "Renato Lima" and r["client_name"] == "Clínica Bem Estar"
    # Piero picks it up, then waits on Renato
    status, r, _ = call(f"{base}/api/requests/{r['id']}", {"status": "doing"}, piero, "PATCH")
    assert status == 200
    r = call(
        f"{base}/api/requests/{r['id']}", {"status": "waiting", "missing": "acesso"}, piero, "PATCH"
    )[1]
    r = call(f"{base}/api/requests/{r['id']}/comments", {"text": "Liberei!"}, nato)[1]
    r = call(f"{base}/api/requests/{r['id']}", {"status": "done"}, piero, "PATCH")[1]
    assert r["done_on"]  # set on completion
    kinds = [(e["kind"], e["account_name"]) for e in r["events"]]
    assert kinds == [
        ("created", "Renato Lima"),
        ("status", "Piero"),
        ("status", "Piero"),
        ("edited", "Piero"),
        ("comment", "Renato Lima"),
        ("status", "Piero"),
    ]
    assert r["events"][-1]["text"] == "waiting>done"
    # bad values are refused, not stored
    for bad in (
        {"status": "lost"},
        {"due": "05/11/2026"},
        {"creatives_url": "javascript:x"},
        {"budget": "muito"},
        {"client": 999},
        {"what": ""},
    ):
        assert call(f"{base}/api/requests/{r['id']}", bad, piero, "PATCH")[0] == 400, bad
    # members can't delete; the admin can, and a client with requests can't be deleted
    assert call(f"{base}/api/requests/{r['id']}", cookie=piero, method="DELETE")[0] == 403
    assert call(f"{base}/api/clients/{c['id']}", cookie=nato, method="DELETE")[0] == 400
    assert call(f"{base}/api/requests/{r['id']}", cookie=nato, method="DELETE")[0] == 200
    assert call(f"{base}/api/clients/{c['id']}", cookie=nato, method="DELETE")[0] == 200


def test_admin_deletes_a_client_with_its_requests(team):
    base, nato, piero, _ = team
    c = call(f"{base}/api/clients", {"name": "Teste", "ads_page": "fb.com/ads/x"}, nato)[1]
    assert c["ads_page"] == "fb.com/ads/x"
    call(f"{base}/api/requests", {"client": c["id"], "what": "a"}, nato)
    url = f"{base}/api/clients/{c['id']}?with_requests=1"
    assert call(url, cookie=piero, method="DELETE")[0] == 403  # members can't
    assert call(f"{base}/api/clients/{c['id']}", cookie=nato, method="DELETE")[0] == 400
    status, doc, _ = call(url, cookie=nato, method="DELETE")
    assert status == 200 and doc == {"ok": True, "requests_deleted": 1}
    assert call(f"{base}/api/requests", cookie=nato)[1] == []
    assert call(url, cookie=nato, method="DELETE")[0] == 404


def test_cross_origin_writes_refused(team):
    base, nato, _, _ = team
    evil = {"Origin": "https://evil.example"}
    assert call(f"{base}/api/clients", {"name": "X"}, nato, headers=evil)[0] == 403
    assert call(f"{base}/api/clients", {"name": "X"}, nato, headers={"Origin": ORIGIN})[0] == 200


def test_admin_tools(team):
    base, nato, piero, _ = team
    members = call(f"{base}/api/members", cookie=piero)[1]
    pid = next(m["id"] for m in members if m["name"] == "Piero")
    rid = next(m["id"] for m in members if m["name"] == "Renato Lima")
    assert call(f"{base}/api/members/{rid}", {"disabled": True}, piero, "PATCH")[0] == 403
    assert call(f"{base}/api/members/{rid}", {"disabled": True}, nato, "PATCH")[0] == 400  # self
    assert call(f"{base}/api/members/{pid}", {"disabled": True}, nato, "PATCH")[0] == 200
    assert call(f"{base}/api/requests", cookie=piero)[0] == 401  # disabled: session dead
    opts = call(f"{base}/api/options/kind", {"values": ["A", "a", " B ", ""]}, nato, "PUT")[1]
    assert opts["kind"] == ["A", "B"]


def test_gravatar(team):
    base, nato, piero, _ = team
    assert call(f"{base}/api/me", {"email": "nope"}, nato, "PATCH")[0] == 400
    me = call(f"{base}/api/me", {"email": " Nato@Example.com "}, nato, "PATCH")[1]
    want = hashlib.sha256(b"nato@example.com").hexdigest()
    assert me["avatar"] == want and me["email"] == "Nato@Example.com"
    assert me["name"] == "Renato Lima"  # untouched when only the email changes
    members = call(f"{base}/api/members", cookie=piero)[1]
    renato = next(m for m in members if m["name"] == "Renato Lima")
    assert renato["avatar"] == want and "email" not in renato  # teammates get the hash only
    boot = call(f"{base}/api/boot", cookie=piero)[1]
    assert boot["avatars"] == {str(renato["id"]): want}
    assert "email" not in json.dumps(boot["members"])
    me = call(f"{base}/api/me", {"email": ""}, nato, "PATCH")[1]
    assert me["avatar"] == ""


def test_schema_v1_upgrade(tmp_path):
    db = sqlite3.connect(tmp_path / "pauta.db")
    db.executescript(
        "CREATE TABLE account (id INTEGER PRIMARY KEY, name TEXT NOT NULL, "
        "handle TEXT NOT NULL UNIQUE, is_admin INTEGER NOT NULL DEFAULT 0, "
        "disabled INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL DEFAULT (datetime('now')));"
        "INSERT INTO account(name, handle) VALUES ('Old', 'old');"
    )
    db.commit()
    db.close()
    store = Store(tmp_path / "pauta.db")
    assert store.members()[0]["avatar"] == ""


def test_open_mode(tmp_path):
    store = Store(tmp_path / "pauta.db")
    httpd, base = start(store, Auth(store, enabled=False))
    try:
        assert call(f"{base}/api/me")[1]["is_admin"]
        assert call(f"{base}/api/clients", {"name": "Local"})[0] == 200
        assert call(f"{base}/api/invite", {})[0] == 400
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_link_preview_is_public(site):
    """Crawlers (WhatsApp, Slack...) see the Open Graph tags and fetch the card without a login."""
    base, _, _ = site
    with urllib.request.urlopen(f"{base}/") as r:
        html = r.read().decode()
    for tag in (
        'property="og:title"',
        'property="og:image" content="https://pauta.cc/og.png"',
        'name="twitter:card" content="summary_large_image"',
    ):
        assert tag in html
    for path, ctype in (("/og.png", "image/png"), ("/apple-touch-icon.png", "image/png")):
        with urllib.request.urlopen(f"{base}{path}") as r:
            assert r.headers["Content-Type"] == ctype and r.read(8) == b"\x89PNG\r\n\x1a\n"
