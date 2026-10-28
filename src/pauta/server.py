"""Tiny stdlib HTTP server: the static app plus JSON endpoints under /api.

Everything except the login/join endpoints needs a signed-in account (client data is private;
there is no public view). Writes must come from an allowed origin with a JSON body, and the
session cookie is SameSite=Strict.
"""

from __future__ import annotations

import json
import mimetypes
import re
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

from .auth import Auth, AuthError
from .db import Invalid, NotFound, Store
from .ratelimit import RateLimiter

STATIC = Path(__file__).parent / "static"
MAX_BODY = 256 * 1024
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
}
ID = r"(\d{1,9})"


class Reply(Exception):
    def __init__(self, status: int, doc: dict | list):
        super().__init__(status)
        self.status, self.doc = status, doc


def make_handler(store: Store, auth: Auth, limiter: RateLimiter | None = None):
    limiter = limiter or RateLimiter()
    routes: list[tuple[str, re.Pattern, str, str]] = []  # method, path, handler, access

    def route(method: str, pattern: str, access: str = "member"):
        def deco(fn):
            routes.append((method, re.compile(f"^{pattern}$"), fn.__name__, access))
            return fn

        return deco

    class Handler(BaseHTTPRequestHandler):
        server_version = "pauta"
        sys_version = ""

        def log_message(self, fmt, *args):  # quieter: method, path, status only
            if not str(args[1] if len(args) > 1 else "").startswith("2"):
                super().log_message(fmt, *args)

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

        def _headers(self, ctype: str, length: int, extra: dict | None = None):
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(length))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header("Content-Security-Policy", CSP)
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
            self.wfile.write(body)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise Reply(413, {"error": "pedido grande demais"})
            if n and "application/json" not in (self.headers.get("Content-Type") or ""):
                raise Reply(415, {"error": "envie JSON"})
            raw = self.rfile.read(n) if n else b"{}"
            try:
                doc = json.loads(raw or b"{}")
            except ValueError:
                raise Reply(400, {"error": "JSON inválido"}) from None
            if not isinstance(doc, dict):
                raise Reply(400, {"error": "JSON inválido"})
            return doc

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
                self.wfile.write(ROBOTS)
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
            self.wfile.write(body)

        def _dispatch(self, method: str):
            path = urlparse(self.path).path
            if not path.startswith("/api/"):
                if method != "GET":
                    return self._json(405, {"error": "método não permitido"})
                return self._static(path)
            try:
                if method != "GET":
                    self._check_origin()
                bucket = RATE_BUCKETS.get(path)
                if bucket:
                    wait = limiter.hit(bucket, self._ip())
                    if wait:
                        raise Reply(429, {"error": f"muitas tentativas; espere {wait}s"})
                viewer = auth.viewer(self.headers.get("Cookie"))
                for m, pattern, name, access in routes:
                    match = pattern.match(path)
                    if m != method or not match:
                        continue
                    if access in ("member", "admin") and not viewer["logged_in"]:
                        raise Reply(401, {"error": "entre com sua passkey"})
                    if access == "admin" and not viewer["is_admin"]:
                        raise Reply(403, {"error": "só para administradores"})
                    body = self._body() if method in ("POST", "PUT", "PATCH") else {}
                    out = getattr(self, name)(viewer, body, *match.groups())
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

        def do_GET(self):  # noqa: N802
            self._dispatch("GET")

        def do_POST(self):  # noqa: N802
            self._dispatch("POST")

        def do_PUT(self):  # noqa: N802
            self._dispatch("PUT")

        def do_PATCH(self):  # noqa: N802
            self._dispatch("PATCH")

        def do_DELETE(self):  # noqa: N802
            self._dispatch("DELETE")

        # ---- who am I ---------------------------------------------------------------------

        @route("GET", "/api/me", "open")
        def me(self, viewer, _body):
            return viewer

        @route("PATCH", "/api/me")
        def edit_me(self, viewer, body):
            if viewer["account"] is None:
                raise Reply(400, {"error": "sem contas no modo local"})
            if "name" in body:
                auth.rename(viewer["account"], body["name"])
            if "email" in body:
                auth.set_email(viewer["account"], body["email"])
            return auth.viewer(self.headers.get("Cookie"))

        @route("GET", "/api/boot")
        def boot(self, viewer, _body):
            everyone = store.members()
            members = [{"id": m["id"], "name": m["name"]} for m in everyone if not m["disabled"]]
            # Gravatar ids by account, for avatars on requests and the timeline
            avatars = {m["id"]: m["avatar"] for m in everyone if m["avatar"]}
            return {
                "me": viewer,
                "options": store.options(),
                "members": members,
                "avatars": avatars,
            }

        @route("GET", "/api/export")
        def export(self, viewer, _body):
            return {
                "exported": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "clients": store.clients(),
                "requests": [store.request(r["id"]) for r in store.requests()],
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
            store.delete_request(int(rid))
            return {"ok": True}

        # ---- clients ----------------------------------------------------------------------

        @route("GET", "/api/clients")
        def list_clients(self, viewer, _body):
            return store.clients()

        @route("POST", "/api/clients")
        def new_client(self, viewer, body):
            return store.save_client(body)

        @route("GET", f"/api/clients/{ID}")
        def get_client(self, viewer, _body, cid):
            return store.client(int(cid))

        @route("PATCH", f"/api/clients/{ID}")
        def edit_client(self, viewer, body, cid):
            return store.save_client(body, int(cid))

        @route("DELETE", f"/api/clients/{ID}", "admin")
        def delete_client(self, viewer, _body, cid):
            store.delete_client(int(cid))
            return {"ok": True}

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

        @route("PUT", "/api/options/(kind|goal|segment)", "admin")
        def options(self, viewer, body, lst):
            store.set_options(lst, body.get("values"))
            return store.options()

        # ---- passkeys and invites ---------------------------------------------------------

        @route("POST", "/api/invite", "admin")
        def invite(self, viewer, body):
            if not auth.enabled:
                raise Reply(400, {"error": "convites precisam de passkeys (PAUTA_AUTH)"})
            token, expires = auth.create_invite(
                admin=bool(body.get("admin")),
                uses=int(body.get("uses") or 1),
                created_by=viewer["account"],
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
            if body.get("invite"):
                return auth.register_options(invite=str(body["invite"]), name=body.get("name"))
            acc = auth.account_from_cookie(self.headers.get("Cookie"))
            if not acc:
                raise Reply(401, {"error": "entre primeiro para adicionar um aparelho"})
            return auth.register_options(account=acc)

        @route("POST", "/api/passkey/register/verify", "open")
        def register_verify(self, viewer, body):
            acc = auth.register_verify(body.get("flow"), body.get("credential") or {})
            me = {
                "auth": True,
                "logged_in": True,
                "account": acc["id"],
                "name": acc["name"],
                "is_admin": bool(acc["is_admin"]),
            }
            return me, auth.make_cookie(acc["id"], self._secure())

        @route("POST", "/api/passkey/login/options", "open")
        def login_options(self, viewer, _body):
            if not auth.enabled:
                raise Reply(400, {"error": "passkeys estão desligadas"})
            return auth.login_options()

        @route("POST", "/api/passkey/login/verify", "open")
        def login_verify(self, viewer, body):
            acc = auth.login_verify(body.get("flow"), body.get("credential") or {})
            me = {
                "auth": True,
                "logged_in": True,
                "account": acc["id"],
                "name": acc["name"],
                "is_admin": bool(acc["is_admin"]),
            }
            return me, auth.make_cookie(acc["id"], self._secure())

        @route("POST", "/api/logout", "open")
        def logout(self, viewer, _body):
            return {"ok": True}, auth.clear_cookie(self._secure())

    return Handler
