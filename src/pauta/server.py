"""Tiny stdlib HTTP server: the static app plus JSON endpoints under /api.

Everything except the login/join endpoints needs a signed-in account (client data is private;
there is no public view). Writes must come from an allowed origin with a JSON body (file
uploads send the file itself), and the session cookie is SameSite=Strict.
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
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__, obs
from .auth import MOVE_LINK_DAYS, Auth, AuthError
from .db import Invalid, NotFound, Store
from .onedrive import DriveError, OneDrive
from .ratelimit import RateLimiter

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
}
ID = r"(\d{1,9})"
# passkey answers that fail are logged as auth_failed (the request line has the status too)
AUTH_ROUTES = ("/api/passkey/register/verify", "/api/passkey/login/verify")
QUIET = ("/healthz", "/metrics")  # probes every few minutes: not logged or counted when ok
SENT = object()  # a route that wrote its own response (a redirect, an image)


class Reply(Exception):
    def __init__(self, status: int, doc: dict | list):
        super().__init__(status)
        self.status, self.doc = status, doc


def finance_visible(viewer: dict, settings: dict) -> bool:
    """Who sees money: everyone, or admins only, per the team's setting; nobody when off."""
    if not settings.get("enabled"):
        return False
    return settings.get("visibility") == "all" or bool(viewer.get("is_admin"))


