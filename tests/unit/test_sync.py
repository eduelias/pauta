"""The sync pass (sync.run) against the fake Meta, what is due when, and the scheduler's
tick."""

import logging
import threading
from datetime import UTC, date, datetime, timedelta

import pytest
from test_meta import connect

from fakemeta import BUSINESS, CONVERSATIONS, EMPTY_ACCOUNT, OTHER_BUSINESS, TODAY, TZ, expected
from pauta import meta as meta_mod
from pauta import sync
from pauta.db import cents_per
from pauta.meta import NOT_CONNECTED, REVOKED, THROTTLED, MetaError, local_today
from pauta.sync import BUSY, ORPHAN, UNCLAIMED


@pytest.fixture()
def team(store, meta_on, fake_meta):
    """Meta connected; the clinic owns account 111, the bakery 222."""
    connect(meta_on, fake_meta)
    clinic = store.save_client({"name": "Clínica Bem Estar"})
    bakery = store.save_client({"name": "Padaria Trigo de Ouro"})
    store.sync_meta_accounts(
        [{"id": "111", "name": "Clínica"}, {"id": "222", "name": "Padaria"}, {"id": "333"}]
    )
    store.link_meta_account("111", clinic["id"])
    store.link_meta_account("222", bakery["id"])
    return store, meta_on, fake_meta, clinic, bakery


def days(store, meta_id):
    return [d["day"] for d in store.campaign(campaign_of(store, meta_id))["days"]]


def campaign_of(store, meta_id):
    with store.db() as db:
        return db.execute("SELECT id FROM campaign WHERE meta_id=?", (meta_id,)).fetchone()[0]


def test_run_syncs_linked_accounts_and_fetches_history(team, caplog):
    store, meta, fake, clinic, bakery = team
    caplog.set_level(logging.INFO, logger="pauta")
    out = sync.run(store, meta, days=2, today=TODAY)
    assert out == {
        "connections": 1,
        "accounts": 2,
        "campaigns_new": 3,
        "insight_rows": out["insight_rows"],
        "errors": [],
        "linked": 0,
    }
    # last two days for every live campaign, plus each new campaign's history to its start
    assert days(store, "23850001") == [
        (date(2026, 10, 3) + timedelta(days=i)).isoformat() for i in range(18)
    ]
    assert days(store, "23850002")[0] == "2026-10-12" and days(store, "23850004")[0] == "2026-10-15"
    assert out["insight_rows"] == 18 + 9 + 6
    rows = store.campaign_rows("2026-10-01", "2026-10-20")
    assert [c["name"] for c in rows] == ["Clínica Bem Estar", "Padaria Trigo de Ouro"]
    assert [k["name"] for k in rows[0]["campaigns"]] == [
        "Botox outubro",
        "Limpeza de pele novembro",
    ]
    want = expected("23850001", date(2026, 10, 1), TODAY, date(2026, 10, 3))
    limpeza = rows[0]["campaigns"][1]
    assert limpeza["spend_cents"] == want["spend_cents"]
    assert limpeza["link_clicks"] == want["link_clicks"]
    # Ads Manager's Resultados, per objective: conversations for Limpeza, "—" for Botox (an
    # indicator, no values), link clicks for Panetone (no entry: the objective's fallback)
    assert limpeza["results"] == want["results"] == 2 * want["days"]
    assert limpeza["result_indicator"] == CONVERSATIONS
    assert limpeza["cost_per_result_cents"] == cents_per(want["spend_cents"], want["results"])
    assert limpeza["daily_budget_cents"] == 1500 and limpeza["lifetime_budget_cents"] is None
    botox = rows[0]["campaigns"][0]
    assert botox["results"] is None and botox["result_indicator"] == "lead"
    assert botox["cost_per_result_cents"] is None and botox["lifetime_budget_cents"] == 45000
    panetone = rows[1]["campaigns"][0]
    want = expected("23850004", date(2026, 10, 1), TODAY, date(2026, 10, 15))
    assert panetone["results"] == want["results"] == panetone["link_clicks"]
    assert panetone["result_indicator"] == "link_click"
    # the unlinked 333 was never asked about; the paused one never appeared
    assert "GET /act_333/campaigns" not in fake.calls
    assert meta.last_sync and meta.sync_error == ""
    assert store.sync_state() == {"last_sync": meta.last_sync, "sync_error": ""}
    events = [r.getMessage() for r in caplog.records if '"meta_sync"' in r.getMessage()]
    assert len(events) == 1 and '"campaigns_new":3' in events[0]
    # a second pass: nothing new, only the window is re-read (no history calls)
    fake.calls.clear()
    out = sync.run(store, meta, days=2, today=TODAY)
    assert out["campaigns_new"] == 0 and out["insight_rows"] == 2 + 2 + 2
    insights = [c for c in fake.calls if "/insights" in c]
    assert len(insights) == 2


