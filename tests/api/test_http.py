"""HTTP plumbing: health, HEAD, static files, headers, body rules, rate limits, proxy trust."""

import http.client
import json
import re
import sqlite3
from urllib.parse import urlparse

import pytest

from pauta import __version__
from pauta.auth import Auth
from pauta.ratelimit import RateLimiter
from softpasskey import ORIGIN, RP_ID, call, start


def raw(base, method, path, body=b"", headers=None):
    """One request with full control over method, body and headers (urllib adds its own)."""
    u = urlparse(base)
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=5)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        r = conn.getresponse()
        return r.status, dict(r.getheaders()), r.read()
    finally:
        conn.close()


def test_health(site):
    base, _, _ = site
    status, doc, headers = call(f"{base}/healthz")
    assert status == 200 and doc == {"status": "ok", "version": __version__}
    assert headers["Cache-Control"] == "no-store"
    status, headers, body = raw(base, "HEAD", "/healthz")
    assert status == 200 and body == b"" and int(headers["Content-Length"]) > 0
    assert raw(base, "POST", "/healthz")[0] == 405


def test_health_reports_a_broken_database(site, monkeypatch):
    base, _, store = site

    def broken():
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(store, "db", broken)
    monkeypatch.setattr(store, "_reload", (0.0, ""))  # the reload mark is due a read as well
    status, doc, headers = call(f"{base}/healthz")
    assert status == 503 and doc["status"] == "error"
    assert "X-Pauta-Reload" not in headers  # no mark to give, and the answer still goes out


def test_security_headers_everywhere(site):
    base, _, _ = site
    for path in ("/", "/app.js", "/api/me", "/healthz", "/r/nobody", "/api/r/nobody"):
        _, headers, _ = raw(base, "GET", path)
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["Referrer-Policy"] == "same-origin"
        assert headers["X-Robots-Tag"] == "noindex, nofollow"
        csp = headers["Content-Security-Policy"]
        assert "default-src 'self'" in csp and "script-src 'self'" in csp
        assert "unsafe-eval" not in csp and "frame-ancestors 'none'" in csp
        assert headers["Server"].startswith("pauta")  # no Python version leaked


def test_static_files(site):
    base, _, _ = site
    status, headers, body = raw(base, "GET", "/style.css")
    assert status == 200 and headers["Content-Type"] == "text/css; charset=utf-8"
    assert headers["Cache-Control"] == "public, max-age=300"
    status, headers, body = raw(base, "GET", "/robots.txt")
    assert body == b"User-agent: *\nDisallow: /\n"
    status, headers, body = raw(base, "HEAD", "/app.js")
    assert status == 200 and body == b"" and int(headers["Content-Length"]) > 1000


def test_what_the_shell_names_is_cached_for_good(site):
    base, _, _ = site
    status, headers, shell = raw(base, "GET", "/")
    assert status == 200 and headers["Cache-Control"] == "no-cache"
    refs = re.findall(r'(?:src|href)="(/[^"]+)"', shell.decode())
    assert len(refs) == 6 and all("?v=" in r for r in refs)
    for ref in refs:
        status, headers, body = raw(base, "GET", ref)
        assert status == 200 and len(body) > 100, ref
        assert headers["Cache-Control"] == "public, max-age=31536000, immutable", ref
    # the app's scripts are one file, served as JavaScript
    (script,) = (r for r in refs if r.startswith("/app.bundle.js"))
    status, headers, body = raw(base, "GET", script)
    assert headers["Content-Type"] == "text/javascript; charset=utf-8"
    assert b"// ---- app.js" in body and b"// ---- app-router.js" in body
    # the picture the stylesheet names carries its tag too
    css = raw(base, "GET", next(r for r in refs if "style.css" in r))[2].decode()
    icon = re.search(r"url\((/icon\.svg\?v=[0-9a-f]+)\)", css)[1]
    assert raw(base, "GET", icon)[1]["Cache-Control"].endswith("immutable")
    # an address from an older page is served, but not pinned: its tag is not today's file
    status, headers, _ = raw(base, "GET", "/app.bundle.js?v=000000000000")
    assert status == 200 and headers["Cache-Control"] == "no-cache"
    # the QR code library is no longer part of every load; the boot data says where it is
    assert b"qrcode.js" not in shell


@pytest.mark.parametrize(
    "path", ["/some/route", "/../pyproject.toml", "/%2e%2e/%2e%2e/etc/passwd", "/static/../db.py"]
)
def test_unknown_paths_get_the_app_shell_not_files(site, path):
    base, _, _ = site
    status, headers, body = raw(base, "GET", path)
    assert status == 200 and headers["Cache-Control"] == "no-cache"
    assert b"<!doctype html>" in body and b"[project]" not in body and b"root:" not in body


def test_methods(site):
    base, _, _ = site
    assert raw(base, "POST", "/")[0] == 405
    assert raw(base, "HEAD", "/api/me")[0] == 405
    assert call(f"{base}/api/nope")[0] == 404
    assert raw(base, "DELETE", "/api/me")[0] == 404


def test_body_rules(team):
    base, nato, _, _ = team
    json_hdr = {"Content-Type": "application/json", "Cookie": nato}
    big = b"{" + b" " * (256 * 1024) + b"}"
    assert raw(base, "POST", "/api/clients", big, json_hdr)[0] == 413
    form = {"Content-Type": "application/x-www-form-urlencoded", "Cookie": nato}
    assert raw(base, "POST", "/api/clients", b"name=x", form)[0] == 415
    status, _, body = raw(base, "POST", "/api/clients", b"{nope", json_hdr)
    assert status == 400 and json.loads(body)["error"] == "JSON inválido"
    assert raw(base, "POST", "/api/clients", b"[1]", json_hdr)[0] == 400
    status, _, body = raw(base, "POST", "/api/clients", b"{}", json_hdr)
    assert status == 400 and "nome" in json.loads(body)["error"]


def test_rate_limit_on_login(store):
    auth = Auth(store, enabled=True, rp_id=RP_ID, origins=[ORIGIN])
    httpd, base = start(store, auth, RateLimiter({"login": (2, 60)}))
    try:
        codes = [call(f"{base}/api/passkey/login/options", {})[0] for _ in range(3)]
        assert codes == [200, 200, 429]
        assert "espere" in call(f"{base}/api/passkey/login/options", {})[1]["error"]
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_behind_the_proxy_cookies_are_secure(store, auth):
    """From loopback (Caddy), X-Forwarded-Proto: https makes the session cookie Secure."""
    httpd, base = start(store, auth)
    try:
        _, headers, _ = raw(
            base,
            "POST",
            "/api/logout",
            b"{}",
            {"Content-Type": "application/json", "X-Forwarded-Proto": "https"},
        )
        assert headers["Set-Cookie"].endswith("Secure")
        _, headers, _ = raw(
            base, "POST", "/api/logout", b"{}", {"Content-Type": "application/json"}
        )
        assert "Secure" not in headers["Set-Cookie"]
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_passkeys_off_in_open_mode(store):
    httpd, base = start(store, Auth(store, enabled=False))
    try:
        for path in ("/api/passkey/register/options", "/api/passkey/login/options"):
            assert call(f"{base}{path}", {})[0] == 400
        assert call(f"{base}/api/me", {"name": "x"}, method="PATCH")[0] == 400
        boot = call(f"{base}/api/boot")[1]
        assert boot["version"] == __version__ and boot["me"]["is_admin"]
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_add_device_needs_a_session(site):
    base, _, _ = site
    status, doc, _ = call(f"{base}/api/passkey/register/options", {})
    assert status == 401 and "entre" in doc["error"]
