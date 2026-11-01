"""Campaign tracking in the Store (decision 8, phase 2): the v8 → v9 migration, campaigns
following Meta's list, daily numbers, requests linked by their Ads Manager link, the period
sums, Não acompanhar / Acompanhar, and the export tables."""

import sqlite3

import pytest

from pauta.db import SCHEMA_VERSION, Invalid, NotFound, Store, campaign_id_in

ACTIVE = {
    "id": "23850001",
    "name": "Limpeza de pele",
    "objective": "OUTCOME_LEADS",
    "effective_status": "ACTIVE",
    "started": "2026-10-03",
}
PAUSED = {**ACTIVE, "id": "23850003", "name": "Peeling", "effective_status": "PAUSED"}
TODAY = "2026-10-20"


@pytest.fixture()
def linked(store):
    """The clinic with ad account 111 linked; 222 exists but belongs to nobody."""
    c = store.save_client({"name": "Clínica Bem Estar"})
    store.sync_meta_accounts([{"id": "111", "name": "Clínica"}, {"id": "222", "name": "Pad"}])
    store.link_meta_account("111", c["id"])
    return c


def campaigns(store):
    with store.db() as db:
        return {r["meta_id"]: dict(r) for r in db.execute("SELECT * FROM campaign")}


def test_schema_v8_gains_the_tracking_tables(tmp_path):
    Store(tmp_path / "old.db")
    conn = sqlite3.connect(tmp_path / "old.db")
    conn.executescript(  # as the previous release left it: no tracking tables, version 8
        "DROP TABLE insight; DROP TABLE review; DROP TABLE campaign;"
        "UPDATE meta SET value='8' WHERE key='schema';"
    )
    conn.commit()
    conn.close()
    store = Store(tmp_path / "old.db")
    with store.db() as db:
        assert db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0] == "9"
        assert SCHEMA_VERSION == 9
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"campaign", "review", "insight"} <= tables
    assert store.campaign_rows("2026-01-01", "2026-12-31") == []


def test_unlinked_account_is_not_tracked(store, linked):
    assert store.sync_campaigns("222", [ACTIVE], TODAY) == {"new": [], "ended": 0, "reopened": 0}
    assert store.sync_campaigns("999", [ACTIVE], TODAY)["new"] == []
    assert campaigns(store) == {}


def test_new_active_campaigns_appear_paused_ones_do_not(store, linked):
    res = store.sync_campaigns("act_111", [ACTIVE, PAUSED, {"id": ""}], TODAY)
    assert res == {"new": ["23850001"], "ended": 0, "reopened": 0}
    rows = campaigns(store)
    assert list(rows) == ["23850001"]
    row = rows["23850001"]
    assert row == {
        **row,
        "client": linked["id"],
        "account_id": "111",
        "name": "Limpeza de pele",
        "objective": "OUTCOME_LEADS",
        "state": "active",
        "effective_status": "ACTIVE",
        "started": "2026-10-03",
        "ended": None,
        "request": None,
        "last_seen": TODAY,
    }
    # no start date known: today
    store.sync_campaigns("111", [{**ACTIVE, "id": "5", "started": None}], TODAY)
    assert campaigns(store)["5"]["started"] == TODAY


def test_campaigns_follow_metas_status(store, linked):
    store.sync_campaigns("111", [ACTIVE], "2026-10-10")
    # renamed and paused in Meta: the row ends today
    res = store.sync_campaigns(
        "111", [{**ACTIVE, "name": "Limpeza (nova)", "effective_status": "PAUSED"}], TODAY
    )
    assert res == {"new": [], "ended": 1, "reopened": 0}
    row = campaigns(store)["23850001"]
    assert row["state"] == "ended" and row["ended"] == TODAY
    assert row["name"] == "Limpeza (nova)" and row["effective_status"] == "PAUSED"
    # still paused: nothing changes
    assert store.sync_campaigns("111", [PAUSED, {**ACTIVE, "effective_status": "PAUSED"}], TODAY)
    assert campaigns(store)["23850001"]["ended"] == TODAY
    # active again: reopened, the end date cleared
    res = store.sync_campaigns("111", [ACTIVE], "2026-10-25")
    assert res == {"new": [], "ended": 0, "reopened": 1}
    row = campaigns(store)["23850001"]
    assert row["state"] == "active" and row["ended"] is None and row["last_seen"] == "2026-10-25"
    # a campaign that vanished from the list keeps its row untouched
    store.sync_campaigns("111", [], "2026-10-26")
    assert campaigns(store)["23850001"]["last_seen"] == "2026-10-25"