def test_the_hourly_pass_keeps_the_account_list_warm(team):
    """A visit after the pass answers from memory: the pass reads the list itself."""
    store, meta, fake, *_ = team
    fake.calls.clear()
    sync.run(store, meta, days=2, today=TODAY)
    assert "GET /me/adaccounts" in fake.calls
    assert meta.status()["accounts_at"] is not None
    n = len(fake.calls)
    meta.accounts()
    assert len(fake.calls) == n  # the pass just read it


def test_a_history_read_that_failed_is_tried_again_until_it_works(team):
    """A campaign first seen in a pass gets its numbers back to its start. When Meta fails
    that one read the campaign is already saved, so it is no longer new: the next passes
    must still fetch what is missing (once: a history that was read is not read again)."""
    store, meta, fake, *_ = team
    fake.fail_history.add("23850001")
    out = sync.run(store, meta, days=2, today=TODAY)
    assert [e["account"] for e in out["errors"]] == ["111"] and out["campaigns_new"] == 3
    assert days(store, "23850001") == ["2026-10-19", "2026-10-20"]  # the window only
    # the account's new numbers are in, and the campaign after it got its history
    assert "111" not in meta.unsynced and days(store, "23850002")[0] == "2026-10-12"
    # a day later Meta answers: the history runs from the start to where the window begins
    fake.fail_history.clear()
    tomorrow = TODAY + timedelta(days=1)
    out = sync.run(store, meta, days=2, today=tomorrow)
    assert out["errors"] == [] and out["campaigns_new"] == 0
    assert days(store, "23850001") == [
        (date(2026, 10, 3) + timedelta(days=i)).isoformat() for i in range(19)
    ]
    assert days(store, "23850002")[0] == "2026-10-12"  # the one after it in the account too
    # read once: the next pass asks for the windows only
    fake.calls.clear()
    sync.run(store, meta, days=2, today=tomorrow)
    assert sum("/insights" in c for c in fake.calls) == 2


def test_a_pause_asked_during_a_history_read_ends_the_pass(team, monkeypatch):
    store, meta, *_ = team
    real, asked = meta.daily_insights, []

    def paused(*args, meta_ids=None, **kw):
        if meta_ids:  # a history read, by campaign id
            asked.append(meta_ids)
            raise MetaError(THROTTLED, 503)
        return real(*args, meta_ids=meta_ids, **kw)

    monkeypatch.setattr(meta, "daily_insights", paused)
    out = sync.run(store, meta, days=2, today=TODAY)
    assert len(asked) == 1  # not one more read once Meta asked for a pause
    assert [e["status"] for e in out["errors"]] == [503]


def test_run_links_done_requests(team):
    store, meta, fake, clinic, _ = team
    r = store.create_request(
        {
            "client": clinic["id"],
            "kind": "Criar campanha",
            "what": "Limpeza de pele",
            "campaign_url": "https://adsmanager.facebook.com/adsmanager/manage/campaigns"
            "?act=111&selected_campaign_ids=23850001",
        },
        None,
    )
    store.update_request(r["id"], {"status": "done"}, None)
    out = sync.run(store, meta, days=2, today=TODAY)
    assert out["linked"] == 1
    assert store.campaign(campaign_of(store, "23850001"))["request"] == r["id"]


def test_run_collects_one_accounts_error_and_goes_on(team):
    store, meta, fake, *_ = team
    fake.fail_campaigns.add("111")
    out = sync.run(store, meta, days=2, today=TODAY)
    assert out["accounts"] == 2 and out["campaigns_new"] == 1
    assert out["errors"] == [
        {
            "account": "111",
            "business_id": BUSINESS,
            "error": out["errors"][0]["error"],
            "status": 502,
        }
    ]
    assert meta.sync_error == out["errors"][0]["error"]
    assert store.sync_state()["sync_error"] == meta.sync_error
    # the clinic's campaigns never arrived; the bakery's did
    assert store.campaign_rows("2026-10-01", "2026-10-31")[0]["name"] == "Padaria Trigo de Ouro"


