"""Campaign tracking over HTTP: the period list with sums, cost per lead and reach, Não
acompanhar / Acompanhar, the admin's "Atualizar agora" and its 15-minute limit, /metrics
and the export."""

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
