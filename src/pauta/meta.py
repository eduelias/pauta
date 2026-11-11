"""The team's Meta business portfolios, read through the Marketing API (decision 8, phase 2).

An admin clicks "Conectar Meta" on Configurações. Pauta sends them to Facebook Login for Business
with Du7's app and its login configuration (a system-user token, MANAGE on the ad accounts,
`ads_read` only); they pick ONE portfolio and its ad accounts and Meta sends them back to
`/api/meta/callback` with a one-time code. Pauta exchanges the code, with the app secret, for
the system user's token, which does not expire. Pauta only reads: it never creates, edits,
pauses or pays for anything.

Connections belong to the team, not to a person, and a team has several: Facebook Login for
Business connects one business portfolio per login, and the system user Pauta gets lives in
that portfolio (on acceptance, a client's). So Pauta keeps **one connection per connected
portfolio**, keyed by the business id `/me` reports (`client_business_id`; the system user's
own id when Meta doesn't say). Every read is the union over connections, each account tagged
with its `business_id`; a revoked token (Graph error 190) marks only its connection.

Token files, one per business, next to the database (like the OneDrive token), never in it,
so backups and the export can't be turned into Meta access:

  <db>.meta-token.<business_id>   {"access_token", "business_id", "business_name",
                                   "connected_at", "by", "state", "error"}, mode 600
  <db>.meta-token                 the single file releases before this one wrote: moved to
                                  the per-business name when `Meta` is built. One without a
                                  business id becomes <db>.meta-token.legacy, listed with a
                                  "reconecte" state and never read

`Meta` owns these files and knows no SQLite: `connections()` lists them (business_id, name,
connected_at, by, state, error). The database mirrors them in `meta_connection` (plus
`last_sync`, which the sync writes): the server binds `on_change` to `Store.sync_connections`
and calls it once at startup, so the rows follow the files, never the other way round.

The session cookie is SameSite=Strict, so it is not sent on the redirect back from
facebook.com: the callback is authorized by the one-time `state` instead, made for the
admin who clicked (and for the business they were adding accounts to, if any), kept in
memory for 10 minutes and used once. A login that comes back for another business than the
one it was started for is saved under its own business: a connection never overwrites
another.

Reading is two HTTP calls per connection per 50 accounts, not one per account:
`/me/adaccounts`, then one Graph batch request carrying every account's insights and balance
reads, each with that connection's token and appsecret_proof. The union is kept for 10
minutes; concurrent cold readers wait for one read and share it; a read that failed as a
whole is remembered for a minute (two when Meta asked for a pause) so a page full of client
cards doesn't hammer Meta, unless an admin asks to refresh. One account whose numbers Meta
won't return comes back with `numbers: false` and a reason; one connection Meta refuses is
left out (a revoked token marks it `revoked` on `connections()`; Meta not answering for it
is passing trouble) and the others still read; only a throttle, or every connection
failing, fails the whole list.

Campaign tracking (`sync.py`) reads more: each linked account's campaign list (paged) and
its per-campaign daily insights for a range, plus the period's reach per campaign (reach
doesn't add up over days, so it is asked for as a whole and kept for an hour). Those reads
take the account's business (`business_id`, or the map `business_of` filled by the last
account read and seeded by the server from `meta_account`; with a single connection, that
one). Meta keeps 37 months of insights; older `since` dates are clamped. `cmd_serve` starts
the sync scheduler (an hourly pass over the last two days, a nightly one over the last 28)
unless PAUTA_META_SYNC=off; `last_sync` and `sync_error` on this object feed /metrics.

Revoking access is the portfolio's side: that business's Settings → Integrations →
Connected apps. "Desconectar" only forgets that one token here.

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
  <db>.meta-token.<id>   written by Pauta per connected portfolio (mode 600)
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
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from . import obs

VERSION = "v26.0"
GRAPH = f"https://graph.facebook.com/{VERSION}"
DIALOG = f"https://www.facebook.com/{VERSION}/dialog/oauth"
DEV_REDIRECT = "http://localhost:8088/api/meta/callback"
TIMEOUT = 15
STATE_SECONDS = 600
CACHE_SECONDS = 600  # the account list is answered from memory this long...
STALE_SECONDS = 24 * 3600  # ...and, while Meta is read again behind it, up to this long
FAIL_SECONDS = 60  # a failed read is not retried before this...
THROTTLE_FAIL_SECONDS = 120  # ...or this, when Meta asked for a pause
BATCH = 50  # the Graph batch API's maximum per request
MAX_PENDING = 20
INSIGHTS_FIELDS = "spend,impressions,reach,inline_link_clicks,cost_per_inline_link_click"
BALANCE_FIELDS = "is_prepay_account,funding_source_details,spend_cap,amount_spent"
ACCOUNT_FIELDS = "name,account_id,currency,account_status,timezone_name"
CAMPAIGN_FIELDS = (
    "id,name,objective,effective_status,status,start_time,stop_time,created_time,"
    "daily_budget,lifetime_budget"
)
DAILY_FIELDS = (
    "campaign_id,spend,impressions,reach,inline_link_clicks,actions,results,cost_per_result"
)
# Ads Manager's Resultados when Meta's `results` entry is missing: the campaign's objective
# names the action type that counts (read from `actions`). Objectives not here get no result.
OBJECTIVE_RESULTS = {
    "OUTCOME_LEADS": "lead",
    "OUTCOME_SALES": "purchase",
    "OUTCOME_TRAFFIC": "link_click",
    "LINK_CLICKS": "link_click",
    "OUTCOME_ENGAGEMENT": "post_engagement",
    "MESSAGES": "onsite_conversion.messaging_conversation_started_7d",
    "OUTCOME_MESSAGES": "onsite_conversion.messaging_conversation_started_7d",
}
# "today" is the ad account's day, not the server's (du7 runs on CET; Piero's accounts are
# in São Paulo): the team's default when an account doesn't say, PAUTA_TZ overrides it
DEFAULT_TZ = "America/Sao_Paulo"
DEFAULT_PERIOD_DAYS = 30  # Ads Manager's own default period: "Últimos 30 dias", yesterday back
REACH_SECONDS = 3600  # a period's reach per campaign is answered from memory this long...
REACH_STALE_SECONDS = 24 * 3600  # ...and, while Meta is read again behind it, up to this long
HISTORY_MONTHS = 37  # Meta keeps this much insight history
MAX_PAGES = 200  # paging stops here whatever Meta says: never loop forever
LEGACY = "legacy"  # the business "id" of a pre-connection token file without one

UNAVAILABLE = "a Meta não respondeu; tente de novo"
REVOKED = "a conexão com a Meta foi revogada ou expirou; conecte de novo"
NOT_CONNECTED = "a Meta não está conectada; um administrador conecta em Configurações → Meta"
NO_BUSINESS = "a Meta não disse qual é o portfólio; tente de novo"
UNKNOWN_BUSINESS = "este portfólio não está conectado"
RECONNECT = "conexão antiga sem portfólio identificado; reconecte em Adicionar contas"
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


def _digits(value) -> str:
    return "".join(c for c in str(value or "") if c.isdigit())


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


def _now() -> datetime:
    return datetime.now(UTC)


def local_today(tz_name: str, now: datetime | None = None) -> date:
    """Today in the ad account's time zone (`timezone_name` as Meta reports it, e.g.
    "America/Sao_Paulo"); an empty or unknown name falls back to `PAUTA_TZ`, then
    `DEFAULT_TZ`, then UTC."""
    now = now or _now()
    for name in (tz_name, os.environ.get("PAUTA_TZ", ""), DEFAULT_TZ):
        if not name:
            continue
        try:
            return now.astimezone(ZoneInfo(str(name))).date()
        except (KeyError, ValueError, OSError):
            continue
    return now.astimezone(UTC).date()


def results_of(row: dict, objective: str = "") -> tuple[int | None, str]:
    """Ads Manager's Resultados for one insights row: (count, indicator), the indicator
    being the action type after `actions:`. Meta's `results` entry is
    [{"indicator": "actions:<type>", "values": [{"value": "4", "attribution_windows":
    ["default"]}]}]; one without `values` has no events (Ads Manager shows "—"): None.
    With no entry at all, the campaign's `objective` names the type (OBJECTIVE_RESULTS)
    and the count comes from `actions`, None when the type isn't there; an objective not
    mapped gives (None, "")."""
    for entry in row.get("results") if isinstance(row.get("results"), list) else []:
        if not isinstance(entry, dict) or not entry.get("indicator"):
            continue
        indicator = str(entry["indicator"]).removeprefix("actions:")
        values = entry.get("values") if isinstance(entry.get("values"), list) else []
        values = [v for v in values if isinstance(v, dict) and v.get("value") not in (None, "")]
        if not values:
            return None, indicator
        default = [v for v in values if "default" in (v.get("attribution_windows") or [])]
        return _int((default or values)[0].get("value")), indicator
    kind = OBJECTIVE_RESULTS.get(str(objective or ""))
    if not kind:
        return None, ""
    actions = actions_map(row.get("actions"))
    return actions.get(kind), kind


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


def _stamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


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
        self.legacy_file = Path(f"{db_path}.meta-token")  # the single file of releases < v10
        self._lock = threading.Lock()
        # state -> (account, business being re-logged into or None, expiry)
        self._states: dict[str, tuple[int | None, str | None, float]] = {}
        # states that already connected: a second load of the same callback (a reload, the
        # browser retrying) says "conectado" again instead of "expirou"
        self._done: dict[str, float] = {}  # state -> expiry
        self._cache: tuple[float, list[dict]] | None = None
        # bumped by a connect, a disconnect or a revocation: a read that started before
        # one of those is of the connections before it and is not kept
        self._gen = 0
        self._failed: tuple[float, MetaError] | None = None  # the last read that failed whole
        self._reading = threading.Lock()  # one Meta read at a time (accounts())
        self.last_sync: str | None = None  # when the campaign sync last finished (ISO, UTC)
        self.sync_error = ""  # what the last sync ran into, "" when it went well
        self._reach: dict[tuple, tuple[float, dict[str, int]]] = {}
        self._reach_reading = threading.Lock()  # one reach read behind a page at a time
        self._reach_failed = 0.0  # when a read behind a page last failed (not retried for a minute)
        # account id -> business id, from the last read; the server seeds it from the DB
        self.business_of: dict[str, str] = {}
        # linked accounts the sync's last placing read could not put under a connection
        # (gone from Meta, or their portfolio disconnected): the sync reads again only
        # when this set changes, and reports these at INFO after the first time
        self.orphans: frozenset[str] = frozenset()
        # called with the fresh list each time Meta is actually read (not from the cache);
        # the server keeps the account ↔ client mapping there (db.sync_meta_accounts)
        self.on_read: Callable[[list[dict]], None] | None = None
        # called with connections() after a connect, a disconnect or a state change; the
        # server mirrors them into meta_connection (db.sync_connections)
        self.on_change: Callable[[list[dict]], None] | None = None
        self._migrate()

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

    # ---- configuration and the token files -----------------------------------------------

    def _secret(self) -> str:
        try:
            return self.secret_file.read_text().strip()
        except (OSError, UnicodeDecodeError):
            return ""

    @property
    def enabled(self) -> bool:
        return bool(self.app_id and self.config_id and self._secret())

    def token_file(self, business_id: str) -> Path:
        return self.legacy_file.with_name(f"{self.legacy_file.name}.{business_id}")

    @staticmethod
    def _load(path: Path) -> dict | None:
        try:
            doc = json.loads(path.read_text())
        except (OSError, ValueError):
            return None
        return doc if isinstance(doc, dict) and doc.get("access_token") else None

    def _saved(self, business_id: str) -> dict | None:
        return self._load(self.token_file(business_id)) if business_id else None

    def _save(self, doc: dict, *, create: bool = True) -> bool:
        """Write a connection's file (mode 600, atomically). With `create` off it only
        updates a file that is still there: a 190 answered during Desconectar must not
        bring the token back. Returns whether it wrote."""
        target = self.token_file(doc["business_id"])
        if not create and not target.exists():
            return False
        tmp = target.with_name(target.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(doc, f)
        os.replace(tmp, target)
        return True

    def _migrate(self) -> None:
        """The single `<db>.meta-token` of earlier releases becomes a per-business file (the
        same bytes, so the mode stays 600). One without a business id can't be placed:
        it is kept as `.legacy`, shown as "reconecte" and never read. One that isn't a
        token document at all (unreadable JSON, say) is moved aside the same way, with a
        warning, so the next start doesn't trip over it again."""
        if not self.legacy_file.exists():
            return
        doc = self._load(self.legacy_file)
        if doc is None:
            obs.event("meta_token_unreadable", logging.WARNING)
        business_id = _digits(doc.get("business_id")) if doc else ""
        target = self.token_file(business_id or LEGACY)
        if target.exists():  # connected again since: the newer file wins
            self.legacy_file.unlink()
        else:
            os.replace(self.legacy_file, target)
        if doc:
            obs.event("meta_token_migrated", legacy=not business_id)

    def _files(self) -> dict[str, dict]:
        """Every connection's saved document, by business id (digits, or "legacy")."""
        out: dict[str, dict] = {}
        prefix = self.legacy_file.name + "."
        try:
            names = sorted(os.listdir(self.legacy_file.parent))
        except OSError:
            return out
        for name in names:
            if not name.startswith(prefix):
                continue
            business_id = name[len(prefix) :]
            if not (business_id.isdigit() or business_id == LEGACY):
                continue  # a .tmp, or something that isn't ours
            doc = self._load(self.legacy_file.parent / name)
            if doc:
                out[business_id] = {**doc, "business_id": business_id}
        return out

    def _connection(self, business_id: str, doc: dict) -> dict:
        state, error = str(doc.get("state") or "ok"), str(doc.get("error") or "")
        if business_id == LEGACY:
            state, error = "error", RECONNECT
        return {
            "business_id": business_id,
            "business_name": str(doc.get("business_name") or ""),
            "connected_at": str(doc.get("connected_at") or ""),
            "by": doc.get("by") if isinstance(doc.get("by"), int) else None,
            "state": state,
            "error": error,
        }

    def connections(self) -> list[dict]:
        """Every connected portfolio, oldest first, never the token: {business_id,
        business_name, connected_at, by, state (ok|revoked|error), error}."""
        if not self.enabled:
            return []
        conns = [self._connection(b, doc) for b, doc in self._files().items()]
        return sorted(conns, key=lambda c: (c["connected_at"], c["business_id"]))

    def _readable(self) -> list[dict]:
        """The connections whose token is worth trying (not the legacy leftover)."""
        return [c for c in self.connections() if c["business_id"] != LEGACY]

    @property
    def connected(self) -> bool:
        """Something is connected (whatever its state): there is a portfolio to read."""
        return bool(self.connections())

    @property
    def error(self) -> str:
        """The first connection's trouble, for /metrics and the old callers; "" when fine."""
        return next((c["error"] for c in self.connections() if c["error"]), "")

    def _mark(self, business_id: str, state: str, error: str) -> None:
        """A connection's state, kept in its file so it outlives a restart. Read and write
        under the lock, and only a file still there: Desconectar (which unlinks under the
        same lock) wins over a late 190."""
        with self._lock:
            doc = self._saved(business_id)
            if doc and (doc.get("state") or "ok", doc.get("error") or "") != (state, error):
                self._save(
                    {**doc, "business_id": business_id, "state": state, "error": error},
                    create=False,
                )
        self._changed()

    def _changed(self) -> None:
        if self.on_change:
            self.on_change(self.connections())

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

    def _fail(self, status: int, doc: dict, step: str, business_id: str = "") -> MetaError:
        """The error for a Graph answer that wasn't 200 (logged without any message text).
        A 190 marks the one connection it came from as revoked; the others go on."""
        code = self._code(doc)
        obs.event("meta_error", logging.WARNING, status=status, code=code, step=step)
        if code == 190:
            # dropped, not aged: the pages must report the revocation, not an old list
            self._cache = None
            self._gen += 1
            obs.event("meta_revoked", logging.ERROR, business=business_id or None)
            if business_id:
                self._mark(business_id, "revoked", REVOKED)
            return MetaError(REVOKED, 409)
        if self._throttle(code):
            return MetaError(THROTTLED, 503)
        return MetaError(UNAVAILABLE)

    def _token(self, business_id: str) -> str:
        saved = self._saved(business_id) if self.enabled else None
        if not saved:
            raise MetaError(NOT_CONNECTED if not self.connected else UNKNOWN_BUSINESS, 409)
        return saved["access_token"]

    def _graph(self, path: str, params: dict, step: str, business_id: str) -> dict:
        status, doc = self._get(path, params, self._token(business_id))
        if status != 200:
            raise self._fail(status, doc, step, business_id)
        return doc

    def _business_for(self, account_id: str, business_id: str | None = None) -> str:
        """Which connection reads an ad account: the one given, the one the last account
        read saw it under, or, with a single connection, that one."""
        if business_id:
            return _digits(business_id) or business_id
        aid = _digits(account_id)
        known = self.business_of.get(aid)
        if known:
            return known
        conns = self._readable()
        if len(conns) == 1:
            return conns[0]["business_id"]
        raise MetaError(NOT_CONNECTED if not conns else UNKNOWN_BUSINESS, 409)

    # ---- connecting ----------------------------------------------------------------------

    def start_connect(self, account_id: int | None, business_id: str | None = None) -> str:
        """A one-time state for this admin and the URL of Meta's login dialog. `business_id`
        is the connection they are adding accounts to (a re-login on that portfolio);
        None connects another portfolio."""
        if not self.enabled:
            raise MetaError("o servidor não tem a Meta configurada", 400, "desligado")
        business_id = _digits(business_id) or None
        if business_id and not self._saved(business_id):
            raise MetaError(UNKNOWN_BUSINESS, 404)
        state = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock:
            self._states = {s: v for s, v in self._states.items() if v[2] > now}
            while len(self._states) >= MAX_PENDING:  # the oldest go first
                self._states.pop(min(self._states, key=lambda s: self._states[s][2]))
            self._states[state] = (account_id, business_id, now + STATE_SECONDS)
        query = {
            "client_id": self.app_id,
            "config_id": self.config_id,
            "response_type": "code",
            "override_default_response_type": "true",
            "redirect_uri": self.redirect_uri,
            "state": state,
        }
        obs.event("meta_connect_started", account=account_id, business=business_id)
        return f"{self.dialog}?{urllib.parse.urlencode(query)}"

    def take_state(self, state: str) -> tuple[int | None, str | None]:
        """Use up a state: (the account that started it, the business it was re-logging
        into or None). Unknown, expired or used: MetaError."""
        with self._lock:
            entry = self._states.pop(state or "", None)
        if not entry or entry[2] < time.time():
            obs.event("meta_bad_state", logging.WARNING)
            raise MetaError("o pedido de conexão expirou; comece de novo", 400, "expirou")
        return entry[0], entry[1]

    def finish_connect(self, state: str, code: str) -> dict | None:
        """Meta sent the admin back with a code: exchange it and keep the token under the
        business it belongs to. Returns the connection (None for a repeated callback)."""
        if not self.enabled:
            raise MetaError("o servidor não tem a Meta configurada", 400, "desligado")
        with self._lock:
            done = self._done.get(state or "", 0) > time.time()
        if done:
            obs.event("meta_callback_repeated")
            return None
        by, wanted = self.take_state(state)
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
        # a Graph id is digits; anything else never reaches a path. Without a portfolio id
        # the system user's own id keys the connection (it is unique to its portfolio too)
        business_id = _digits(me.get("client_business_id"))
        business_name = ""
        if business_id:
            status, biz = self._get(f"/{business_id}", {"fields": "name"}, token)
            if status == 200:
                business_name = str(biz.get("name") or "")
        else:
            business_id = _digits(me.get("id"))
        if not business_id:
            raise MetaError(NO_BUSINESS, 502)
        if wanted and wanted != business_id:
            obs.event("meta_connected_other_business", logging.WARNING, wanted=wanted)
        self._save(
            {
                "access_token": token,
                "business_id": business_id,
                "business_name": business_name or str(me.get("name") or ""),
                "connected_at": _stamp(),
                "by": by,
                "state": "ok",
                "error": "",
            }
        )
        with self._lock:
            self._age_list()  # the new portfolio's accounts come with the read behind
            now = time.time()
            self._done = {s: t for s, t in self._done.items() if t > now}
            self._done[state] = now + STATE_SECONDS
        obs.event("meta_connected", account=by, business=business_id)
        self._changed()
        return self._connection(business_id, self._saved(business_id) or {})

    def disconnect(self, business_id: str | None = None) -> None:
        """Forget one portfolio's token here (every one when `business_id` is None).
        Revoking it in Meta is the portfolio owner's step."""
        gone = [business_id] if business_id else list(self._files())
        with self._lock:
            for b in gone:
                with contextlib.suppress(FileNotFoundError):
                    self.token_file(b).unlink()
            if business_id:
                self._age_list(business_id)
            else:
                self._cache = self._failed = None
                self._gen += 1
        obs.event("meta_disconnected", business=business_id)
        self._changed()

    def status(self) -> dict:
        """For the Configurações page and /metrics. Never the token."""
        conns = self.connections()
        cached = self._cache
        failed = self._recent_failure()
        return {
            "enabled": self.enabled,
            "connected": bool(conns),
            "connections": conns,
            "error": next((c["error"] for c in conns if c["error"]), ""),
            # when the account list was last read from Meta (what the pages show may be
            # that old while a new read runs behind it); None before the first read
            "accounts_at": (
                datetime.fromtimestamp(cached[0], UTC).isoformat(timespec="seconds")
                if cached
                else None
            ),
            # the list the pages answer with is past its ten minutes (or there is none):
            # Meta is being read behind it, and the page asks again until this clears
            "accounts_stale": not cached or time.time() - cached[0] >= CACHE_SECONDS,
            # what the last read ran into, while it is too recent to try again ("" otherwise)
            "accounts_error": str(failed) if failed else "",
        }

    def _age_list(self, drop_business: str | None = None) -> None:
        """A connect or a disconnect (`_lock` held): the kept list is not dropped but aged
        past its ten minutes, so the next page answers with it at once (without
        `drop_business`'s accounts) while Meta is read again behind it. Dropping it made
        the first page after a connect wait for a full read of every portfolio (seven to
        seventeen seconds with nine of them). A revocation still drops it: the pages
        must report that, not show an old list."""
        self._gen += 1
        self._failed = None
        cached = self._cache
        if not cached:
            return
        kept = [a for a in cached[1] if a.get("business_id") != drop_business]
        self._cache = (min(cached[0], time.time() - CACHE_SECONDS), kept)

    # ---- reading -------------------------------------------------------------------------

    def accounts(self, refresh: bool = False, stale: bool = True) -> list[dict]:
        """Every ad account every connection reads, each tagged with its `business_id` and
        `business_name`, with this month's numbers and, when Meta lets Pauta read it, the
        balance. Kept for 10 minutes; after that the last list is answered at once and
        Meta is read again on a thread behind it (`stale=False` waits for the new list
        instead, as the sync does; `refresh` asks Meta whatever the cache says). A read
        that failed as a whole is raised again, without asking Meta, for a minute
        (`refresh` asks anyway), unless there is a list to answer with. Readers arriving
        while one read is under way wait for it and get the same list."""
        fresh = self._fresh(refresh)
        if fresh is not None:
            return fresh
        if stale and not refresh:
            kept = self._stale()
            if kept is not None:
                self._refresh_soon()
                return kept
        if not refresh:
            self._raise_recent_failure()
        with self._reading:
            fresh = self._fresh(refresh)  # someone else may just have read it
            if fresh is not None:
                return fresh
            if not refresh:
                self._raise_recent_failure()
            return self._read_into_cache()

    def _fresh(self, refresh: bool) -> list[dict] | None:
        """The cached list while it counts as fresh."""
        if refresh:
            return None
        cached = self._cache
        if cached and time.time() - cached[0] < CACHE_SECONDS:
            return cached[1]
        return None

    def _stale(self) -> list[dict] | None:
        """The cached list past its ten minutes but still worth showing while Meta is read
        again; None when there is none, or it is a day old (then the reader waits)."""
        cached = self._cache
        if cached and time.time() - cached[0] < STALE_SECONDS:
            return cached[1]
        return None

    def _recent_failure(self) -> MetaError | None:
        """The last read's failure while it is too recent to ask Meta again."""
        failed = self._failed
        if failed:
            at, err = failed
            keep = THROTTLE_FAIL_SECONDS if err.status == 503 else FAIL_SECONDS
            if time.time() - at < keep:
                return err
        return None

    def _raise_recent_failure(self) -> None:
        err = self._recent_failure()
        if err:
            raise MetaError(str(err), err.status, err.reason)

    def _refresh_soon(self) -> None:
        """Read Meta again on a thread of its own, unless a read is already under way or
        the last one failed a moment ago (the stale list stands until the minute is up)."""
        if self._recent_failure() or not self._reading.acquire(blocking=False):
            return

        def work():
            try:
                if self._fresh(False) is None:  # unless a reader just did it
                    self._read_into_cache()
            except MetaError:
                pass  # in `_failed`; the next reader after a minute tries again
            except Exception:
                obs.event("meta_read_failed", logging.ERROR)
                logging.getLogger("pauta").exception("account list read failed behind a page")
            finally:
                self._reading.release()

        try:
            threading.Thread(target=work, name="meta-accounts", daemon=True).start()
        except RuntimeError:  # no thread to be had: the kept list stands, nothing waits
            self._reading.release()
            obs.event("meta_read_thread_failed", logging.ERROR)

    def _read_into_cache(self) -> list[dict]:
        """Meta, now, with `_reading` held: the list into the cache (and to `on_read`), or
        the failure into `_failed` and raised. A connect, disconnect or revocation while
        Meta answered makes the list one of the connections before it: read once more,
        and if it happens again answer with it but keep nothing."""
        for _ in range(2):
            gen = self._gen
            try:
                out = self._read()
            except MetaError as e:
                self._failed = (time.time(), e)
                raise
            if gen == self._gen:
                break
        else:
            return out
        self._cache, self._failed = (time.time(), out), None
        obs.event("meta_read", accounts=len(out))
        if self.on_read:
            self.on_read(out)
        return out

    def _read(self) -> list[dict]:
        """The union over connections. One connection Meta refuses is left out (a revoked
        one is marked so, by _fail; Meta not answering for it is passing trouble, no state
        change); a throttle, or every connection failing, fails the list."""
        conns = self._readable()
        if not conns:
            raise MetaError(NOT_CONNECTED, 409)
        out: list[dict] = []
        errors: list[MetaError] = []
        for conn in conns:
            try:
                out.extend(self._read_one(conn["business_id"], conn["business_name"]))
            except MetaError as e:
                if e.status == 503:
                    raise  # Meta asked the app to pause: no point trying the others
                errors.append(e)
        if len(errors) == len(conns):
            raise errors[0]
        return out

    def _read_one(self, business_id: str, business_name: str) -> list[dict]:
        """One connection's list from Meta: /me/adaccounts (paged: a portfolio with more
        than a hundred accounts lists them all), then every account's insights and balance
        in batch requests of up to 50 reads (two per account)."""
        rows = self._pages(
            "/me/adaccounts",
            {
                # not business{name}: that field needs business_management, which this
                # read-only login doesn't ask for (Meta answers #100 for the whole list)
                "fields": ACCOUNT_FIELDS,
                "limit": "100",
            },
            "adaccounts",
            business_id,
        )
        out = []
        for a in rows:
            aid = _digits(a.get("account_id") or a.get("id"))
            status = _int(a.get("account_status"))
            out.append(
                {
                    "id": aid,
                    "name": str(a.get("name") or ""),
                    "currency": str(a.get("currency") or "BRL"),
                    "status": status,
                    "status_label": ACCOUNT_STATUS.get(status, ""),
                    "timezone_name": str(a.get("timezone_name") or ""),
                    "business_id": business_id,
                    "business_name": business_name,
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
            answers.extend(self._batch(reads[i : i + BATCH], business_id))
        for acc, i in zip(out, range(0, len(answers), 2), strict=True):
            acc.update(self._numbers(answers[i], business_id))
            acc["balance"] = self._balance(answers[i + 1], business_id)
        with self._lock:
            for acc in out:
                self.business_of[acc["id"]] = business_id
        return out

    def _batch(self, reads: list[str], business_id: str) -> list[tuple[int | None, dict]]:
        """One Graph batch request with one connection's token: each read's (code, JSON),
        in order; (None, {}) for a read Meta gave up on (a null entry)."""
        token = self._token(business_id)
        items = [{"method": "GET", "relative_url": r} for r in reads]
        status, doc = self._post(
            "/", {"batch": json.dumps(items), "include_headers": "false"}, token
        )
        if status != 200 or not isinstance(doc, list):
            raise self._fail(status, doc if isinstance(doc, dict) else {}, "batch", business_id)
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

    def _numbers(self, answer: tuple[int | None, dict], business_id: str = "") -> dict:
        """This month's numbers from an insights read. Meta not answering for this one
        account is not the list's problem: `numbers: false` and a reason (the UI shows
        dashes); a revoked token or a throttle is."""
        status, ins = answer
        if status != 200:
            code = self._code(ins)
            if code == 190 or self._throttle(code):
                raise self._fail(status or 0, ins, "insights", business_id)
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

    def _balance(self, answer: tuple[int | None, dict], business_id: str = "") -> dict:
        """What is left on the account. Meta shows the funding details only to a token with
        more than ANALYZE on the account (decision 8, "Saldo"): a refusal is not an error."""
        status, doc = answer
        if status is None:  # Meta gave up on this read: the rest of the account still shows
            obs.event("meta_balance_missing", logging.WARNING)
            return {"available": False, "reason": NO_BALANCE_ANSWER}
        if status != 200:
            code = self._code(doc)
            if code == 190 or self._throttle(code) or status >= 500 or code is None:
                raise self._fail(status, doc, "balance", business_id)
            # 10, 100, 200-299: the token may not read these fields
            obs.event("meta_balance_refused", code=code)
            # refused: only a fresh connection carries a changed system-user task (the UI
            # says "reconecte em Adicionar contas")
            return {"available": False, "refused": True, "reason": NO_BALANCE}
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

    def _pages(self, path: str, params: dict, step: str, business_id: str) -> list[dict]:
        """Every `data` entry of a paged Graph list, following `paging.cursors.after`."""
        out: list[dict] = []
        query = dict(params)
        for _ in range(MAX_PAGES):
            doc = self._graph(path, query, step, business_id)
            out.extend(d for d in doc.get("data") or [] if isinstance(d, dict))
            paging = doc.get("paging") if isinstance(doc.get("paging"), dict) else {}
            after = (paging.get("cursors") or {}).get("after") if paging else None
            if not paging.get("next") or not after or after == query.get("after"):
                break
            query["after"] = after
        return out

    def campaigns(self, account_id: str, business_id: str | None = None) -> list[dict]:
        """Every campaign of one ad account, as {id, name, objective, effective_status,
        status, started, stopped, daily_budget_cents, lifetime_budget_cents}: dates are
        `YYYY-MM-DD` (the start date, or the creation date when Meta has no start); the
        budgets are the campaign's own (CBO; minor units, None when set on the ad sets).
        Read with the account's portfolio's token."""
        aid = _digits(account_id)
        rows = self._pages(
            f"/act_{aid}/campaigns",
            {"fields": CAMPAIGN_FIELDS, "limit": "100"},
            "campaigns",
            self._business_for(aid, business_id),
        )
        out = []
        for c in rows:
            cid = _digits(c.get("id"))
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
                    "daily_budget_cents": _minor(c.get("daily_budget")),
                    "lifetime_budget_cents": _minor(c.get("lifetime_budget")),
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
        business_id: str | None = None,
        objectives: dict[str, str] | None = None,
    ) -> list[dict]:
        """One row per campaign per day in the range: {meta_id, day, spend_cents, impressions,
        reach, link_clicks, actions, results, result_indicator}. `since` is clamped to what
        Meta still keeps; an empty range asks nothing. `meta_ids` narrows the read to those
        campaigns; `objectives` ({meta_id: objective}) feeds the Resultados fallback
        (`results_of`) for rows Meta sends without a `results` entry."""
        aid = _digits(account_id)
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
        business = self._business_for(aid, business_id)
        for r in self._pages(f"/act_{aid}/insights", params, "insights", business):
            mid = _digits(r.get("campaign_id"))
            day = _day(r.get("date_start"))
            if not mid or not day:
                continue
            results, indicator = results_of(r, (objectives or {}).get(mid, ""))
            out.append(
                {
                    "meta_id": mid,
                    "day": day,
                    "spend_cents": cents(r.get("spend")) or 0,
                    "impressions": _int(r.get("impressions")),
                    "reach": _int(r.get("reach")),
                    "link_clicks": _int(r.get("inline_link_clicks")),
                    "actions": actions_map(r.get("actions")),
                    "results": results,
                    "result_indicator": indicator,
                }
            )
        return out

    def reach(
        self,
        pairs: list[tuple[str, str]],
        since: date,
        until: date,
        today: date | None = None,
        stale: bool = True,
    ) -> dict[str, int]:
        """The period's reach per campaign ({meta_id: people}) for (account_id, meta_id)
        pairs: one batched read per account, with its portfolio's token, answered from
        memory for an hour per (account, period). After the hour the last numbers answer
        at once (up to a day old) while Meta is read again on a thread of its own, so the
        page never waits for a read it already had once; `stale=False` (the hourly sync, a
        refresh) waits for Meta. Reach doesn't add over days, so this is the only honest
        period number. A campaign Meta says nothing about is left out (the caller shows
        a dash)."""
        since = clamp_since(since, today)
        if since > until or not pairs:
            return {}
        by_account: dict[str, list[str]] = {}
        for account_id, meta_id in pairs:
            by_account.setdefault(_digits(account_id), []).append(str(meta_id))
        now = time.time()
        out: dict[str, int] = {}
        todo: list[str] = []
        behind: list[str] = []  # answered from an old read: Meta is asked again behind
        kept: dict[str, int] = {}  # ...those old answers
        with self._lock:
            for aid, ids in by_account.items():
                hit = self._reach.get((aid, since, until))
                if not hit or not all(m in hit[1] for m in ids):
                    todo.append(aid)
                    continue
                age = now - hit[0]
                if age < REACH_SECONDS:
                    out.update({m: hit[1][m] for m in ids if hit[1][m] is not None})
                elif stale and age < REACH_STALE_SECONDS:
                    kept.update({m: hit[1][m] for m in ids if hit[1][m] is not None})
                    behind.append(aid)
                else:
                    todo.append(aid)
        if not todo:
            if behind:
                out.update(kept)
                self._refresh_reach_soon(
                    [(a, m) for a, m in pairs if _digits(a) in behind], since, until, today
                )
            return out
        todo += behind  # Meta is asked anyway: the old answers are read fresh in one go
        by_business: dict[str, list[str]] = {}
        for aid in todo:
            try:
                business_id = self._business_for(aid)
            except MetaError:
                if not self._readable():
                    raise
                # several portfolios and no read has placed this account yet: its campaigns
                # show a dash, the others still get their reach
                obs.event("meta_reach_unplaced", logging.WARNING)
                continue
            by_business.setdefault(business_id, []).append(aid)
        for business_id, aids in by_business.items():
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
                for aid in aids
            ]
            answers: list = []
            for i in range(0, len(reads), BATCH):
                answers.extend(self._batch(reads[i : i + BATCH], business_id))
            for aid, (status, doc) in zip(aids, answers, strict=True):
                if status != 200:
                    code = self._code(doc)
                    if code == 190 or self._throttle(code):
                        raise self._fail(status or 0, doc, "reach", business_id)
                    obs.event("meta_reach_missing", logging.WARNING, status=status, code=code)
                    continue
                got: dict[str, int | None] = dict.fromkeys(by_account[aid], None)
                for r in doc.get("data") or []:
                    mid = _digits(r.get("campaign_id"))
                    if mid in got:
                        got[mid] = _int(r.get("reach"))
                with self._lock:
                    self._reach = {
                        k: v for k, v in self._reach.items() if now - v[0] < REACH_STALE_SECONDS
                    }
                    self._reach[(aid, since, until)] = (now, got)
                out.update({m: v for m, v in got.items() if v is not None})
        return out

    def _refresh_reach_soon(
        self, pairs: list[tuple[str, str]], since: date, until: date, today: date | None
    ) -> None:
        """Read the period's reach again on a thread of its own, unless one is already
        under way or the last one failed a moment ago (the old numbers stand meanwhile)."""
        if time.time() - self._reach_failed < FAIL_SECONDS:
            return
        if not self._reach_reading.acquire(blocking=False):
            return

        def work():
            try:
                self.reach(pairs, since, until, today=today, stale=False)
            except MetaError:
                self._reach_failed = time.time()  # the next page after a minute tries again
            except Exception:
                obs.event("meta_reach_failed", logging.ERROR)
                logging.getLogger("pauta").exception("reach read failed behind a page")
            finally:
                self._reach_reading.release()

        try:
            threading.Thread(target=work, name="meta-reach", daemon=True).start()
        except RuntimeError:  # no thread to be had: the old numbers stand, nothing waits
            self._reach_reading.release()
            obs.event("meta_read_thread_failed", logging.ERROR)