def test_run_stops_on_a_revoked_token_or_a_throttle(team):
    store, meta, fake, *_ = team
    fake.token_invalid = True
    out = sync.run(store, meta, days=2, today=TODAY)
    assert out["accounts"] == 1 and out["errors"][0]["error"] == REVOKED
    assert out["errors"][0]["status"] == 409 and meta.sync_error == REVOKED
    fake.token_invalid = False
    fake.throttle = True
    out = sync.run(store, meta, days=2, today=TODAY)
    assert out["accounts"] == 1 and out["errors"][0]["error"] == THROTTLED
    fake.throttle = False
    fake.close()
    out = sync.run(store, meta, days=2, today=TODAY)
    assert out["accounts"] == 2 and [e["status"] for e in out["errors"]] == [502, 502]


def test_run_needs_a_connection(store, meta_on):
    with pytest.raises(MetaError) as e:
        sync.run(store, meta_on, days=2)
    assert e.value.status == 409 and str(e.value) == NOT_CONNECTED


def test_run_defaults_to_today_and_at_least_one_day(team):
    store, meta, fake, *_ = team
    out = sync.run(store, meta, days=0)
    assert out["accounts"] == 2
    today = local_today("").isoformat()  # the fixture rows carry no zone: the default's day
    assert store.campaign(campaign_of(store, "23850001"))["last_seen"] == today
    # a campaign whose start Meta doesn't know gets no history call
    fake.campaigns["222"].append(
        {"id": "7", "name": "x", "effective_status": "ACTIVE", "created_time": ""}
    )
    fake.calls.clear()
    out = sync.run(store, meta, days=2, today=TODAY)
    assert out["campaigns_new"] == 1
    assert sum("/insights" in c for c in fake.calls) == 2  # the two windows, no history


def test_run_uses_each_accounts_day(team, monkeypatch):
    """01:30 CET on 1 Nov is 21:30 on 31 Oct in São Paulo: the hourly pass reads 30 and 31
    Oct for a São Paulo account, never 1 Nov; an account in another zone gets its own pair."""
    store, meta, fake, *_ = team
    monkeypatch.setattr(meta_mod, "_now", lambda: datetime(2026, 11, 1, 0, 30, tzinfo=UTC))
    store.sync_meta_accounts(
        [{"id": "111", "timezone_name": TZ}, {"id": "222", "timezone_name": "Europe/Amsterdam"}]
    )
    fake.calls.clear()
    out = sync.run(store, meta, days=2)
    assert out["accounts"] == 2 and out["errors"] == []
    assert days(store, "23850001")[-2:] == ["2026-10-30", "2026-10-31"]
    assert days(store, "23850001")[0] == "2026-10-03"  # the history still runs to the start
    assert store.campaign(campaign_of(store, "23850001"))["last_seen"] == "2026-10-31"
    assert days(store, "23850004")[-1] == "2026-11-01"  # the bakery's Dutch day
    assert store.campaign(campaign_of(store, "23850004"))["last_seen"] == "2026-11-01"
    # the Scheduler's tick never passes a day: the accounts' own (a nightly window too)
    s = sync.Scheduler(store, meta, clock=lambda: datetime(2026, 11, 1, 3, 11))
    s.last_nightly = None
    s.tick()
    assert days(store, "23850001")[-1] == "2026-10-31"


def test_due():
    t = datetime(2026, 10, 20, 10, 0)
    assert sync.due(t, None, t) == {"hourly"}
    assert sync.due(t, t - timedelta(minutes=59), t) == set()
    assert sync.due(t, t - timedelta(minutes=60), t) == {"hourly"}
    # nightly: past 03:10 and not yet today
    assert sync.due(t, t, None) == {"nightly"}
    assert sync.due(t, t, t - timedelta(days=1)) == {"nightly"}
    assert sync.due(t, t, t.replace(hour=3, minute=12)) == set()
    early = datetime(2026, 10, 20, 2, 0)
    assert sync.due(early, early, None) == set()
    assert sync.due(datetime(2026, 10, 20, 3, 10), None, None) == {"hourly", "nightly"}


