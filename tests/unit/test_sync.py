"""The sync pass (sync.run) against the fake Meta, what is due when, and the scheduler's
tick."""

import logging
from datetime import date, datetime, timedelta

import pytest
from test_meta import connect

from fakemeta import BUSINESS, OTHER_BUSINESS, TODAY, expected
from pauta import sync
from pauta.meta import NOT_CONNECTED, REVOKED, THROTTLED, MetaError


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
    assert (
        limpeza["spend_cents"] == want["spend_cents"] and limpeza["results"] == want["link_clicks"]
    )
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
    today = date.today().isoformat()
    assert store.campaign(campaign_of(store, "23850001"))["last_seen"] == today
    # a campaign whose start Meta doesn't know gets no history call
    fake.campaigns["222"].append(
        {"id": "7", "name": "x", "effective_status": "ACTIVE", "created_time": ""}
    )
    fake.calls.clear()
    out = sync.run(store, meta, days=2, today=TODAY)
    assert out["campaigns_new"] == 1
    assert sum("/insights" in c for c in fake.calls) == 2  # the two windows, no history


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
    # with two connections an untagged, unread row is nobody's until a read tags it
    fake.business = OTHER_BUSINESS
    connect(meta, fake)
    fake.business = BUSINESS
    out = sync.run(store, meta, days=2, today=TODAY)
    assert out["accounts"] == 0
    meta.accounts()  # the read fills meta.business_of (the server also seeds it from rows)
    out = sync.run(store, meta, days=2, today=TODAY)
    assert out["accounts"] == 2
