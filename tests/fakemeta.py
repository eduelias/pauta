"""A fake Meta on localhost: Facebook Login for Business's dialog, the code exchange and the
few Graph reads Pauta makes (the system user, its portfolio, ad accounts, and, through the
batch API, each account's insights and balance), plus the campaign tracking reads: an
account's campaigns (paged) and campaign-level insights by day or for a whole range.

Insights are deterministic from the day of month (spend 10.00 + day cents, impressions
100 × day, reach 80 × day, link clicks = day) for every ACTIVE campaign that had started, so
a test can predict any sum; a range without `time_increment` gives one row per campaign
with reach 500 × days. Ads Manager's Resultados come in the real `results` shape, one case
per fixture campaign (`RESULTS`): 23850001 counts conversations started (2 a day, with
`values`), 23850002 has an indicator and no `values` (Ads Manager shows "—"), the others
have no `results` entry at all, so Pauta falls back to the campaign's objective (Panetone,
OUTCOME_TRAFFIC, counts link clicks; Delta's OUTCOME_LEADS finds no `lead` action).
Every ad account is in America/Sao_Paulo; 23850001 has a daily budget of R$ 15,00 and
23850002 a lifetime one of R$ 450,00 (campaign-level, as Piero's).

A token belongs to the business `fake.business` named when it was minted (Facebook Login
for Business connects one portfolio per login): `/me` reports that business, and the token
reads `fake.accounts_by_business[business]` when the test set it, else `fake.accounts`.
`BUSINESS` is "Agência Exemplo" with accounts 111 and 222; `OTHER_BUSINESS` ("Delta
Imóveis") is ready with account 444: set `fake.business = OTHER_BUSINESS` before a login to
connect it. `fake.revoke(business)` kills that business's tokens only (190).

Tests never talk to the real Meta. Point a Meta at it with
`Meta(path, app_id=APP_ID, config_id=CONFIG_ID, graph=fake.graph, dialog=fake.dialog)` and
write SECRET to `<db>.meta-secret` (see `secret()`).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
import urllib.error
import urllib.request
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

APP_ID = "1000000000000001"
CONFIG_ID = "2000000000000002"
SECRET = "fake-app-secret-0123456789abcdef"
BUSINESS = "300000000000003"
OTHER_BUSINESS = "400000000000004"  # a client's own portfolio (where Piero's system user lives)
BUSINESSES = {BUSINESS: "Agência Exemplo", OTHER_BUSINESS: "Delta Imóveis"}

TZ = "America/Sao_Paulo"  # every fixture account's `timezone_name`, as Piero's
ACCOUNTS = [
    {
        "id": "act_111",
        "account_id": "111",
        "name": "Clínica Bem Estar",
        "currency": "BRL",
        "account_status": 1,
        "timezone_name": TZ,
    },
    {
        "id": "act_222",
        "account_id": "222",
        "name": "Padaria Trigo de Ouro",
        "currency": "BRL",
        "account_status": 2,
        "timezone_name": TZ,
    },
]
OTHER_ACCOUNTS = [
    {
        "id": "act_444",
        "account_id": "444",
        "name": "Delta Imóveis",
        "currency": "BRL",
        "account_status": 1,
        "timezone_name": TZ,
    },
]
INSIGHTS = {
    "444": {
        "spend": "80.00",
        "impressions": "4000",
        "reach": "3000",
        "inline_link_clicks": "40",
        "cost_per_inline_link_click": "2.00",
        "date_start": "2026-10-01",
        "date_stop": "2026-10-31",
    },
    "111": {
        "spend": "1234.56",
        "impressions": "48210",
        "reach": "20118",
        "inline_link_clicks": "903",
        "cost_per_inline_link_click": "1.367176",
        "date_start": "2026-10-01",
        "date_stop": "2026-10-31",
    },
}
# campaigns per ad account: 111 has two live ones started earlier in October 2026 and a
# paused one; 222 has one live one. Tests sync "today" = TODAY.
TODAY = date(2026, 10, 20)
CAMPAIGNS = {
    "111": [
        {
            "id": "23850001",
            "name": "Limpeza de pele novembro",
            "objective": "OUTCOME_ENGAGEMENT",
            "effective_status": "ACTIVE",
            "status": "ACTIVE",
            "start_time": "2026-10-03T00:00:00-0300",
            "created_time": "2026-10-02T18:12:00-0300",
            "daily_budget": "1500",
        },
        {
            "id": "23850002",
            "name": "Botox outubro",
            "objective": "OUTCOME_LEADS",
            "effective_status": "ACTIVE",
            "status": "ACTIVE",
            "start_time": "2026-10-12T00:00:00-0300",
            "created_time": "2026-10-11T09:00:00-0300",
            "lifetime_budget": "45000",
        },
        {
            "id": "23850003",
            "name": "Peeling (pausada)",
            "objective": "OUTCOME_TRAFFIC",
            "effective_status": "PAUSED",
            "status": "PAUSED",
            "start_time": "2026-09-01T00:00:00-0300",
            "stop_time": "2026-09-30T23:59:59-0300",
            "created_time": "2026-08-30T10:00:00-0300",
        },
    ],
    "222": [
        {
            "id": "23850004",
            "name": "Panetone",
            "objective": "OUTCOME_TRAFFIC",
            "effective_status": "ACTIVE",
            "status": "ACTIVE",
            # no start_time: Pauta falls back to the creation date
            "created_time": "2026-10-15T08:00:00-0300",
        },
    ],
    "444": [
        {
            "id": "23850044",
            "name": "Apartamentos Centro",
            "objective": "OUTCOME_LEADS",
            "effective_status": "ACTIVE",
            "status": "ACTIVE",
            "start_time": "2026-10-10T00:00:00-0300",
            "created_time": "2026-10-09T10:00:00-0300",
        },
    ],
}


CONVERSATIONS = "onsite_conversion.messaging_conversation_started_7d"
# Resultados per fixture campaign: (indicator, results per day or None for "no values");
# a campaign not here gets no `results` entry (Pauta falls back to its objective)
RESULTS: dict[str, tuple[str, int | None]] = {
    "23850001": (CONVERSATIONS, 2),
    "23850002": ("lead", None),
}
# what Pauta should count per day after the fallback (Panetone: link clicks = the day)
RESULTS_PER_DAY = {"23850001": lambda d: 2, "23850004": lambda d: d.day}


def day_row(meta_id: str, day: date) -> dict:
    """The fake's insight row for one campaign on one day (what the real Meta would send)."""
    n = day.day
    row = {
        "campaign_id": meta_id,
        "spend": f"10.{n:02d}",
        "impressions": str(100 * n),
        "reach": str(80 * n),
        "inline_link_clicks": str(n),
        "actions": [
            {"action_type": "link_click", "value": str(n)},
            {"action_type": CONVERSATIONS, "value": "2"},
        ],
        "date_start": day.isoformat(),
        "date_stop": day.isoformat(),
    }
    if meta_id in RESULTS:
        indicator, per_day = RESULTS[meta_id]
        row["results"] = [{"indicator": f"actions:{indicator}"}]
        row["cost_per_result"] = [{"indicator": f"actions:{indicator}"}]
        if per_day is not None:
            windows = ["default"]
            row["results"][0]["values"] = [{"value": str(per_day), "attribution_windows": windows}]
            row["cost_per_result"][0]["values"] = [
                {"value": f"{(1000 + n) / per_day / 100:.6f}", "attribution_windows": windows}
            ]
    return row


