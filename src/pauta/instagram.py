"""A portfolio's Instagram accounts, through the Instagram API with Unified Login
(docs/publishing-spec.md). A second integration, apart from meta.py on purpose: that one
reads ad accounts with `ads_read` and never writes; this one publishes to an account, with
its own Meta app, its own secret and its own tokens.

Meta closed "Instagram Login" to apps created from late 2026 on: a new app gets Unified
Login, which is Facebook Login for Business with a configuration whose asset is an Instagram
account. An admin clicks "Conectar Instagram". Pauta sends them to Meta's login with the
app id and that configuration; they sign in (with Facebook or with Instagram), pick the
portfolio and its accounts, and Meta sends the browser back to `/api/instagram/callback`
with a one-time code. Pauta exchanges it, with the app secret, for a system-user token, and
asks which portfolio it belongs to and which Instagram accounts it was given: a connection
is a portfolio, as on the ads side, and which client each account is for is an admin's
choice afterwards (publishing.py). The token does not expire (the configuration says so);
a revoked one marks the connection "conecte de novo".

Files, next to the database (never in it, so an export or a backup of the DB has no token):
  <db>.ig-secret   the Meta app secret of the publishing app, one line, mode 600
  <db>.ig-tokens   {"biz-<portfolio id>": {"token", "expires" (epoch seconds or null),
                   "obtained"}}, mode 600: one token per connection

Configuration (the unit's environment; publishing is off without all three):
  PAUTA_IG_APP_ID     the publishing app's Meta app id (its own app, not the ads one)
  PAUTA_IG_CONFIG_ID  its Facebook Login for Business configuration: Instagram account as
                      the asset, `instagram_basic` and `instagram_content_publish`
  PAUTA_ORIGIN        the app's address: the callback and the images' public addresses

Nothing here logs a URL, a token or Meta's message text.
"""

from __future__ import annotations

import contextlib
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
ACCOUNT_PAGES = 20  # requests for one login's list of accounts: 100 accounts each
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
NO_ACCOUNT = "nenhuma conta do Instagram veio com o login: escolha as contas na tela da Meta"

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


def _digits(value) -> str:
    return "".join(c for c in str(value or "") if c.isdigit())


