"""A fake push service on localhost: it takes the empty pushes the app sends to a device's
address and keeps what arrived, to assert on. Tests never call a real one.

Point a Push at it with `Push(store, services=(fake.host,), scheme="http")`; a device's
address is `fake.endpoint("piero-phone")`. Put a name in `fake.gone` and the service
answers 410 for it, as a real one does once the person removed the app.
"""

from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakePush:
    def __init__(self):
        self.pushes: list[dict] = []  # {device, authorization, ttl, body}
        self.gone: set[str] = set()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):  # noqa: N802
                device = self.path.rsplit("/", 1)[1]
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                fake.pushes.append(
                    {
                        "device": device,
                        "authorization": self.headers.get("Authorization", ""),
                        "ttl": self.headers.get("TTL", ""),
                        "body": body,
                    }
                )
                self.send_response(410 if device in fake.gone else 201)
                self.send_header("Content-Length", "0")
                self.end_headers()

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.host = f"127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, args=(0.02,), daemon=True).start()

    def endpoint(self, device: str) -> str:
        return f"http://{self.host}/send/{device}"

    def wait(self, n: int, seconds: float = 3.0) -> list[str]:
        """The devices pushed so far, once there are `n` of them (the app sends on a thread)."""
        deadline = time.monotonic() + seconds
        while len(self.pushes) < n and time.monotonic() < deadline:
            time.sleep(0.01)
        return [p["device"] for p in self.pushes]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
