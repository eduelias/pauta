"""Campaign tracking over HTTP: the period list with sums, cost per lead and reach, Não
acompanhar / Acompanhar, the admin's "Atualizar agora" and its 15-minute limit, /metrics
and the export."""

import json
from datetime import date

import pytest
from test_meta_api import connected

from fakemeta import expected
from pauta import server as server_mod
from pauta.meta import NOT_CONNECTED
from softpasskey import call


@pytest.fixture()
def meta(meta_on):
    return meta_on


def synced(team, fake_meta):
    """Connected, both accounts linked to clients, one sync done (today's real date)."""
    base, nato, piero = connected(team, fake_meta)
    clinic = call(f"{base}/api/clients", {"name": "Clínica Bem Estar"}, nato)[1]
    bakery = call(f"{base}/api/clients", {"name": "Padaria Trigo de Ouro"}, nato)[1]
    call(f"{base}/api/meta", cookie=nato)  # reads the accounts into meta_account
    call(f"{base}/api/meta/accounts/111", {"client": clinic["id"]}, nato, method="PATCH")
    call(f"{base}/api/meta/accounts/222", {"client": bakery["id"]}, nato, method="PATCH")
    status, out, _ = call(f"{base}/api/meta/sync", {}, nato)
    assert status == 200, out
    return base, nato, piero, out


def test_sync_then_the_list(team, fake_meta):
    base, nato, piero, out = synced(team, fake_meta)
    assert out["accounts"] == 2 and out["campaigns_new"] == 3 and out["errors"] == []
    today = date.today()
    status, doc, _ = call(f"{base}/api/campaigns", cookie=piero)
    assert status == 200
    assert doc["since"] == today.replace(day=1).isoformat() and doc["until"] == today.isoformat()
    assert doc["today_included"] is True
    assert doc["last_sync"].endswith("Z")  # how fresh the stored numbers are
    assert [c["name"] for c in doc["clients"]] == ["Clínica Bem Estar", "Padaria Trigo de Ouro"]
    k = {x["meta_id"]: x for c in doc["clients"] for x in c["campaigns"]}
    assert set(k) == {"23850001", "23850002", "23850004"}
    limpeza = k["23850001"]
    want = expected("23850001", today.replace(day=1), today, date(2026, 10, 3))
    assert limpeza["spend_cents"] == want["spend_cents"]
    assert limpeza["results"] == want["link_clicks"] == limpeza["link_clicks"]
    assert limpeza["cpl_cents"] == round(want["spend_cents"] / want["link_clicks"])
    assert limpeza["reach"] == 500 * want["days"]
    assert limpeza["actions"]["link_click"] == want["link_clicks"]
    assert limpeza == {
        **limpeza,
        "name": "Limpeza de pele novembro",
        "state": "active",
        "started": "2026-10-03",
        "ended": None,
        "account_id": "111",
        "currency": "BRL",
        "request": None,
    }


def test_custom_and_invalid_periods(team, fake_meta):
    base, nato, piero, _ = synced(team, fake_meta)
    status, doc, _ = call(f"{base}/api/campaigns?since=2026-10-10&until=2026-10-12", cookie=piero)
    assert status == 200 and doc["today_included"] is False
    k = {x["meta_id"]: x for c in doc["clients"] for x in c["campaigns"]}
    assert k["23850001"]["spend_cents"] == 1010 + 1011 + 1012 and k["23850001"]["results"] == 33
    assert k["23850001"]["reach"] == 500 * 3
    assert k["23850002"]["spend_cents"] == 1012  # started the 12th
    assert k["23850004"]["spend_cents"] == 0 and k["23850004"]["cpl_cents"] is None
    assert k["23850004"]["reach"] is None  # Meta had no row for it (not started yet)
    # a period with no numbers at all is still a list
    doc = call(f"{base}/api/campaigns?since=2025-01-01&until=2025-01-31", cookie=piero)[1]
    assert all(x["spend_cents"] == 0 for c in doc["clients"] for x in c["campaigns"])
    for query in ("since=2026-13-01", "until=hoje", "since=2026-10-20&until=2026-10-19"):
        status, doc, _ = call(f"{base}/api/campaigns?{query}", cookie=piero)
        assert status == 400, query
    status, doc, _ = call(f"{base}/api/campaigns?since=2025-01-01&until=2026-02-05", cookie=piero)
    assert status == 400 and "400 dias" in doc["error"]
    # reach failing is never the list's problem
    fake_meta.token_invalid = True
    fake_meta.calls.clear()
    status, doc, _ = call(f"{base}/api/campaigns?since=2026-09-01&until=2026-09-30", cookie=piero)
    assert status == 200 and all(x["reach"] is None for c in doc["clients"] for x in c["campaigns"])
    assert call(f"{base}/api/campaigns", cookie=None)[0] == 401


