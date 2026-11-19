"""Tiny stdlib HTTP server: the static app plus JSON endpoints under /api.

Everything except the login/join endpoints and the Meta login's return (authorized by its
one-time state, see meta.py) needs a signed-in account (client data is private). The one
public view is a campaign report behind an unguessable, expiring token (`/r/<token>`,
decision 12), which shows that card and nothing else. Writes must come from an allowed
origin with a JSON body (file uploads send the file itself), and the session cookie is
SameSite=Strict.
"""

from __future__ import annotations

import contextlib
import json
import logging
import mimetypes
import os
import re
import sqlite3
import threading
import time
import traceback
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

from . import __version__, obs, sync
from .auth import Auth, AuthError
from .db import (
    Invalid,
    NotFound,
    Store,
)
from .meta import Meta, MetaError
from .onedrive import DriveError, OneDrive
from .ratelimit import RateLimiter
from .routes import META_DOWN as META_DOWN  # the tests import it from here
from .routes import (
    SENT,
    Reply,
    account,
    campaigns,
    clients,
    finance,
    requests,
    team,
    usage,
)

STATIC = Path(__file__).parent / "static"
MAX_BODY = 256 * 1024
# a connection that sends nothing for this long is dropped, and only so many are served at
# once: slow or stalled clients can't pile up threads on the Pi
IDLE_SECONDS = 15
MAX_CONNECTIONS = 64
BUSY = b"HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\nRetry-After: 5\r\n\r\n"
ROBOTS = b"User-agent: *\nDisallow: /\n"
CSP = (
    "default-src 'self'; img-src 'self' data: https://gravatar.com; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
    "form-action 'self'"
)
RATE_BUCKETS = {
    "/api/invite": "invite",
    "/api/passkey/register/options": "register",
    "/api/passkey/register/verify": "register",
    "/api/passkey/login/options": "login",
    "/api/passkey/login/verify": "login",
    "/api/move": "register",
    "/api/me/move": "invite",
    # Meta's login sends the browser back here with no cookie: a one-time state is all that
    # guards it, so guesses are counted like login attempts
    "/api/meta/callback": "login",
}
# the same, for paths with a parameter in them: a report link for the client is handed out
# like an invite, and a guess at one (the page or its data) is counted like a login attempt
RATE_PATTERNS = (
    (re.compile(r"^/api/campaigns/\d{1,9}/links$"), "invite"),
    (re.compile(r"^(?:/api)?/r/"), "login"),
)


# passkey answers that fail are logged as auth_failed (the request line has the status too)
AUTH_ROUTES = ("/api/passkey/register/verify", "/api/passkey/login/verify")
# probes every few minutes, and the usage log's own batches: not logged or counted when ok
QUIET = ("/healthz", "/metrics", "/api/usage")


MANUAL_SYNC_SECONDS = 15 * 60  # "Atualizar agora" (POST /api/meta/sync) at most this often
SYNC_TOO_SOON = "a última atualização foi há menos de 15 minutos; espere um pouco"