def test_skipped_is_never_touched_by_the_sync(store, linked):
    store.sync_campaigns("111", [ACTIVE], TODAY)
    cid = campaigns(store)["23850001"]["id"]
    store.set_campaign_state(cid, "skipped", by=None)
    store.sync_campaigns("111", [{**ACTIVE, "effective_status": "PAUSED"}], TODAY)
    assert campaigns(store)["23850001"]["state"] == "skipped"
    store.sync_campaigns("111", [ACTIVE], TODAY)
    assert campaigns(store)["23850001"]["state"] == "skipped"
    assert store.campaign_rows("2026-10-01", "2026-10-31") == []
    rows = store.campaign_rows("2026-10-01", "2026-10-31", states=("skipped",))
    assert rows[0]["campaigns"][0]["state"] == "skipped"


def test_set_state_transitions(store, linked):
    store.sync_campaigns("111", [ACTIVE], TODAY)
    cid = campaigns(store)["23850001"]["id"]
    with pytest.raises(Invalid, match="estado inválido"):
        store.set_campaign_state(cid, "ended")
    with pytest.raises(Invalid, match="já está assim"):
        store.set_campaign_state(cid, "active")
    out = store.set_campaign_state(cid, "skipped", by=1)
    assert out["state"] == "skipped" and out["client_name"] == "Clínica Bem Estar"
    assert store.set_campaign_state(cid, "active")["state"] == "active"
    # an ended one is Meta's to reopen, not ours
    store.sync_campaigns("111", [PAUSED, {**ACTIVE, "effective_status": "PAUSED"}], TODAY)
    with pytest.raises(Invalid, match="a Meta decide"):
        store.set_campaign_state(cid, "active")
    with pytest.raises(NotFound):
        store.set_campaign_state(999, "skipped")
    with pytest.raises(NotFound):
        store.campaign(999)


def rows_for(meta_id, days, spend=1000):
    return [
        {
            "meta_id": meta_id,
            "day": f"2026-10-{d:02d}",
            "spend_cents": spend + d,
            "impressions": 100 * d,
            "reach": 80 * d,
            "link_clicks": d,
            "actions": {"link_click": d, "lead": 1},
        }
        for d in days
    ]


def test_store_insights_is_idempotent(store):
    assert store.store_insights(rows_for("1", [1, 2, 3]), fetched="2026-10-20T10:00:00Z") == 3
    assert store.store_insights(rows_for("1", [3, 4], spend=2000), "2026-10-21T10:00:00Z") == 2
    # odd rows are skipped
    assert store.store_insights([{"meta_id": "", "day": "2026-10-01"}, {"meta_id": "1"}]) == 0
    with store.db() as db:
        rows = [dict(r) for r in db.execute("SELECT * FROM insight ORDER BY day")]
    assert [r["day"] for r in rows] == ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"]
    assert rows[2]["spend_cents"] == 2003 and rows[2]["fetched"] == "2026-10-21T10:00:00Z"
    assert rows[0]["fetched"] == "2026-10-20T10:00:00Z"
    assert rows[0]["actions"] == '{"lead":1,"link_click":1}'


def test_campaign_id_in_links():
    assert (
        campaign_id_in(
            "https://adsmanager.facebook.com/adsmanager/manage/campaigns?act=111&selected_campaign_ids=23850001"
        )
        == "23850001"
    )
    assert (
        campaign_id_in(
            "https://business.facebook.com/adsmanager/manage/adsets?act=111&campaign_id=23850002&x=1"
        )
        == "23850002"
    )
    assert campaign_id_in("https://adsmanager.facebook.com/campaigns/23850003/ads") == "23850003"
    assert campaign_id_in("https://example.com/?x=23850001") is None
    assert campaign_id_in("") is None and campaign_id_in(None) is None