def test_scheduler_ticks(team, monkeypatch, caplog):
    store, meta, fake, *_ = team
    caplog.set_level(logging.INFO, logger="pauta")
    now = {"t": datetime(2026, 10, 20, 12, 0)}
    s = sync.Scheduler(store, meta, clock=lambda: now["t"])
    # started after 03:10: today's nightly counts as done, so the first tick is hourly
    assert s.last_nightly == now["t"] and s.last_hourly is None
    runs = []
    real = sync.run

    def spy(store, meta, *, days, today=None):
        runs.append(days)
        return real(store, meta, days=days, today=TODAY)

    monkeypatch.setattr(sync, "run", spy)
    assert s.tick()["accounts"] == 2 and runs == [2]
    now["t"] += timedelta(minutes=30)
    assert s.tick() is None and runs == [2]
    now["t"] += timedelta(minutes=30)
    s.tick()
    assert runs == [2, 2]
    # the next day after 03:10: the nightly, 28 days, counts as the hourly too
    now["t"] = datetime(2026, 10, 21, 3, 11)
    s.tick()
    assert runs == [2, 2, 28] and s.last_nightly == now["t"] and s.last_hourly == now["t"]
    now["t"] += timedelta(minutes=5)
    assert s.tick() is None
    # not connected: nothing runs, nothing fails
    meta.disconnect()
    now["t"] += timedelta(hours=2)
    assert s.tick() is None and len(runs) == 3
    connect(meta, fake)
    # a surprise never kills the thread; it is logged and shown as the sync error
    monkeypatch.setattr(sync, "run", lambda *a, **k: 1 / 0)
    now["t"] += timedelta(hours=2)
    assert s.tick() is None
    assert meta.sync_error == "a sincronização falhou; veja o log"
    assert any('"meta_sync_failed"' in r.getMessage() for r in caplog.records)
    # started before 03:10: the nightly is still due today
    early = sync.Scheduler(store, meta, clock=lambda: datetime(2026, 10, 22, 2, 0))
    assert early.last_nightly.date() == date(2026, 10, 21)


def test_scheduler_thread_starts_and_stops(team, monkeypatch):
    store, meta, *_ = team
    monkeypatch.setattr(sync, "FIRST_RUN_SECONDS", 0.01)
    monkeypatch.setattr(sync, "TICK_SECONDS", 0.01)
    ticks = []
    s = sync.Scheduler(store, meta)
    monkeypatch.setattr(s, "tick", lambda: ticks.append(1))
    s.start()
    assert s.thread.daemon and s.thread.name == "meta-sync"
    for _ in range(200):
        if len(ticks) >= 2:
            break
        s._stop.wait(0.01)
    s.stop()
    s.thread.join(1)
    assert len(ticks) >= 2 and not s.thread.is_alive()


def test_run_loops_every_connection_and_records_each_ones_sync(team, caplog):
    """Two portfolios: the agency's accounts and the client's own one are both synced; each
    connection gets its own last_sync; a revoked token on one stops only that one."""
    store, meta, fake, clinic, _ = team
    meta.on_change = store.sync_connections
    store.sync_connections(meta.connections())
    fake.business = OTHER_BUSINESS
    connect(meta, fake, account=1)
    fake.business = BUSINESS
    delta = store.save_client({"name": "Delta Imóveis"})
    # a read tags every row with the portfolio whose token listed it (the fixture's rows,
    # written without one, get theirs now)
    store.sync_meta_accounts(meta.accounts())
    store.link_meta_account("444", delta["id"])
    rows = {a["id"]: a["business_id"] for a in store.meta_accounts()}
    assert rows == {"111": BUSINESS, "222": BUSINESS, "333": "", "444": OTHER_BUSINESS}
    out = sync.run(store, meta, days=2, today=TODAY)
    assert out["connections"] == 2 and out["accounts"] == 3 and out["campaigns_new"] == 4
    assert out["errors"] == []
    conns = {c["business_id"]: c for c in store.connections()}
    assert conns[BUSINESS]["last_sync"] == meta.last_sync
    assert conns[OTHER_BUSINESS]["last_sync"] == meta.last_sync
    assert [c["name"] for c in store.campaign_rows("2026-10-01", "2026-10-20")] == [
        "Clínica Bem Estar",
        "Delta Imóveis",
        "Padaria Trigo de Ouro",
    ]
    # the client's portfolio revoked Pauta: its account fails, the agency's still sync
    fake.revoke(OTHER_BUSINESS)
    fake.calls.clear()
    out = sync.run(store, meta, days=2, today=TODAY)
    assert out["accounts"] == 3 and len(out["errors"]) == 1
    assert out["errors"][0] == {
        "account": "444",
        "business_id": OTHER_BUSINESS,
        "error": REVOKED,
        "status": 409,
    }
    assert sum("/act_111/" in c or "/act_222/" in c for c in fake.calls) >= 4
    conns = {c["business_id"]: c for c in store.connections()}
    assert conns[OTHER_BUSINESS]["state"] == "revoked" and conns[BUSINESS]["state"] == "ok"
    assert conns[BUSINESS]["error"] == "" and conns[OTHER_BUSINESS]["error"] == REVOKED
    assert meta.sync_error == REVOKED  # the pass as a whole had a problem, for /metrics
    assert [e["kind"] for e in store.meta_log_rows()] == ["revoked"]


