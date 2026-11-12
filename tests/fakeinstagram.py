"""A fake Instagram on localhost for the Publicações tests (docs/publishing-spec.md): the
login dialog, the code exchange, the 60-day token and its refresh, /me, and the three
publishing calls. Like the real one it fetches the image itself from the address it is
given, so a test fails when that address isn't public at that moment.

  dialog   <base>/oauth/authorize      (www.instagram.com)
  api      <base>                      (api.instagram.com: POST /oauth/access_token)
  graph    <base>/graph                (graph.instagram.com: /access_token, /v27.0/...)
"""

import json
import struct
import threading
import urllib.error
import urllib.request
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

IG_APP_ID = "990011223344"
IG_SECRET = "ig-app-secret-for-tests"
IG_ID = "17841400000000001"  # the professional account's id: what later paths take
SCOPED_ID = "9988776655"  # the app-scoped one the code exchange also returns
USERNAME = "du7.dev"
EXPIRES_IN = 5183944  # about 60 days


def ig_secret(db_path) -> Path:
    path = Path(f"{db_path}.ig-secret")
    path.write_text(IG_SECRET + "\n")
    return path


def jpeg(width: int = 1080, height: int = 1350, pad: int = 0) -> bytes:
    """The smallest thing with a JPEG's frame header (not a picture a decoder would show)."""
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, height, width, 3) + bytes(9)
    return b"\xff\xd8" + app0 + sof + bytes(pad) + b"\xff\xd9"