def test_link_requests_to_campaigns(store, linked):
    def req(kind, status, url, client=None):
        r = store.create_request(
            {"client": client or linked["id"], "kind": kind, "what": "x", "campaign_url": url},
            None,
        )
        if status != "todo":
            store.update_request(r["id"], {"status": status}, None)
        return r["id"]

    ads = "https://adsmanager.facebook.com/adsmanager/manage/campaigns?act=111&"
    wrong_kind = req("Relatório", "done", ads + "selected_campaign_ids=23850001")
    not_done = req("Criar campanha", "doing", ads + "selected_campaign_ids=23850001")
    right = req("Criar campanha", "done", ads + "selected_campaign_ids=23850001")
    by_id = req("Reativar campanha", "done", ads + "campaign_id=23850002")
    by_path = req("Criar campanha", "done", "https://business.facebook.com/campaigns/23850004/x")
    # a longer id that merely contains ours is not a match
    req("Criar campanha", "done", ads + "selected_campaign_ids=238500049")
    metas = [
        ACTIVE,
        {**ACTIVE, "id": "23850002"},
        {**ACTIVE, "id": "23850004"},
        {**ACTIVE, "id": "23850005"},
    ]
    store.sync_campaigns("111", metas, TODAY)
    assert store.link_requests_to_campaigns() == 3
    rows = campaigns(store)
    assert rows["23850001"]["request"] == right
    assert rows["23850002"]["request"] == by_id
    assert rows["23850004"]["request"] == by_path
    assert rows["23850005"]["request"] is None
    events = store.request(right)["events"]
    assert events[-1]["kind"] == "campaign" and events[-1]["text"] == "meta:23850001"
    assert events[-1]["account"] is None
    assert all(e["kind"] != "campaign" for e in store.request(wrong_kind)["events"])
    assert all(e["kind"] != "campaign" for e in store.request(not_done)["events"])
    # nothing left to link: a second pass is quiet
    assert store.link_requests_to_campaigns() == 0
    # deleting the request leaves the campaign, unlinked
    store.delete_request(right)
    assert campaigns(store)["23850001"]["request"] is None


def test_campaign_rows_sums_and_order(store, linked):
    bakery = store.save_client({"name": "Padaria"})
    store.link_meta_account("222", bakery["id"])
    store.sync_campaigns(
        "111",
        [
            {**ACTIVE, "id": "1", "name": "Zebra"},
            {**ACTIVE, "id": "2", "name": "Alfa"},
            {**ACTIVE, "id": "3", "name": "Meio"},
        ],
        "2026-10-10",
    )
    store.sync_campaigns(
        "111", [{**ACTIVE, "id": "3", "name": "Meio", "effective_status": "PAUSED"}], TODAY
    )
    store.sync_campaigns("222", [{**ACTIVE, "id": "4", "name": "Pão"}], TODAY)
    store.store_insights(rows_for("1", [1, 2, 3, 4]))  # days 1-4
    store.store_insights(rows_for("2", [5]))
    store.store_insights(rows_for("4", [2, 30]))
    out = store.campaign_rows("2026-10-02", "2026-10-10")
    assert [c["name"] for c in out] == ["Clínica Bem Estar", "Padaria"]
    clinic = out[0]["campaigns"]
    # active first, then by name; the ended one last
    assert [k["name"] for k in clinic] == ["Alfa", "Zebra", "Meio"]
    zebra = clinic[1]
    assert zebra["spend_cents"] == (1002 + 1003 + 1004) and zebra["impressions"] == 900
    assert zebra["link_clicks"] == 9 and zebra["results"] == 9
    assert zebra["actions"] == {"link_click": 9, "lead": 3}
    assert clinic[0]["spend_cents"] == 1005 and clinic[2]["spend_cents"] == 0
    assert clinic[2]["actions"] == {} and clinic[2]["results"] == 0
    assert clinic[2]["state"] == "ended" and clinic[2]["ended"] == TODAY
    assert out[1]["campaigns"][0]["spend_cents"] == 1002  # the 30th is outside the range
    assert out[1]["campaigns"][0]["account_id"] == "222"
    # one campaign with its days
    one = store.campaign(zebra["id"], "2026-10-02", "2026-10-03")
    assert [d["day"] for d in one["days"]] == ["2026-10-02", "2026-10-03"]
    assert one["days"][0]["actions"] == {"link_click": 2, "lead": 1}
    assert len(store.campaign(zebra["id"])["days"]) == 4
    # a client that is gone takes its campaigns along
    store.delete_client(bakery["id"])
    assert [c["name"] for c in store.campaign_rows("2026-10-01", "2026-10-31")] == [
        "Clínica Bem Estar"
    ]


def test_export_tables_and_sync_state(store, linked):
    store.sync_campaigns("111", [ACTIVE], TODAY)
    store.store_insights(rows_for("23850001", [1]))
    assert store.table("campaign")[0]["meta_id"] == "23850001"
    assert store.table("review") == []
    assert store.table("insight")[0]["actions"] == {"link_click": 1, "lead": 1}
    with pytest.raises(Invalid):
        store.table("account")
    assert store.sync_state() == {"last_sync": None, "sync_error": ""}
    store.set_sync_state("2026-10-20T10:00:00Z", "")
    assert store.sync_state() == {"last_sync": "2026-10-20T10:00:00Z", "sync_error": ""}
    store.set_sync_state("2026-10-20T11:00:00Z", "a Meta pediu uma pausa")
    assert store.sync_state()["sync_error"] == "a Meta pediu uma pausa"