def test_run_falls_back_to_the_only_connection_for_untagged_rows(team):
    """Rows from before v10 carry no business_id: with one connection they are its."""
    store, meta, fake, *_ = team
    assert all(a["business_id"] == "" for a in store.meta_accounts())
    out = sync.run(store, meta, days=2, today=TODAY)
    assert out["accounts"] == 2 and out["errors"] == []
    # with two connections an untagged, unread row is nobody's: the pass lists each
    # connection's accounts first (one call each) and that read places the rows
    fake.business = OTHER_BUSINESS
    connect(meta, fake)
    fake.business = BUSINESS
    fake.calls.clear()
    out = sync.run(store, meta, days=2, today=TODAY)
    assert out["accounts"] == 2 and out["errors"] == []
    assert fake.calls.count("GET /me/adaccounts") == 2
    assert meta.business_of["111"] == BUSINESS and meta.business_of["444"] == OTHER_BUSINESS
    # the list is cached: the next pass doesn't ask again
    fake.calls.clear()
    out = sync.run(store, meta, days=2, today=TODAY)
    assert out["accounts"] == 2 and "GET /me/adaccounts" not in fake.calls


def test_run_reports_a_linked_account_no_connection_claims(team, caplog):
    """Two connections, and a linked account neither portfolio lists (its row carries no
    business_id): before, nobody synced it and nothing said so. Now the pass reads each
    connection's list first (which places 111 and 222), and the one still unplaced is in
    `errors` with what to do, and in the log."""
    store, meta, fake, clinic, _ = team
    caplog.set_level(logging.INFO, logger="pauta")
    meta.on_read = store.sync_meta_accounts
    orphan = store.save_client({"name": "Órfã"})
    store.link_meta_account("333", orphan["id"])
    fake.business = OTHER_BUSINESS
    connect(meta, fake)
    fake.business = BUSINESS
    assert all(a["business_id"] == "" for a in store.meta_accounts())
    out = sync.run(store, meta, days=2, today=TODAY)
    assert out["connections"] == 2 and out["accounts"] == 2
    msg = ORPHAN.format(id="333")
    assert out["errors"] == [{"account": "333", "business_id": "", "error": msg, "status": 0}]
    assert msg == (
        "conta 333 sem portfólio: desvincule a conta em Configurações → Meta ou reconecte o "
        "portfólio"
    )
    assert meta.sync_error == msg and store.sync_state()["sync_error"] == msg
    assert "GET /act_333/campaigns" not in fake.calls
    assert fake.calls.count("GET /me/adaccounts") == 2  # one list per connection
    # the read placed the rows it could; each connection still got its last_sync
    rows = {a["id"]: a["business_id"] for a in store.meta_accounts()}
    assert rows == {"111": BUSINESS, "222": BUSINESS, "333": "", "444": OTHER_BUSINESS}
    assert all(c["last_sync"] == meta.last_sync for c in store.connections())
    events = [r for r in caplog.records if '"meta_account_unclaimed"' in r.getMessage()]
    assert len(events) == 1 and events[0].levelno == logging.WARNING
    assert '"account":"333"' in events[0].getMessage()
    assert meta.orphans == {"333"}


