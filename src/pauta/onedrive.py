"""Files on requests, stored in one OneDrive (a personal Microsoft account) through Graph.

The team uploads through Pauta; Pauta passes the bytes on to OneDrive in chunks, so nothing
but the file's id and name stays on du7. Teammates never need access to that OneDrive: a
download is a redirect to a short-lived link Graph hands out.

Signing in uses the device code flow: an admin clicks "Conectar", Pauta shows a short code,
the owner of the OneDrive types it at microsoft.com/link and approves. There is no client
secret and no redirect URL. The refresh token lives in a file next to the database (like the
session key), never in it, so the nightly backups can't be turned into OneDrive access.

Configuration (environment):
  PAUTA_ONEDRIVE_CLIENT_ID   the app registration's client id; unset turns files off
  PAUTA_ONEDRIVE_ROOT        optional folder in the drive, e.g. /Clientes/Pauta. Unset keeps
                             Pauta in its own app folder (Apps/<app name>) and asks for
                             Files.ReadWrite.AppFolder only; set asks for the whole drive
  PAUTA_UPLOAD_MAX_MB        largest file accepted (default 200)
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import obs

GRAPH = "https://graph.microsoft.com/v1.0"
LOGIN = "https://login.microsoftonline.com/consumers/oauth2/v2.0"
APP_SCOPES = "offline_access User.Read Files.ReadWrite.AppFolder"
DRIVE_SCOPES = "offline_access User.Read Files.ReadWrite"
# upload chunks must be multiples of 320 KiB; 5 MiB keeps memory low on the Pi
CHUNK = 16 * 320 * 1024
TIMEOUT = 30
DEFAULT_MAX_MB = 200
# what OneDrive refuses in a file or folder name
BAD_NAME = re.compile(r'["*:<>?/\\|\x00-\x1f\x7f]')


class DriveError(Exception):
    """A user-facing reason (in Portuguese) a OneDrive step failed, with an HTTP status."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


NOT_CONNECTED = "o OneDrive não está conectado; um administrador conecta em Equipe"
UNAVAILABLE = "o OneDrive não respondeu; tente de novo"


def safe_name(name: str, limit: int = 120) -> str:
    """A name OneDrive accepts: no reserved characters, no leading/trailing dots or spaces."""
    name = BAD_NAME.sub("_", " ".join(str(name or "").split()))
    name = name.strip(" .")[:limit].strip(" .")
    return name or "arquivo"


def _limit_mb() -> int:
    try:
        return max(1, int(os.environ.get("PAUTA_UPLOAD_MAX_MB") or DEFAULT_MAX_MB))
    except ValueError:
        return DEFAULT_MAX_MB


