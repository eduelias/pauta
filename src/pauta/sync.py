"""The Meta sync (decision 8, phase 2): which campaigns are live, and their daily numbers.

`run()` walks every ad account linked to a client: Meta's campaign list keeps the `campaign`
rows (new ACTIVE ones appear, ones Meta stopped delivering end), then the last `days` days
of per-campaign insights are written to `insight`; a campaign seen for the first time also
gets its history back to its start (Meta keeps 37 months). Finally done "Criar/Reativar
campanha" requests whose Ads Manager link names a campaign are tied to it.

One account's trouble doesn't stop the others; a revoked token or a throttle does (nothing
retries in a loop: the next scheduled pass tries again). `Scheduler` runs it in a daemon
thread from `pauta serve`: a first pass a minute after start, then hourly over today and
yesterday, and nightly after 03:10 over the last 28 days (conversions keep arriving for up
to 28 days after a click). `pauta meta sync` runs one pass from the shell.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timedelta
from datetime import time as dtime

from . import obs
from .db import Store
from .meta import NOT_CONNECTED, Meta, MetaError

HOURLY_DAYS = 2
NIGHTLY_DAYS = 28
HOURLY_MINUTES = 60
NIGHTLY_AFTER = dtime(3, 10)
FIRST_RUN_SECONDS = 60
TICK_SECONDS = 60


def _stamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def run(store: Store, meta: Meta, *, days: int, today: date | None = None) -> dict:
    """One pass over every linked ad account. Returns {accounts, campaigns_new,
    insight_rows, errors}; per-account errors are collected, not raised, except that a
    revoked token or a throttle ends the pass early. Raises MetaError when Meta is not
    connected at all (nothing to sync)."""
    if not meta.connected:
        raise MetaError(NOT_CONNECTED, 409)
    today = today or date.today()
    days = max(1, int(days))
    since = today - timedelta(days=days - 1)
    out: dict = {"accounts": 0, "campaigns_new": 0, "insight_rows": 0, "errors": []}
    fetched = _stamp()
    for account in store.meta_accounts():
        if not account["client"]:
            continue
        aid = account["id"]
        out["accounts"] += 1
        try:
            metas = meta.campaigns(aid)
            res = store.sync_campaigns(aid, metas, today.isoformat())
            rows = meta.daily_insights(aid, since, today, today=today)
            out["insight_rows"] += store.store_insights(rows, fetched)
            starts = {m["id"]: m.get("started") for m in metas}
            for mid in res["new"]:
                out["campaigns_new"] += 1
                started = starts.get(mid)
                if not started or date.fromisoformat(started) >= since:
                    continue
                history = meta.daily_insights(
                    aid,
                    date.fromisoformat(started),
                    since - timedelta(days=1),
                    meta_ids=[mid],
                    today=today,
                )
                out["insight_rows"] += store.store_insights(history, fetched)
        except MetaError as e:
            out["errors"].append({"account": aid, "error": str(e), "status": e.status})
            obs.event("meta_sync_account_failed", logging.WARNING, status=e.status)
            if e.status in (409, 503):  # revoked, or Meta asked for a pause: stop here
                break
    out["linked"] = store.link_requests_to_campaigns()
    error = out["errors"][0]["error"] if out["errors"] else ""
    meta.last_sync, meta.sync_error = fetched, error
    store.set_sync_state(fetched, error)
    obs.event(
        "meta_sync",
        logging.WARNING if error else logging.INFO,
        days=days,
        accounts=out["accounts"],
        campaigns_new=out["campaigns_new"],
        insight_rows=out["insight_rows"],
        errors=len(out["errors"]),
    )
    return out


def due(now: datetime, last_hourly: datetime | None, last_nightly: datetime | None) -> set[str]:
    """Which passes are due at `now` (local time): 'hourly' an hour after the last one (or
    never run), 'nightly' once a day after 03:10."""
    out = set()
    if last_hourly is None or now - last_hourly >= timedelta(minutes=HOURLY_MINUTES):
        out.add("hourly")
    if now.time() >= NIGHTLY_AFTER and (last_nightly is None or last_nightly.date() != now.date()):
        out.add("nightly")
    return out


class Scheduler:
    """The sync on a daemon thread. Nothing it meets can kill it: every pass is wrapped,
    failures are logged (and shown on /metrics as `meta.sync_error`)."""

    def __init__(self, store: Store, meta: Meta, clock=datetime.now):
        self.store, self.meta, self.clock = store, meta, clock
        now = clock()
        self.last_hourly: datetime | None = None  # so the first tick runs the hourly pass
        # the nightly waits for tomorrow's 03:10 when the server starts after today's
        self.last_nightly: datetime | None = (
            now if now.time() >= NIGHTLY_AFTER else now - timedelta(days=1)
        )
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, name="meta-sync", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        delay = FIRST_RUN_SECONDS
        while not self._stop.wait(delay):
            delay = TICK_SECONDS
            self.tick()

    def tick(self) -> dict | None:
        """One check: run what is due. Returns the pass's summary, or None when nothing ran."""
        now = self.clock()
        what = due(now, self.last_hourly, self.last_nightly)
        if not what or not self.meta.connected:
            return None
        days = NIGHTLY_DAYS if "nightly" in what else HOURLY_DAYS
        self.last_hourly = now
        if "nightly" in what:
            self.last_nightly = now
        try:
            return run(self.store, self.meta, days=days)
        except Exception as e:  # noqa: BLE001 - the thread must outlive any surprise
            self.meta.sync_error = "a sincronização falhou; veja o log"
            obs.event("meta_sync_failed", logging.ERROR, error=type(e).__name__)
            return None