def png(width: int = 400, height: int = 400, rgb: tuple[int, int, int] = (90, 70, 200)) -> bytes:
    """A real one-colour PNG, for the browser to open and turn into a JPEG."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    row = b"\x00" + bytes(rgb) * width
    head = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", head)
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


def graph_error(code: int, subcode: int | None = None, message: str = "refused") -> dict:
    err = {"message": message, "type": "IGApiException", "code": code, "fbtrace_id": "T"}
    if subcode:
        err["error_subcode"] = subcode
    return {"error": err}


class FakeInstagram:
    def __init__(self):
        self.codes: dict[str, str] = {}  # code -> the redirect_uri it was issued for
        self.tokens: set[str] = set()  # the long-lived tokens that work
        self.deny = False  # the person cancels in the dialog
        self.flat = False  # answer the exchange and /me unwrapped, as the API also has
        self.account_type = "Business"
        self.username = USERNAME
        self.ig_id = IG_ID
        self.revoked = False  # every token answers 190
        self.fail_fetch = False  # the container step can't download the image
        self.at_limit = False  # media_publish answers "max posts reached"
        self.not_ready = 0  # how many status reads say IN_PROGRESS first
        self.container_error = False  # the container ends in ERROR
        self.down = False
        self.refreshes = 0
        self.fetched: list[dict] = []  # each image fetch: url, status, content type, magic
        self.containers: dict[str, dict] = {}
        self.published: list[dict] = []  # what went out: ig_id, caption, alt_text, image
        self.calls: list[str] = []
        self._n = 0
        self._lock = threading.Lock()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status, doc=None, location=None):
                body = json.dumps(doc or {}).encode()
                self.send_response(status)
                if location:
                    self.send_header("Location", location)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # noqa: N802
                fake.route(self, "GET", {})

            def do_POST(self):  # noqa: N802
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                fake.route(self, "POST", {k: v[0] for k, v in parse_qs(raw.decode()).items()})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, args=(0.02,), daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.dialog = f"{self.base}/oauth/authorize"
        self.api = self.base
        self.graph = f"{self.base}/graph"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def _next(self, prefix: str) -> str:
        with self._lock:
            self._n += 1
            return f"{prefix}{self._n}"

    # ---- routing --------------------------------------------------------------------------

    def route(self, h, method: str, form: dict):
        url = urlparse(h.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        path = url.path
        self.calls.append(f"{method} {path}")
        if self.down:
            return h._send(500, graph_error(2, message="down"))
        if path == "/oauth/authorize":
            return self._authorize(h, q)
        if path == "/oauth/access_token" and method == "POST":
            return self._exchange(h, form)
        if path == "/graph/access_token":
            return self._long(h, q)
        if path == "/graph/refresh_access_token":
            return self._refresh(h, q)
        parts = path.removeprefix("/graph/").split("/")
        if not path.startswith("/graph/v") or len(parts) < 2:
            return h._send(404, graph_error(100, message="unknown path"))
        token = (h.headers.get("Authorization") or "").removeprefix("Bearer ") or q.get(
            "access_token", form.get("access_token", "")
        )
        if self.revoked or token not in self.tokens:
            return h._send(400, graph_error(190, message="Invalid OAuth 2.0 Access Token"))
        return self._graph(h, method, parts[1:], q, form)

    def _authorize(self, h, q):
        assert q["client_id"] == IG_APP_ID and q["response_type"] == "code", q
        assert q["scope"] == "instagram_business_basic,instagram_business_content_publish", q
        back = q["redirect_uri"]
        if self.deny:
            why = {
                "error": "access_denied",
                "error_reason": "user_denied",
                "error_description": "The user denied your request",
                "state": q["state"],
            }
            return h._send(302, location=f"{back}?{urlencode(why)}")
        code = self._next("code-")
        self.codes[code] = back
        # the real one appends "#_" after the code
        return h._send(302, location=f"{back}?{urlencode({'code': code, 'state': q['state']})}#_")

    def _exchange(self, h, form):
        good = (
            form.get("client_id") == IG_APP_ID
            and form.get("client_secret") == IG_SECRET
            and form.get("grant_type") == "authorization_code"
            and self.codes.pop(form.get("code", ""), None) == form.get("redirect_uri")
        )
        if not good:
            return h._send(
                400,
                {
                    "error_type": "OAuthException",
                    "code": 400,
                    "error_message": "Matching code was not found or was already used",
                },
            )
        short = self._next("short-")
        self._short = short
        doc = {"access_token": short, "user_id": SCOPED_ID, "permissions": "a,b"}
        return h._send(200, doc if self.flat else {"data": [doc]})

    def _long(self, h, q):
        good = (
            q.get("grant_type") == "ig_exchange_token"
            and q.get("client_secret") == IG_SECRET
            and q.get("access_token") == getattr(self, "_short", None)
        )
        if not good:
            return h._send(400, graph_error(190))
        token = self._next("long-")
        self.tokens.add(token)
        return h._send(
            200, {"access_token": token, "token_type": "bearer", "expires_in": EXPIRES_IN}
        )

    def _refresh(self, h, q):
        old = q.get("access_token")
        if q.get("grant_type") != "ig_refresh_token" or old not in self.tokens or self.revoked:
            return h._send(400, graph_error(190))
        self.refreshes += 1
        token = self._next("long-")
        self.tokens.discard(old)
        self.tokens.add(token)
        return h._send(
            200, {"access_token": token, "token_type": "bearer", "expires_in": EXPIRES_IN}
        )

    def _graph(self, h, method, parts, q, form):
        if parts == ["me"]:
            me = {
                "id": SCOPED_ID,
                "user_id": self.ig_id,
                "username": self.username,
                "name": "Du7",
                "account_type": self.account_type,
            }
            return h._send(200, me if self.flat else {"data": [me]})
        if method == "POST" and parts == [self.ig_id, "media"]:
            return self._container(h, form)
        if method == "POST" and parts == [self.ig_id, "media_publish"]:
            return self._publish(h, form)
        if parts == [self.ig_id, "content_publishing_limit"]:
            used = len(self.published)
            row = {"quota_usage": used, "config": {"quota_total": 50, "quota_duration": 86400}}
            return h._send(200, {"data": [row]})
        if len(parts) == 1 and parts[0] in self.containers:
            box = self.containers[parts[0]]
            if self.container_error:
                return h._send(200, {"status_code": "ERROR", "id": parts[0]})
            if box["waits"] > 0:
                box["waits"] -= 1
                return h._send(200, {"status_code": "IN_PROGRESS", "id": parts[0]})
            return h._send(200, {"status_code": "FINISHED", "id": parts[0]})
        if len(parts) == 1 and any(p["id"] == parts[0] for p in self.published):
            return h._send(200, {"permalink": f"https://www.instagram.com/p/{parts[0]}/"})
        return h._send(404, graph_error(100, 33, "unknown object"))

    def _container(self, h, form):
        url = form.get("image_url", "")
        seen = {"url": url, "status": 0, "type": "", "magic": b""}
        try:
            with urllib.request.urlopen(url, timeout=5) as r:  # noqa: S310 - the app's own
                raw = r.read()
                seen.update(status=r.status, type=r.headers.get("Content-Type", ""), magic=raw[:3])
        except urllib.error.HTTPError as e:
            seen["status"] = e.code
        except OSError:
            pass
        self.fetched.append(seen)
        if self.fail_fetch or seen["status"] != 200 or seen["magic"] != b"\xff\xd8\xff":
            return h._send(400, graph_error(9004, 2207052, "could not fetch"))
        cid = self._next("1790")
        self.containers[cid] = {
            "image": url,
            "caption": form.get("caption", ""),
            "alt_text": form.get("alt_text", ""),
            "waits": self.not_ready,
        }
        return h._send(200, {"id": cid})

    def _publish(self, h, form):
        box = self.containers.get(form.get("creation_id", ""))
        if not box:
            return h._send(400, graph_error(24, 2207008, "container missing"))
        if self.at_limit:
            return h._send(400, graph_error(9, 2207042, "max posts reached"))
        mid = self._next("1800")
        self.published.append({"id": mid, "ig_id": self.ig_id, **box})
        return h._send(200, {"id": mid})