def test_a_permanent_orphan_is_read_once_and_reported_quietly_after(team, caplog):
    """The placing read pages every account's insights and balance: with an account that
    stays nobody's (gone from Meta, or its portfolio disconnected) it must not run on
    every hourly pass, nor must Campanhas toast "Sincronização com problema" on every
    Atualizar agora while the advice can't help. The read runs when the set of unplaced
    accounts changes; a known orphan is in `errors` and the log at INFO, not in
    `sync_error`."""
    store, meta, fake, clinic, _ = team
    caplog.set_level(logging.INFO, logger="pauta")
    meta.on_read = store.sync_meta_accounts
    store.link_meta_account("333", store.save_client({"name": "Órfã"})["id"])
    fake.business = OTHER_BUSINESS
    connect(meta, fake)
    fake.business = BUSINESS
    msg = ORPHAN.format(id="333")
    out = sync.run(store, meta, days=2, today=TODAY)
    assert [e["error"] for e in out["errors"]] == [msg] and meta.sync_error == msg
    assert fake.calls.count("GET /me/adaccounts") == 2
    # the same orphan again: no read, the same error in the summary at INFO, no sync_error
    fake.calls.clear()
    caplog.clear()
    meta._cache = None  # ten minutes passed: the pass reads the list again, once
    out = sync.run(store, meta, days=2, today=TODAY)
    assert out["accounts"] == 2
    assert out["errors"] == [{"account": "333", "business_id": "", "error": msg, "status": 0}]
    assert fake.calls.count("GET /me/adaccounts") == 2  # one per connection
    assert meta.sync_error == "" and store.sync_state()["sync_error"] == ""
    events = [r for r in caplog.records if '"meta_account_unclaimed"' in r.getMessage()]
    assert len(events) == 1 and events[0].levelno == logging.INFO
    assert '"repeat":true' in events[0].getMessage()
    assert not any(r.levelno == logging.WARNING for r in caplog.records)
    # a real Meta error still sets sync_error; the orphan stays out of it
    fake.fail_campaigns.add("111")
    out = sync.run(store, meta, days=2, today=TODAY)
    assert [e["status"] for e in out["errors"]] == [502, 0]
    assert meta.sync_error == out["errors"][0]["error"] != msg
    fake.fail_campaigns.clear()
    # a new untagged linked row: the set changed, the read runs again and places it; the
    # old orphan is still a repeat
    fake.accounts.append(EMPTY_ACCOUNT)
    store.sync_meta_accounts([{"id": "555", "name": "Estúdio"}])
    store.link_meta_account("555", store.save_client({"name": "Estúdio Pilates Leve"})["id"])
    fake.calls.clear()
    caplog.clear()
    meta._cache = None
    out = sync.run(store, meta, days=2, today=TODAY)
    assert fake.calls.count("GET /me/adaccounts") == 2
    assert out["accounts"] == 3 and [e["error"] for e in out["errors"]] == [msg]
    assert meta.sync_error == "" and meta.orphans == {"333"}
    assert {a["id"]: a["business_id"] for a in store.meta_accounts()}["555"] == BUSINESS
    # unlinking the orphan empties the set; linking it again is a change: loud once more
    store.link_meta_account("333", None)
    out = sync.run(store, meta, days=2, today=TODAY)
    assert out["errors"] == [] and meta.orphans == frozenset()
    store.link_meta_account("333", clinic["id"])
    caplog.clear()
    out = sync.run(store, meta, days=2, today=TODAY)
    assert [e["error"] for e in out["errors"]] == [msg] and meta.sync_error == msg
    events = [r for r in caplog.records if '"meta_account_unclaimed"' in r.getMessage()]
    assert [e.levelno for e in events] == [logging.WARNING]
    # Meta refusing the placing read decides nothing: a row the read never placed is
    # reported the old way (open Configurações → Meta, which reads), the known orphan
    # stays quiet, and the next pass reads again
    store.sync_meta_accounts([{"id": "666", "name": "Nova"}])
    store.link_meta_account("666", store.save_client({"name": "Nova"})["id"])
    fake.throttle = True
    meta._cache = None
    caplog.clear()
    out = sync.run(store, meta, days=2, today=TODAY)
    assert any('"meta_sync_accounts_read_failed"' in r.getMessage() for r in caplog.records)
    assert out["errors"][0]["status"] == 503 and meta.sync_error == THROTTLED
    assert {e["error"] for e in out["errors"][1:]} == {msg, UNCLAIMED}
    assert meta.orphans == {"333"}


def test_the_pass_remembers_which_accounts_got_no_new_numbers(team):
    """What Visão geral's "sem dados novos da Meta" goes by: the linked accounts the last
    pass has nothing new for, each with why and the failing account named, and no other
    (one account in trouble used to mark every client of its portfolio)."""
    store, meta, fake, *_ = team
    assert meta.unsynced == {}
    fake.fail_campaigns.add("111")
    out = sync.run(store, meta, days=2, today=TODAY)
    assert meta.unsynced == {"111": f"conta 111: {out['errors'][0]['error']}"}
    fake.fail_campaigns.clear()
    sync.run(store, meta, days=2, today=TODAY)
    assert meta.unsynced == {}
    # a throttle ends the pass: the accounts it never reached have nothing new either
    fake.throttle = True
    sync.run(store, meta, days=2, today=TODAY)
    assert meta.unsynced == {"111": f"conta 111: {THROTTLED}", "222": THROTTLED}


def test_an_account_whose_portfolio_was_disconnected_is_reported_not_skipped(team):
    """Desconectar forgets a portfolio's token; its linked accounts keep that portfolio's
    id on their rows. It matches no connection any more, so the pass used to skip them
    without a word, their campaigns "active" with frozen numbers. They are nobody's now:
    reported like any account no portfolio lists."""
    store, meta, fake, *_ = team
    meta.on_read = store.sync_meta_accounts
    fake.business = OTHER_BUSINESS
    connect(meta, fake)
    fake.business = BUSINESS
    sync.run(store, meta, days=2, today=TODAY)  # the read tags every row with its portfolio
    store.link_meta_account("444", store.save_client({"name": "Cliente A"})["id"])
    out = sync.run(store, meta, days=2, today=TODAY)
    assert out["accounts"] == 3 and out["errors"] == [] and meta.unsynced == {}
    meta.disconnect(OTHER_BUSINESS)
    out = sync.run(store, meta, days=2, today=TODAY)
    msg = ORPHAN.format(id="444")
    assert out["accounts"] == 2
    assert out["errors"] == [{"account": "444", "business_id": "", "error": msg, "status": 0}]
    assert meta.unsynced == {"444": msg} and meta.sync_error == msg


