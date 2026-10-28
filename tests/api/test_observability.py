"""Request logs, GET /metrics and crash handling, against a real server."""

import json
import logging
import os
import time

import pytest
from test_http import raw

from pauta import __version__, obs
from pauta.ratelimit import RateLimiter
from softpasskey import SoftPasskey, call, login, start


@pytest.fixture()
def logs(caplog):
    caplog.set_level(logging.INFO, logger="pauta")

    def events(name=None):
        out = [json.loads(r.getMessage()) for r in caplog.records if r.name == "pauta"]
        return [e for e in out if name is None or e["event"] == name]

    return events


def test_one_line_per_request_with_the_route_pattern(team, logs):
    base, nato, _, _ = team
    c = call(f"{base}/api/clients", {"name": "Padaria Segredo"}, nato)[1]
    body = {"client": c["id"], "what": "Campanha secreta de Natal"}
    status, req, _ = call(f"{base}/api/requests", body, nato)
    assert status == 200
    call(f"{base}/api/requests/{req['id']}", cookie=nato)
    call(f"{base}/api/requests/999999", cookie=nato)
    lines = logs("request")
    get = [e for e in lines if e["method"] == "GET" and e["route"] == "/api/requests/{id}"]
    assert [e["status"] for e in get] == [200, 404]
    assert all(e["account"] == 1 and e["ms"] >= 0 for e in get)
    everything = json.dumps(logs())
    # no bodies, names, ids from the path, cookies or tokens in the log
    for secret in ("Segredo", "secreta", "Renato", "999999", nato.split("=", 1)[1]):
        assert secret not in everything


def test_static_files_and_probes(site, logs):
    base, _, _ = site
    raw(base, "GET", "/app.js")
    raw(base, "GET", "/healthz")
    raw(base, "GET", "/metrics")
    assert [(e["route"], e["status"]) for e in logs("request")] == [("static", 200)]
    raw(base, "GET", "/api/nope")
    assert logs("request")[-1]["route"] == "/api/unknown"


def test_failed_logins_and_rate_limits_are_events(team, logs):
    base, _, _, _ = team
    status, _, _ = login(base, SoftPasskey())  # a passkey nobody registered
    assert status == 400
    assert logs("auth_failed") == [
        {"event": "auth_failed", "route": "/api/passkey/login/verify", "status": 400}
    ]


def test_rate_limited_event(store, auth, logs):
    httpd, base = start(store, auth, RateLimiter({"login": (1, 60)}))
    try:
        call(f"{base}/api/passkey/login/options", {})
        assert call(f"{base}/api/passkey/login/options", {})[0] == 429
    finally:
        httpd.shutdown()
        httpd.server_close()
    assert logs("rate_limited") == [
        {"event": "rate_limited", "route": "/api/passkey/login/options"}
    ]


def test_metrics_on_loopback(site, monkeypatch, tmp_path):
    base, _, _ = site
    monkeypatch.setenv("PAUTA_BACKUP_DIR", str(tmp_path))
    (tmp_path / "pauta-20261028-034000.db").write_bytes(b"x")
    os.utime(tmp_path / "pauta-20261028-034000.db", (time.time() - 3600,) * 2)
    raw(base, "GET", "/api/me")
    raw(base, "GET", "/api/requests")
    status, doc, headers = call(f"{base}/metrics")
    assert status == 200 and headers["Cache-Control"] == "no-store"
    assert doc["version"] == __version__
    assert doc["requests"]["total"] == 2 and doc["window"]["requests"] == 2
    assert doc["window"]["errors_5xx"] == 0
    assert doc["db"]["bytes"] > 0
    assert 3590 <= doc["backup"]["newest_age_s"] <= 3610
    status, headers, body = raw(base, "HEAD", "/metrics")
    assert status == 200 and body == b""
    assert raw(base, "POST", "/metrics")[0] == 405


def test_metrics_without_a_backup_dir(site, monkeypatch):
    base, _, _ = site
    monkeypatch.delenv("PAUTA_BACKUP_DIR", raising=False)
    assert call(f"{base}/metrics")[1]["backup"] is None


def test_metrics_are_not_served_through_caddy(site):
    base, _, _ = site
    status, _, body = raw(base, "GET", "/metrics", headers={"X-Forwarded-For": "203.0.113.9"})
    assert status == 404 and b"version" not in body


def test_metrics_are_not_served_off_loopback(store, auth, monkeypatch):
    httpd, base = start(store, auth)
    try:
        monkeypatch.setattr(httpd.RequestHandlerClass, "_proxied", lambda self: False)
        assert raw(base, "GET", "/metrics")[0] == 404
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_a_crash_is_a_500_with_a_logged_traceback(team, site, logs, monkeypatch):
    base, nato, _, _ = team
    store = site[2]

    def boom(*_):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(store, "clients", boom)
    status, doc, _ = call(f"{base}/api/clients", cookie=nato)
    assert status == 500 and doc == {"error": "erro interno; tente de novo"}
    err = logs("error")[-1]
    assert err["route"] == "/api/clients" and "RuntimeError: kaboom" in err["traceback"]
    assert logs("request")[-1] == {**logs("request")[-1], "status": 500, "route": "/api/clients"}
    snap = call(f"{base}/metrics")[1]["window"]
    assert snap["errors_5xx"] == 1 and snap["failing_routes"] == {"/api/clients": 1}


def served(store, auth, monkeypatch, name, fn):
    """A fresh server whose handler has one method swapped, for failures mid-response."""
    httpd, base = start(store, auth)
    monkeypatch.setattr(httpd.RequestHandlerClass, name, fn)
    try:
        try:
            raw(base, "GET", "/")
        except OSError:  # the connection is cut: that's all a client can be told
            pass
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_a_crash_after_the_headers_went_out(site, logs, monkeypatch):
    _, auth, store = site

    def late(self, path):
        self.send_response(200)
        raise RuntimeError("half way")

    served(store, auth, monkeypatch, "_static", late)
    assert logs("request")[-1]["status"] == 500
    assert "half way" in logs("error")[-1]["traceback"]


def test_a_client_that_hangs_up_is_not_an_error(site, logs, monkeypatch):
    _, auth, store = site

    def gone(self, path):
        raise BrokenPipeError()

    served(store, auth, monkeypatch, "_static", gone)
    assert logs("error") == [] and logs("request")[-1]["status"] == 499


def test_malformed_requests_log_only_the_status(site, logs):
    import socket
    from urllib.parse import urlparse

    u = urlparse(site[0])
    with socket.create_connection((u.hostname, u.port), timeout=5) as s:
        s.sendall(b"BREW /coffee?token=abc HTCPCP/1.0\r\n\r\n")
        s.recv(1024)
    assert logs("protocol_error") == [{"event": "protocol_error", "status": 400}]


def test_the_window_is_fifteen_minutes():
    assert obs.WINDOW == 900  # the watchdog's 5xx check reads "the last 15 minutes"
