"""Tiny stdlib HTTP server: the static app plus JSON endpoints under /api.

Everything except the login/join endpoints and the Meta login's return (authorized by its
one-time state, see meta.py) needs a signed-in account (client data is private; there is no
public view). Writes must come from an allowed origin with a JSON body (file
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
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__, obs, sync
from .auth import MOVE_LINK_DAYS, Auth, AuthError
from .db import (
    CAMPAIGN_STATES,
    EXPORT_TABLES,
    TRACKED_STATES,
    Invalid,
    NotFound,
    Store,
    period_results,
    valid_date,
)
from .meta import ACCOUNT_STATUS, NOT_CONNECTED, Meta, MetaError, local_today
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
    # Meta's login sends the browser back here with no cookie: a one-time state is all that
    # guards it, so guesses are counted like login attempts
    "/api/meta/callback": "login",
}
ID = r"(\d{1,9})"
# passkey answers that fail are logged as auth_failed (the request line has the status too)
AUTH_ROUTES = ("/api/passkey/register/verify", "/api/passkey/login/verify")
QUIET = ("/healthz", "/metrics")  # probes every few minutes: not logged or counted when ok
SENT = object()  # a route that wrote its own response (a redirect, an image)
# what a member sees when Meta fails: the real reason ("conecte de novo") is the admin's
META_DOWN = "os números da Meta estão indisponíveis no momento"
MAX_PERIOD_DAYS = 400  # /api/campaigns refuses a longer range
DEFAULT_PERIOD_DAYS = 30  # Ads Manager's own default: "Últimos 30 dias", yesterday back
MANUAL_SYNC_SECONDS = 15 * 60  # "Atualizar agora" (POST /api/meta/sync) at most this often
SYNC_TOO_SOON = "a última atualização foi há menos de 15 minutos; espere um pouco"


def _stale(row: dict, names: dict[str, str] | None = None) -> dict:
    """A meta_account row as an account entry without numbers (not in Meta's latest list),
    labelled with its portfolio (`names`: business id -> name)."""
    return {
        "id": row["id"],
        "name": row["name"],
        "currency": row["currency"],
        "status": row["status"],
        "status_label": ACCOUNT_STATUS.get(row["status"], ""),
        "client": row["client"],
        "seen": row["seen"],
        "business_id": row.get("business_id") or "",
        "business_name": (names or {}).get(row.get("business_id") or "", ""),
    }


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
    manual_sync = {"at": 0.0}  # when an admin last asked for a sync, with its lock
    manual_lock = threading.Lock()
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
            except (DriveError, MetaError) as e:
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
                "meta": {"enabled": meta.enabled},
            }

        @route("GET", "/api/export", "admin")
        def export(self, viewer, _body):
            return {
                "exported": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "clients": store.clients(),
                "requests": [store.request(r["id"]) for r in store.requests()],
                "finance": store.finance_settings(),
                "payments": [p for c in store.clients() for p in store.client(c["id"])["payments"]],
                "meta_account": store.meta_accounts(),
                **{t: store.table(t) for t in EXPORT_TABLES},
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

        @route("GET", f"/api/clients/{ID}/meta")
        def client_meta(self, viewer, _body, cid):
            """This client's linked ad accounts with this month's numbers (from the Meta
            cache; a cold cache reads Meta). Meta off or not connected is not an error, and
            neither is Meta failing: 200 with `error` (the reason for admins, a neutral line
            for members) so the card says so instead of the page breaking."""
            store.client(int(cid))  # 404 for an unknown client
            if not meta.connected:
                return {"connected": False, "accounts": []}
            try:
                live = {a["id"]: a for a in meta.accounts()}  # a cold cache syncs the rows
            except MetaError as e:
                if not store.client(int(cid))["meta_accounts"]:
                    return {"connected": True, "accounts": []}  # nothing to show anyway
                error = str(e) if viewer["is_admin"] else META_DOWN
                return {"connected": True, "accounts": [], "error": error}
            linked = store.client(int(cid))["meta_accounts"]
            rows = {r["id"]: r for r in store.meta_accounts()}
            names = {c["business_id"]: c["business_name"] for c in meta.connections()}
            return {
                "connected": True,
                "accounts": [
                    {**live[a["id"]], "stale": False}
                    if a["id"] in live
                    else {**_stale(rows[a["id"]], names), "stale": True}
                    for a in linked
                ],
            }

        # ---- campaign tracking (decision 8): per campaign, tracked ones only, by day --------

        def _today(self) -> date:
            """The team's today: the first linked ad account's day (its time zone), else the
            default zone's. Never the server's own date (du7 runs on CET, Brazil is behind)."""
            tz = next((a["timezone_name"] for a in store.meta_accounts() if a["client"]), "")
            return local_today(tz)

        def _period(self) -> tuple[str, str, str]:
            """`since` and `until` from the query (Ads Manager's default when absent: the
            last 30 days, yesterday back, today excluded) as ISO strings, plus today's, all
            in the team's time zone."""
            q = parse_qs(urlparse(self.path).query)
            today = self._today()
            yesterday = today - timedelta(days=1)
            since = (
                valid_date(q.get("since", [""])[0])
                or (yesterday - timedelta(days=DEFAULT_PERIOD_DAYS - 1)).isoformat()
            )
            until = valid_date(q.get("until", [""])[0]) or yesterday.isoformat()
            if since > until:
                raise Invalid("o início do período vem depois do fim")
            if (date.fromisoformat(until) - date.fromisoformat(since)).days >= MAX_PERIOD_DAYS:
                raise Invalid(f"período grande demais (máximo {MAX_PERIOD_DAYS} dias)")
            return since, until, today.isoformat()

        def _reach(self, pairs: list[tuple[str, str]], since: str, until: str) -> dict:
            """The period's reach per campaign from Meta; {} when Meta won't say (reach is
            never the screen's problem: the caller shows a dash)."""
            if not pairs or not meta.connected:
                return {}
            try:
                return meta.reach(pairs, date.fromisoformat(since), date.fromisoformat(until))
            except MetaError:
                return {}

        @route("GET", "/api/campaigns")
        def campaigns(self, viewer, _body):
            """Every tracked campaign by client with the period's sums, Ads Manager's
            Resultados (`results`, `result_indicator`, `cost_per_result_cents`), the lead
            cost (`cpl_cents`: spend ÷ link clicks) and the campaign's budget; `reach`
            comes from Meta for the period as a whole (null when Meta won't say: never the
            list's problem). `include_skipped=1` adds the campaigns marked Não acompanhar
            (so an admin can bring one back); `client=<id>` keeps one client's. `last_sync`
            says how fresh the stored numbers are."""
            since, until, today = self._period()
            q = parse_qs(urlparse(self.path).query)
            states = CAMPAIGN_STATES if q.get("include_skipped", [""])[0] == "1" else TRACKED_STATES
            clients = store.campaign_rows(since, until, states)
            client = q.get("client", [""])[0]
            if client:
                if not client.isdigit():
                    raise Invalid("cliente inválido")
                clients = [c for c in clients if c["id"] == int(client)]
            pairs = [
                (k["account_id"], k["meta_id"])
                for c in clients
                for k in c["campaigns"]
                if k["meta_id"] and k["account_id"]
            ]
            reach = self._reach(pairs, since, until)
            seen = store.seen_on(today)
            for c in clients:
                c["seen_today"] = seen.get(c["id"])
                for k in c["campaigns"]:
                    clicks = k["link_clicks"]
                    k["cpl_cents"] = round(k["spend_cents"] / clicks) if clicks else None
                    k["reach"] = reach.get(k["meta_id"])
            return {
                "since": since,
                "until": until,
                "today_included": until >= today,
                "last_sync": meta.last_sync,
                # the daily check: how many of these clients someone has been through today
                "seen": {
                    "done": sum(1 for c in clients if c["seen_today"]),
                    "total": len(clients),
                },
                "clients": clients,
            }

        @route("POST", f"/api/clients/{ID}/reviews")
        def review_client(self, viewer, body, cid):
            """Visto hoje: one `review` per active campaign of the client, dated today (the
            team's day, not the server's), with this month's numbers as the snapshot (so
            the note sits next to the numbers it was about). Returns the client's check
            status."""
            cid = int(cid)
            store.client(cid)
            note = str(body.get("note") or "").strip()[:500]
            today = self._today()
            since, until = today.replace(day=1).isoformat(), today.isoformat()
            rows = [
                k
                for c in store.campaign_rows(since, until, ("active",))
                if c["id"] == cid
                for k in c["campaigns"]
            ]
            if not rows:
                raise Invalid("este cliente não tem campanha ativa para marcar")
            reach = self._reach(
                [(k["account_id"], k["meta_id"]) for k in rows if k["meta_id"]], since, until
            )
            snaps = [
                (
                    k["id"],
                    {
                        "since": since,
                        "until": until,
                        "spend_cents": k["spend_cents"],
                        "link_clicks": k["link_clicks"],
                        "cpl_cents": round(k["spend_cents"] / k["link_clicks"])
                        if k["link_clicks"]
                        else None,
                        "results": k["results"],
                        "result_indicator": k["result_indicator"],
                        "cost_per_result_cents": k["cost_per_result_cents"],
                        "reach": reach.get(k["meta_id"]),
                        "impressions": k["impressions"],
                    },
                )
                for k in rows
            ]
            n = store.add_reviews(cid, until, viewer["account"], note, snaps)
            obs.event("campaign_review", account=viewer["account"], client=cid, campaigns=n)
            return {"client": cid, "campaigns": n, "seen_today": store.seen_on(until).get(cid)}

        @route("GET", f"/api/campaigns/{ID}")
        def campaign(self, viewer, _body, cid):
            """One campaign for the period: the row, its daily rows (`days`), the period's
            sums, cost per lead and Ads Manager's Resultados (summed over the days that had
            a count; the latest indicator), and the period's reach from Meta (null when it
            won't say)."""
            since, until, today = self._period()
            k = store.campaign(int(cid), since, until)
            days = k["days"]
            k["spend_cents"] = sum(d["spend_cents"] for d in days)
            k["impressions"] = sum(d["impressions"] for d in days)
            k["link_clicks"] = sum(d["link_clicks"] for d in days)
            actions: dict[str, int] = {}
            for d in days:
                for name, n in d["actions"].items():
                    actions[name] = actions.get(name, 0) + int(n)
            k["actions"] = actions
            counted = [d["results"] for d in days if d["results"] is not None]
            k.update(period_results(sum(counted) if counted else None, k["spend_cents"]))
            k["result_indicator"] = next(
                (d["result_indicator"] for d in reversed(days) if d["result_indicator"]), ""
            )
            clicks = k["link_clicks"]
            k["cpl_cents"] = round(k["spend_cents"] / clicks) if clicks else None
            pairs = [(k["account_id"], k["meta_id"])] if k["meta_id"] and k["account_id"] else []
            k["reach"] = self._reach(pairs, since, until).get(k["meta_id"])
            return {
                "since": since,
                "until": until,
                "today_included": until >= today,
                "last_sync": meta.last_sync,
                "campaign": k,
            }

        @route("PATCH", f"/api/campaigns/{ID}")
        def campaign_state(self, viewer, body, cid):
            return store.set_campaign_state(int(cid), body.get("state"), viewer["account"])

        @route("POST", "/api/meta/sync", "admin")
        def meta_sync(self, viewer, _body):
            """Atualizar agora: the hourly pass, at most once every 15 minutes."""
            if not meta.connected:
                raise MetaError(NOT_CONNECTED, 409)
            with manual_lock:
                wait = manual_sync["at"] + MANUAL_SYNC_SECONDS - time.time()
                if wait > 0:
                    raise Reply(429, {"error": SYNC_TOO_SOON, "retry_in_s": round(wait)})
                manual_sync["at"] = time.time()
            obs.event("meta_sync_requested", account=viewer["account"])
            return sync.run(store, meta, days=sync.HOURLY_DAYS)

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

        # ---- Meta (decision 8, phase 2): read-only ad account numbers ---------------------

        @route("GET", "/api/meta", "admin")
        def meta_status(self, viewer, _body):
            """The connections (one per portfolio, with who connected it and its last sync)
            and every account under them. Meta failing is reported in `error`, with the
            accounts Pauta already knew (stale), never as a failed page: the admin still
            sees each connection's state and can act on it."""
            accounts, failed = None, ""
            if meta.connected:
                refresh = parse_qs(urlparse(self.path).query).get("refresh") == ["1"]
                try:
                    accounts = meta.accounts(refresh=refresh)
                except MetaError as e:
                    accounts, failed = [], str(e)
            out = meta.status()  # after the read: a 190 just now shows on its connection
            out["connections"] = self._connections()
            out["error"] = failed or out["error"]
            if accounts is not None:
                out["accounts"] = self._with_clients(accounts)
            return out

        def _connections(self) -> list[dict]:
            """meta.connections() (the files, the truth) with what the rows add: the
            connecting person's name and each connection's last sync."""
            rows = {r["business_id"]: r for r in store.connections()}
            out = []
            for c in meta.connections():
                row = rows.get(c["business_id"]) or {}
                out.append({**c, "by_name": row.get("by_name"), "last_sync": row.get("last_sync")})
            return out

        def _with_clients(self, accounts: list[dict]) -> list[dict]:
            """Each account with its Pauta client ({id, name} or null) and, when unlinked,
            a suggested client by name (never saved: the admin picks). Accounts kept from
            an earlier read but missing now come last, with `stale` and no numbers."""
            rows = {r["id"]: r for r in store.meta_accounts()}
            names = {c["id"]: c["name"] for c in store.clients()}
            portfolios = {c["business_id"]: c["business_name"] for c in meta.connections()}
            out = []
            for a in accounts:
                row = rows.pop(a["id"], None)
                client = row["client"] if row else None
                sid = None if client else store.suggest_client(a["name"])
                suggested = {"id": sid, "name": names[sid]} if sid in names else None
                out.append({**a, "client": client, "suggested": suggested, "stale": False})
            for row in rows.values():
                out.append({**_stale(row, portfolios), "suggested": None, "stale": True})
            return out

        @route("PATCH", "/api/meta/accounts/([0-9]{3,20})", "admin")
        def meta_link(self, viewer, body, aid):
            if "client" not in body:
                raise Invalid("informe o cliente (ou null para desvincular)")
            row = store.link_meta_account(aid, body["client"], viewer["account"])
            store.meta_log(
                "linked" if row["client"] else "unlinked",
                row["business_id"],
                viewer["account"],
                account_id=row["id"],
                account_name=row["name"],
                client_name=(row["client"] or {}).get("name"),
            )
            return row

        @route("POST", "/api/meta/connect", "admin")
        def meta_connect(self, viewer, body):
            """The login URL. `business_id` set: "Adicionar contas" on that connection (a
            re-login on the same portfolio); unset: "Conectar outro portfólio"."""
            business = body.get("business_id") if isinstance(body, dict) else None
            if business is not None and not (isinstance(business, str) and business.isdigit()):
                raise Invalid("portfólio inválido")
            return {"url": meta.start_connect(viewer["account"], business)}

        @route("GET", "/api/meta/callback", "open")
        def meta_callback(self, viewer, _body):
            """Meta's login sends the admin back here. The SameSite=Strict cookie doesn't come
            along on that cross-site redirect, so the one-time state is the authorization.
            Whatever portfolio the login came back for is saved as its own connection."""
            q = parse_qs(urlparse(self.path).query)
            state, code = q.get("state", [""])[0], q.get("code", [""])[0]
            try:
                if q.get("error") or not code:  # cancelled or refused in Meta's dialog
                    with contextlib.suppress(MetaError):
                        meta.take_state(state)
                    obs.event("meta_connect_cancelled", logging.WARNING)
                    raise MetaError("cancelado", 400, "cancelado")
                conn = meta.finish_connect(state, code)
            except MetaError as e:
                self._redirect(f"/#/equipe?meta=erro&motivo={e.reason}")
                return SENT
            if conn:  # not a repeated callback
                store.meta_log(
                    "connected",
                    conn["business_id"],
                    conn["by"],
                    business_name=conn["business_name"],
                )
            self._redirect("/#/equipe?meta=conectado")
            return SENT

        @route("DELETE", "/api/meta/connections/([0-9]{1,30}|legacy)", "admin")
        def meta_disconnect(self, viewer, _body, business_id):
            """Forget one portfolio's token. Its accounts stay as rows (stale) so the
            client mapping survives a reconnect."""
            conn = next((c for c in meta.connections() if c["business_id"] == business_id), None)
            if not conn:
                raise NotFound("conexão não encontrada")
            meta.disconnect(business_id)
            store.meta_log(
                "disconnected",
                business_id,
                viewer["account"],
                business_name=conn["business_name"],
            )
            out = meta.status()
            out["connections"] = self._connections()
            return out

        @route("GET", "/api/meta/log", "admin")
        def meta_log(self, viewer, _body):
            """The latest 20 lines of the Meta history, newest first, with the actor."""
            return store.meta_log_rows(20)

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