def expected(meta_id: str, since: date, until: date, start: date) -> dict:
    """What Pauta should hold for a campaign over a range: the sums of `day_row`."""
    days = [since + timedelta(days=i) for i in range((until - since).days + 1)]
    days = [d for d in days if d >= start]
    per_day = RESULTS_PER_DAY.get(meta_id)
    return {
        "spend_cents": sum(1000 + d.day for d in days),
        "impressions": sum(100 * d.day for d in days),
        "link_clicks": sum(d.day for d in days),
        "results": sum(per_day(d) for d in days) if per_day and days else None,
        "days": len(days),
    }


BALANCE = {
    "111": {
        "is_prepay_account": True,
        "funding_source_details": {"id": "FS1", "display_string": "Saldo disponível", "type": 20},
        "spend_cap": "500000",
        "amount_spent": "123456",
    },
    "222": {"is_prepay_account": False, "spend_cap": "0", "amount_spent": "0"},
    "444": {"is_prepay_account": True, "spend_cap": "100000", "amount_spent": "8000"},
}


def secret(db_path) -> Path:
    """Put the fake app secret where Pauta looks for it."""
    f = Path(f"{db_path}.meta-secret")
    f.write_text(SECRET + "\n")
    f.chmod(0o600)
    return f


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def fetch(url: str, cookie: str | None = None) -> tuple[int, str | None, bytes]:
    """A GET that doesn't follow redirects, like a browser's first hop: (status, Location,
    body). For walking the login round trip one redirect at a time."""
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, headers={"Cookie": cookie} if cookie else {})
    try:
        with opener.open(req) as r:
            return r.status, r.headers.get("Location"), r.read()
    except urllib.error.HTTPError as e:
        with e:
            return e.code, e.headers.get("Location"), e.read()