def _key(conn: str) -> str:
    """Where a connection's token is in the tokens file. Keys without the prefix are from
    before connections (one per profile id): a login drops them (`finish`)."""
    return f"biz-{conn}"


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
        # state -> (the user who started the login, expiry)
        self._states: dict[str, tuple[int | None, float]] = {}
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

    def _token(self, conn: str) -> str:
        entry = self._tokens().get(_key(conn)) or {}
        token = entry.get("token") or ""
        if not token:
            raise InstagramError(REVOKED, step="token", revoked=True, status=409)
        return token

    def _keep(self, conn: str, token: str, expires_in) -> str | None:
        """Store a connection's token; returns when it expires as the database writes
        moments, or None for one that doesn't (a system-user token of a "never"
        configuration)."""
        try:
            until = time.time() + int(expires_in) if expires_in else None
        except (TypeError, ValueError):
            until = None
        with self._lock:
            doc = self._tokens()
            doc[_key(conn)] = {"token": token, "expires": until, "obtained": time.time()}
            self._write_tokens(doc)
        if until is None:
            return None
        return datetime.fromtimestamp(until, UTC).strftime("%Y-%m-%d %H:%M:%S")

    def forget(self, conn: str) -> None:
        with self._lock:
            doc = self._tokens()
            if doc.pop(_key(conn), None) is not None:
                self._write_tokens(doc)

    def expires_in(self, conn: str, now: datetime | None = None) -> timedelta | None:
        """How long the connection's token still has: None when there is no token, and
        `timedelta.max` for one that doesn't expire."""
        entry = self._tokens().get(_key(conn)) or {}
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

    # ---- connecting a portfolio -----------------------------------------------------------

    def start(self, by: int | None) -> str:
        """A one-time state for the user who pressed the button (None only in local mode,
        which has no users), and the address of Instagram's login."""
        state = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock:
            self._states = {s: v for s, v in self._states.items() if v[1] > now}
            while len(self._states) >= MAX_PENDING:
                self._states.pop(min(self._states, key=lambda s: self._states[s][1]))
            self._states[state] = (by, now + STATE_SECONDS)
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

    def take_state(self, state: str) -> int | None:
        """Use up a state: the user who started that login."""
        with self._lock:
            entry = self._states.pop(state or "", None)
        if not entry or entry[1] < time.time():
            obs.event("ig_bad_state", logging.WARNING)
            raise InstagramError(BAD_STATE, step="state", status=400)
        return entry[0]

    def finish(self, code: str) -> tuple[dict, list[dict], str | None]:
        """Exchange the callback's code. Returns (the portfolio: {business_id,
        business_name}, its Instagram accounts: [{ig_id, username}], when the token expires
        or None); the token is kept under the portfolio's id.

        The token is the portfolio's system user, so it carries every Instagram account the
        business shared with the app, not only the one picked on Meta's last screen: an
        agency with ten clients in one portfolio gets ten. Which client each is for is an
        admin's choice afterwards, never this login's. Nothing is stored unless all of it
        was read."""
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
        # which portfolio: its id is the connection's key, the system user's own when Meta
        # sends none (as meta.py's finish_connect does); digits only, it goes into a path
        status, me = self._get(f"{self.graph}/me", {"fields": "id,name,client_business_id"}, token)
        if status != 200:
            raise self._fail(status, me, "me")
        business = _digits(me.get("client_business_id"))
        conn = business or _digits(me.get("id"))
        if not conn:
            raise InstagramError(UNAVAILABLE, step="me", status=503)
        name = str(me.get("name") or "")
        if business:
            with contextlib.suppress(InstagramError):  # the name is a nicety
                status, biz = self._get(f"{self.graph}/{business}", {"fields": "name"}, token)
                if status == 200 and biz.get("name"):
                    name = str(biz["name"])
        accounts = self._accounts(token)
        if not accounts:
            raise InstagramError(NO_ACCOUNT, step="me", status=400)
        expires = self._keep(conn, token, expires_in)
        with self._lock:  # the keys from before connections, one per account: superseded
            doc = self._tokens()
            old = [a["ig_id"] for a in accounts if a["ig_id"] in doc]
            if old:
                for key in old:
                    del doc[key]
                self._write_tokens(doc)
        return {"business_id": conn, "business_name": name}, accounts, expires

    def _accounts(self, token: str) -> list[dict]:
        """Every Instagram account the token was given, a page at a time as meta.py's
        `_pages` reads a list: each request is built here from the cursor, and the address
        in `paging.next` is never followed. A list that does not end is a failure: half a
        list would disconnect the accounts it missed."""
        out: list[dict] = []
        query = {"fields": "id,username", "limit": "100"}
        for _ in range(ACCOUNT_PAGES):
            status, doc = self._get(f"{self.graph}/me/assigned_instagram_accounts", query, token)
            if status != 200:
                raise self._fail(status, doc, "accounts")
            for row in doc.get("data") or []:
                if isinstance(row, dict) and row.get("id"):
                    out.append(
                        {"ig_id": str(row["id"]), "username": str(row.get("username") or "")}
                    )
            paging = doc.get("paging") if isinstance(doc.get("paging"), dict) else {}
            after = (paging.get("cursors") or {}).get("after")
            if not paging.get("next") or not after or after == query.get("after"):
                return out
            query = {**query, "after": after}
        raise InstagramError(UNAVAILABLE, step="accounts", status=503)

    # ---- publishing -----------------------------------------------------------------------

    def create_container(
        self,
        conn: str,
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
        status, doc = self._post(f"{self.graph}/{ig_id}/media", form, self._token(conn))
        if status != 200 or not doc.get("id"):
            raise self._fail(status, doc, "container")
        return str(doc["id"])

    def container_state(self, conn: str, container: str) -> str:
        """One read of where a container stands: IN_PROGRESS, FINISHED, PUBLISHED, ERROR,
        EXPIRED."""
        status, doc = self._get(
            f"{self.graph}/{container}", {"fields": "status_code"}, self._token(conn)
        )
        if status != 200:
            raise self._fail(status, doc, "status")
        return str(doc.get("status_code") or "")

    def wait_ready(self, conn: str, container: str) -> None:
        """Until Instagram has fetched and prepared the image."""
        for attempt in range(READY_TRIES):
            state = self.container_state(conn, container)
            if state in ("FINISHED", "PUBLISHED"):
                return
            if state in ("ERROR", "EXPIRED"):
                obs.event("ig_container_failed", logging.WARNING, state=state)
                raise InstagramError(NO_FETCH if state == "ERROR" else NOT_READY, step="status")
            if attempt + 1 < READY_TRIES:
                self.sleep(READY_PAUSE)
        raise InstagramError(NOT_READY, step="status")

    def publish(self, conn: str, ig_id: str, container: str) -> str:
        status, doc = self._post(
            f"{self.graph}/{ig_id}/media_publish", {"creation_id": container}, self._token(conn)
        )
        if status != 200 or not doc.get("id"):
            raise self._fail(status, doc, "publish")
        return str(doc["id"])

    def permalink(self, conn: str, media_id: str) -> str:
        status, doc = self._get(
            f"{self.graph}/{media_id}", {"fields": "permalink"}, self._token(conn)
        )
        if status != 200:
            raise self._fail(status, doc, "permalink")
        link = str(doc.get("permalink") or "")
        return link if link.startswith("https://") else ""

    def quota(self, conn: str, ig_id: str) -> dict | None:
        """How many posts the profile made through the API in the last 24 h and its limit;
        None when Instagram won't say (never a reason to stop)."""
        try:
            status, doc = self._get(
                f"{self.graph}/{ig_id}/content_publishing_limit",
                {"fields": "quota_usage,config"},
                self._token(conn),
            )
        except InstagramError:
            return None
        rows = doc.get("data") if status == 200 else None
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            return None
        config = rows[0].get("config") if isinstance(rows[0].get("config"), dict) else {}
        return {"used": rows[0].get("quota_usage"), "limit": config.get("quota_total")}
