"""Notifications on a person's own devices (Web Push): a new request, a status change or a
comment tells everyone else who switched them on (Perfil), on each device they did it on.

A push carries no text. It only wakes the device, whose service worker (static/sw.js) then
asks this server, signed in as the person, what to show (`POST /api/push/news`). So nothing
of the team's data passes through Apple's, Google's or Mozilla's push services, and there
is no message encryption to get right here: the one piece of crypto is the signature that
tells the push service who is sending (VAPID, RFC 8292), made by `cryptography`.

The signing key is a file next to the database, like the session key and never in it. A
device's subscription is tied to that key: without the file every device has to switch
notifications on again (the page does that by itself the next time it opens).

A device's address is given by its browser, so it is only ever called when it is on one of
the push services below: the server never fetches an address a client made up.
"""

from __future__ import annotations

import base64
import http.client
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from . import obs
from .db import STATUSES, Store

# Chrome and Android, Safari and iOS, Firefox, Edge (wns2-xx.notify.windows.com)
SERVICES = (
    "fcm.googleapis.com",
    "web.push.apple.com",
    "updates.push.services.mozilla.com",
    "notify.windows.com",
)
MAX_ENDPOINT = 2000  # characters of a device's address
TTL = 24 * 3600  # seconds a push service keeps a push for a device that is off
TOKEN_SECONDS = 12 * 3600  # how long one signature is good for (a day at most)
CUT = 140  # characters of a request's or a comment's text in a notification
HOST = re.compile(r"[a-z0-9.-]+(:\d+)?")  # a push service's host, as urlsplit lowercases it


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _cut(text: str) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= CUT else text[: CUT - 1].rstrip() + "…"


def describe(row: dict) -> dict:
    """One row of Store.push_news as what the device shows: title, body, the request's
    address in the app, and a tag (a newer notification about the same request replaces
    the one still on the screen)."""
    who = (row["by_name"] or "Alguém").split()[0]
    if row["kind"] == "created":
        title = f"Novo pedido · {row['client']}"
        body = _cut(": ".join(p for p in (row["request_kind"], row["what"]) if p))
    elif row["kind"] == "comment":
        title = f"{who} comentou · {row['client']}"
        body = _cut(row["text"])
    else:  # status: "todo>waiting"
        to = row["text"].rpartition(">")[2]
        title = f"{STATUSES.get(to, to)} · {row['client']}"
        waiting = to == "waiting" and row["missing"]
        body = _cut(f"Falta: {row['missing']}" if waiting else row["what"])
    return {
        "title": title,
        "body": body,
        "url": f"/#/pedido/{row['request']}",
        "tag": f"pedido-{row['request']}",
    }


class Push:
    def __init__(
        self,
        store: Store,
        contact: str = "",
        services: tuple[str, ...] = SERVICES,
        scheme: str = "https",
    ):
        self.store = store
        # who a push service may write to about this sender: the app's own address
        self.contact = contact or "https://pauta.cc"
        self.services, self.scheme = services, scheme  # the tests' fake is http on localhost
        self.key_file = Path(f"{store.path}.push-key")
        self._key: ec.EllipticCurvePrivateKey | None = None
        self._lock = threading.Lock()

    # ---- the signing key ----------------------------------------------------------------

    def _private(self) -> ec.EllipticCurvePrivateKey:
        with self._lock:
            if self._key is None:
                try:
                    fd = os.open(self.key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                except FileExistsError:
                    pem = self.key_file.read_bytes()
                    self._key = serialization.load_pem_private_key(pem, password=None)
                else:
                    self._key = ec.generate_private_key(ec.SECP256R1())
                    with os.fdopen(fd, "wb") as f:
                        f.write(
                            self._key.private_bytes(
                                serialization.Encoding.PEM,
                                serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption(),
                            )
                        )
            return self._key

    @property
    def public_key(self) -> str:
        """What a browser subscribes with (its applicationServerKey), base64url."""
        point = (
            self._private()
            .public_key()
            .public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        )
        return _b64(point)

    def _authorization(self, audience: str) -> str:
        """The VAPID header for one push service: a JWT (ES256) saying who sends, until when."""
        claims = {"aud": audience, "exp": int(time.time()) + TOKEN_SECONDS, "sub": self.contact}
        head = _b64(b'{"typ":"JWT","alg":"ES256"}')
        signed = f"{head}.{_b64(json.dumps(claims, separators=(',', ':')).encode())}"
        der = self._private().sign(signed.encode(), ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der)  # a JWT wants the two numbers, 32 bytes each
        token = f"{signed}.{_b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
        return f"vapid t={token}, k={self.public_key}"

    # ---- devices ------------------------------------------------------------------------

    def _host(self, endpoint) -> str:
        """Where a device's address would be called (`host` or `host:port`), or "" when the
        server won't: only a known push service, on its own port, with nothing else in the
        address (no user@, no odd characters a resolver might read another way)."""
        if not isinstance(endpoint, str) or not 0 < len(endpoint) <= MAX_ENDPOINT:
            return ""
        try:
            url = urlsplit(endpoint)
            host = f"{url.hostname}:{url.port}" if url.port else url.hostname or ""
        except ValueError:
            return ""
        plain = url.username is None and url.password is None and HOST.fullmatch(host)
        known = any(host == s or host.endswith(f".{s}") for s in self.services)
        return host if url.scheme == self.scheme and plain and known else ""

    def allowed(self, endpoint) -> bool:
        return bool(self._host(endpoint))

    def send(self, endpoint: str) -> int:
        """One empty push to one device; the push service's status (0: it did not answer,
        or the address is not one the server calls)."""
        host = self._host(endpoint)
        if not host:
            return 0
        url = urlsplit(endpoint)
        make = http.client.HTTPSConnection if self.scheme == "https" else http.client.HTTPConnection
        conn = make(host, timeout=10)  # http.client follows no redirect
        try:
            conn.request(
                "POST",
                url.path + (f"?{url.query}" if url.query else ""),
                headers={
                    "Authorization": self._authorization(f"{url.scheme}://{host}"),
                    "TTL": str(TTL),
                    "Content-Length": "0",
                },
            )
            res = conn.getresponse()
            res.read()
            return res.status
        except (OSError, http.client.HTTPException):
            return 0
        finally:
            conn.close()

    def tell_others(self, by: int | None) -> None:
        """Wake every other person's devices, off the request's thread. A device its push
        service no longer knows (404, 410: the app was removed, the permission taken back)
        is forgotten."""
        targets = self.store.push_targets(by)
        if targets:
            threading.Thread(target=self._send_all, args=(targets,), daemon=True).start()

    def _send_all(self, targets: list[str]) -> None:
        sent = gone = failed = 0
        for endpoint in targets:
            status = self.send(endpoint)
            if status in (404, 410):
                self.store.push_forget(endpoint=endpoint)
                gone += 1
            elif 200 <= status < 300:
                sent += 1
            else:
                failed += 1
                obs.event("push_failed", logging.WARNING, status=status)
        obs.event("push", sent=sent, gone=gone, failed=failed)