def make_handler(
    store: Store,
    auth: Auth,
    limiter: RateLimiter | None = None,
    metrics: obs.Metrics | None = None,
    drive: OneDrive | None = None,
):
    limiter = limiter or RateLimiter()
    metrics = metrics or obs.Metrics()
    drive = drive or OneDrive.from_env(store.path)
    slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
    # method, path, handler, access, raw (the body is a file, not JSON)
    routes: list[tuple[str, re.Pattern, str, str, bool]] = []

    def route(method: str, pattern: str, access: str = "member", raw: bool = False):
        def deco(fn):
            routes.append((method, re.compile(f"^{pattern}$"), fn.__name__, access, raw))
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
            if not path.startswith("/api/"):
                return "static"
            for _, pattern, *_ in routes:
                if pattern.match(path):
                    return obs.route_label(pattern.pattern)
            return "/api/unknown"

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
            extra = {"Cache-Control": "no-store"}
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
            if not path.startswith("/api/"):
                if method not in ("GET", "HEAD"):
                    return self._json(405, {"error": "método não permitido"})
                return self._static(path)
            if method == "HEAD":
                return self._json(405, {"error": "método não permitido"})
            try:
                if method != "GET":
                    self._check_origin()
                bucket = RATE_BUCKETS.get(path)
                if bucket:
                    wait = limiter.hit(bucket, self._ip())
                    if wait:
                        raise Reply(429, {"error": f"muitas tentativas; espere {wait}s"})
                viewer = auth.viewer(self.headers.get("Cookie"))
                self._account = viewer["account"]
                for m, pattern, name, access, raw in routes:
                    match = pattern.match(path)
                    if m != method or not match:
                        continue
                    if access in ("member", "admin") and not viewer["logged_in"]:
                        raise Reply(401, {"error": "entre com sua passkey"})
                    if access == "admin" and not viewer["is_admin"]:
                        raise Reply(403, {"error": "só para administradores"})
                    body = self._body() if method in ("POST", "PUT", "PATCH") and not raw else {}
                    out = getattr(self, name)(viewer, body, *match.groups())
                    if out is SENT:
                        return
                    if isinstance(out, tuple):
                        return self._json(200, out[0], cookie=out[1])
                    return self._json(200, out)
                raise Reply(404, {"error": "não encontrado"})
            except Reply as r:
                self._json(r.status, r.doc)
            except (Invalid, AuthError) as e:
                self._json(400, {"error": str(e)})
            except NotFound as e:
                self._json(404, {"error": str(e)})
            except DriveError as e:
                self._json(e.status, {"error": str(e)})

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
            }
            self._json(200, doc)

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
            return self._me(auth.viewer(self.headers.get("Cookie")))

        @route("GET", "/api/boot")
        def boot(self, viewer, _body):
            everyone = store.members()
            fin = store.finance_settings()
            members = [{"id": m["id"], "name": m["name"]} for m in everyone if not m["disabled"]]
            # Gravatar ids by account, for avatars on requests and the timeline
            avatars = {m["id"]: m["avatar"] for m in everyone if m["avatar"]}
            return {
                "me": self._me(viewer),
                "options": store.options(),
                "members": members,
                "avatars": avatars,
                "version": __version__,
                "files": {
                    "enabled": drive.enabled,
                    "connected": drive.connected,
                    "max_mb": drive.max_bytes // (1024 * 1024),
                },
                "finance": {**fin, "visible": finance_visible(viewer, fin)},
            }

        @route("GET", "/api/export", "admin")
        def export(self, viewer, _body):
            return {
                "exported": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "clients": store.clients(),
                "requests": [store.request(r["id"]) for r in store.requests()],
                "finance": store.finance_settings(),
                "payments": [p for c in store.clients() for p in store.client(c["id"])["payments"]],
            }

        # ---- requests ---------------------------------------------------------------------

        @route("GET", "/api/requests")
        def list_requests(self, viewer, _body):
            return store.requests()

        @route("POST", "/api/requests")
        def new_request(self, viewer, body):
            return store.create_request(body, viewer["account"])

        @route("GET", f"/api/requests/{ID}")
        def get_request(self, viewer, _body, rid):
            return store.request(int(rid))

        @route("PATCH", f"/api/requests/{ID}")
        def edit_request(self, viewer, body, rid):
            return store.update_request(int(rid), body, viewer["account"])

        @route("POST", f"/api/requests/{ID}/comments")
        def comment(self, viewer, body, rid):
            return store.comment(int(rid), body.get("text"), viewer["account"])

        @route("DELETE", f"/api/requests/{ID}", "admin")
        def delete_request(self, viewer, _body, rid):
            store.delete_request(int(rid))  # its files stay in OneDrive
            return {"ok": True}

        # ---- files (in OneDrive) ----------------------------------------------------------

        @route("POST", f"/api/requests/{ID}/files", raw=True)
        def upload(self, viewer, _body, rid):
            """The body is the file; its name comes URI-encoded in X-File-Name."""
            # one upload per connection: after an error the rest of the body is unread
            self.close_connection = True
            folder = store.file_folder(int(rid))
            length = (self.headers.get("Content-Length") or "").strip()
            if not length.isdigit():
                raise Reply(411, {"error": "envie o tamanho do arquivo"})
            name = unquote(self.headers.get("X-File-Name") or "").strip()
            if not name:
                raise Reply(400, {"error": "o arquivo precisa de um nome"})
            item = drive.upload(folder, name, int(length), self._reader())
            obs.event("file_uploaded", bytes=item["size"])
            return store.add_file(int(rid), item, viewer["account"])

        @route("GET", f"/api/files/{ID}")
        def download(self, viewer, _body, fid):
            self._redirect(drive.download_url(store.file(int(fid))["item"]))
            return SENT

        @route("GET", f"/api/files/{ID}/thumb")
        def thumb(self, viewer, _body, fid):
            raw, ctype = drive.thumbnail(store.file(int(fid))["item"])
            self.send_response(200)
            self._headers(ctype, len(raw), {"Cache-Control": "private, max-age=86400"})
            self._write(raw)
            return SENT

        @route("DELETE", f"/api/files/{ID}")
        def remove_file(self, viewer, _body, fid):
            f = store.file(int(fid))
            if not viewer["is_admin"] and f["account"] != viewer["account"]:
                raise Reply(403, {"error": "só quem enviou ou um administrador pode remover"})
            drive.delete(f["item"])
            return store.remove_file(int(fid), viewer["account"])

        @route("POST", f"/api/requests/{ID}/share")
        def share(self, viewer, _body, rid):
            folder = store.request_folder(int(rid))
            if not folder:
                raise Reply(400, {"error": "envie um arquivo primeiro"})
            return {"url": drive.share_link(folder)}

        # ---- clients ----------------------------------------------------------------------

        @route("GET", "/api/clients")
        def list_clients(self, viewer, _body):
            return store.clients()

        @route("POST", "/api/clients")
        def new_client(self, viewer, body):
            body.pop("billed", None)
            return self._client_for(viewer, store.save_client(body, by=viewer["account"]))

        @route("GET", f"/api/clients/{ID}")
        def get_client(self, viewer, _body, cid):
            return self._client_for(viewer, store.client(int(cid)))

        @route("PATCH", f"/api/clients/{ID}")
        def edit_client(self, viewer, body, cid):
            body.pop("billed", None)  # that one goes through /billing, with the finance check
            return self._client_for(viewer, store.save_client(body, int(cid), viewer["account"]))

        def _client_for(self, viewer, client: dict) -> dict:
            if not finance_visible(viewer, store.finance_settings()):
                client = {**client, "billing": None, "payments": []}
            return client

        # ---- finance (decision 7) ---------------------------------------------------------

        def _finance(self, viewer):
            """Every finance route: 404 when the module is off, 403 when this person may not."""
            fin = store.finance_settings()
            if not fin["enabled"]:
                raise Reply(404, {"error": "o financeiro está desligado"})
            if not finance_visible(viewer, fin):
                raise Reply(403, {"error": "só administradores veem o financeiro"})

        @route("GET", "/api/finance")
        def finance_panel(self, viewer, _body):
            self._finance(viewer)
            month = parse_qs(urlparse(self.path).query).get("month", [None])[0]
            return store.finance(month=month)

        @route("GET", "/api/finance/settings", "admin")
        def finance_settings(self, viewer, _body):
            return store.finance_settings()

        @route("PATCH", "/api/finance/settings", "admin")
        def edit_finance_settings(self, viewer, body):
            return store.set_finance_settings(body)

        @route("PATCH", f"/api/clients/{ID}/billing")
        def edit_billing(self, viewer, body, cid):
            self._finance(viewer)
            return store.set_billing(int(cid), body, viewer["account"])

        @route("POST", f"/api/clients/{ID}/payments")
        def add_payment(self, viewer, body, cid):
            self._finance(viewer)
            return store.add_payment(int(cid), body, viewer["account"])

        @route("DELETE", f"/api/payments/{ID}")
        def void_payment(self, viewer, _body, pid):
            self._finance(viewer)
            return store.void_payment(int(pid), viewer["account"], viewer["is_admin"])

        @route("DELETE", f"/api/clients/{ID}", "admin")
        def delete_client(self, viewer, _body, cid):
            query = parse_qs(urlparse(self.path).query)
            with_requests = query.get("with_requests") == ["1"]
            n = store.delete_client(int(cid), with_requests=with_requests)
            return {"ok": True, "requests_deleted": n}

        # ---- team and settings ------------------------------------------------------------

        @route("GET", "/api/members")
        def members(self, viewer, _body):
            return store.members()

        @route("PATCH", f"/api/members/{ID}", "admin")
        def edit_member(self, viewer, body, aid):
            auth.set_member(
                int(aid),
                disabled=body.get("disabled"),
                is_admin=body.get("is_admin"),
                by=viewer["account"],
            )
            return store.members()

        @route("GET", "/api/onedrive", "admin")
        def drive_status(self, viewer, _body):
            """Also how the Equipe page waits for the code to be approved: each call while
            a connection is pending asks Microsoft once."""
            state = drive.poll() if drive.pending() else "idle"
            return {**drive.status(quota=state != "pending"), "state": state}

        @route("POST", "/api/onedrive/connect", "admin")
        def drive_connect(self, viewer, _body):
            drive.start_connect()
            return {**drive.status(), "state": "pending"}

        @route("DELETE", "/api/onedrive", "admin")
        def drive_disconnect(self, viewer, _body):
            drive.disconnect()
            return {**drive.status(), "state": "idle"}

        @route("PUT", "/api/options/(kind|goal|segment)", "admin")
        def options(self, viewer, body, lst):
            store.set_options(lst, body.get("values"))
            return store.options()

        # ---- passkeys and invites ---------------------------------------------------------

        @route("POST", "/api/invite", "admin")
        def invite(self, viewer, body):
            if not auth.enabled:
                raise Reply(400, {"error": "convites precisam de passkeys (PAUTA_AUTH)"})
            uses = body.get("uses") or 1
            if not isinstance(uses, int) or isinstance(uses, bool):
                raise Reply(400, {"error": "número de usos inválido"})
            token, expires = auth.create_invite(
                admin=body.get("admin") is True, uses=uses, created_by=viewer["account"]
            )
            return {"path": f"/#/entrar/{token}", "expires": expires}

        @route("GET", "/api/invite/([A-Za-z0-9_-]{10,64})", "open")
        def invite_info(self, viewer, _body, token):
            info = auth.invite_info(token)
            if not info:
                raise Reply(404, {"error": "este convite não vale mais; peça um novo"})
            return info

        @route("POST", "/api/passkey/register/options", "open")
        def register_options(self, viewer, body):
            if not auth.enabled:
                raise Reply(400, {"error": "passkeys estão desligadas"})
            rp_id = auth.rp_for(self._page_origin())
            if body.get("move"):
                if rp_id != auth.rp_id:
                    raise Reply(400, {"error": f"abra este link em {auth.home_host}"})
                return auth.register_options(move=str(body["move"]), rp_id=rp_id)
            if body.get("invite"):
                return auth.register_options(
                    invite=str(body["invite"]), name=body.get("name"), rp_id=rp_id
                )
            acc = auth.account_from_cookie(self.headers.get("Cookie"))
            if not acc:
                raise Reply(401, {"error": "entre primeiro para adicionar um aparelho"})
            return auth.register_options(account=acc, rp_id=rp_id)

        @route("POST", "/api/passkey/register/verify", "open")
        def register_verify(self, viewer, body):
            acc = auth.register_verify(body.get("flow"), body.get("credential") or {})
            return auth.viewer_for(acc), auth.make_cookie(acc["id"], self._secure())

        @route("POST", "/api/passkey/login/options", "open")
        def login_options(self, viewer, _body):
            if not auth.enabled:
                raise Reply(400, {"error": "passkeys estão desligadas"})
            return auth.login_options(auth.rp_for(self._page_origin()))

        @route("POST", "/api/move")
        def move(self, viewer, _body):
            """From the old domain: a one-time link to make a passkey on the new one."""
            hint = auth.move_hint(self._page_origin(), viewer["account"])
            if not hint or viewer["account"] is None:
                raise Reply(400, {"error": "a Pauta não está mudando de endereço"})
            if hint["here"]:
                raise Reply(400, {"error": f"você já está em {hint['to']}"})
            token, _ = auth.create_move(viewer["account"])
            return {"url": f"{hint['url']}/#/mudar/{token}"}

        @route("POST", f"/api/members/{ID}/move", "admin")
        def move_link(self, viewer, _body, mid):
            """An admin's link for someone else: sent on WhatsApp, one tap and Face ID on the
            home domain. Also the way back in after a lost phone."""
            if not auth.enabled or not auth.home:
                raise Reply(400, {"error": "links de mudança precisam de passkeys (PAUTA_AUTH)"})
            token, expires = auth.create_move(
                int(mid), MOVE_LINK_DAYS * 86400, created_by=viewer["account"]
            )
            return {"url": f"{auth.home}/#/mudar/{token}", "expires": expires, "to": auth.home_host}

        @route("GET", "/api/move/([A-Za-z0-9_-]{20,64})", "open")
        def move_info(self, viewer, _body, token):
            info = auth.move_info(token)
            if not info:
                raise Reply(404, {"error": "este link de mudança expirou"})
            return info

        @route("POST", "/api/passkey/login/verify", "open")
        def login_verify(self, viewer, body):
            acc = auth.login_verify(body.get("flow"), body.get("credential") or {})
            return auth.viewer_for(acc), auth.make_cookie(acc["id"], self._secure())

        @route("POST", "/api/logout", "open")
        def logout(self, viewer, _body):
            if auth.enabled:  # ends this person's sessions on every device, not just this one
                auth.end_sessions(viewer["account"])
            return {"ok": True}, auth.clear_cookie(self._secure())

    return Handler