def test_skip_and_follow_again(team, fake_meta):
    base, nato, piero, _ = synced(team, fake_meta)
    doc = call(f"{base}/api/campaigns", cookie=piero)[1]
    cid = doc["clients"][0]["campaigns"][0]["id"]
    status, out, _ = call(f"{base}/api/campaigns/{cid}", {"state": "skipped"}, piero, "PATCH")
    assert status == 200 and out["state"] == "skipped" and out["id"] == cid
    ids = [
        x["id"]
        for c in call(f"{base}/api/campaigns", cookie=piero)[1]["clients"]
        for x in c["campaigns"]
    ]
    assert cid not in ids
    assert call(f"{base}/api/meta/sync", {}, nato)[0] == 429  # the one in synced() was just now
    status, out, _ = call(f"{base}/api/campaigns/{cid}", {"state": "active"}, piero, "PATCH")
    assert status == 200 and out["state"] == "active"
    status, out, _ = call(f"{base}/api/campaigns/{cid}", {"state": "ended"}, piero, "PATCH")
    assert status == 400
    status, out, _ = call(f"{base}/api/campaigns/{cid}", {}, piero, "PATCH")
    assert status == 400
    assert call(f"{base}/api/campaigns/999", {"state": "skipped"}, piero, "PATCH")[0] == 404


def test_one_campaign_with_its_days(team, fake_meta):
    base, nato, piero, _ = synced(team, fake_meta)
    doc = call(f"{base}/api/campaigns", cookie=piero)[1]
    k = {x["meta_id"]: x for c in doc["clients"] for x in c["campaigns"]}
    cid = k["23850001"]["id"]
    status, doc, _ = call(
        f"{base}/api/campaigns/{cid}?since=2026-10-10&until=2026-10-12", cookie=piero
    )
    assert status == 200
    assert doc["since"] == "2026-10-10" and doc["until"] == "2026-10-12"
    assert doc["today_included"] is False and doc["last_sync"].endswith("Z")
    c = doc["campaign"]
    assert c["id"] == cid and c["name"] == "Limpeza de pele novembro"
    assert c["client_name"] == "Clínica Bem Estar" and c["state"] == "active"
    assert c["currency"] == "BRL"  # the account's: money is in it
    assert [d["day"] for d in c["days"]] == ["2026-10-10", "2026-10-11", "2026-10-12"]
    assert c["days"][0] == {
        **c["days"][0],
        "spend_cents": 1010,
        "impressions": 1000,
        "reach": 800,
        "link_clicks": 10,
        "actions": {
            "link_click": 10,
            "onsite_conversion.messaging_conversation_started_7d": 2,
        },
    }
    assert c["spend_cents"] == 1010 + 1011 + 1012 and c["impressions"] == 3300
    assert c["link_clicks"] == c["results"] == 33
    assert c["cpl_cents"] == round(3033 / 33)
    assert c["reach"] == 500 * 3
    assert c["actions"] == {
        "link_click": 33,
        "onsite_conversion.messaging_conversation_started_7d": 6,
    }
    # the default period is this month so far, like the list's
    today = date.today()
    doc = call(f"{base}/api/campaigns/{cid}", cookie=piero)[1]
    assert doc["since"] == today.replace(day=1).isoformat() and doc["until"] == today.isoformat()
    # a period before the campaign: no days, zero sums, no cost per lead, no reach
    doc = call(f"{base}/api/campaigns/{cid}?since=2025-01-01&until=2025-01-31", cookie=piero)[1]
    assert doc["campaign"]["days"] == [] and doc["campaign"]["spend_cents"] == 0
    assert doc["campaign"]["cpl_cents"] is None and doc["campaign"]["reach"] is None
    assert (
        call(f"{base}/api/campaigns/{cid}?since=2026-10-20&until=2026-10-19", cookie=piero)[0]
        == 400
    )
    assert call(f"{base}/api/campaigns/999", cookie=piero)[0] == 404
    assert call(f"{base}/api/campaigns/{cid}")[0] == 401
    # reach failing is never the page's problem
    fake_meta.token_invalid = True
    status, doc, _ = call(
        f"{base}/api/campaigns/{cid}?since=2026-09-01&until=2026-09-30", cookie=piero
    )
    assert status == 200 and doc["campaign"]["reach"] is None