def test_one_pass_at_a_time(team):
    """Atualizar agora and the scheduler's tick at the same moment: one pass runs, the other
    is told "já está sincronizando" at once, and Meta is read once, not twice."""
    store, meta, fake, *_ = team
    sync.run(store, meta, days=2, today=TODAY)  # the campaigns are known: no history reads
    fake.hold()  # the first pass stops inside its first Graph read, holding the lock
    fake.calls.clear()
    results = []
    first = threading.Thread(
        target=lambda: results.append(sync.run(store, meta, days=2, today=TODAY))
    )
    first.start()
    assert fake.held.wait(30), "the first pass never reached Meta"
    assert sync.running()
    with pytest.raises(MetaError) as e:
        sync.run(store, meta, days=2, today=TODAY)
    assert str(e.value) == BUSY and e.value.status == 409 and e.value.reason == "busy"
    assert "já está sincronizando" in BUSY
    fake.release()
    first.join(timeout=30)
    assert not sync.running() and len(results) == 1
    assert results[0]["accounts"] == 2 and results[0]["errors"] == []
    assert results[0]["campaigns_new"] == 0
    one_pass = list(fake.calls)
    # the same pass alone makes the same calls: nothing was doubled
    fake.calls.clear()
    sync.run(store, meta, days=2, today=TODAY)
    assert sorted(fake.calls) == sorted(one_pass)


def test_start_runs_on_a_thread_and_refuses_a_second(team, caplog):
    store, meta, fake, *_ = team
    caplog.set_level(logging.INFO, logger="pauta")
    fake.hold()
    thread = sync.start(store, meta, days=2)
    assert thread.daemon and sync.running()  # held before start() returned
    with pytest.raises(MetaError) as e:
        sync.start(store, meta, days=2)
    assert str(e.value) == BUSY and e.value.status == 409
    with pytest.raises(MetaError) as e:
        sync.run(store, meta, days=2)
    assert e.value.reason == "busy"
    assert thread.is_alive() and meta.last_sync is None  # still on it
    fake.release()
    thread.join(timeout=30)
    assert not sync.running() and meta.last_sync and meta.sync_error == ""
    assert store.sync_state()["last_sync"] == meta.last_sync
    # a pass that blows up on the thread is logged and shown, and the lock comes back
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sync, "_run", lambda *a, **k: 1 / 0)
        sync.start(store, meta, days=2).join(timeout=10)
    assert not sync.running() and meta.sync_error == sync.SYNC_FAILED
    assert any('"meta_sync_failed"' in r.getMessage() for r in caplog.records)
    # a Meta refusal on the thread is shown with its own words
    meta.disconnect()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(meta_mod.Meta, "connections", lambda self: [])
        sync.start(store, meta, days=2).join(timeout=10)
    assert meta.sync_error == NOT_CONNECTED


def test_start_gives_the_lock_back_when_the_thread_cannot_start(team):
    """`start` takes the lock, then starts the thread: the OS refusing ("can't start new
    thread") must not leave the lock held, or every pass gets BUSY until a restart."""
    store, meta, fake, *_ = team

    def refuse(self):
        raise RuntimeError("can't start new thread")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(threading.Thread, "start", refuse)
        with pytest.raises(RuntimeError, match="can't start new thread"):
            sync.start(store, meta, days=2)
    assert not sync.running()
    # the next pass, either way in, works as if nothing had happened
    out = sync.run(store, meta, days=2, today=TODAY)
    assert out["accounts"] == 2 and out["errors"] == []
    sync.start(store, meta, days=2).join(timeout=30)
    assert not sync.running() and meta.sync_error == ""


