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

Reading is two HTTP calls per 50 accounts, not one per account: `/me/adaccounts`, then one
Graph batch request carrying every account's insights and balance reads. The list is kept
for 10 minutes; concurrent cold readers wait for one read and share it; a failure is
remembered for a minute (two when Meta asked for a pause) so a page full of client cards
doesn't hammer Meta, unless an admin asks to refresh. One account whose numbers Meta won't
return comes back with `numbers: false` and a reason; only a revoked token or a throttle
fails the whole list.

Campaign tracking (`sync.py`) reads more: each linked account's campaign list (paged) and
its per-campaign daily insights for a range, plus the period's reach per campaign (reach
doesn't add up over days, so it is asked for as a whole and kept for an hour). Meta keeps 37
months of insights; older `since` dates are clamped. `cmd_serve` starts the sync scheduler
(an hourly pass over the last two days, a nightly one over the last 28) unless
PAUTA_META_SYNC=off; `last_sync` and `sync_error` on this object feed /metrics.

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
  PAUTA_META_SYNC        "off" keeps the in-process sync scheduler from starting (the CLI's
                         `pauta meta sync` still works); anything else, or unset, runs it
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import http.client
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
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from . import obs

VERSION = "v26.0"
GRAPH = f"https://graph.facebook.com/{VERSION}"
DIALOG = f"https://www.facebook.com/{VERSION}/dialog/oauth"
DEV_REDIRECT = "http://localhost:8088/api/meta/callback"
TIMEOUT = 15
STATE_SECONDS = 600
CACHE_SECONDS = 600
FAIL_SECONDS = 60  # a failed read is not retried before this...
THROTTLE_FAIL_SECONDS = 120  # ...or this, when Meta asked for a pause
BATCH = 50  # the Graph batch API's maximum per request
MAX_PENDING = 20
INSIGHTS_FIELDS = "spend,impressions,reach,inline_link_clicks,cost_per_inline_link_click"
BALANCE_FIELDS = "is_prepay_account,funding_source_details,spend_cap,amount_spent"
CAMPAIGN_FIELDS = "id,name,objective,effective_status,status,start_time,stop_time,created_time"
DAILY_FIELDS = "campaign_id,spend,impressions,reach,inline_link_clicks,actions"
REACH_SECONDS = 3600  # a period's reach per campaign is kept this long
HISTORY_MONTHS = 37  # Meta keeps this much insight history
MAX_PAGES = 200  # paging stops here whatever Meta says: never loop forever

UNAVAILABLE = "a Meta não respondeu; tente de novo"
REVOKED = "a conexão com a Meta foi revogada ou expirou; conecte de novo"
NOT_CONNECTED = "a Meta não está conectada; um administrador conecta em Equipe"
NO_BALANCE = "sem permissão para ler o saldo"
NO_NUMBERS = "a Meta não devolveu os números desta conta"
NO_BALANCE_ANSWER = "a Meta não devolveu o saldo desta conta"
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


