"""The team's Meta business portfolio, read through the Marketing API (decision 8, phase 2).

An admin clicks "Conectar Meta" on Equipe. Pauta sends them to Facebook Login for Business
with Du7's app and its login configuration (a system-user token, ANALYZE on the ad accounts,
`ads_read` only); they pick the portfolio and its ad accounts and Meta sends them back to
`/api/meta/callback` with a one-time code. Pauta exchanges the code, with the app secret, for
the system user's token, which does not expire. The token lives in a file next to the
database (like the OneDrive token), never in it, so backups and the export can't be turned
into Meta access. Pauta only reads: it never creates, edits, pauses or pays for anything.

The session cookie is SameSite=Strict, so it is not sent on the redirect back from
facebook.com: the callback is authorized by the one-time `state` instead, made for the
admin who clicked, kept in memory for 10 minutes and used once.

Revoking access is the client's side: Business Settings → Integrations → Connected apps.
"Desconectar" only forgets the token here.

Configuration:
  PAUTA_META_APP_ID      the Meta app's id (public); unset turns Meta off
  PAUTA_META_CONFIG_ID   the Facebook Login for Business configuration id (public)
  PAUTA_ORIGIN           the app's own origin first (see auth.py): the redirect URI is
                         <first origin>/api/meta/callback, which must be listed in the
                         configuration's valid OAuth redirect URIs. Unset (local dev):
                         http://localhost:8088/api/meta/callback
  <db>.meta-secret       a file next to the database holding the app secret, one line,
                         mode 600 (e.g. /var/lib/pauta/pauta.db.meta-secret). Never in the
                         environment, the database, the logs or an answer. Missing or empty
                         turns Meta off
  <db>.meta-token        written by Pauta when connected (mode 600)
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from . import obs

VERSION = "v26.0"
GRAPH = f"https://graph.facebook.com/{VERSION}"
DIALOG = f"https://www.facebook.com/{VERSION}/dialog/oauth"
DEV_REDIRECT = "http://localhost:8088/api/meta/callback"
TIMEOUT = 30
STATE_SECONDS = 600
CACHE_SECONDS = 600
MAX_PENDING = 20

UNAVAILABLE = "a Meta não respondeu; tente de novo"
REVOKED = "a conexão com a Meta foi revogada ou expirou; conecte de novo"
NOT_CONNECTED = "a Meta não está conectada; um administrador conecta em Equipe"
NO_BALANCE = "sem permissão para ler o saldo"
THROTTLED = "a Meta pediu uma pausa; tente de novo em alguns minutos"
# Graph error codes: 190 is an invalid or revoked token; these say "slow down"
THROTTLE_CODES = {4, 17, 32, 613}
ACCOUNT_STATUS = {
    1: "Ativa",
    2: "Desativada",
    3: "Pagamento pendente",
    7: "Em análise",
    8: "Acerto pendente",
    9: "Em período de carência",
    100: "Fechamento pendente",
    101: "Fechada",
}


class MetaError(Exception):
    """A user-facing reason (in Portuguese) a Meta step failed, with an HTTP status and a
    short fixed reason code for the callback's redirect."""

    def __init__(self, message: str, status: int = 502, reason: str = "meta"):
        super().__init__(message)
        self.status = status
        self.reason = reason