def oauth_error(code: int, message: str = "fake") -> dict:
    return {"error": {"message": message, "type": "OAuthException", "code": code}}


class FakeMeta:
    def __init__(self):
        self.codes: dict[str, str] = {}  # code -> the redirect_uri it was issued for
        self.token_n = 0
        self.token = ""  # the latest token minted
        self.tokens: dict[str, str | None] = {}  # every token -> the business it was minted for
        self.business: str | None = BUSINESS  # the portfolio the next login connects
        self.accounts = list(ACCOUNTS)  # what a token reads: the accounts picked in Meta...
        # ...unless its business has its own list here (two portfolios, two lists)
        self.accounts_by_business: dict[str | None, list] = {OTHER_BUSINESS: list(OTHER_ACCOUNTS)}
        self.default_accounts = ACCOUNTS
        self.invalid_tokens: set[str] = set()  # revoked one portfolio at a time (code 190)
        self.refuse_balance = False  # the token may not read funding details (code 200)
        self.fail_insights: set[str] = set()  # account ids whose insights answer 400 (#100)
        self.timeouts: set[str] = set()  # account ids whose batch items time out (null entries)
        self.token_invalid = False  # the token was revoked (code 190)
        self.campaigns = {k: [dict(c) for c in v] for k, v in CAMPAIGNS.items()}
        self.fail_campaigns: set[str] = set()  # account ids whose campaign list answers 400
        self.throttle = False  # every read answers code 4 (too many calls)
        self.down = False  # Meta answers 500
        self.deny = False  # the person cancels in the dialog
        self.exchanges = 0
        self.seen: list[str] = []  # Graph paths asked for, with the token (batch items too)
        self.calls: list[str] = []  # every HTTP request: "GET /me/adaccounts", "POST /"
        self._n = 0
        self._lock = threading.Lock()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status, doc=None, location=None):
                body = json.dumps(doc or {}).encode()
                self.send_response(status)
                if location:
                    self.send_header("Location", location)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # noqa: N802
                fake.route(self, "GET", {})

            def do_POST(self):  # noqa: N802
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                form = {k: v[0] for k, v in parse_qs(raw.decode()).items()}
                fake.route(self, "POST", form)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, args=(0.02,), daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.graph = f"{self.base}/v26.0"
        self.dialog = f"{self.base}/v26.0/dialog/oauth"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def revoke(self, business: str) -> None:
        """The portfolio's owner removed Pauta in Business Settings: its tokens die."""
        self.invalid_tokens |= {t for t, b in self.tokens.items() if b == business}

    def tokens_of(self, business: str) -> list[str]:
        return [t for t, b in self.tokens.items() if b == business]

    # ---- the login dialog ------------------------------------------------------------------

    def approve(self, url: str) -> dict:
        """What the dialog does when the person approves: checks the URL Pauta built and
        returns the query Meta sends back ({code, state}, or {error, state})."""
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        assert q["client_id"] == APP_ID and q["config_id"] == CONFIG_ID, q
        assert q["response_type"] == "code" and q["override_default_response_type"] == "true"
        assert q["redirect_uri"].endswith("/api/meta/callback") and q["state"]
        if self.deny:
            return {
                "error": "access_denied",
                "error_reason": "user_denied",
                "state": q["state"],
            }
        with self._lock:
            self._n += 1
            code = f"code-{self._n}"
            self.codes[code] = q["redirect_uri"]
        return {"code": code, "state": q["state"]}

    # ---- routing ---------------------------------------------------------------------------

    def route(self, h, method: str, form: dict):
        url = urlparse(h.path)
        path = url.path
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if path == "/v26.0/dialog/oauth":
            back = self.approve(f"{self.base}{h.path}")
            redirect = parse_qs(url.query)["redirect_uri"][0]
            return h._send(302, location=f"{redirect}?{urlencode(back)}")
        if not path.startswith("/v26.0/"):
            return h._send(404, oauth_error(803))
        path = path[len("/v26.0") :]
        self.calls.append(f"{method} {path}")
        if self.down:
            return h._send(500, oauth_error(2, "Service temporarily unavailable"))
        if path == "/oauth/access_token":
            return self._exchange(h, q)
        # the token: a Bearer header on a GET, a form field on the batch POST
        auth = h.headers.get("Authorization") or ""
        token = form.get("access_token") or auth.removeprefix("Bearer ")
        if token not in self.tokens or token in self.invalid_tokens or self.token_invalid:
            return h._send(400, oauth_error(190, "Error validating access token"))
        proof = hmac.new(SECRET.encode(), token.encode(), hashlib.sha256).hexdigest()
        if (form.get("appsecret_proof") or q.get("appsecret_proof")) != proof:
            return h._send(400, oauth_error(100, "Invalid appsecret_proof"))
        if method == "POST" and path == "/" and "batch" in form:
            return h._send(200, self._batch(form, token))
        self.seen.append(path)
        return h._send(*self._graph(path, q, token))

    def _batch(self, form: dict, token: str) -> list:
        """The Graph batch API: each item GETs its relative_url; the answer is a list, in
        order, of {code, headers, body} (body is a JSON string), or null for one that timed
        out on Meta's side."""
        items = json.loads(form["batch"])
        assert isinstance(items, list) and 0 < len(items) <= 50, items
        assert form.get("include_headers") == "false"
        out = []
        for item in items:
            assert item["method"] == "GET", item
            rel = urlparse("/" + item["relative_url"].lstrip("/"))
            q = {k: v[0] for k, v in parse_qs(rel.query).items()}
            self.seen.append(rel.path)
            m = re.fullmatch(r"/act_(\d+)(/insights)?", rel.path)
            if m and m.group(1) in self.timeouts:
                out.append(None)
                continue
            status, doc = self._graph(rel.path, q, token)
            out.append({"code": status, "headers": [], "body": json.dumps(doc)})
        return out

    def _exchange(self, h, q):
        if q.get("client_id") != APP_ID or q.get("client_secret") != SECRET:
            return h._send(400, oauth_error(1, "Error validating client secret"))
        with self._lock:
            redirect = self.codes.pop(q.get("code", ""), None)
        if redirect is None or redirect != q.get("redirect_uri"):
            return h._send(400, oauth_error(100, "Invalid verification code format"))
        self.exchanges += 1
        self.token_n += 1
        self.token = f"EAAfake{self.token_n}"
        self.tokens[self.token] = self.business
        return h._send(200, {"access_token": self.token, "token_type": "bearer"})

    def _graph(self, path, q, token: str = "") -> tuple[int, dict]:
        """One Graph read with a valid token: (status, JSON), the same for a plain GET and
        for an item of a batch. The token says whose portfolio asks."""
        business = self.tokens.get(token)
        if path == "/me":
            doc = {"id": "500000000000005", "name": "Pauta (usuário do sistema)"}
            if business:
                doc["client_business_id"] = business
            return 200, doc
        if path.strip("/") in BUSINESSES:
            bid = path.strip("/")
            return 200, {"id": bid, "name": BUSINESSES[bid]}
        if path == "/me/adaccounts":
            if "business" in q.get("fields", ""):  # what the real Meta says to ads_read
                need = "Requires business_management permission to access the field."
                return 400, oauth_error(100, need)
            accounts = self.accounts_by_business.get(business, self.accounts)
            return 200, {"data": accounts, "paging": {"cursors": {}}}
        if self.throttle:
            return 400, oauth_error(4, "Application request limit reached")
        m = re.fullmatch(r"/act_(\d+)(/insights|/campaigns)?", path)
        if not m or m.group(1) not in BALANCE:
            return 400, oauth_error(100, "Unsupported get request")
        aid = m.group(1)
        if m.group(2) == "/campaigns":
            if aid in self.fail_campaigns:
                return 400, oauth_error(100, "Unsupported get request")
            assert q.get("fields") and "effective_status" in q["fields"], q
            return self._page(self.campaigns.get(aid, []), q)
        if m.group(2) and q.get("level") == "campaign":
            return self._campaign_insights(aid, q)
        if m.group(2):
            assert q.get("date_preset") == "this_month"
            if aid in self.fail_insights:
                return 400, oauth_error(100, "Unsupported get request")
            row = INSIGHTS.get(aid)
            return 200, {"data": [row] if row else [], "paging": {"cursors": {}}}
        if self.refuse_balance:
            return 400, oauth_error(200, "(#200) Requires business_management or ads_management")
        return 200, {"id": f"act_{aid}", **BALANCE[aid]}

    # ---- campaign tracking reads ---------------------------------------------------------

    @staticmethod
    def _page(items: list, q: dict) -> tuple[int, dict]:
        """Cursor paging the Graph way: `limit` items from `after` (the index, as a cursor),
        `paging.next` only while there is more."""
        limit = int(q.get("limit") or 25)
        start = int(q["after"]) if q.get("after") else 0
        chunk = items[start : start + limit]
        paging: dict = {"cursors": {"before": str(start), "after": str(start + len(chunk))}}
        if start + len(chunk) < len(items):
            paging["next"] = "https://graph.facebook.com/next"
        return 200, {"data": chunk, "paging": paging}

    def _campaign_insights(self, aid: str, q: dict) -> tuple[int, dict]:
        rng = json.loads(q["time_range"])
        since, until = date.fromisoformat(rng["since"]), date.fromisoformat(rng["until"])
        assert since <= until, rng
        wanted = None
        if q.get("filtering"):
            (flt,) = json.loads(q["filtering"])
            assert flt == {**flt, "field": "campaign.id", "operator": "IN"}, flt
            wanted = set(flt["value"])
        live = [
            c
            for c in self.campaigns.get(aid, [])
            if c["effective_status"] == "ACTIVE" and (wanted is None or c["id"] in wanted)
        ]
        rows = []
        for c in live:
            raw = (c.get("start_time") or c.get("created_time") or "")[:10]
            if not raw:  # a campaign Meta can't date has nothing to report
                continue
            start = date.fromisoformat(raw)
            if q.get("time_increment") == "1":
                day = max(since, start)
                while day <= until:
                    rows.append(day_row(c["id"], day))
                    day += timedelta(days=1)
            elif start <= until:
                days = (until - max(since, start)).days + 1
                rows.append(
                    {
                        "campaign_id": c["id"],
                        "reach": str(500 * days),
                        "date_start": since.isoformat(),
                        "date_stop": until.isoformat(),
                    }
                )
        return self._page(rows, q)