def test_skipped_ones_on_request_and_one_clients_campaigns(team, fake_meta):
    base, nato, piero, _ = synced(team, fake_meta)
    doc = call(f"{base}/api/campaigns", cookie=piero)[1]
    clinic, bakery = doc["clients"]
    cid = clinic["campaigns"][0]["id"]
    call(f"{base}/api/campaigns/{cid}", {"state": "skipped"}, piero, "PATCH")
    # the list leaves it out; include_skipped=1 brings it back, marked
    plain = call(f"{base}/api/campaigns", cookie=piero)[1]
    assert cid not in [x["id"] for c in plain["clients"] for x in c["campaigns"]]
    full = call(f"{base}/api/campaigns?include_skipped=1", cookie=piero)[1]
    k = {x["id"]: x for c in full["clients"] for x in c["campaigns"]}
    assert k[cid]["state"] == "skipped"
    assert len(k) == 3 and sum(1 for x in k.values() if x["state"] == "skipped") == 1
    # one client's campaigns (the client page): the bakery's only
    mine = call(f"{base}/api/campaigns?client={bakery['id']}", cookie=piero)[1]
    assert [c["id"] for c in mine["clients"]] == [bakery["id"]]
    assert [x["meta_id"] for x in mine["clients"][0]["campaigns"]] == ["23850004"]
    assert call(f"{base}/api/campaigns?client=999", cookie=piero)[1]["clients"] == []
    assert call(f"{base}/api/campaigns?client=abc", cookie=piero)[0] == 400


