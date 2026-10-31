"""A software authenticator (real P-256 signatures) and HTTP helpers for the passkey tests."""

import hashlib
import json
import secrets
import struct
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn.helpers import bytes_to_base64url

from pauta.server import make_handler

RP_ID = "localhost"
ORIGIN = "http://localhost:8088"


class SoftPasskey:
    """Enough of a platform authenticator to create and use one discoverable credential."""

    def __init__(self, rp_id: str = RP_ID, origin: str = ORIGIN):
        self.rp_id, self.origin = rp_id, origin  # the domain and page it was made on
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.cred_id = secrets.token_bytes(16)
        self.count = 0

    def _auth_data(self, flags: int, attested: bytes = b"") -> bytes:
        self.count += 1
        rp_hash = hashlib.sha256(self.rp_id.encode()).digest()
        return rp_hash + bytes([flags]) + struct.pack(">I", self.count) + attested

    def _client_data(self, kind: str, challenge: str) -> bytes:
        return json.dumps({"type": kind, "challenge": challenge, "origin": self.origin}).encode()

    def create(self, options: dict) -> dict:
        nums = self.key.public_key().public_numbers()
        cose = cbor2.dumps(
            {1: 2, 3: -7, -1: 1, -2: nums.x.to_bytes(32, "big"), -3: nums.y.to_bytes(32, "big")}
        )
        attested = bytes(16) + struct.pack(">H", len(self.cred_id)) + self.cred_id + cose
        auth_data = self._auth_data(0x45, attested)  # UP | UV | AT
        att = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        cid = bytes_to_base64url(self.cred_id)
        client = self._client_data("webauthn.create", options["challenge"])
        return {
            "id": cid,
            "rawId": cid,
            "type": "public-key",
            "clientExtensionResults": {},
            "response": {
                "clientDataJSON": bytes_to_base64url(client),
                "attestationObject": bytes_to_base64url(att),
                "transports": ["internal"],
            },
        }

    def get(self, options: dict, user_handle: str) -> dict:
        auth_data = self._auth_data(0x05)  # UP | UV
        client = self._client_data("webauthn.get", options["challenge"])
        sig = self.key.sign(auth_data + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
        cid = bytes_to_base64url(self.cred_id)
        return {
            "id": cid,
            "rawId": cid,
            "type": "public-key",
            "clientExtensionResults": {},
            "response": {
                "clientDataJSON": bytes_to_base64url(client),
                "authenticatorData": bytes_to_base64url(auth_data),
                "signature": bytes_to_base64url(sig),
                "userHandle": user_handle,
            },
        }


def start(store, auth, limiter=None):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(store, auth, limiter))
    # a short poll so shutdown() doesn't wait half a second per test
    threading.Thread(target=httpd.serve_forever, args=(0.02,), daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def call(url, data=None, cookie=None, method=None, headers=None):
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    if cookie:
        hdrs["Cookie"] = cookie
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode() if data is not None else None,
        headers=hdrs,
        method=method or ("POST" if data is not None else "GET"),
    )
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read() or b"{}"), r.headers
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}"), e.headers


def join(base, token, name, key):
    _, opts, _ = call(f"{base}/api/passkey/register/options", {"invite": token, "name": name})
    if "flow" not in opts:
        return 400, opts, ""
    body = {"flow": opts["flow"], "credential": key.create(opts["options"])}
    status, me, headers = call(f"{base}/api/passkey/register/verify", body)
    return status, me, (headers.get("Set-Cookie") or "").split(";")[0]


def login(base, key, user_handle=""):
    _, opts, _ = call(f"{base}/api/passkey/login/options", {})
    body = {"flow": opts["flow"], "credential": key.get(opts["options"], user_handle)}
    status, me, headers = call(f"{base}/api/passkey/login/verify", body)
    return status, me, (headers.get("Set-Cookie") or "").split(";")[0]
