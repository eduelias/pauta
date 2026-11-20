"""The Meta sync (decision 8, phase 2): which campaigns are live, and their daily numbers.

`run()` walks every connected portfolio and, under each, every ad account linked to a
client: Meta's campaign list keeps the `campaign` rows (new ACTIVE ones appear, ones Meta
stopped delivering end), then the last `days` days of per-campaign insights are written to
`insight`; a campaign seen for the first time also gets its history back to its start (Meta
keeps 37 months), asked for again on the next passes for as long as that read fails. Finally
done "Criar/Reativar campanha" requests whose Ads Manager link names a campaign are tied to
it.

One account's trouble doesn't stop the others; a linked account no connection has placed
under its portfolio is reported rather than skipped in silence, after one account list per
connection tried to place it (`UNCLAIMED` when that read failed, `ORPHAN` when it ran and
the account is still nobody's: it vanished from Meta, or its portfolio was disconnected).
That read runs once per pass (it also keeps the list the pages answer from at most an
hour old). A permanent orphan is reported once with a WARNING and `sync_error`
(`meta.orphans` remembers it), then at INFO in the pass's `errors` only, so Campanhas
doesn't toast the same problem on every Atualizar agora. A revoked token stops only its
own connection's accounts (the other
portfolios still sync); a throttle stops the pass (nothing retries in a loop: the next
scheduled pass tries again). Each connection gets its
`last_sync` and the first error met under it; `meta.unsynced` says which linked accounts
the pass has no new numbers for and why (Visão geral marks their clients, no others).
`Scheduler` runs it in a daemon
thread from `pauta serve`: a first pass a minute after start, then hourly over today and
yesterday, and nightly after 03:10 over the last 28 days (conversions keep arriving for up
to 28 days after a click). "Today" is each ad account's own day (`timezone_name` from
Meta, `meta.local_today`), not the server's: du7 runs on CET, and in the evening in Brazil
a server-local today is already tomorrow. `pauta meta sync` runs one pass from the shell.

One pass at a time: `run` takes a module lock without waiting and a second caller (the
scheduler's tick while "Atualizar agora" runs, or the other way round) gets `BUSY` (409)
instead of doubling every Graph read. `start` is the manual route's way in: it takes the
lock and runs the pass on a daemon thread, so the request answers at once and the UI polls
`last_sync` for the end.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timedelta
from datetime import time as dtime

from . import obs
from .db import CAMPAIGN_STATES, Store
from .meta import DEFAULT_PERIOD_DAYS, LEGACY, NOT_CONNECTED, Meta, MetaError, local_today

HOURLY_DAYS = 2
NIGHTLY_DAYS = 28
HOURLY_MINUTES = 60
NIGHTLY_AFTER = dtime(3, 10)
SYNC_FAILED = "a sincronização falhou; veja o log"
FIRST_RUN_SECONDS = 60
TICK_SECONDS = 60
BUSY = "a Meta já está sincronizando; espere essa passagem terminar"
UNCLAIMED = "conta sem portfólio conhecido; abra Configurações → Meta para a Pauta ler as contas"
ORPHAN = (
    "conta {id} sem portfólio: desvincule a conta em Configurações → Meta ou reconecte o portfólio"
)

_lock = threading.Lock()  # one pass at a time, whoever asks


def running() -> bool:
    """A pass is under way (the lock is held)."""
    return _lock.locked()


STAMP = "%Y-%m-%dT%H:%M:%SZ"


def _stamp() -> str:
    return time.strftime(STAMP, time.gmtime())


def _pass_stamp(previous: str | None) -> str:
    """A pass's stamp: now, to the second, or one second on when that is exactly the stamp
    of the pass before. `last_sync` is how a pass is told from the one before (after
    Atualizar agora the page polls until it moves; no move and nothing running reads as "the
    pass never ended"), and two passes can start within one second: against the fake Meta
    on a fast machine, hardly against the real one, where a pass takes seconds and holds
    the lock meanwhile. Only an equal stamp is moved, so a clock that was set back is
    never pushed ahead of itself."""
    now = _stamp()
    if now != previous:
        return now
    return (datetime.strptime(now, STAMP) + timedelta(seconds=1)).strftime(STAMP)


def run(store: Store, meta: Meta, *, days: int, today: date | None = None) -> dict:
    """One pass over every connection and, under each, every ad account linked to a client.
    Returns {connections, accounts, campaigns_new, insight_rows, errors, linked}; per-account
    errors are collected, not raised. A revoked token (409) ends that connection's part and
    the next connection goes on; a throttle (503) ends the pass. Each connection's
    `last_sync` is written; `meta.last_sync`/`sync_error` sum the pass up for /metrics.
    The window is the last `days` days up to `today`, which is each account's own day
    (its time zone) unless given. Raises MetaError when nothing is connected at all
    (nothing to sync), or `BUSY` (409) when another pass is still running."""
    if not _lock.acquire(blocking=False):
        raise MetaError(BUSY, 409, "busy")
    try:
        return _run(store, meta, days=days, today=today)
    finally:
        _lock.release()


def start(store: Store, meta: Meta, *, days: int) -> threading.Thread:
    """`run` on a daemon thread, for "Atualizar agora": the lock is taken here, so by the
    time this returns a second caller already gets `BUSY`; the thread releases it when the
    pass ends. Raises `BUSY` (409) when a pass is under way. Whatever the pass meets is
    logged and shown as `meta.sync_error`, as the scheduler does: no thread dies loudly.
    A thread that can't start (the OS refusing) gives the lock back before raising: held
    forever, every later pass would get `BUSY` until a restart."""
    if not _lock.acquire(blocking=False):
        raise MetaError(BUSY, 409, "busy")

    def work():
        try:
            _run(store, meta, days=days)
        except Exception as e:  # noqa: BLE001 - the thread must outlive any surprise
            meta.sync_error = str(e) if isinstance(e, MetaError) else SYNC_FAILED
            obs.event("meta_sync_failed", logging.ERROR, error=type(e).__name__)
        finally:
            _lock.release()

    thread = threading.Thread(target=work, name="meta-sync-now", daemon=True)
    try:
        thread.start()
    except BaseException:  # can't start new thread: the lock must not stay held forever
        _lock.release()
        raise
    return thread


def _run(store: Store, meta: Meta, *, days: int, today: date | None = None) -> dict:
    conns = [c for c in meta.connections() if c["business_id"] != LEGACY]
    if not conns:
        raise MetaError(NOT_CONNECTED, 409)
    days = max(1, int(days))
    out: dict = {
        "connections": len(conns),
        "accounts": 0,
        "campaigns_new": 0,
        "insight_rows": 0,
        "errors": [],
    }
    # the previous pass from the database: a new process (the CLI, a restart) has no memory
    fetched = _pass_stamp(store.sync_state()["last_sync"])
    known = meta.orphans  # unplaced after the last pass: reported before
    accounts, placed = _linked(store, meta, conns)
    first_error = ""  # what `sync_error` says: Meta's errors, and an orphan the first time
    throttled = False
    done: set[str] = set()  # the accounts this pass has new numbers for
    why: dict[str, str] = {}  # account id -> what kept the pass from its numbers
    stopped = ""  # what ended a connection's part (a revoked token) or the pass (a throttle)
    for conn in conns:
        bid = conn["business_id"]
        mine = [a for a in accounts if _business(a, meta, conns) == bid]
        conn_error = ""
        for account in mine:
            aid = account["id"]
            out["accounts"] += 1
            day = today or local_today(account.get("timezone_name") or "")
            since = day - timedelta(days=days - 1)
            try:
                _sync_account(store, meta, aid, bid, since, day, fetched, out, done)
            except MetaError as e:
                out["errors"].append(
                    {"account": aid, "business_id": bid, "error": str(e), "status": e.status}
                )
                why[aid] = f"conta {aid}: {e}"
                conn_error = conn_error or str(e)
                first_error = first_error or str(e)
                obs.event("meta_sync_account_failed", logging.WARNING, status=e.status)
                if e.status == 503:  # Meta asked for a pause: stop the whole pass
                    throttled = True
                if e.status in (409, 503):  # revoked: the rest of this connection would too
                    stopped = str(e)
                    break
        store.set_connection_sync(bid, fetched, conn_error)
        if throttled:
            break
    # linked, and still no connection's: never synced, so say so. Once per change loudly
    # (WARNING, and the pass's `sync_error`); a repeat is in `errors` and the log at INFO
    unplaced = [a for a in accounts if not _business(a, meta, conns)]
    for account in unplaced:
        aid = account["id"]
        repeat = aid in known
        msg = ORPHAN.format(id=aid) if repeat or placed else UNCLAIMED
        out["errors"].append({"account": aid, "business_id": "", "error": msg, "status": 0})
        why[aid] = msg
        level = logging.INFO if repeat else logging.WARNING
        obs.event("meta_account_unclaimed", level, account=aid, repeat=repeat)
        if not repeat:
            first_error = first_error or msg
    if placed or not unplaced:  # a failed read decides nothing: the next pass reads again
        meta.orphans = frozenset(a["id"] for a in unplaced)
    # an account the pass never reached has nothing new either, for the reason it stopped
    meta.unsynced = {a["id"]: why.get(a["id"], stopped) for a in accounts if a["id"] not in done}
    out["linked"] = store.link_requests_to_campaigns()
    if not throttled:
        _warm_reach(store, meta, accounts, today)
    error = first_error
    meta.last_sync, meta.sync_error = fetched, error
    store.set_sync_state(fetched, error)
    obs.event(
        "meta_sync",
        logging.WARNING if error else logging.INFO,
        days=days,
        connections=len(conns),
        accounts=out["accounts"],
        campaigns_new=out["campaigns_new"],
        insight_rows=out["insight_rows"],
        errors=len(out["errors"]),
    )
    return out


def _linked(store: Store, meta: Meta, conns: list[dict]) -> tuple[list[dict], bool]:
    """The ad accounts linked to a client, after the pass's read of the account list
    (this month's numbers, balances): read here, once an hour, so a visit to Campanhas or
    a client's page never waits for it (`Meta.accounts` answers from memory and reads
    behind the page). That read also places every account under the portfolio that reads
    it (`meta.business_of` and, on the server, the rows through `on_read`), so a linked
    row written before v10 or linked before any read gets its portfolio here. The second
    value says whether the read happened: a failed one decides nothing about orphans.
    Meta refusing the read is the pass's business, not this step's."""
    try:
        meta.accounts(stale=False)
    except MetaError as e:
        obs.event("meta_sync_accounts_read_failed", logging.WARNING, status=e.status)
        return [a for a in store.meta_accounts() if a["client"]], False
    return [a for a in store.meta_accounts() if a["client"]], True


def quick_periods(day: date) -> list[tuple[date, date]]:
    """The periods Campanhas' picker offers, as the browser computes them for `day`
    (app-campanhas.js periodDates), the default first: Últimos 30 dias, Últimos 7 dias,
    Este mês, Ontem, Hoje, Mês passado. Personalizado can't be known ahead."""
    yesterday = day - timedelta(days=1)
    first = day.replace(day=1)
    last_month_end = first - timedelta(days=1)
    periods = [
        (yesterday - timedelta(days=DEFAULT_PERIOD_DAYS - 1), yesterday),
        (yesterday - timedelta(days=6), yesterday),
        (first, day),
        (yesterday, yesterday),
        (day, day),
        (last_month_end.replace(day=1), last_month_end),
    ]
    return list(dict.fromkeys(periods))  # on the 1st, Ontem and Mês passado can coincide


def _warm_reach(store: Store, meta: Meta, accounts: list[dict], today: date | None) -> None:
    """Every quick period of Campanhas' picker answers its reach per campaign from memory
    after the pass: read here, once an hour, like the account list (until 1.8.5 only the
    default period was, and a browser that remembered "Este mês" or "Últimos 7 dias" read
    Meta on the page, six seconds with nine portfolios). A custom period, or a first visit
    before any pass, still reads on the page (then from memory for an hour, and after that
    the old numbers answer while Meta is read behind). A failed read is the next pass's
    to retry, never the pass's error; a throttle ends the warm-up."""
    if not accounts:
        return
    day = today or local_today(accounts[0].get("timezone_name") or "")
    pairs = [  # every state: the "include skipped" view asks for the skipped ones too
        (k["account_id"], k["meta_id"])
        for c in store.campaign_rows(day.isoformat(), day.isoformat(), CAMPAIGN_STATES)
        for k in c["campaigns"]
        if k["meta_id"] and k["account_id"]
    ]
    if not pairs:
        return
    for since, until in quick_periods(day):
        try:
            meta.reach(pairs, since, until, today=day, stale=False)
        except MetaError as e:
            obs.event("meta_sync_reach_read_failed", logging.WARNING, status=e.status)
            if e.status == 503:
                return


def _business(account: dict, meta: Meta, conns: list[dict]) -> str:
    """Which connection reads an account: the one its row says, else the one the last Meta
    read saw it under, else (rows from before v10, one connection) the only one. A
    portfolio that is no longer connected reads nothing: its accounts are nobody's ("")."""
    known = [b for b in (account.get("business_id"), meta.business_of.get(account["id"])) if b]
    if known:
        current = {c["business_id"] for c in conns}
        return next((b for b in known if b in current), "")
    return conns[0]["business_id"] if len(conns) == 1 else ""


def _sync_account(store, meta, aid, bid, since, today, fetched, out, done) -> None:
    metas = meta.campaigns(aid, business_id=bid)
    res = store.sync_campaigns(aid, metas, today.isoformat())
    objectives = {m["id"]: m.get("objective") or "" for m in metas}
    rows = meta.daily_insights(
        aid, since, today, today=today, business_id=bid, objectives=objectives
    )
    out["insight_rows"] += store.store_insights(rows, fetched)
    done.add(aid)  # the window's numbers are in, whatever happens to the history below
    out["campaigns_new"] += len(res["new"])
    starts = {m["id"]: m.get("started") for m in metas}
    # the new ones, and the ones an earlier pass saved and then failed to read back
    failed = None  # one campaign's history failing doesn't hold back the others
    for mid in res["pending"]:
        started = starts.get(mid)
        if started and date.fromisoformat(started) < since:
            try:
                history = meta.daily_insights(
                    aid,
                    date.fromisoformat(started),
                    since - timedelta(days=1),
                    meta_ids=[mid],
                    today=today,
                    business_id=bid,
                    objectives=objectives,
                )
            except MetaError as e:
                if e.status in (409, 503):  # revoked or a pause: the pass stops here
                    raise
                failed = failed or e
                continue  # still pending: the next pass asks again
            out["insight_rows"] += store.store_insights(history, fetched)
        store.history_done(mid)
    if failed:
        raise failed  # reported as the account's error, though its window is in


def due(now: datetime, last_hourly: datetime | None, last_nightly: datetime | None) -> set[str]:
    """Which passes are due at `now` (the server's local time): 'hourly' an hour after the
    last one (or never run), 'nightly' once a day after 03:10. The trigger is server-local;
    the days each pass covers are the accounts' own (`run` without `today`)."""
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
        before = self.last_hourly, self.last_nightly
        self.last_hourly = now
        if "nightly" in what:
            self.last_nightly = now
        try:
            return run(self.store, self.meta, days=days)
        except Exception as e:  # noqa: BLE001 - the thread must outlive any surprise
            if isinstance(e, MetaError) and e.reason == "busy":
                # Atualizar agora is on it: this pass is due again at the next tick
                self.last_hourly, self.last_nightly = before
                obs.event("meta_sync_busy")
                return None
            self.meta.sync_error = SYNC_FAILED
            obs.event("meta_sync_failed", logging.ERROR, error=type(e).__name__)
            return None
