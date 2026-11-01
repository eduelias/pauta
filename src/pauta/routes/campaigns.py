"""Meta (decision 8): campaign tracking and the ad accounts."""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

from .. import (
    obs,
    server,  # for the settings the tests patch there
    sync,
)
from ..db import CAMPAIGN_STATES, TRACKED_STATES, Invalid, NotFound, period_results, valid_date
from ..meta import NOT_CONNECTED, MetaError, local_today
from . import DEFAULT_PERIOD_DAYS, ID, MAX_PERIOD_DAYS, SENT, Reply, _stale


def install(route, store, auth, drive, meta):
    manual_sync = {"at": 0.0}  # when an admin last asked for a sync, with its lock
    manual_lock = threading.Lock()

    # ---- campaign tracking (decision 8): per campaign, tracked ones only, by day --------

    def _today(self) -> date:
        """The team's today: the first linked ad account's day (its time zone), else the
        default zone's. Never the server's own date (du7 runs on CET, Brazil is behind)."""
        tz = next((a["timezone_name"] for a in store.meta_accounts() if a["client"]), "")
        return local_today(tz)

    def _period(self) -> tuple[str, str, str]:
        """`since` and `until` from the query (Ads Manager's default when absent: the
        last 30 days, yesterday back, today excluded) as ISO strings, plus today's, all
        in the team's time zone."""
        q = parse_qs(urlparse(self.path).query)
        today = _today(self)
        yesterday = today - timedelta(days=1)
        since = (
            valid_date(q.get("since", [""])[0])
            or (yesterday - timedelta(days=DEFAULT_PERIOD_DAYS - 1)).isoformat()
        )
        until = valid_date(q.get("until", [""])[0]) or yesterday.isoformat()
        if since > until:
            raise Invalid("o início do período vem depois do fim")
        if (date.fromisoformat(until) - date.fromisoformat(since)).days >= MAX_PERIOD_DAYS:
            raise Invalid(f"período grande demais (máximo {MAX_PERIOD_DAYS} dias)")
        return since, until, today.isoformat()

    def _reach(self, pairs: list[tuple[str, str]], since: str, until: str) -> dict:
        """The period's reach per campaign from Meta; {} when Meta won't say (reach is
        never the screen's problem: the caller shows a dash)."""
        if not pairs or not meta.connected:
            return {}
        try:
            return meta.reach(pairs, date.fromisoformat(since), date.fromisoformat(until))
        except MetaError:
            return {}

    def _live_accounts(self) -> dict[str, dict]:
        """Meta's latest account list by id (the cached read, as the client cards use);
        {} when Meta isn't connected or won't say: a balance is never the list's
        problem (the caller shows null)."""
        if not meta.connected:
            return {}
        try:
            return {a["id"]: a for a in meta.accounts()}
        except MetaError:
            return {}

    @route("GET", "/api/campaigns")
    def campaigns(self, viewer, _body):
        """Every client with a tracked campaign or a linked ad account. Each comes
        with its campaigns and the period's sums, Ads Manager's Resultados (`results`,
        `result_indicator`, `cost_per_result_cents`), the lead cost (`cpl_cents`: spend
        ÷ link clicks) and the campaign's budget; `reach` comes from Meta for the period
        as a whole (null when Meta won't say: never the list's problem). A client whose
        linked accounts hold no tracked campaign (a portfolio just connected, say) is
        listed with `campaigns: []`, so it doesn't look like the connection failed.
        `accounts` is the client's linked ad accounts with the balance from Meta's
        cached list (null when Meta won't say). `include_skipped=1` adds the campaigns
        marked Não acompanhar (so an admin can bring one back); `client=<id>` keeps one
        client's. `last_sync` says how fresh the stored numbers are. `seen` counts the
        clients with campaigns only: Visto hoje needs an active one."""
        since, until, today = _period(self)
        q = parse_qs(urlparse(self.path).query)
        states = CAMPAIGN_STATES if q.get("include_skipped", [""])[0] == "1" else TRACKED_STATES
        clients = store.campaign_rows(since, until, states)
        linked = [r for r in store.meta_accounts() if r["client"]]
        listed = {c["id"] for c in clients}
        for r in linked:  # clients with accounts and no campaign come after, by name
            if r["client"]["id"] not in listed:
                listed.add(r["client"]["id"])
                clients.append({**r["client"], "campaigns": []})
        client = q.get("client", [""])[0]
        if client:
            if not client.isdigit():
                raise Invalid("cliente inválido")
            clients = [c for c in clients if c["id"] == int(client)]
        pairs = [
            (k["account_id"], k["meta_id"])
            for c in clients
            for k in c["campaigns"]
            if k["meta_id"] and k["account_id"]
        ]
        reach = _reach(self, pairs, since, until)
        live = _live_accounts(self)
        portfolios = {c["business_id"]: c["business_name"] for c in meta.connections()}
        seen = store.seen_on(today)
        for c in clients:
            c["seen_today"] = seen.get(c["id"])
            c["accounts"] = [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "currency": r["currency"],
                    "business_name": (live.get(r["id"]) or {}).get("business_name")
                    or portfolios.get(r["business_id"], ""),
                    "balance": live[r["id"]]["balance"] if r["id"] in live else None,
                }
                for r in linked
                if r["client"]["id"] == c["id"]
            ]
            for k in c["campaigns"]:
                clicks = k["link_clicks"]
                k["cpl_cents"] = round(k["spend_cents"] / clicks) if clicks else None
                k["reach"] = reach.get(k["meta_id"])
        checkable = [c for c in clients if c["campaigns"]]
        return {
            "since": since,
            "until": until,
            "today_included": until >= today,
            "last_sync": meta.last_sync,
            # the daily check: how many of the clients with something to check someone
            # has been through today
            "seen": {
                "done": sum(1 for c in checkable if c["seen_today"]),
                "total": len(checkable),
            },
            "clients": clients,
        }

    @route("POST", f"/api/clients/{ID}/reviews")
    def review_client(self, viewer, body, cid):
        """Visto hoje: one `review` per active campaign of the client, dated today (the
        team's day, not the server's), with this month's numbers as the snapshot (so
        the note sits next to the numbers it was about). Returns the client's check
        status."""
        cid = int(cid)
        store.client(cid)
        note = str(body.get("note") or "").strip()[:500]
        today = _today(self)
        since, until = today.replace(day=1).isoformat(), today.isoformat()
        rows = [
            k
            for c in store.campaign_rows(since, until, ("active",))
            if c["id"] == cid
            for k in c["campaigns"]
        ]
        if not rows:
            raise Invalid("este cliente não tem campanha ativa para marcar")
        reach = _reach(
            self, [(k["account_id"], k["meta_id"]) for k in rows if k["meta_id"]], since, until
        )
        snaps = [
            (
                k["id"],
                {
                    "since": since,
                    "until": until,
                    "spend_cents": k["spend_cents"],
                    "link_clicks": k["link_clicks"],
                    "cpl_cents": round(k["spend_cents"] / k["link_clicks"])
                    if k["link_clicks"]
                    else None,
                    "results": k["results"],
                    "result_indicator": k["result_indicator"],
                    "cost_per_result_cents": k["cost_per_result_cents"],
                    "reach": reach.get(k["meta_id"]),
                    "impressions": k["impressions"],
                },
            )
            for k in rows
        ]
        n = store.add_reviews(cid, until, viewer["account"], note, snaps)
        obs.event("campaign_review", account=viewer["account"], client=cid, campaigns=n)
        return {"client": cid, "campaigns": n, "seen_today": store.seen_on(until).get(cid)}

    @route("GET", f"/api/campaigns/{ID}")
    def campaign(self, viewer, _body, cid):
        """One campaign for the period: the row, its daily rows (`days`), the period's
        sums, cost per lead and Ads Manager's Resultados (summed over the days that had
        a count; the latest indicator), and the period's reach from Meta (null when it
        won't say)."""
        since, until, today = _period(self)
        k = store.campaign(int(cid), since, until)
        days = k["days"]
        k["spend_cents"] = sum(d["spend_cents"] for d in days)
        k["impressions"] = sum(d["impressions"] for d in days)
        k["link_clicks"] = sum(d["link_clicks"] for d in days)
        actions: dict[str, int] = {}
        for d in days:
            for name, n in d["actions"].items():
                actions[name] = actions.get(name, 0) + int(n)
        k["actions"] = actions
        counted = [d["results"] for d in days if d["results"] is not None]
        k.update(period_results(sum(counted) if counted else None, k["spend_cents"]))
        k["result_indicator"] = next(
            (d["result_indicator"] for d in reversed(days) if d["result_indicator"]), ""
        )
        clicks = k["link_clicks"]
        k["cpl_cents"] = round(k["spend_cents"] / clicks) if clicks else None
        pairs = [(k["account_id"], k["meta_id"])] if k["meta_id"] and k["account_id"] else []
        k["reach"] = _reach(self, pairs, since, until).get(k["meta_id"])
        return {
            "since": since,
            "until": until,
            "today_included": until >= today,
            "last_sync": meta.last_sync,
            "campaign": k,
        }

    @route("PATCH", f"/api/campaigns/{ID}")
    def campaign_state(self, viewer, body, cid):
        return store.set_campaign_state(int(cid), body.get("state"), viewer["account"])

    @route("POST", "/api/meta/sync", "admin")
    def meta_sync(self, viewer, _body):
        """Atualizar agora: the hourly pass, at most once every 15 minutes."""
        if not meta.connected:
            raise MetaError(NOT_CONNECTED, 409)
        with manual_lock:
            wait = manual_sync["at"] + server.MANUAL_SYNC_SECONDS - time.time()
            if wait > 0:
                raise Reply(429, {"error": server.SYNC_TOO_SOON, "retry_in_s": round(wait)})
            manual_sync["at"] = time.time()
        obs.event("meta_sync_requested", account=viewer["account"])
        return sync.run(store, meta, days=sync.HOURLY_DAYS)

    # ---- Meta (decision 8, phase 2): read-only ad account numbers ---------------------

    @route("GET", "/api/meta", "admin")
    def meta_status(self, viewer, _body):
        """The connections (one per portfolio, with who connected it and its last sync)
        and every account under them. Meta failing is reported in `error`, with the
        accounts Pauta already knew (stale), never as a failed page: the admin still
        sees each connection's state and can act on it."""
        accounts, failed = None, ""
        if meta.connected:
            refresh = parse_qs(urlparse(self.path).query).get("refresh") == ["1"]
            try:
                accounts = meta.accounts(refresh=refresh)
            except MetaError as e:
                accounts, failed = [], str(e)
        out = meta.status()  # after the read: a 190 just now shows on its connection
        out["connections"] = _connections(self)
        out["error"] = failed or out["error"]
        if accounts is not None:
            out["accounts"] = _with_clients(self, accounts)
        return out

    def _connections(self) -> list[dict]:
        """meta.connections() (the files, the truth) with what the rows add: the
        connecting person's name and each connection's last sync."""
        rows = {r["business_id"]: r for r in store.connections()}
        out = []
        for c in meta.connections():
            row = rows.get(c["business_id"]) or {}
            out.append({**c, "by_name": row.get("by_name"), "last_sync": row.get("last_sync")})
        return out

    def _with_clients(self, accounts: list[dict]) -> list[dict]:
        """Each account with its Pauta client ({id, name} or null) and, when unlinked,
        a suggested client by name (never saved: the admin picks). Accounts kept from
        an earlier read but missing now come last, with `stale` and no numbers."""
        rows = {r["id"]: r for r in store.meta_accounts()}
        names = {c["id"]: c["name"] for c in store.clients()}
        portfolios = {c["business_id"]: c["business_name"] for c in meta.connections()}
        out = []
        for a in accounts:
            row = rows.pop(a["id"], None)
            client = row["client"] if row else None
            sid = None if client else store.suggest_client(a["name"])
            suggested = {"id": sid, "name": names[sid]} if sid in names else None
            out.append({**a, "client": client, "suggested": suggested, "stale": False})
        for row in rows.values():
            out.append({**_stale(row, portfolios), "suggested": None, "stale": True})
        return out

    @route("PATCH", "/api/meta/accounts/([0-9]{3,20})", "admin")
    def meta_link(self, viewer, body, aid):
        if "client" not in body:
            raise Invalid("informe o cliente (ou null para desvincular)")
        row = store.link_meta_account(aid, body["client"], viewer["account"])
        store.meta_log(
            "linked" if row["client"] else "unlinked",
            row["business_id"],
            viewer["account"],
            account_id=row["id"],
            account_name=row["name"],
            client_name=(row["client"] or {}).get("name"),
        )
        return row

    @route("POST", "/api/meta/connect", "admin")
    def meta_connect(self, viewer, body):
        """The login URL. `business_id` set: "Adicionar contas" on that connection (a
        re-login on the same portfolio); unset: "Conectar outro portfólio"."""
        business = body.get("business_id") if isinstance(body, dict) else None
        if business is not None and not (isinstance(business, str) and business.isdigit()):
            raise Invalid("portfólio inválido")
        return {"url": meta.start_connect(viewer["account"], business)}

    @route("GET", "/api/meta/callback", "open")
    def meta_callback(self, viewer, _body):
        """Meta's login sends the admin back here. The SameSite=Strict cookie doesn't come
        along on that cross-site redirect, so the one-time state is the authorization.
        Whatever portfolio the login came back for is saved as its own connection."""
        q = parse_qs(urlparse(self.path).query)
        state, code = q.get("state", [""])[0], q.get("code", [""])[0]
        try:
            if q.get("error") or not code:  # cancelled or refused in Meta's dialog
                with contextlib.suppress(MetaError):
                    meta.take_state(state)
                obs.event("meta_connect_cancelled", logging.WARNING)
                raise MetaError("cancelado", 400, "cancelado")
            conn = meta.finish_connect(state, code)
        except MetaError as e:
            self._redirect(f"/#/configuracoes?meta=erro&motivo={e.reason}")
            return SENT
        if conn:  # not a repeated callback
            store.meta_log(
                "connected",
                conn["business_id"],
                conn["by"],
                business_name=conn["business_name"],
            )
        self._redirect("/#/configuracoes?meta=conectado")
        return SENT

    @route("DELETE", "/api/meta/connections/([0-9]{1,30}|legacy)", "admin")
    def meta_disconnect(self, viewer, _body, business_id):
        """Forget one portfolio's token. Its accounts stay as rows (stale) so the
        client mapping survives a reconnect."""
        conn = next((c for c in meta.connections() if c["business_id"] == business_id), None)
        if not conn:
            raise NotFound("conexão não encontrada")
        meta.disconnect(business_id)
        store.meta_log(
            "disconnected",
            business_id,
            viewer["account"],
            business_name=conn["business_name"],
        )
        out = meta.status()
        out["connections"] = _connections(self)
        return out

    @route("GET", "/api/meta/log", "admin")
    def meta_log(self, viewer, _body):
        """The latest 20 lines of the Meta history, newest first, with the actor."""
        return store.meta_log_rows(20)

    @route("PUT", "/api/options/(kind|goal|segment)", "admin")
    def options(self, viewer, body, lst):
        store.set_options(lst, body.get("values"))
        return store.options()