def _day(value) -> str | None:
    """The date part of a Graph timestamp ("2026-10-03T00:00:00-0300"), in the account's
    own time zone as Meta wrote it, or None."""
    text = str(value or "")[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def earliest(today: date) -> date:
    """The oldest day Meta still serves insights for: today minus 37 months."""
    months = today.year * 12 + today.month - 1 - HISTORY_MONTHS
    first = date(months // 12, months % 12 + 1, 1)
    last_day = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return first.replace(day=min(today.day, last_day.day))


def clamp_since(since: date, today: date | None = None) -> date:
    return max(since, earliest(today or date.today()))


def actions_map(items) -> dict[str, int]:
    """Meta's `actions` list ([{action_type, value}, ...]) as {action_type: int}."""
    out: dict[str, int] = {}
    for a in items if isinstance(items, list) else []:
        if isinstance(a, dict) and a.get("action_type"):
            out[str(a["action_type"])] = out.get(str(a["action_type"]), 0) + _int(a.get("value"))
    return out


def _time_range(since: date, until: date) -> str:
    return json.dumps(
        {"since": since.isoformat(), "until": until.isoformat()}, separators=(",", ":")
    )


def _filter_ids(meta_ids) -> str:
    return json.dumps(
        [{"field": "campaign.id", "operator": "IN", "value": [str(m) for m in meta_ids]}],
        separators=(",", ":"),
    )


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
        self._failed: tuple[float, MetaError] | None = None  # the last failed read
        self._reading = threading.Lock()  # one Meta read at a time (accounts())
        self.error = ""  # why the connection stopped working, until reconnected
        self.last_sync: str | None = None  # when the campaign sync last finished (ISO, UTC)
        self.sync_error = ""  # what the last sync ran into, "" when it went well
        self._reach: dict[tuple, tuple[float, dict[str, int]]] = {}
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

    def _proof(self, token: str) -> str:
        """Proves the call comes from the app's server ("Require app secret" in Meta)."""
        return hmac.new(self._secret().encode(), token.encode(), hashlib.sha256).hexdigest()

    def _get(self, path: str, params: dict, token: str | None = None) -> tuple[int, dict]:
        """One GET to the Graph. Returns (status, JSON); raises MetaError only when Meta
        can't be reached. Never logs the URL: it may carry the code or the secret."""
        query = dict(params)
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
            query["appsecret_proof"] = self._proof(token)
        url = f"{self.graph}{path}?{urllib.parse.urlencode(query)}"
        status, doc = self._send(urllib.request.Request(url, headers=headers))
        return status, doc if isinstance(doc, dict) else {}

    def _post(self, path: str, form: dict, token: str) -> tuple[int, dict | list]:
        """One POST to the Graph with a form body (the token and its proof included)."""
        body = urllib.parse.urlencode(
            {**form, "access_token": token, "appsecret_proof": self._proof(token)}
        ).encode()
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        return self._send(urllib.request.Request(f"{self.graph}{path}", body, headers))

    @staticmethod
    def _send(req: urllib.request.Request) -> tuple[int, dict | list]:
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                status, raw = r.status, r.read()
        except urllib.error.HTTPError as e:
            with e:
                status, raw = e.code, e.read()
        except (OSError, ValueError, http.client.HTTPException) as e:
            # HTTPException: a short or malformed answer (IncompleteRead, a bad status line)
            obs.event("meta_unreachable", logging.WARNING, error=type(e).__name__)
            raise MetaError(UNAVAILABLE) from None
        try:
            doc = json.loads(raw or b"{}")
        except ValueError:
            doc = {}
        return status, doc if isinstance(doc, (dict, list)) else {}

    @staticmethod
    def _code(doc: dict) -> int | None:
        err = doc.get("error") if isinstance(doc, dict) else None
        return err.get("code") if isinstance(err, dict) else None

    @staticmethod
    def _throttle(code) -> bool:
        return code in THROTTLE_CODES or (isinstance(code, int) and 80000 <= code < 80100)

    def _fail(self, status: int, doc: dict, step: str) -> MetaError:
        """The error for a Graph answer that wasn't 200 (logged without any message text)."""
        code = self._code(doc)
        obs.event("meta_error", logging.WARNING, status=status, code=code, step=step)
        if code == 190:
            self.error = REVOKED
            self._cache = None
            obs.event("meta_revoked", logging.ERROR)
            return MetaError(REVOKED, 409)
        if self._throttle(code):
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
        # a Graph id is digits; anything else never reaches a path
        business_id = str(me.get("client_business_id") or "")
        business_id = business_id if business_id.isdigit() else ""
        business_name = ""
        if business_id:
            status, biz = self._get(f"/{business_id}", {"fields": "name"}, token)
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
        self._cache = self._failed = None
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
            self._cache = self._failed = None
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
        Pauta read it, the balance. Kept for 10 minutes unless `refresh`; a failed read is
        raised again, without asking Meta, for a minute (`refresh` asks anyway). Readers
        arriving while one read is under way wait for it and get the same list."""
        fresh = self._fresh(refresh)
        if fresh is not None:
            return fresh
        with self._reading:
            fresh = self._fresh(refresh)  # someone else may just have read it
            if fresh is not None:
                return fresh
            try:
                out = self._read()
            except MetaError as e:
                self._failed = (time.time(), e)
                raise
            self._cache, self._failed = (time.time(), out), None
        obs.event("meta_read", accounts=len(out))
        if self.on_read:
            self.on_read(out)
        return out

    def _fresh(self, refresh: bool) -> list[dict] | None:
        """The cached list when it may be used; raises the last failure while it is recent."""
        if refresh:
            return None
        now = time.time()
        cached = self._cache
        if cached and now - cached[0] < CACHE_SECONDS:
            return cached[1]
        failed = self._failed
        if failed:
            at, err = failed
            keep = THROTTLE_FAIL_SECONDS if err.status == 503 else FAIL_SECONDS
            if now - at < keep:
                raise MetaError(str(err), err.status, err.reason)
        return None

    def _read(self) -> list[dict]:
        """The list from Meta: /me/adaccounts, then every account's insights and balance in
        batch requests of up to 50 reads (two per account)."""
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
        out = []
        for a in doc.get("data") or []:
            if not isinstance(a, dict):
                continue
            aid = "".join(c for c in str(a.get("account_id") or a.get("id") or "") if c.isdigit())
            status = _int(a.get("account_status"))
            out.append(
                {
                    "id": aid,
                    "name": str(a.get("name") or ""),
                    "currency": str(a.get("currency") or "BRL"),
                    "status": status,
                    "status_label": ACCOUNT_STATUS.get(status, ""),
                }
            )
        reads = []
        for acc in out:
            reads.append(
                f"act_{acc['id']}/insights?date_preset=this_month&fields={INSIGHTS_FIELDS}"
            )
            reads.append(f"act_{acc['id']}?fields={BALANCE_FIELDS}")
        answers: list = []
        for i in range(0, len(reads), BATCH):
            answers.extend(self._batch(reads[i : i + BATCH]))
        for acc, i in zip(out, range(0, len(answers), 2), strict=True):
            acc.update(self._numbers(answers[i]))
            acc["balance"] = self._balance(answers[i + 1])
        return out

    def _batch(self, reads: list[str]) -> list[tuple[int | None, dict]]:
        """One Graph batch request: each read's (code, JSON), in order; (None, {}) for a read
        Meta gave up on (a null entry)."""
        saved = self._saved() if self.enabled else None
        if not saved:
            raise MetaError(NOT_CONNECTED, 409)
        items = [{"method": "GET", "relative_url": r} for r in reads]
        status, doc = self._post(
            "/",
            {"batch": json.dumps(items), "include_headers": "false"},
            saved["access_token"],
        )
        if status != 200 or not isinstance(doc, list):
            raise self._fail(status, doc if isinstance(doc, dict) else {}, "batch")
        out: list[tuple[int | None, dict]] = []
        for entry in list(doc)[: len(reads)] + [None] * (len(reads) - len(doc)):
            if not isinstance(entry, dict):
                out.append((None, {}))
                continue
            try:
                body = json.loads(entry.get("body") or "{}")
            except (ValueError, TypeError):
                body = {}
            code = entry.get("code")
            out.append(
                (code if isinstance(code, int) else None, body if isinstance(body, dict) else {})
            )
        return out

    def _numbers(self, answer: tuple[int | None, dict]) -> dict:
        """This month's numbers from an insights read. Meta not answering for this one
        account is not the list's problem: `numbers: false` and a reason (the UI shows
        dashes); a revoked token or a throttle is."""
        status, ins = answer
        if status != 200:
            code = self._code(ins)
            if code == 190 or self._throttle(code):
                raise self._fail(status or 0, ins, "insights")
            obs.event("meta_numbers_missing", logging.WARNING, status=status, code=code)
            return {
                "numbers": False,
                "reason": NO_NUMBERS,
                "spend_cents": None,
                "impressions": None,
                "reach": None,
                "link_clicks": None,
                "cpc_cents": None,
            }
        row = next(iter(ins.get("data") or []), None) or {}
        return {
            "numbers": True,
            "spend_cents": cents(row.get("spend")) or 0,
            "impressions": _int(row.get("impressions")),
            "reach": _int(row.get("reach")),
            "link_clicks": _int(row.get("inline_link_clicks")),
            "cpc_cents": cents(row.get("cost_per_inline_link_click")),
        }

    def _balance(self, answer: tuple[int | None, dict]) -> dict:
        """What is left on the account. Meta shows the funding details only to a token with
        more than ANALYZE on the account (decision 8, "Saldo"): a refusal is not an error."""
        status, doc = answer
        if status is None:  # Meta gave up on this read: the rest of the account still shows
            obs.event("meta_balance_missing", logging.WARNING)
            return {"available": False, "reason": NO_BALANCE_ANSWER}
        if status != 200:
            code = self._code(doc)
            if code == 190 or self._throttle(code) or status >= 500 or code is None:
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

    # ---- campaign tracking reads (sync.py) ---------------------------------------------------

    def _pages(self, path: str, params: dict, step: str) -> list[dict]:
        """Every `data` entry of a paged Graph list, following `paging.cursors.after`."""
        out: list[dict] = []
        query = dict(params)
        for _ in range(MAX_PAGES):
            doc = self._graph(path, query, step)
            out.extend(d for d in doc.get("data") or [] if isinstance(d, dict))
            paging = doc.get("paging") if isinstance(doc.get("paging"), dict) else {}
            after = (paging.get("cursors") or {}).get("after") if paging else None
            if not paging.get("next") or not after or after == query.get("after"):
                break
            query["after"] = after
        return out

    def campaigns(self, account_id: str) -> list[dict]:
        """Every campaign of one ad account, as {id, name, objective, effective_status,
        status, started, stopped}: dates are `YYYY-MM-DD` (the start date, or the creation
        date when Meta has no start)."""
        aid = "".join(c for c in str(account_id) if c.isdigit())
        rows = self._pages(
            f"/act_{aid}/campaigns", {"fields": CAMPAIGN_FIELDS, "limit": "100"}, "campaigns"
        )
        out = []
        for c in rows:
            cid = "".join(ch for ch in str(c.get("id") or "") if ch.isdigit())
            if not cid:
                continue
            out.append(
                {
                    "id": cid,
                    "name": str(c.get("name") or ""),
                    "objective": str(c.get("objective") or ""),
                    "effective_status": str(c.get("effective_status") or ""),
                    "status": str(c.get("status") or ""),
                    "started": _day(c.get("start_time")) or _day(c.get("created_time")),
                    "stopped": _day(c.get("stop_time")),
                }
            )
        return out

    def daily_insights(
        self,
        account_id: str,
        since: date,
        until: date,
        meta_ids: list[str] | None = None,
        today: date | None = None,
    ) -> list[dict]:
        """One row per campaign per day in the range: {meta_id, day, spend_cents, impressions,
        reach, link_clicks, actions}. `since` is clamped to what Meta still keeps; an empty
        range asks nothing. `meta_ids` narrows the read to those campaigns."""
        aid = "".join(c for c in str(account_id) if c.isdigit())
        since = clamp_since(since, today)
        if since > until:
            return []
        params = {
            "level": "campaign",
            "time_increment": "1",
            "time_range": _time_range(since, until),
            "fields": DAILY_FIELDS,
            "limit": "500",
        }
        if meta_ids:
            params["filtering"] = _filter_ids(meta_ids)
        out = []
        for r in self._pages(f"/act_{aid}/insights", params, "insights"):
            mid = "".join(c for c in str(r.get("campaign_id") or "") if c.isdigit())
            day = _day(r.get("date_start"))
            if not mid or not day:
                continue
            out.append(
                {
                    "meta_id": mid,
                    "day": day,
                    "spend_cents": cents(r.get("spend")) or 0,
                    "impressions": _int(r.get("impressions")),
                    "reach": _int(r.get("reach")),
                    "link_clicks": _int(r.get("inline_link_clicks")),
                    "actions": actions_map(r.get("actions")),
                }
            )
        return out

    def reach(
        self, pairs: list[tuple[str, str]], since: date, until: date, today: date | None = None
    ) -> dict[str, int]:
        """The period's reach per campaign ({meta_id: people}) for (account_id, meta_id)
        pairs: one batched read per account, kept for an hour per (account, period). Reach
        doesn't add over days, so this is the only honest period number. A campaign Meta
        says nothing about is left out (the caller shows a dash)."""
        since = clamp_since(since, today)
        if since > until or not pairs:
            return {}
        by_account: dict[str, list[str]] = {}
        for account_id, meta_id in pairs:
            aid = "".join(c for c in str(account_id) if c.isdigit())
            by_account.setdefault(aid, []).append(str(meta_id))
        now = time.time()
        out: dict[str, int] = {}
        todo: list[str] = []
        with self._lock:
            for aid, ids in by_account.items():
                hit = self._reach.get((aid, since, until))
                if hit and now - hit[0] < REACH_SECONDS and all(m in hit[1] for m in ids):
                    out.update({m: hit[1][m] for m in ids if hit[1][m] is not None})
                else:
                    todo.append(aid)
        if not todo:
            return out
        reads = [
            f"act_{aid}/insights?"
            + urllib.parse.urlencode(
                {
                    "level": "campaign",
                    "time_range": _time_range(since, until),
                    "fields": "campaign_id,reach",
                    "filtering": _filter_ids(by_account[aid]),
                    "limit": "500",
                }
            )
            for aid in todo
        ]
        answers: list = []
        for i in range(0, len(reads), BATCH):
            answers.extend(self._batch(reads[i : i + BATCH]))
        for aid, (status, doc) in zip(todo, answers, strict=True):
            if status != 200:
                code = self._code(doc)
                if code == 190 or self._throttle(code):
                    raise self._fail(status or 0, doc, "reach")
                obs.event("meta_reach_missing", logging.WARNING, status=status, code=code)
                continue
            got: dict[str, int | None] = dict.fromkeys(by_account[aid], None)
            for r in doc.get("data") or []:
                mid = "".join(c for c in str(r.get("campaign_id") or "") if c.isdigit())
                if mid in got:
                    got[mid] = _int(r.get("reach"))
            with self._lock:
                self._reach = {k: v for k, v in self._reach.items() if now - v[0] < REACH_SECONDS}
                self._reach[(aid, since, until)] = (now, got)
            out.update({m: v for m, v in got.items() if v is not None})
        return out