def test_scheduler_tick_waits_when_a_manual_pass_runs(team, caplog):
    """The tick meeting Atualizar agora's pass doesn't count as the hourly: it is due again
    at the next tick, and nothing is logged as a failure."""
    store, meta, fake, *_ = team
    caplog.set_level(logging.INFO, logger="pauta")
    now = datetime(2026, 10, 21, 3, 11)
    s = sync.Scheduler(store, meta, clock=lambda: now)
    s.last_nightly = None
    fake.hold()
    thread = sync.start(store, meta, days=2)
    assert s.tick() is None
    assert s.last_hourly is None and s.last_nightly is None and meta.sync_error == ""
    assert any('"meta_sync_busy"' in r.getMessage() for r in caplog.records)
    assert not any('"meta_sync_failed"' in r.getMessage() for r in caplog.records)
    fake.release()
    thread.join(timeout=30)
    assert s.tick()["accounts"] == 2  # the next tick runs it (the nightly, here)
    assert s.last_hourly == now and s.last_nightly == now


def test_the_hourly_pass_keeps_every_quick_period_reach_warm(team):
    """Every period of Campanhas' picker (the default 30 days, yesterday back, and the
    other quick choices) answers its reach from memory after the pass: the pass reads
    them itself; a custom period still reads on the page."""
    store, meta, fake, *_ = team
    sync.run(store, meta, days=2, today=TODAY)
    periods = sync.quick_periods(TODAY)
    until = TODAY - timedelta(days=1)
    since = until - timedelta(days=meta_mod.DEFAULT_PERIOD_DAYS - 1)
    assert periods[0] == (since, until) and len(periods) == 6
    assert {k[1:] for k in meta._reach} >= set(periods)
    n = fake.calls.count("POST /")
    pairs = [
        (k["account_id"], k["meta_id"])
        for c in store.campaign_rows(since.isoformat(), until.isoformat())
        for k in c["campaigns"]
    ]
    assert pairs
    for a, b in periods:
        meta.reach(pairs, a, b, today=TODAY)
    assert fake.calls.count("POST /") == n  # the pass just read them
    meta.reach(pairs, since - timedelta(days=1), until, today=TODAY)
    assert fake.calls.count("POST /") == n + 1


def test_quick_periods_are_the_pickers():
    """What app-campanhas.js periodDates computes, for a day mid-month and on the 1st."""
    d = date(2026, 11, 10)
    assert sync.quick_periods(d) == [
        (date(2026, 10, 11), date(2026, 11, 9)),  # Últimos 30 dias
        (date(2026, 11, 3), date(2026, 11, 9)),  # Últimos 7 dias
        (date(2026, 11, 1), date(2026, 11, 10)),  # Este mês
        (date(2026, 11, 9), date(2026, 11, 9)),  # Ontem
        (date(2026, 11, 10), date(2026, 11, 10)),  # Hoje
        (date(2026, 10, 1), date(2026, 10, 31)),  # Mês passado
    ]
    # on the 1st, Últimos 30 dias is Mês passado, Hoje is Este mês, Ontem is one day: 4 reads
    first = sync.quick_periods(date(2026, 12, 1))
    assert (date(2026, 11, 1), date(2026, 11, 30)) in first and len(first) == 4


def test_two_passes_within_one_second_are_still_told_apart(team, monkeypatch):
    """`last_sync` is how a pass is told from the one before (the page polls after
    Atualizar agora until it moves), and it has whole seconds: a pass that starts within
    the second of the previous one takes the next second instead of the same stamp."""
    store, meta, *_ = team
    second = "2026-10-20T12:00:00Z"
    monkeypatch.setattr(sync, "_stamp", lambda: second)
    sync.run(store, meta, days=1, today=TODAY)
    assert meta.last_sync == second == store.sync_state()["last_sync"]
    sync.run(store, meta, days=1, today=TODAY)
    assert meta.last_sync == "2026-10-20T12:00:01Z" == store.sync_state()["last_sync"]
    # only an equal stamp is moved: once the clock is elsewhere the stamp is the clock's,
    # and a clock set back is not pushed ahead of itself
    for now in ("2026-10-20T12:00:30Z", "2026-10-20T11:59:00Z"):
        monkeypatch.setattr(sync, "_stamp", lambda now=now: now)
        sync.run(store, meta, days=1, today=TODAY)
        assert meta.last_sync == now


def test_a_fresh_meta_object_reads_the_previous_stamp_from_the_store(team, monkeypatch):
    """`pauta meta sync` from the CLI, or the server right after a restart: the previous
    pass is known from the database, not from memory."""
    store, meta, *_ = team
    second = "2026-10-20T12:00:00Z"
    monkeypatch.setattr(sync, "_stamp", lambda: second)
    sync.run(store, meta, days=1, today=TODAY)
    meta.last_sync = None  # as a new process starts
    sync.run(store, meta, days=1, today=TODAY)
    assert meta.last_sync == "2026-10-20T12:00:01Z"
