"""A fake Microsoft login and Graph on localhost: the device code flow, token refresh, upload
sessions, downloads, thumbnails, sharing links and deletes, with enough state to assert on.

Tests never talk to the real Microsoft. Point a OneDrive at it with
`OneDrive(path, client_id=CLIENT, graph=fake.graph, login=fake.login)`.
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

CLIENT = "00000000-0000-0000-0000-00000000c1d0"
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)


class FakeGraph:
    def __init__(self):
        self.approved = False  # the person typed the code and said yes
        self.deny = False
        self.refresh_fails = ""  # an OAuth error code for the next refreshes
        self.refreshes = 0
        self.token_n = 0
        self.items: dict[str, dict] = {}  # id -> {name, path, data, mime, folder}
        self.sessions: dict[str, dict] = {}
        self.links: list[str] = []
        self.deleted: list[str] = []
        self.scopes: list[str] = []
        self.fail_upload = False
        self.down = False  # Graph answers 503
        self.quota_full = False
        self._n = 0
        self._lock = threading.Lock()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status, doc=None, raw=None, ctype="application/json"):
                body = raw if raw is not None else json.dumps(doc or {}).encode()
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _body(self):
                n = int(self.headers.get("Content-Length") or 0)
                return self.rfile.read(n) if n else b""

            def do_POST(self):  # noqa: N802
                fake.route(self, "POST")

            def do_GET(self):  # noqa: N802
                fake.route(self, "GET")

            def do_PUT(self):  # noqa: N802
                fake.route(self, "PUT")

            def do_DELETE(self):  # noqa: N802
                fake.route(self, "DELETE")

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, args=(0.02,), daemon=True).start()
        base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.base = base
        self.login = f"{base}/consumers/oauth2/v2.0"
        self.graph = f"{base}/v1.0"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def add_item(self, name: str, data: bytes, mime: str = "image/png") -> str:
        with self._lock:
            self._n += 1
            iid = f"ITEM{self._n}"
            self.items[iid] = {"name": name, "path": name, "data": data, "mime": mime, "folder": ""}
        return iid

    def _tokens(self):
        self.token_n += 1
        return {
            "access_token": f"at{self.token_n}",
            "refresh_token": f"rt{self.token_n}",
            "expires_in": 3600,
        }

    # ---- routing --------------------------------------------------------------------------

    def route(self, h, method):
        url = urlparse(h.path)
        path = unquote(url.path)
        body = h._body()
        if path.startswith("/consumers/oauth2/v2.0/"):
            return self._login(h, path.rsplit("/", 1)[1], parse_qs(body.decode()))
        if path.startswith("/upload/"):
            return self._upload(h, method, path.split("/")[2], body)
        if path.startswith("/download/"):
            item = self.items.get(path.split("/")[2])
            return h._send(200, raw=item["data"], ctype=item["mime"]) if item else h._send(404)
        if path.startswith("/thumbs/"):
            return h._send(200, raw=PNG, ctype="image/png")
        if not path.startswith("/v1.0/"):
            return h._send(404)
        auth = h.headers.get("Authorization") or ""
        if not re.fullmatch(r"Bearer at\d+", auth) or auth != f"Bearer at{self.token_n}":
            return h._send(401, {"error": {"code": "InvalidAuthenticationToken"}})
        if self.down:
            return h._send(503, {"error": {"code": "serviceNotAvailable"}})
        return self._graph(h, method, path[len("/v1.0") :], body)

    def _login(self, h, step, form):
        one = lambda k: (form.get(k) or [""])[0]  # noqa: E731
        if one("client_id") != CLIENT:
            return h._send(400, {"error": "invalid_client"})
        if step == "devicecode":
            self.scopes.append(one("scope"))
            return h._send(
                200,
                {
                    "device_code": "DEV-CODE",
                    "user_code": "ABCD-1234",
                    "verification_uri": "https://microsoft.com/link",
                    "expires_in": 900,
                    "interval": 0,
                },
            )
        grant = one("grant_type")
        if grant.endswith("device_code"):
            if self.deny:
                return h._send(400, {"error": "access_denied"})
            if not self.approved:
                return h._send(400, {"error": "authorization_pending"})
            return h._send(200, self._tokens())
        if grant == "refresh_token":
            if self.refresh_fails:
                return h._send(400, {"error": self.refresh_fails})
            if one("refresh_token") != f"rt{self.token_n}":
                return h._send(400, {"error": "invalid_grant"})
            self.refreshes += 1
            return h._send(200, self._tokens())
        return h._send(400, {"error": "unsupported_grant_type"})

    def _graph(self, h, method, path, body):
        if path == "/me":
            return h._send(200, {"displayName": "Piero", "userPrincipalName": "piero@example.com"})
        if path == "/me/drive":
            return h._send(200, {"quota": {"used": 5 * 2**30, "total": 1024 * 2**30}})
        m = re.fullmatch(r"/me/drive/(special/approot|root):/(.+):/createUploadSession", path)
        if m and method == "POST":
            if self.quota_full:
                return h._send(507, {"error": {"code": "quotaLimitReached"}})
            sid = f"S{len(self.sessions) + 1}"
            prefix = "approot" if m.group(1) == "special/approot" else "root"
            self.sessions[sid] = {"path": f"{prefix}/{m.group(2)}", "data": b"", "body": body}
            return h._send(200, {"uploadUrl": f"{self.base}/upload/{sid}"})
        m = re.fullmatch(r"/me/drive/items/([^/]+)(/.*)?", path)
        if not m:
            return h._send(404, {"error": {"code": "itemNotFound"}})
        iid, rest = m.group(1), m.group(2) or ""
        item = self.items.get(iid)
        if method == "DELETE" and not rest:
            if not item:
                return h._send(404, {"error": {"code": "itemNotFound"}})
            self.deleted.append(iid)
            del self.items[iid]
            return h._send(204, raw=b"")
        if method == "POST" and rest == "/createLink":
            link = f"https://1drv.ms/f/s!{iid}"
            self.links.append(iid)
            return h._send(200, {"link": {"webUrl": link}})
        if not item:
            return h._send(404, {"error": {"code": "itemNotFound"}})
        if rest == "/thumbnails/0/medium":
            if not item["mime"].startswith(("image/", "video/")):
                return h._send(404, {"error": {"code": "itemNotFound"}})
            return h._send(200, {"url": f"{self.base}/thumbs/{iid}"})
        if not rest:
            return h._send(
                200, {"id": iid, "@microsoft.graph.downloadUrl": f"{self.base}/download/{iid}"}
            )
        return h._send(404, {"error": {"code": "itemNotFound"}})

    def _upload(self, h, method, sid, body):
        s = self.sessions.get(sid)
        if not s:
            return h._send(404)
        if method == "DELETE":
            del self.sessions[sid]
            return h._send(204, raw=b"")
        if h.headers.get("Authorization"):
            return h._send(400, {"error": {"code": "invalidRequest"}})  # like the real one
        if self.fail_upload:
            return h._send(500, {"error": {"code": "generalException"}})
        m = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", h.headers.get("Content-Range") or "")
        start, end, total = map(int, m.groups())
        assert start == len(s["data"]) and end - start + 1 == len(body)
        s["data"] += body
        if len(s["data"]) < total:
            return h._send(202, {"nextExpectedRanges": [f"{len(s['data'])}-"]})
        folder_path, name = s["path"].rsplit("/", 1)
        taken = {i["path"] for i in self.items.values()}
        n, final = 1, name
        while f"{folder_path}/{final}" in taken:
            stem, dot, ext = name.rpartition(".")
            n += 1
            final = f"{stem} {n}.{ext}" if dot else f"{name} {n}"
        folder = "FOLDER-" + folder_path.replace("/", "~")
        with self._lock:
            self._n += 1
            iid = f"ITEM{self._n}"
            mime = "image/png" if final.endswith(".png") else "application/pdf"
            if final.endswith(".mp4"):
                mime = "video/mp4"
            self.items[iid] = {
                "name": final,
                "path": f"{folder_path}/{final}",
                "data": s["data"],
                "mime": mime,
                "folder": folder,
            }
        del self.sessions[sid]
        return h._send(
            201,
            {
                "id": iid,
                "name": final,
                "size": len(s["data"]),
                "file": {"mimeType": mime},
                "parentReference": {"id": folder},
            },
        )
