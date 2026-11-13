"""A fake Meta on localhost for the Publicações tests (docs/publishing-spec.md): Unified
Login's dialog (Facebook Login for Business with an Instagram configuration), the code
exchange for a system-user token, the Instagram accounts that token was given, and the
three publishing calls. Like the real one it fetches the image itself from the address it
is given, so a test fails when that address isn't public at that moment, and it checks the
app secret's proof on every call.

  dialog   <base>/dialog/oauth         (www.facebook.com)
  graph    <base>/graph                (graph.facebook.com: /v27.0/oauth/access_token, ...)
"""

import hashlib
import hmac
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
IG_CONFIG_ID = "1692300000000950"
IG_SECRET = "ig-app-secret-for-tests"
IG_ID = "17841400000000001"  # the professional account's id: what the paths take
USERNAME = "du7dev"


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
        self.tokens: set[str] = set()  # the system-user tokens that work
        self.deny = False  # the person cancels in the dialog
        self.expires_in: int | None = None  # a "never" configuration: no expiry in the answer
        self.username = USERNAME
        self.ig_id = IG_ID
        # the Instagram accounts the person shared in the login (None: this one profile)
        self.accounts: list[dict] | None = None
        self.not_professional = False  # the container call answers (#10)
        self.bad_proof = 0  # calls that came without the app secret's proof
        self.revoked = False  # every token answers 190
        self.fail_fetch = False  # the container step can't download the image
        self.at_limit = False  # media_publish answers "max posts reached"
        self.not_ready = 0  # how many status reads say IN_PROGRESS first
        self.container_error = False  # the container ends in ERROR
        self.down = False
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
        self.dialog = f"{self.base}/dialog/oauth"
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
        if path == "/dialog/oauth":
            return self._authorize(h, q)
        parts = path.removeprefix("/graph/").split("/")
        if not path.startswith("/graph/v") or len(parts) < 2:
            return h._send(404, graph_error(100, message="unknown path"))
        if parts[1:] == ["oauth", "access_token"]:
            return self._exchange(h, q)
        token = (h.headers.get("Authorization") or "").removeprefix("Bearer ")
        if self.revoked or token not in self.tokens:
            return h._send(400, graph_error(190, message="Invalid OAuth 2.0 Access Token"))
        proof = hmac.new(IG_SECRET.encode(), token.encode(), hashlib.sha256).hexdigest()
        if q.get("appsecret_proof", form.get("appsecret_proof")) != proof:
            self.bad_proof += 1
            return h._send(400, graph_error(100, message="Invalid appsecret_proof"))
        return self._graph(h, method, parts[1:], q, form)

    def _authorize(self, h, q):
        assert q["client_id"] == IG_APP_ID and q["config_id"] == IG_CONFIG_ID, q
        assert q["response_type"] == "code" and "scope" not in q, q
        assert q["override_default_response_type"] == "true", q
        back = q["redirect_uri"]
        if self.deny:
            why = {
                "error": "access_denied",
                "error_reason": "user_denied",
                "error_description": "Permissions error",
                "state": q["state"],
            }
            return h._send(302, location=f"{back}?{urlencode(why)}")
        code = self._next("code-")
        self.codes[code] = back
        # Facebook's dialog appends "#_=_" after the query
        return h._send(302, location=f"{back}?{urlencode({'code': code, 'state': q['state']})}#_=_")

    def _exchange(self, h, q):
        good = (
            q.get("client_id") == IG_APP_ID
            and q.get("client_secret") == IG_SECRET
            and self.codes.pop(q.get("code", ""), None) == q.get("redirect_uri")
        )
        if not good:
            return h._send(400, graph_error(100, 36009, "This authorization code has been used."))
        token = self._next("suat-")
        self.tokens.add(token)
        doc = {"access_token": token, "token_type": "bearer"}
        if self.expires_in:
            doc["expires_in"] = self.expires_in
        return h._send(200, doc)

    def _graph(self, h, method, parts, q, form):
        if parts == ["me", "assigned_instagram_accounts"]:
            rows = self.accounts
            if rows is None:
                rows = [{"id": self.ig_id, "username": self.username}]
            return h._send(200, {"data": rows, "paging": {"cursors": {}}})
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
        if self.not_professional:
            message = "(#10) Access is denied because the instagram account type is not business"
            return h._send(400, graph_error(10, message=message))
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