def make_handler(
    store: Store,
    auth: Auth,
    limiter: RateLimiter | None = None,
    metrics: obs.Metrics | None = None,
    drive: OneDrive | None = None,
    meta: Meta | None = None,
):
    limiter = limiter or RateLimiter()
    metrics = metrics or obs.Metrics()
    drive = drive or OneDrive.from_env(store.path)
    meta = meta or Meta.from_env(store.path)
    meta.on_read = store.sync_meta_accounts  # each real read keeps the account rows current
    meta.on_change = store.sync_connections  # the connection rows follow the token files...
    store.sync_connections(meta.connections())  # ...from the start (a migrated file too)
    for row in store.meta_accounts():  # which portfolio reads each account, before any read
        if row["business_id"]:
            meta.business_of.setdefault(row["id"], row["business_id"])
    state = store.sync_state()  # the last sync outlives a restart, for /metrics
    meta.last_sync, meta.sync_error = state["last_sync"], state["sync_error"]
    slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
    # method, path, handler, access, raw (the body is a file, not JSON)
    routes: list[tuple[str, re.Pattern, Callable, str, bool]] = []

    def route(method: str, pattern: str, access: str = "member", raw: bool = False):
        def deco(fn):
            routes.append((method, re.compile(f"^{pattern}$"), fn, access, raw))
            return fn

        return deco

    class Handler(BaseHTTPRequestHandler):
        server_version = "pauta"
        sys_version = ""
        timeout = IDLE_SECONDS
        # buffered: a response leaves when do_* returns, after its log line and metrics
        wbufsize = -1

        def handle(self):
            if not slots.acquire(blocking=False):
                with contextlib.suppress(OSError):  # take the request head first: an unread
                    self.connection.settimeout(0.5)  # request makes the close a reset
                    self.connection.recv(16384)
                self.wfile.write(BUSY)
                metrics.record("busy", 503, 0)
                return
            try:
                super().handle()
            finally:
                slots.release()

        def log_request(self, code="-", size="-"):  # _observed logs requests as JSON
            pass

        def log_error(self, fmt, *args):  # malformed requests, before any route: no details
            obs.event("protocol_error", logging.WARNING, status=args[0] if args else None)

        def send_response(self, code, message=None):
            self._status = code
            super().send_response(code, message)

        def _label(self, path: str) -> str:
            if path in QUIET:
                return path
            if not path.startswith(("/api/", "/r/")):
                return "static"
            for _, pattern, *_ in routes:
                if pattern.match(path):
                    return obs.route_label(pattern.pattern)
            return "/r/unknown" if path.startswith("/r/") else "/api/unknown"

        def _observed(self, method: str):
            """Every request: dispatch, turn a crash into a 500, then one log line."""
            start = time.perf_counter()
            self._status, self._account = 0, None
            path = urlparse(self.path).path
            try:
                self._dispatch(method)
            except (BrokenPipeError, ConnectionResetError):
                self._status = self._status or 499  # the client went away
            except Exception:
                obs.event(
                    "error",
                    logging.ERROR,
                    method=method,
                    route=self._label(path),
                    traceback=traceback.format_exc(),
                )
                if not self._status:
                    self._json(500, {"error": "erro interno; tente de novo"})
                self._status = 500
            ms = round((time.perf_counter() - start) * 1000, 1)
            route = self._label(path)
            if route in QUIET and self._status < 400:
                return
            metrics.record(route, self._status, ms)
            level = logging.ERROR if self._status >= 500 else logging.INFO
            obs.event(
                "request",
                level,
                method=method,
                route=route,
                status=self._status,
                ms=ms,
                account=self._account,
            )
            if route in AUTH_ROUTES and self._status != 200:
                obs.event("auth_failed", logging.WARNING, route=route, status=self._status)
            elif self._status == 429:
                obs.event("rate_limited", logging.WARNING, route=route)

        # ---- plumbing ---------------------------------------------------------------------

        def _proxied(self) -> bool:
            return self.client_address[0] in ("127.0.0.1", "::1")

        def _ip(self) -> str:
            fwd = self.headers.get("X-Forwarded-For")
            if fwd and self._proxied():
                return fwd.split(",")[-1].strip()
            return self.client_address[0]

        def _secure(self) -> bool:
            return self._proxied() and self.headers.get("X-Forwarded-Proto") == "https"

        def _page_origin(self) -> str:
            """The address the app is open on: the Origin header when the browser sends one
            (every write does), else the Host Caddy passed on."""
            if origin := self.headers.get("Origin"):
                return origin
            return f"{'https' if self._secure() else 'http'}://{self.headers.get('Host', '')}"

        def _me(self, viewer: dict) -> dict:
            return {**viewer, "move": auth.move_hint(self._page_origin(), viewer["account"])}

        def _headers(self, ctype: str, length: int, extra: dict | None = None):
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(length))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
            self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
            self.send_header("X-Robots-Tag", "noindex, nofollow")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()

        def _json(self, status: int, doc, cookie: str | None = None):
            body = json.dumps(doc, ensure_ascii=False).encode()
            # the version on every answer: a tab open since before a release sees it changed
            extra = {"Cache-Control": "no-store", "X-Pauta-Version": __version__}
            if cookie:
                extra["Set-Cookie"] = cookie
            self.send_response(status)
            self._headers("application/json; charset=utf-8", len(body), extra)
            self._write(body)

        def _write(self, body: bytes):
            if self.command != "HEAD":
                self.wfile.write(body)

        def _body(self) -> dict:
            length = (self.headers.get("Content-Length") or "0").strip()
            if not length.isdigit():
                raise Reply(400, {"error": "pedido inválido"})
            n = int(length)
            if n > MAX_BODY:
                raise Reply(413, {"error": "pedido grande demais"})
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if n and ctype != "application/json":
                raise Reply(415, {"error": "envie JSON"})
            try:
                raw = self.rfile.read(n) if n else b"{}"
            except TimeoutError:
                raise Reply(408, {"error": "o pedido demorou demais"}) from None
            try:
                doc = json.loads(raw or b"{}")
            except ValueError:
                raise Reply(400, {"error": "JSON inválido"}) from None
            if not isinstance(doc, dict):
                raise Reply(400, {"error": "JSON inválido"})
            return doc

        def _redirect(self, url: str):
            self.send_response(302)
            self._headers("text/plain", 0, {"Location": url, "Cache-Control": "no-store"})

        def _page(self, status: int, body: bytes | Path):
            """An HTML page of our own (the public report, its 404), never cached."""
            if isinstance(body, Path):
                body = body.read_bytes()
            self.send_response(status)
            self._headers("text/html; charset=utf-8", len(body), {"Cache-Control": "no-store"})
            self._write(body)
            return SENT

        def _reader(self):
            def read(n: int) -> bytes:
                try:
                    return self.rfile.read(n)
                except TimeoutError:
                    raise DriveError("o envio parou no meio; tente de novo", 408) from None

            return read

        def _check_origin(self):
            if not auth.enabled:
                return
            origin = self.headers.get("Origin")
            if origin and origin not in auth.origins:
                raise Reply(403, {"error": "origem não permitida"})

        def _static(self, path: str):
            if path == "/robots.txt":
                self.send_response(200)
                self._headers("text/plain", len(ROBOTS))
                self._write(ROBOTS)
                return
            rel = path.lstrip("/")
            target = (STATIC / rel).resolve() if rel else None
            if not target or not target.is_file() or STATIC.resolve() not in target.parents:
                target = STATIC / "index.html"  # the app routes with #/...
            body = target.read_bytes()
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith(("javascript", "json", "svg+xml")):
                ctype += "; charset=utf-8"
            cache = "no-cache" if target.name == "index.html" else "public, max-age=300"
            self.send_response(200)
            self._headers(ctype, len(body), {"Cache-Control": cache})
            self._write(body)

        def _dispatch(self, method: str):
            path = urlparse(self.path).path
            if path == "/healthz":
                return self._health(method)
            if path == "/metrics":
                return self._metrics(method)
            public_page = path.startswith("/r/")  # the client's report (decision 12)
            if not path.startswith("/api/") and not public_page:
                if method not in ("GET", "HEAD"):
                    return self._json(405, {"error": "método não permitido"})
                return self._static(path)
            if method == "HEAD" and not public_page:  # a link preview may HEAD the page
                return self._json(405, {"error": "método não permitido"})
            if public_page and method not in ("GET", "HEAD"):  # the page is read-only
                return self._json(405, {"error": "método não permitido"})
            try:
                if method not in ("GET", "HEAD"):
                    self._check_origin()
                bucket = RATE_BUCKETS.get(path) or next(
                    (b for p, b in RATE_PATTERNS if p.match(path)), None
                )
                if bucket:
                    wait = limiter.hit(bucket, self._ip())
                    if wait:
                        raise Reply(429, {"error": f"muitas tentativas; espere {wait}s"})
                viewer = auth.viewer(self.headers.get("Cookie"))
                self._account = viewer["account"]
                want = "GET" if method == "HEAD" else method
                for m, pattern, fn, access, raw in routes:
                    match = pattern.match(path)
                    if m != want or not match:
                        continue
                    if access in ("member", "admin") and not viewer["logged_in"]:
                        raise Reply(401, {"error": "entre com sua passkey"})
                    if access == "admin" and not viewer["is_admin"]:
                        raise Reply(403, {"error": "só para administradores"})
                    body = self._body() if method in ("POST", "PUT", "PATCH") and not raw else {}
                    out = fn(self, viewer, body, *match.groups())
                    if out is SENT:
                        return
                    if isinstance(out, tuple):
                        return self._json(200, out[0], cookie=out[1])
                    return self._json(200, out)
                if public_page:  # not even the shape of a token: the same plain page
                    return self._page(404, STATIC / "report-gone.html")
                raise Reply(404, {"error": "não encontrado"})
            except Reply as r:
                self._json(r.status, r.doc)
            except (Invalid, AuthError) as e:
                self._json(400, {"error": str(e)})
            except NotFound as e:
                self._json(404, {"error": str(e)})
            except DriveError as e:
                self._json(e.status, {"error": str(e)})
            except MetaError as e:  # `reason` is the fixed code: the UI waits on "busy"
                self._json(e.status, {"error": str(e), "reason": e.reason})

        def _health(self, method: str):
            """For the deploy and uptime checks: no auth, no data, just "the DB answers"."""
            if method not in ("GET", "HEAD"):
                return self._json(405, {"error": "método não permitido"})
            try:
                with store.db() as db:
                    db.execute("SELECT 1 FROM meta LIMIT 1").fetchone()
            except sqlite3.Error:
                return self._json(503, {"status": "error", "version": __version__})
            self._json(200, {"status": "ok", "version": __version__})

        def _metrics(self, method: str):
            """For du7's watchdog: straight to 127.0.0.1:8088 only. Caddy always adds
            X-Forwarded-For, so through app.pauta.cc this is a 404."""
            if not self._proxied() or self.headers.get("X-Forwarded-For"):
                return self._json(404, {"error": "não encontrado"})
            if method not in ("GET", "HEAD"):
                return self._json(405, {"error": "método não permitido"})
            backups = os.environ.get("PAUTA_BACKUP_DIR")
            doc = {
                "version": __version__,
                **metrics.snapshot(),
                "db": {"bytes": obs.file_bytes(store.path)},
                "backup": {"dir": backups, "newest_age_s": obs.newest_age(backups)}
                if backups
                else None,
                "onedrive": {
                    "enabled": drive.enabled,
                    "connected": drive.connected,
                    "error": drive.error,
                },
                "meta": self._meta_metrics(),
            }
            self._json(200, doc)

        @staticmethod
        def _meta_metrics() -> dict:
            """`connected` is "at least one portfolio reads"; the counts say how many are
            connected and how many Meta revoked (du7's watchdog alerts on those)."""
            conns = meta.connections()
            return {
                "enabled": meta.enabled,
                "connected": any(c["state"] == "ok" for c in conns),
                "connections": len(conns),
                "revoked": sum(1 for c in conns if c["state"] == "revoked"),
                "error": next((c["error"] for c in conns if c["error"]), ""),
                "last_sync": meta.last_sync,
                "sync_error": meta.sync_error,
                "syncing": sync.running(),
            }

        def do_GET(self):  # noqa: N802
            self._observed("GET")

        def do_HEAD(self):  # noqa: N802
            self._observed("HEAD")

        def do_POST(self):  # noqa: N802
            self._observed("POST")

        def do_PUT(self):  # noqa: N802
            self._observed("PUT")

        def do_PATCH(self):  # noqa: N802
            self._observed("PATCH")

        def do_DELETE(self):  # noqa: N802
            self._observed("DELETE")

        # ---- who am I ---------------------------------------------------------------------

        @route("GET", "/api/me", "open")
        def me(self, viewer, _body):
            return self._me(viewer)

        @route("PATCH", "/api/me")
        def edit_me(self, viewer, body):
            if viewer["account"] is None:
                raise Reply(400, {"error": "sem contas no modo local"})
            if "name" in body:
                auth.rename(viewer["account"], body["name"])
            if "email" in body:
                auth.set_email(viewer["account"], body["email"])
            if "whatsapp" in body:
                auth.set_whatsapp(viewer["account"], body["whatsapp"])
            if "start" in body:
                auth.set_start(viewer["account"], body["start"])
            return self._me(auth.viewer(self.headers.get("Cookie")))

    # the rest of /api, by area; same table, same order as before the split
    for area in (requests, clients, campaigns, finance, team, account, usage):
        area.install(route, store, auth, drive, meta)
    return Handler