def test_visto_hoje_writes_a_review_per_active_campaign(team, fake_meta):
    base, nato, piero, _ = synced(team, fake_meta)
    doc = call(f"{base}/api/campaigns", cookie=piero)[1]
    clinic, bakery = doc["clients"]
    assert doc["seen"] == {"done": 0, "total": 2}
    assert clinic["seen_today"] is None and bakery["seen_today"] is None
    # a member marks the clinic as seen, with a note
    status, out, _ = call(
        f"{base}/api/clients/{clinic['id']}/reviews", {"note": "subi a verba"}, piero
    )
    assert status == 200, out
    assert out["client"] == clinic["id"] and out["campaigns"] == 2  # its two ACTIVE ones
    assert out["seen_today"]["by"] == "Piero" and out["seen_today"]["at"]
    doc = call(f"{base}/api/campaigns", cookie=piero)[1]
    assert doc["seen"] == {"done": 1, "total": 2}
    assert doc["clients"][0]["seen_today"]["by"] == "Piero"
    assert doc["clients"][1]["seen_today"] is None
    # the rows: dated today, by Piero, the note next to this month's numbers
    today = date.today()
    reviews = call(f"{base}/api/export", cookie=nato)[1]["review"]
    assert len(reviews) == 2 and {r["on"] for r in reviews} == {today.isoformat()}
    assert all(r["note"] == "subi a verba" for r in reviews)
    by_campaign = {r["campaign"]: json.loads(r["snapshot"]) for r in reviews}
    limpeza = next(k for k in clinic["campaigns"] if k["meta_id"] == "23850001")
    snap = by_campaign[limpeza["id"]]
    assert snap["since"] == today.replace(day=1).isoformat() and snap["until"] == today.isoformat()
    assert snap["spend_cents"] == limpeza["spend_cents"]
    assert snap["link_clicks"] == limpeza["link_clicks"]
    assert snap["cpl_cents"] == limpeza["cpl_cents"]
    assert snap["reach"] == limpeza["reach"] and snap["impressions"] == limpeza["impressions"]
    # a second tap the same day is another row, not an error; the status stays "seen"
    assert call(f"{base}/api/clients/{clinic['id']}/reviews", {}, piero)[0] == 200
    assert call(f"{base}/api/clients/999/reviews", {}, piero)[0] == 404
    assert call(f"{base}/api/clients/{clinic['id']}/reviews", {})[0] == 401
    # a client with no active campaign has nothing to mark
    extra = call(f"{base}/api/clients", {"name": "Sem campanha"}, nato)[1]
    status, out, _ = call(f"{base}/api/clients/{extra['id']}/reviews", {}, piero)
    assert status == 400 and "campanha ativa" in out["error"]


def test_manual_sync_is_for_admins_once_in_15_minutes(team, fake_meta, monkeypatch):
    base, nato, piero = connected(team, fake_meta)
    assert call(f"{base}/api/meta/sync", {}, piero)[0] == 403
    status, out, _ = call(f"{base}/api/meta/sync", {}, nato)
    assert status == 200 and out["accounts"] == 0  # nothing linked yet: nothing to read
    status, out, _ = call(f"{base}/api/meta/sync", {}, nato)
    assert status == 429 and out["error"] == server_mod.SYNC_TOO_SOON
    assert 0 < out["retry_in_s"] <= 900
    monkeypatch.setattr(server_mod, "MANUAL_SYNC_SECONDS", 0)
    assert call(f"{base}/api/meta/sync", {}, nato)[0] == 200
    call(f"{base}/api/meta", cookie=nato, method="DELETE")
    status, out, _ = call(f"{base}/api/meta/sync", {}, nato)
    assert status == 409 and out["error"] == NOT_CONNECTED


def test_metrics_and_export_carry_the_sync(team, fake_meta):
    base, nato, piero, _ = synced(team, fake_meta)
    m = call(f"{base}/metrics")[1]["meta"]
    assert m["last_sync"].endswith("Z") and m["sync_error"] == ""
    doc = call(f"{base}/api/export", cookie=nato)[1]
    assert len(doc["campaign"]) == 3 and doc["review"] == []
    assert len(doc["insight"]) > 0 and isinstance(doc["insight"][0]["actions"], dict)
    # a sync with trouble shows on /metrics
    fake_meta.throttle = True
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(server_mod, "MANUAL_SYNC_SECONDS", 0)
        status, out, _ = call(f"{base}/api/meta/sync", {}, nato)
    assert status == 200 and out["errors"][0]["status"] == 503
    assert call(f"{base}/metrics")[1]["meta"]["sync_error"] == out["errors"][0]["error"]


def test_the_last_sync_outlives_a_restart(site, team, fake_meta):
    base, nato, piero, _ = synced(team, fake_meta)
    _, auth, store = site
    last = call(f"{base}/metrics")[1]["meta"]["last_sync"]
    # another server over the same database (what a restart is) reports the same sync
    from appserver import serve
    from pauta.meta import Meta

    again = serve(store, auth, None, Meta(store.path))
    try:
        port = again.server_address[1]
        m = call(f"http://127.0.0.1:{port}/metrics")[1]["meta"]
        assert m["last_sync"] == last and m["sync_error"] == ""
    finally:
        again.shutdown()
        again.server_close()