class OneDrive:
    def __init__(
        self,
        db_path: Path,
        client_id: str = "",
        root: str = "",
        graph: str = GRAPH,
        login: str = LOGIN,
        max_mb: int | None = None,
        chunk: int = CHUNK,
    ):
        self.client_id = (client_id or "").strip()
        self.root = "/".join(safe_name(p) for p in (root or "").split("/") if p.strip())
        self.graph = graph.rstrip("/")
        self.login = login.rstrip("/")
        self.max_bytes = (max_mb or _limit_mb()) * 1024 * 1024
        self.chunk = chunk
        self.token_file = Path(f"{db_path}.onedrive-token")
        self._lock = threading.Lock()
        self._access: tuple[str, float] | None = None  # token, expiry
        self._pending: dict | None = None  # the device code flow in progress
        self.error = ""  # why the connection stopped working, until reconnected

    @classmethod
    def from_env(cls, db_path: Path) -> OneDrive:
        return cls(
            db_path,
            client_id=os.environ.get("PAUTA_ONEDRIVE_CLIENT_ID", ""),
            root=os.environ.get("PAUTA_ONEDRIVE_ROOT", ""),
        )

    @property
    def enabled(self) -> bool:
        return bool(self.client_id)

    @property
    def scopes(self) -> str:
        return DRIVE_SCOPES if self.root else APP_SCOPES

    # ---- the token file ---------------------------------------------------------------------

    def _saved(self) -> dict | None:
        try:
            doc = json.loads(self.token_file.read_text())
        except (OSError, ValueError):
            return None
        return doc if isinstance(doc, dict) and doc.get("refresh_token") else None

    def _save(self, doc: dict) -> None:
        tmp = self.token_file.with_name(self.token_file.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(doc, f)
        os.replace(tmp, self.token_file)

    @property
    def connected(self) -> bool:
        return self.enabled and self._saved() is not None

    # ---- HTTP -------------------------------------------------------------------------------

    def _http(self, method: str, url: str, data=None, headers=None, form=None):
        """One request. Returns (status, parsed JSON or raw bytes, headers); never raises for
        an HTTP error status, only for a network failure (DriveError)."""
        hdrs = dict(headers or {})
        if form is not None:
            data = urllib.parse.urlencode(form).encode()
            hdrs["Content-Type"] = "application/x-www-form-urlencoded"
        elif isinstance(data, dict):
            data = json.dumps(data).encode()
            hdrs["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                status, raw, rh = r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            status, raw, rh = e.code, e.read(), e.headers
        except (OSError, ValueError) as e:
            obs.event("onedrive_unreachable", logging.WARNING, error=type(e).__name__)
            raise DriveError(UNAVAILABLE) from None
        if "json" in (rh.get("Content-Type") or ""):
            try:
                return status, json.loads(raw or b"{}"), rh
            except ValueError:
                return status, {}, rh
        return status, raw, rh

    def _token_call(self, form: dict) -> tuple[int, dict]:
        status, doc, _ = self._http("POST", f"{self.login}/token", form=form)
        return status, doc if isinstance(doc, dict) else {}

    def _graph(self, method: str, path: str, data=None, ok=(200, 201, 202, 204)):
        status, doc, rh = self._http(
            method,
            f"{self.graph}{path}",
            data=data,
            headers={"Authorization": f"Bearer {self._token()}"},
        )
        if status == 401:  # revoked or expired early: one fresh token, one retry
            self._access = None
            status, doc, rh = self._http(
                method,
                f"{self.graph}{path}",
                data=data,
                headers={"Authorization": f"Bearer {self._token()}"},
            )
        if status == 404:
            raise DriveError("arquivo não encontrado no OneDrive", 404)
        if status not in ok:
            code = doc.get("error", {}).get("code") if isinstance(doc, dict) else None
            obs.event("onedrive_error", logging.WARNING, status=status, code=code)
            if code == "quotaLimitReached":
                raise DriveError("o OneDrive está cheio", 507)
            raise DriveError(UNAVAILABLE)
        return doc, rh

    # ---- signing in ---------------------------------------------------------------------------

    def start_connect(self) -> dict:
        """Begin the device code flow; returns what to show the person who approves it."""
        if not self.enabled:
            raise DriveError("defina PAUTA_ONEDRIVE_CLIENT_ID para usar o OneDrive", 400)
        status, doc, _ = self._http(
            "POST",
            f"{self.login}/devicecode",
            form={"client_id": self.client_id, "scope": self.scopes},
        )
        if status != 200 or not isinstance(doc, dict) or "device_code" not in doc:
            obs.event("onedrive_error", logging.WARNING, status=status, step="devicecode")
            raise DriveError("a Microsoft recusou o pedido de conexão; veja o app no Entra")
        with self._lock:
            self._pending = {
                "device_code": doc["device_code"],
                "user_code": doc["user_code"],
                "verification_uri": doc.get("verification_uri") or "https://microsoft.com/link",
                "expires": time.time() + int(doc.get("expires_in", 900)),
                "interval": int(doc.get("interval", 5)),
                "next": 0.0,
            }
        return self.pending()

    def pending(self) -> dict | None:
        p = self._pending
        if not p:
            return None
        return {
            "user_code": p["user_code"],
            "verification_uri": p["verification_uri"],
            "expires": int(p["expires"]),
            "interval": p["interval"],
        }

    def poll(self) -> str:
        """Ask once (at most every `interval` seconds) whether the code was approved.
        Returns 'connected', 'pending', 'expired', 'denied' or 'idle'."""
        with self._lock:
            p = self._pending
            if not p:
                return "idle"
            now = time.time()
            if now > p["expires"]:
                self._pending = None
                return "expired"
            if now < p["next"]:
                return "pending"
            p["next"] = now + p["interval"]
            status, doc = self._token_call(
                {
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "client_id": self.client_id,
                    "device_code": p["device_code"],
                }
            )
            if status != 200:
                err = doc.get("error")
                if err == "slow_down":
                    p["interval"] += 5
                if err in ("authorization_pending", "slow_down"):
                    return "pending"
                self._pending = None
                return "denied" if err in ("access_denied", "authorization_declined") else "expired"
            self._pending = None
            self._store_tokens(doc, {})
        me, _ = self._graph("GET", "/me?$select=displayName,userPrincipalName")
        saved = self._saved() or {}
        saved["account"] = me.get("userPrincipalName") or me.get("displayName") or ""
        saved["name"] = me.get("displayName") or ""
        self._save(saved)
        obs.event("onedrive_connected")
        return "connected"

    def _store_tokens(self, doc: dict, saved: dict) -> None:
        """Keep the new refresh token (Microsoft rotates them) and the access token."""
        if not doc.get("access_token") or not doc.get("refresh_token"):
            raise DriveError(UNAVAILABLE)
        self._save(
            {
                **saved,
                "refresh_token": doc["refresh_token"],
                "refreshed": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )
        self._access = (doc["access_token"], time.time() + int(doc.get("expires_in", 3600)) - 120)
        self.error = ""

    def _token(self) -> str:
        with self._lock:
            if self._access and time.time() < self._access[1]:
                return self._access[0]
            saved = self._saved()
            if not self.enabled or not saved:
                raise DriveError(NOT_CONNECTED, 409)
            status, doc = self._token_call(
                {
                    "grant_type": "refresh_token",
                    "client_id": self.client_id,
                    "refresh_token": saved["refresh_token"],
                    "scope": self.scopes,
                }
            )
            if status != 200:
                err = doc.get("error")
                obs.event("onedrive_refresh_failed", logging.ERROR, status=status, error=err)
                if err in ("invalid_grant", "interaction_required", "invalid_client"):
                    self.error = "a conexão com o OneDrive expirou ou foi revogada; reconecte"
                    raise DriveError(self.error, 409)
                raise DriveError(UNAVAILABLE)
            self._store_tokens(doc, saved)
            return self._access[0]

    def disconnect(self) -> None:
        with self._lock:
            with contextlib.suppress(FileNotFoundError):
                self.token_file.unlink()
            self._access = None
            self._pending = None
            self.error = ""
        obs.event("onedrive_disconnected")

    def status(self, quota: bool = False) -> dict:
        """For the Equipe page, /metrics and the CLI. Only `quota` calls Graph."""
        saved = self._saved() if self.enabled else None
        out = {
            "enabled": self.enabled,
            "connected": saved is not None,
            "account": (saved or {}).get("account", ""),
            "name": (saved or {}).get("name", ""),
            "refreshed": (saved or {}).get("refreshed", ""),
            "folder": f"/{self.root}" if self.root else "Apps (pasta do app)",
            "max_mb": self.max_bytes // (1024 * 1024),
            "error": self.error,
            "pending": self.pending(),
        }
        if quota and saved:
            try:
                drive, _ = self._graph("GET", "/me/drive?$select=quota")
                q = drive.get("quota") or {}
                out["quota"] = {"used": q.get("used"), "total": q.get("total")}
            except DriveError as e:
                out["error"] = out["error"] or str(e)
        return out

    # ---- files --------------------------------------------------------------------------------

    def _path(self, parts: list[str]) -> str:
        """The Graph address of a path under Pauta's folder."""
        rel = "/".join(urllib.parse.quote(safe_name(p), safe="") for p in parts)
        if self.root:
            base = "/".join(urllib.parse.quote(p, safe="") for p in self.root.split("/"))
            return f"/me/drive/root:/{base}/{rel}:"
        return f"/me/drive/special/approot:/{rel}:"

    def upload(self, folder: list[str], name: str, size: int, read) -> dict:
        """Stream `size` bytes from `read(n)` into folder/name (renamed on a clash).
        Returns {id, name, size, mime, folder}."""
        if size <= 0:
            raise DriveError("o arquivo está vazio", 400)
        if size > self.max_bytes:
            raise DriveError(f"arquivo grande demais (até {self.max_bytes // 2**20} MB)", 413)
        session, _ = self._graph(
            "POST",
            self._path([*folder, name]) + "/createUploadSession",
            data={"item": {"@microsoft.graph.conflictBehavior": "rename"}},
        )
        url = session.get("uploadUrl")
        if not url:
            raise DriveError(UNAVAILABLE)
        sent, item = 0, None
        try:
            while sent < size:
                piece = read(min(self.chunk, size - sent))
                if not piece:
                    raise DriveError("o envio foi interrompido", 400)
                end = sent + len(piece) - 1
                # the upload URL carries its own auth; Graph rejects a bearer token on it
                status, doc, _ = self._http(
                    "PUT",
                    url,
                    data=piece,
                    headers={
                        "Content-Length": str(len(piece)),
                        "Content-Range": f"bytes {sent}-{end}/{size}",
                    },
                )
                if status not in (200, 201, 202):
                    obs.event("onedrive_error", logging.WARNING, status=status, step="upload")
                    raise DriveError(UNAVAILABLE)
                sent = end + 1
                if status in (200, 201):
                    item = doc
        except DriveError:
            with contextlib.suppress(DriveError):
                self._http("DELETE", url)  # drop the half-written upload
            raise
        if not isinstance(item, dict) or not item.get("id"):
            raise DriveError(UNAVAILABLE)
        return {
            "id": item["id"],
            "name": item.get("name") or name,
            "size": int(item.get("size") or size),
            "mime": (item.get("file") or {}).get("mimeType", ""),
            "folder": (item.get("parentReference") or {}).get("id", ""),
        }

    def download_url(self, item: str) -> str:
        doc, _ = self._graph("GET", f"/me/drive/items/{urllib.parse.quote(item, safe='')}")
        url = doc.get("@microsoft.graph.downloadUrl")
        if not url:
            raise DriveError(UNAVAILABLE)
        return url

    def thumbnail(self, item: str) -> tuple[bytes, str]:
        """The medium thumbnail's bytes and type. Graph gives a pre-signed link to them,
        fetched without our token (it must never go to another host)."""
        doc, _ = self._graph(
            "GET", f"/me/drive/items/{urllib.parse.quote(item, safe='')}/thumbnails/0/medium"
        )
        url = doc.get("url") if isinstance(doc, dict) else None
        scheme = urllib.parse.urlparse(str(url or "")).scheme
        if scheme not in ("https", urllib.parse.urlparse(self.graph).scheme):
            raise DriveError("sem miniatura", 404)
        status, raw, rh = self._http("GET", url)
        ctype = (rh.get("Content-Type") or "").split(";")[0]
        if status != 200 or not ctype.startswith("image/") or not isinstance(raw, bytes):
            raise DriveError("sem miniatura", 404)
        return raw, ctype

    def share_link(self, folder: str) -> str:
        """A view-only link anyone can open (the client), to the request's folder."""
        doc, _ = self._graph(
            "POST",
            f"/me/drive/items/{urllib.parse.quote(folder, safe='')}/createLink",
            data={"type": "view", "scope": "anonymous"},
        )
        url = (doc.get("link") or {}).get("webUrl")
        if not url:
            raise DriveError(UNAVAILABLE)
        return url

    def delete(self, item: str) -> None:
        """To OneDrive's recycle bin (30 days to undo there); already gone counts as done."""
        try:
            self._graph("DELETE", f"/me/drive/items/{urllib.parse.quote(item, safe='')}")
        except DriveError as e:
            if e.status != 404:
                raise