def cents(value) -> int | None:
    """A Meta decimal string in the account's currency ("12.34") as integer cents."""
    if value is None or value == "":
        return None
    try:
        return int((Decimal(str(value)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return None


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _minor(value) -> int | None:
    """Ad account money fields (spend_cap, amount_spent) come in the currency's minor unit
    already, as strings."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class Meta:
    def __init__(
        self,
        db_path: Path,
        app_id: str = "",
        config_id: str = "",
        redirect_uri: str = DEV_REDIRECT,
        graph: str = GRAPH,
        dialog: str = DIALOG,
    ):
        self.app_id = (app_id or "").strip()
        self.config_id = (config_id or "").strip()
        self.redirect_uri = redirect_uri
        self.graph = graph.rstrip("/")
        self.dialog = dialog
        self.secret_file = Path(f"{db_path}.meta-secret")
        self.token_file = Path(f"{db_path}.meta-token")
        self._lock = threading.Lock()
        self._states: dict[str, tuple[int | None, float]] = {}  # state -> (account, expiry)
        # states that already connected: a second load of the same callback (a reload, the
        # browser retrying) says "conectado" again instead of "expirou"
        self._done: dict[str, float] = {}  # state -> expiry
        self._cache: tuple[float, list[dict]] | None = None
        self.error = ""  # why the connection stopped working, until reconnected
        # called with the fresh list each time Meta is actually read (not from the cache);
        # the server keeps the account ↔ client mapping there (db.sync_meta_accounts)
        self.on_read: Callable[[list[dict]], None] | None = None

    @classmethod
    def from_env(cls, db_path: Path) -> Meta:
        origins = [o.strip() for o in os.environ.get("PAUTA_ORIGIN", "").split(",") if o.strip()]
        redirect = f"{origins[0].rstrip('/')}/api/meta/callback" if origins else DEV_REDIRECT
        return cls(
            db_path,
            app_id=os.environ.get("PAUTA_META_APP_ID", ""),
            config_id=os.environ.get("PAUTA_META_CONFIG_ID", ""),
            redirect_uri=redirect,
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

    def _saved(self) -> dict | None:
        try:
            doc = json.loads(self.token_file.read_text())
        except (OSError, ValueError):
            return None
        return doc if isinstance(doc, dict) and doc.get("access_token") else None

    def _save(self, doc: dict) -> None:
        tmp = self.token_file.with_name(self.token_file.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(doc, f)
        os.replace(tmp, self.token_file)

    @property
    def connected(self) -> bool:
        return self.enabled and self._saved() is not None

    # ---- HTTP -----------------------------------------------------------------------------

    def _get(self, path: str, params: dict, token: str | None = None) -> tuple[int, dict]:
        """One GET to the Graph. Returns (status, JSON); raises MetaError only when Meta
        can't be reached. Never logs the URL: it may carry the code or the secret."""
        query = dict(params)
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
            # proves the call comes from the app's server ("Require app secret" in Meta)
            query["appsecret_proof"] = hmac.new(
                self._secret().encode(), token.encode(), hashlib.sha256
            ).hexdigest()
        url = f"{self.graph}{path}?{urllib.parse.urlencode(query)}"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                status, raw = r.status, r.read()
        except urllib.error.HTTPError as e:
            with e:
                status, raw = e.code, e.read()
        except (OSError, ValueError) as e:
            obs.event("meta_unreachable", logging.WARNING, error=type(e).__name__)
            raise MetaError(UNAVAILABLE) from None
        try:
            doc = json.loads(raw or b"{}")
        except ValueError:
            doc = {}
        return status, doc if isinstance(doc, dict) else {}

    @staticmethod
    def _code(doc: dict) -> int | None:
        err = doc.get("error")
        return err.get("code") if isinstance(err, dict) else None

    def _fail(self, status: int, doc: dict, step: str) -> MetaError:
        """The error for a Graph answer that wasn't 200 (logged without any message text)."""
        code = self._code(doc)
        obs.event("meta_error", logging.WARNING, status=status, code=code, step=step)
        if code == 190:
            self.error = REVOKED
            self._cache = None
            obs.event("meta_revoked", logging.ERROR)
            return MetaError(REVOKED, 409)
        if code in THROTTLE_CODES or (isinstance(code, int) and 80000 <= code < 80100):
            return MetaError(THROTTLED, 503)
        return MetaError(UNAVAILABLE)

    def _graph(self, path: str, params: dict, step: str) -> dict:
        saved = self._saved() if self.enabled else None
        if not saved:
            raise MetaError(NOT_CONNECTED, 409)
        status, doc = self._get(path, params, saved["access_token"])
        if status != 200:
            raise self._fail(status, doc, step)
        return doc

    # ---- connecting ----------------------------------------------------------------------

    def start_connect(self, account_id: int | None) -> str:
        """A one-time state for this admin and the URL of Meta's login dialog."""
        if not self.enabled:
            raise MetaError("o servidor não tem a Meta configurada", 400, "desligado")
        state = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock:
            self._states = {s: v for s, v in self._states.items() if v[1] > now}
            while len(self._states) >= MAX_PENDING:  # the oldest go first
                self._states.pop(min(self._states, key=lambda s: self._states[s][1]))
            self._states[state] = (account_id, now + STATE_SECONDS)
        query = {
            "client_id": self.app_id,
            "config_id": self.config_id,
            "response_type": "code",
            "override_default_response_type": "true",
            "redirect_uri": self.redirect_uri,
            "state": state,
        }
        obs.event("meta_connect_started", account=account_id)
        return f"{self.dialog}?{urllib.parse.urlencode(query)}"

    def take_state(self, state: str) -> int | None:
        """Use up a state: the account that started it. Unknown, expired or used: MetaError."""
        with self._lock:
            entry = self._states.pop(state or "", None)
        if not entry or entry[1] < time.time():
            obs.event("meta_bad_state", logging.WARNING)
            raise MetaError("o pedido de conexão expirou; comece de novo", 400, "expirou")
        return entry[0]

    def finish_connect(self, state: str, code: str) -> None:
        """Meta sent the admin back with a code: exchange it and keep the token."""
        if not self.enabled:
            raise MetaError("o servidor não tem a Meta configurada", 400, "desligado")
        with self._lock:
            done = self._done.get(state or "", 0) > time.time()
        if done:
            obs.event("meta_callback_repeated")
            return
        by = self.take_state(state)
        if not code:
            raise MetaError("a Meta não mandou o código; tente de novo", 400)
        status, doc = self._get(
            "/oauth/access_token",
            {
                "client_id": self.app_id,
                "client_secret": self._secret(),
                "redirect_uri": self.redirect_uri,
                "code": code,
            },
        )
        token = doc.get("access_token") if status == 200 else None
        if not isinstance(token, str) or not token:
            code = self._code(doc)
            obs.event("meta_error", logging.WARNING, status=status, code=code, step="code")
            raise MetaError("a Meta recusou a conexão; tente de novo", 502)
        status, me = self._get("/me", {"fields": "id,name,client_business_id"}, token)
        if status != 200:
            raise self._fail(status, me, "me")
        business_id = str(me.get("client_business_id") or "")
        business_name = ""
        if business_id:
            path = f"/{urllib.parse.quote(business_id)}"
            status, biz = self._get(path, {"fields": "name"}, token)
            if status == 200:
                business_name = str(biz.get("name") or "")
        self._save(
            {
                "access_token": token,
                "business_id": business_id,
                "business_name": business_name or str(me.get("name") or ""),
                "connected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "by": by,
            }
        )
        self.error = ""
        self._cache = None
        now = time.time()
        with self._lock:
            self._done = {s: t for s, t in self._done.items() if t > now}
            self._done[state] = now + STATE_SECONDS
        obs.event("meta_connected", account=by)

    def disconnect(self) -> None:
        """Forget the token here. Revoking it in Meta is the portfolio owner's step."""
        with self._lock:
            with contextlib.suppress(FileNotFoundError):
                self.token_file.unlink()
            self._cache = None
            self.error = ""
        obs.event("meta_disconnected")

    def status(self) -> dict:
        """For the Equipe page and /metrics. Never the token."""
        saved = self._saved() if self.enabled else None
        return {
            "enabled": self.enabled,
            "connected": saved is not None,
            "business_name": (saved or {}).get("business_name", ""),
            "connected_at": (saved or {}).get("connected_at", ""),
            "error": self.error,
        }

    # ---- reading -------------------------------------------------------------------------

    def accounts(self, refresh: bool = False) -> list[dict]:
        """Every ad account the token reads, with this month's numbers and, when Meta lets
        Pauta read it, the balance. Kept for 10 minutes unless `refresh`."""
        cached = self._cache
        if cached and not refresh and time.time() - cached[0] < CACHE_SECONDS:
            return cached[1]
        doc = self._graph(
            "/me/adaccounts",
            {
                # not business{name}: that field needs business_management, which this
                # read-only login doesn't ask for (Meta answers #100 for the whole list)
                "fields": "name,account_id,currency,account_status",
                "limit": "100",
            },
            "adaccounts",
        )
        out = [self._account(a) for a in doc.get("data") or [] if isinstance(a, dict)]
        self._cache = (time.time(), out)
        obs.event("meta_read", accounts=len(out))
        if self.on_read:
            self.on_read(out)
        return out

    def _account(self, a: dict) -> dict:
        aid = "".join(c for c in str(a.get("account_id") or a.get("id") or "") if c.isdigit())
        status = _int(a.get("account_status"))
        ins = self._graph(
            f"/act_{aid}/insights",
            {
                "date_preset": "this_month",
                "fields": "spend,impressions,reach,inline_link_clicks,cost_per_inline_link_click",
            },
            "insights",
        )
        row = next(iter(ins.get("data") or []), None) or {}
        return {
            "id": aid,
            "name": str(a.get("name") or ""),
            "currency": str(a.get("currency") or "BRL"),
            "status": status,
            "status_label": ACCOUNT_STATUS.get(status, ""),
            "spend_cents": cents(row.get("spend")) or 0,
            "impressions": _int(row.get("impressions")),
            "reach": _int(row.get("reach")),
            "link_clicks": _int(row.get("inline_link_clicks")),
            "cpc_cents": cents(row.get("cost_per_inline_link_click")),
            "balance": self._balance(aid),
        }

    def _balance(self, aid: str) -> dict:
        """What is left on the account. Meta shows the funding details only to a token with
        more than ANALYZE on the account (decision 8, "Saldo"): a refusal is not an error."""
        saved = self._saved()
        if not saved:
            raise MetaError(NOT_CONNECTED, 409)
        status, doc = self._get(
            f"/act_{aid}",
            {"fields": "is_prepay_account,funding_source_details,spend_cap,amount_spent"},
            saved["access_token"],
        )
        if status != 200:
            code = self._code(doc)
            if code == 190 or code in THROTTLE_CODES or status >= 500 or code is None:
                raise self._fail(status, doc, "balance")
            # 10, 100, 200-299: the token may not read these fields
            obs.event("meta_balance_refused", code=code)
            return {"available": False, "reason": NO_BALANCE}
        cap, spent = _minor(doc.get("spend_cap")), _minor(doc.get("amount_spent"))
        funding = doc.get("funding_source_details")
        return {
            "available": True,
            "prepay": bool(doc.get("is_prepay_account")),
            "funding": str((funding or {}).get("display_string") or "")
            if isinstance(funding, dict)
            else "",
            "spend_cap_cents": cap or None,
            "amount_spent_cents": spent,
            # with a spending limit, what is left before Meta stops delivering
            "remaining_cents": max(0, cap - (spent or 0)) if cap else None,
        }
