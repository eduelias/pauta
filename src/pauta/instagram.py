"""A client's Instagram profile, through the Instagram API with Unified Login
(docs/publishing-spec.md). A second integration, apart from meta.py on purpose: that one
reads ad accounts with `ads_read` and never writes; this one publishes to a profile, with
its own Meta app, its own secret and its own tokens.

Meta closed "Instagram Login" to apps created from late 2026 on: a new app gets Unified
Login, which is Facebook Login for Business with a configuration whose asset is an Instagram
account. An admin clicks "Conectar Instagram" on a client. Pauta sends them to Meta's login
with the app id and that configuration; they sign in (with Facebook or with Instagram),
pick the profile, and Meta sends the browser back to `/api/instagram/callback` with a
one-time code. Pauta exchanges it, with the app secret, for a system-user token and asks
which Instagram account it was given. The token does not expire (the configuration says
so); a revoked one marks the profile "conecte de novo".

Files, next to the database (never in it, so an export or a backup of the DB has no token):
  <db>.ig-secret   the Meta app secret of the publishing app, one line, mode 600
  <db>.ig-tokens   {ig_id: {"token", "expires" (epoch seconds or null), "obtained"}}, mode 600

Configuration (the unit's environment; publishing is off without all three):
  PAUTA_IG_APP_ID     the publishing app's Meta app id (its own app, not the ads one)
  PAUTA_IG_CONFIG_ID  its Facebook Login for Business configuration: Instagram account as
                      the asset, `instagram_basic` and `instagram_content_publish`
  PAUTA_ORIGIN        the app's address: the callback and the images' public addresses

Nothing here logs a URL, a token or Meta's message text.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import logging
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import obs

VERSION = "v27.0"
DIALOG = "https://www.facebook.com/dialog/oauth"
GRAPH = "https://graph.facebook.com"
DEV_ORIGIN = "http://localhost:8088"

TIMEOUT = 20
STATE_SECONDS = 10 * 60
MAX_PENDING = 50
READY_TRIES, READY_PAUSE = 20, 2.0  # an image container is ready at once; a slow one gets 40 s

UNAVAILABLE = "não deu para falar com o Instagram agora; tente de novo em instantes"
REVOKED = "o Instagram não aceita mais esta conexão: conecte o perfil de novo"
THROTTLED = "o Instagram pediu uma pausa; tente de novo mais tarde"
DAILY_LIMIT = "este perfil atingiu o limite de publicações do Instagram nas últimas 24 horas"
NO_FETCH = "o Instagram não conseguiu baixar a imagem; tente de novo"
BAD_IMAGE = "o Instagram recusou a imagem (formato ou proporção)"
NOT_READY = "o Instagram demorou para preparar a imagem; tente de novo"
BAD_VIDEO = (
    "o Instagram não conseguiu preparar o vídeo: confira o formato (MP4 ou MOV, H.264 e "
    "AAC) e tente de novo"
)
SLOW_VIDEO = "o Instagram demorou demais para preparar o vídeo; tente de novo"
BAD_STATE = "este pedido de conexão venceu; comece de novo"
DENIED = "a conexão foi cancelada no Instagram"
NOT_PROFESSIONAL = "o perfil precisa ser profissional (Empresa ou Criador de conteúdo)"
NO_ACCOUNT = "nenhum perfil do Instagram veio com o login: escolha o perfil do cliente"
# several profiles and nothing to tell them apart: the client's @ is what decides
MANY_ACCOUNTS = (
    "o login trouxe mais de um perfil: escreva o @ deste cliente no cadastro dele e conecte de novo"
)
NOT_SHARED = (
    "o perfil {want} não veio neste login: marque só ele na tela da Meta, ou confira o @ "
    "no cadastro do cliente"
)

RESTRICTED = "o Instagram restringiu este perfil; veja o aviso no aplicativo do Instagram"
BAD_CAPTION = "o Instagram recusou a legenda"
BAD_CODE = "o Instagram não aceitou este pedido de conexão; comece de novo"

THROTTLE_CODES = {4, 17, 32, 613, 80002}
# error_subcode of a publish Instagram refused (its error-codes reference, read 2026-11-12)
LIMIT_SUBCODES = {2207042}  # code 9: max posts reached
FETCH_SUBCODES = {2207003, 2207052}  # download timeout; could not fetch the media
IMAGE_SUBCODES = {2207004, 2207005, 2207009}  # over 8 MiB; format; aspect ratio
CAPTION_SUBCODES = {2207010}
NOT_READY_SUBCODES = {2207027, 2207008}  # not ready yet; container missing or expired
RESTRICTED_SUBCODES = {2207050, 2207051}  # account restricted; spam restriction


def handle(value) -> str:
    """An Instagram @ as the person wrote it, down to the bare username: "@pauta.cc",
    "instagram.com/pautacc/", "Pautacc " all become comparable."""
    text = str(value or "").strip().lower()
    text = re.sub(r"^https?://(www\.)?instagram\.com/", "", text)
    text = text.split("?")[0].strip("/").lstrip("@")
    return text if re.fullmatch(r"[a-z0-9._]{1,30}", text) else ""


class InstagramError(Exception):
    """A user-facing reason (in Portuguese) an Instagram step failed. `code` is Instagram's
    (None when it never answered), `step` the call, `revoked` whether the token is dead."""

    def __init__(self, message: str, *, code=None, step: str = "", revoked=False, status=502):
        super().__init__(message)
        self.code, self.step, self.revoked, self.status = code, step, revoked, status


class Instagram:
    def __init__(
        self,
        db_path: Path,
        app_id: str = "",
        config_id: str = "",
        origin: str = "",
        dialog: str = DIALOG,
        graph: str = GRAPH,
        version: str = VERSION,
    ):
        self.app_id = (app_id or "").strip()
        self.config_id = (config_id or "").strip()
        self.origin = (origin or DEV_ORIGIN).rstrip("/")
        self.redirect_uri = f"{self.origin}/api/instagram/callback"
        self.dialog = dialog.rstrip("/")
        self.graph = f"{graph.rstrip('/')}/{version}" if version else graph.rstrip("/")
        self.secret_file = Path(f"{db_path}.ig-secret")
        self.tokens_file = Path(f"{db_path}.ig-tokens")
        self._lock = threading.Lock()
        # state -> (client, account, expiry)
        self._states: dict[str, tuple[int, int | None, float]] = {}
        self.sleep = time.sleep  # the tests don't wait

    def at(self, origin: str) -> None:
        """The app's own address: where Instagram sends the login back, and where it fetches
        the images from."""
        self.origin = origin.rstrip("/")
        self.redirect_uri = f"{self.origin}/api/instagram/callback"

    @classmethod
    def from_env(cls, db_path: Path) -> Instagram:
        origins = [o.strip() for o in os.environ.get("PAUTA_ORIGIN", "").split(",") if o.strip()]
        return cls(
            db_path,
            app_id=os.environ.get("PAUTA_IG_APP_ID", ""),
            config_id=os.environ.get("PAUTA_IG_CONFIG_ID", ""),
            origin=origins[0] if origins else "",
        )

    # ---- configuration and the token file -------------------------------------------------

    def _secret(self) -> str:
        try:
            return self.secret_file.read_text().strip()
        except (OSError, UnicodeDecodeError):
            return ""

    @property
    def enabled(self) -> bool:
        return bool(self.app_id and self.config_id and self._secret())

    def _tokens(self) -> dict:
        try:
            doc = json.loads(self.tokens_file.read_text())
        except (OSError, ValueError):
            return {}
        return doc if isinstance(doc, dict) else {}

    def _write_tokens(self, doc: dict) -> None:
        tmp = self.tokens_file.with_name(f".{self.tokens_file.name}.{threading.get_ident()}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(doc, f)
        os.replace(tmp, self.tokens_file)

    def _token(self, ig_id: str) -> str:
        entry = self._tokens().get(str(ig_id)) or {}
        token = entry.get("token") or ""
        if not token:
            raise InstagramError(REVOKED, step="token", revoked=True, status=409)
        return token

    def _keep(self, ig_id: str, token: str, expires_in) -> str | None:
        """Store a token; returns when it expires as the database writes moments, or None
        for one that doesn't (a system-user token of a "never" configuration)."""
        try:
            until = time.time() + int(expires_in) if expires_in else None
        except (TypeError, ValueError):
            until = None
        with self._lock:
            doc = self._tokens()
            doc[str(ig_id)] = {"token": token, "expires": until, "obtained": time.time()}
            self._write_tokens(doc)
        if until is None:
            return None
        return datetime.fromtimestamp(until, UTC).strftime("%Y-%m-%d %H:%M:%S")

    def forget(self, ig_id: str) -> None:
        with self._lock:
            doc = self._tokens()
            if doc.pop(str(ig_id), None) is not None:
                self._write_tokens(doc)

    def expires_in(self, ig_id: str, now: datetime | None = None) -> timedelta | None:
        """How long the profile's token still has: None when there is no token, and
        `timedelta.max` for one that doesn't expire."""
        entry = self._tokens().get(str(ig_id)) or {}
        if not entry.get("token"):
            return None
        if not entry.get("expires"):
            return timedelta.max
        at = (now or datetime.now(UTC)).timestamp()
        return timedelta(seconds=float(entry["expires"]) - at)

    # ---- HTTP -----------------------------------------------------------------------------

    @staticmethod
    def _send(req: urllib.request.Request) -> tuple[int, dict]:
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                status, raw = r.status, r.read()
        except urllib.error.HTTPError as e:
            with e:
                status, raw = e.code, e.read()
        except (OSError, ValueError, http.client.HTTPException) as e:
            obs.event("ig_unreachable", logging.WARNING, error=type(e).__name__)
            raise InstagramError(UNAVAILABLE, step="network", status=503) from None
        try:
            doc = json.loads(raw or b"{}")
        except ValueError:
            doc = {}
        return status, doc if isinstance(doc, dict) else {}

    def _proof(self, token: str) -> str:
        """Proves the call comes from the app's server ("Require app secret" in Meta)."""
        return hmac.new(self._secret().encode(), token.encode(), hashlib.sha256).hexdigest()

    def _get(self, url: str, params: dict, token: str = "") -> tuple[int, dict]:
        headers = {"Accept": "application/json"}
        query = dict(params)
        if token:
            headers["Authorization"] = f"Bearer {token}"
            query["appsecret_proof"] = self._proof(token)
        full = f"{url}?{urllib.parse.urlencode(query)}" if query else url
        return self._send(urllib.request.Request(full, headers=headers))

    def _post(self, url: str, form: dict, token: str = "") -> tuple[int, dict]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        fields = dict(form)
        if token:
            headers["Authorization"] = f"Bearer {token}"
            fields["appsecret_proof"] = self._proof(token)
        body = urllib.parse.urlencode(fields).encode()
        return self._send(urllib.request.Request(url, body, headers))

    @staticmethod
    def _fail(status: int, doc: dict, step: str) -> InstagramError:
        """The error for an answer that wasn't a success, logged with its codes only."""
        err = doc.get("error") if isinstance(doc.get("error"), dict) else {}
        code = err.get("code", doc.get("code"))
        sub = err.get("error_subcode")
        obs.event("ig_error", logging.WARNING, status=status, code=code, subcode=sub, step=step)
        if code == 190:
            return InstagramError(REVOKED, code=code, step=step, revoked=True, status=409)
        if step == "code":  # a code already used, expired, or for another address
            return InstagramError(BAD_CODE, code=code, step=step, status=400)
        if code == 10:  # "(#10) ... the instagram account type is not business or creator"
            return InstagramError(NOT_PROFESSIONAL, code=code, step=step, status=400)
        if sub in LIMIT_SUBCODES:
            return InstagramError(DAILY_LIMIT, code=code, step=step, status=429)
        if sub in RESTRICTED_SUBCODES:
            return InstagramError(RESTRICTED, code=code, step=step, status=409)
        if sub in FETCH_SUBCODES or code == 9004:
            return InstagramError(NO_FETCH, code=code, step=step)
        if sub in IMAGE_SUBCODES:
            return InstagramError(BAD_IMAGE, code=code, step=step, status=400)
        if sub in CAPTION_SUBCODES:
            return InstagramError(BAD_CAPTION, code=code, step=step, status=400)
        if sub in NOT_READY_SUBCODES or code == 9007:
            return InstagramError(NOT_READY, code=code, step=step)
        if code in THROTTLE_CODES:
            return InstagramError(THROTTLED, code=code, step=step, status=503)
        if status >= 500:
            return InstagramError(UNAVAILABLE, code=code, step=step, status=503)
        tail = f"{code}/{sub}" if sub else f"{code or status}"
        return InstagramError(f"o Instagram recusou ({tail})", code=code, step=step)

    # ---- connecting a profile -------------------------------------------------------------

    def start(self, client: int, account: int | None) -> str:
        """A one-time state for this admin and client, and the address of Instagram's login."""
        state = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock:
            self._states = {s: v for s, v in self._states.items() if v[2] > now}
            while len(self._states) >= MAX_PENDING:
                self._states.pop(min(self._states, key=lambda s: self._states[s][2]))
            self._states[state] = (client, account, now + STATE_SECONDS)
        # as the dashboard's own "Login URL" has it: no scope (the configuration carries the
        # permissions), and prompt=login so the person can sign in with Instagram itself
        query = {
            "client_id": self.app_id,
            "config_id": self.config_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "override_default_response_type": "true",
            "state": state,
            "prompt": "login",
        }
        return f"{self.dialog}?{urllib.parse.urlencode(query)}"

    def take_state(self, state: str) -> tuple[int, int | None]:
        """Use up a state: (the client it was started for, the account that started it)."""
        with self._lock:
            entry = self._states.pop(state or "", None)
        if not entry or entry[2] < time.time():
            obs.event("ig_bad_state", logging.WARNING)
            raise InstagramError(BAD_STATE, step="state", status=400)
        return entry[0], entry[1]

    def finish(self, code: str, want: str = "") -> tuple[dict, str | None]:
        """Exchange the callback's code. Returns (who: {ig_id, username, name, account_type},
        when the token expires or None); the token is kept under the profile's id.

        The token is the portfolio's system user, so it carries every Instagram account the
        team has shared with the app, not only the one picked on Meta's last screen: an
        agency with ten clients in one portfolio gets ten. `want` is this client's @ (from
        its own record) and decides which of them this connection is for. Without it, a
        single account still connects; several ask for the @."""
        code = (code or "").split("#")[0]
        status, doc = self._get(
            f"{self.graph}/oauth/access_token",
            {
                "client_id": self.app_id,
                "client_secret": self._secret(),
                "redirect_uri": self.redirect_uri,
                "code": code,
            },
        )
        token = doc.get("access_token") if status == 200 else None
        if not isinstance(token, str) or not token:
            raise self._fail(status, doc, "code")
        expires_in = doc.get("expires_in")  # absent for a token that doesn't expire
        # the token is a system user's: the Instagram accounts it was given are listed apart
        status, doc = self._get(
            f"{self.graph}/me/assigned_instagram_accounts", {"fields": "id,username"}, token
        )
        if status != 200:
            raise self._fail(status, doc, "me")
        rows = [r for r in doc.get("data") or [] if isinstance(r, dict) and r.get("id")]
        if not rows:
            raise InstagramError(NO_ACCOUNT, step="me", status=400)
        wanted = handle(want)
        row = (
            next((r for r in rows if handle(r.get("username")) == wanted), None) if wanted else None
        )
        if row is None:
            if wanted and len(rows) > 1:
                raise InstagramError(NOT_SHARED.format(want=f"@{wanted}"), step="me", status=400)
            if len(rows) > 1:
                raise InstagramError(MANY_ACCOUNTS, step="me", status=400)
            row = rows[0]
            if wanted and handle(row.get("username")) != wanted:
                # one account, and it isn't the one the client's record names: connecting it
                # would quietly publish a client's posts on somebody else's profile
                raise InstagramError(NOT_SHARED.format(want=f"@{wanted}"), step="me", status=400)
        ig_id = str(row["id"])
        expires = self._keep(ig_id, token, expires_in)
        who = {
            "ig_id": ig_id,
            "username": str(row.get("username") or ""),
            "name": "",
            "account_type": "",
        }
        return who, expires

    # ---- publishing -----------------------------------------------------------------------

    def create_container(
        self,
        ig_id: str,
        url: str,
        caption: str,
        alt_text: str = "",
        kind: str = "feed",
        video: bool = False,
    ) -> str:
        """What Instagram is asked to fetch and prepare: a picture for the feed, a Story (a
        picture or a video, no caption) or a Reel (a video, also shown on the profile's
        grid)."""
        form = {"video_url" if video else "image_url": url}
        if kind == "story":
            form["media_type"] = "STORIES"
        else:
            form["caption"] = caption
        if kind == "reel":
            form.update(media_type="REELS", share_to_feed="true")
        if alt_text and kind == "feed":
            form["alt_text"] = alt_text
        status, doc = self._post(f"{self.graph}/{ig_id}/media", form, self._token(ig_id))
        if status != 200 or not doc.get("id"):
            raise self._fail(status, doc, "container")
        return str(doc["id"])

    def container_state(self, ig_id: str, container: str) -> str:
        """One read of where a container stands: IN_PROGRESS, FINISHED, PUBLISHED, ERROR,
        EXPIRED."""
        status, doc = self._get(
            f"{self.graph}/{container}", {"fields": "status_code"}, self._token(ig_id)
        )
        if status != 200:
            raise self._fail(status, doc, "status")
        return str(doc.get("status_code") or "")

    def wait_ready(self, ig_id: str, container: str) -> None:
        """Until Instagram has fetched and prepared the image."""
        for attempt in range(READY_TRIES):
            state = self.container_state(ig_id, container)
            if state in ("FINISHED", "PUBLISHED"):
                return
            if state in ("ERROR", "EXPIRED"):
                obs.event("ig_container_failed", logging.WARNING, state=state)
                raise InstagramError(NO_FETCH if state == "ERROR" else NOT_READY, step="status")
            if attempt + 1 < READY_TRIES:
                self.sleep(READY_PAUSE)
        raise InstagramError(NOT_READY, step="status")

    def publish(self, ig_id: str, container: str) -> str:
        status, doc = self._post(
            f"{self.graph}/{ig_id}/media_publish", {"creation_id": container}, self._token(ig_id)
        )
        if status != 200 or not doc.get("id"):
            raise self._fail(status, doc, "publish")
        return str(doc["id"])

    def permalink(self, ig_id: str, media_id: str) -> str:
        status, doc = self._get(
            f"{self.graph}/{media_id}", {"fields": "permalink"}, self._token(ig_id)
        )
        if status != 200:
            raise self._fail(status, doc, "permalink")
        link = str(doc.get("permalink") or "")
        return link if link.startswith("https://") else ""

    def quota(self, ig_id: str) -> dict | None:
        """How many posts the profile made through the API in the last 24 h and its limit;
        None when Instagram won't say (never a reason to stop)."""
        try:
            status, doc = self._get(
                f"{self.graph}/{ig_id}/content_publishing_limit",
                {"fields": "quota_usage,config"},
                self._token(ig_id),
            )
        except InstagramError:
            return None
        rows = doc.get("data") if status == 200 else None
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            return None
        config = rows[0].get("config") if isinstance(rows[0].get("config"), dict) else {}
        return {"used": rows[0].get("quota_usage"), "limit": config.get("quota_total")}
