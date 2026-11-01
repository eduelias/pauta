"""Campaign tracking over HTTP: the period list (Ads Manager's last 30 days by default, in
the ad account's day) with sums, Resultados per objective, cost per lead, budgets and reach,
Não acompanhar / Acompanhar, the admin's "Atualizar agora" and its 15-minute limit,
/metrics and the export."""

import json
import time
from datetime import UTC, date, datetime, timedelta

import pytest
from test_meta_api import connected

from fakemeta import BUSINESS, CONVERSATIONS, EMPTY_ACCOUNT, TZ, expected
from pauta import meta as meta_mod
from pauta import server as server_mod
from pauta import sync
from pauta.db import cents_per
from pauta.meta import NOT_CONNECTED, THROTTLED, local_today
from softpasskey import call


def today_in_sao_paulo() -> date:
    """The team's today: the fixture accounts are in America/Sao_Paulo (as Piero's)."""
    return local_today(TZ)


def last_30_days(today: date) -> tuple[date, date]:
    return today - timedelta(days=30), today - timedelta(days=1)


@pytest.fixture()
def meta(meta_on):
    return meta_on


def wait_sync(base, timeout=15.0) -> dict:
    """The /metrics `meta` block once the pass Atualizar agora started has ended."""
    deadline = time.time() + timeout
    while True:
        m = call(f"{base}/metrics")[1]["meta"]
        if not m["syncing"]:
            return m
        assert time.time() < deadline, "the sync never ended"
        time.sleep(0.02)


def sync_now(base, cookie) -> dict:
    """Atualizar agora: 202 with the previous `last_sync`, then the pass runs on the
    server's thread; returns /metrics' `meta` block after it ended."""
    before = call(f"{base}/metrics")[1]["meta"]["last_sync"]
    status, out, _ = call(f"{base}/api/meta/sync", {}, cookie)
    assert status == 202 and out == {"started": True, "last_sync": before}, (status, out)
    after = wait_sync(base)
    assert after["last_sync"] and after["last_sync"].endswith("Z")
    return after


def synced(team, fake_meta):
    """Connected, both accounts linked to clients, one sync done (today's real date)."""
    base, nato, piero = connected(team, fake_meta)
    clinic = call(f"{base}/api/clients", {"name": "Clínica Bem Estar"}, nato)[1]
    bakery = call(f"{base}/api/clients", {"name": "Padaria Trigo de Ouro"}, nato)[1]
    call(f"{base}/api/meta", cookie=nato)  # reads the accounts into meta_account
    call(f"{base}/api/meta/accounts/111", {"client": clinic["id"]}, nato, method="PATCH")
    call(f"{base}/api/meta/accounts/222", {"client": bakery["id"]}, nato, method="PATCH")
    return base, nato, piero, sync_now(base, nato)


def test_sync_then_the_list(team, fake_meta):
    base, nato, piero, m = synced(team, fake_meta)
    assert m["sync_error"] == "" and not m["syncing"]
    today = today_in_sao_paulo()
    since, until = last_30_days(today)
    status, doc, _ = call(f"{base}/api/campaigns", cookie=piero)
    assert status == 200
    # Ads Manager's default: the last 30 days, yesterday back, today out
    assert doc["since"] == since.isoformat() and doc["until"] == until.isoformat()
    assert doc["today_included"] is False
    assert doc["last_sync"] == m["last_sync"]  # how fresh the stored numbers are
    assert doc["sync_error"] == "" and doc["syncing"] is False
    assert [c["name"] for c in doc["clients"]] == ["Clínica Bem Estar", "Padaria Trigo de Ouro"]
    k = {x["meta_id"]: x for c in doc["clients"] for x in c["campaigns"]}
    assert set(k) == {"23850001", "23850002", "23850004"}
    limpeza = k["23850001"]
    want = expected("23850001", since, until, date(2026, 10, 3))
    assert limpeza["spend_cents"] == want["spend_cents"]
    assert limpeza["link_clicks"] == want["link_clicks"]
    # half up, as Ads Manager (the fixture lands on an exact half: round() would differ)
    assert limpeza["cpl_cents"] == cents_per(want["spend_cents"], want["link_clicks"])
    assert limpeza["reach"] == 500 * want["days"]
    assert limpeza["actions"]["link_click"] == want["link_clicks"]
    # Resultados as Ads Manager counts them for the campaign's objective
    assert limpeza["results"] == want["results"] == 2 * want["days"]
    assert limpeza["result_indicator"] == CONVERSATIONS
    assert limpeza["cost_per_result_cents"] == cents_per(want["spend_cents"], want["results"])
    assert limpeza == {
        **limpeza,
        "name": "Limpeza de pele novembro",
        "state": "active",
        "started": "2026-10-03",
        "ended": None,
        "account_id": "111",
        "currency": "BRL",
        "request": None,
        "daily_budget_cents": 1500,
        "lifetime_budget_cents": None,
    }
    # an indicator and no values: "—"; no entry: the objective's action from `actions`
    botox, panetone = k["23850002"], k["23850004"]
    assert botox["results"] is None and botox["result_indicator"] == "lead"
    assert botox["cost_per_result_cents"] is None and botox["lifetime_budget_cents"] == 45000
    assert panetone["results"] == panetone["link_clicks"] > 0
    assert panetone["result_indicator"] == "link_click"
    assert panetone["daily_budget_cents"] is None and panetone["lifetime_budget_cents"] is None


def test_custom_and_invalid_periods(team, fake_meta):
    base, nato, piero, _ = synced(team, fake_meta)
    status, doc, _ = call(f"{base}/api/campaigns?since=2026-10-10&until=2026-10-12", cookie=piero)
    assert status == 200 and doc["today_included"] is False
    k = {x["meta_id"]: x for c in doc["clients"] for x in c["campaigns"]}
    assert k["23850001"]["spend_cents"] == 1010 + 1011 + 1012
    assert k["23850001"]["link_clicks"] == 33 and k["23850001"]["results"] == 6
    assert k["23850001"]["cost_per_result_cents"] == round(3033 / 6)
    assert k["23850001"]["reach"] == 500 * 3
    assert k["23850002"]["spend_cents"] == 1012  # started the 12th
    assert k["23850004"]["spend_cents"] == 0 and k["23850004"]["cpl_cents"] is None
    assert k["23850004"]["results"] is None and k["23850004"]["cost_per_result_cents"] is None
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
        "results": 2,
        "result_indicator": CONVERSATIONS,
    }
    assert c["spend_cents"] == 1010 + 1011 + 1012 and c["impressions"] == 3300
    assert c["link_clicks"] == 33 and c["cpl_cents"] == round(3033 / 33)
    assert c["results"] == 6 and c["result_indicator"] == CONVERSATIONS
    assert c["cost_per_result_cents"] == round(3033 / 6)
    assert c["daily_budget_cents"] == 1500 and c["lifetime_budget_cents"] is None
    assert c["reach"] == 500 * 3
    assert c["actions"] == {
        "link_click": 33,
        "onsite_conversion.messaging_conversation_started_7d": 6,
    }
    # the default period is the last 30 days, like the list's
    since, until = last_30_days(today_in_sao_paulo())
    doc = call(f"{base}/api/campaigns/{cid}", cookie=piero)[1]
    assert doc["since"] == since.isoformat() and doc["until"] == until.isoformat()
    assert doc["today_included"] is False
    # a period before the campaign: no days, zero sums, no cost per lead, no reach
    doc = call(f"{base}/api/campaigns/{cid}?since=2025-01-01&until=2025-01-31", cookie=piero)[1]
    assert doc["campaign"]["days"] == [] and doc["campaign"]["spend_cents"] == 0
    assert doc["campaign"]["cpl_cents"] is None and doc["campaign"]["reach"] is None
    assert doc["campaign"]["results"] is None and doc["campaign"]["result_indicator"] == ""
    assert doc["campaign"]["cost_per_result_cents"] is None
    # Botox: Meta names the indicator, counts nothing: "—" on every day and over the period
    botox = k["23850002"]["id"]
    doc = call(f"{base}/api/campaigns/{botox}?since=2026-10-12&until=2026-10-13", cookie=piero)[1]
    assert doc["campaign"]["results"] is None and doc["campaign"]["result_indicator"] == "lead"
    assert all(d["results"] is None for d in doc["campaign"]["days"])
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


def test_a_client_with_linked_accounts_and_no_campaigns_is_listed(team, fake_meta):
    """Piero connected a portfolio whose ad account is a client's but holds no campaign:
    the client stays on Campanhas (campaigns: [], its account and balance) instead of
    vanishing as if the connection had failed. A client with neither doesn't show. Every
    block carries its linked accounts with the balance from Meta's cached list; Meta
    failing nulls the balances and nothing else. Visto hoje still counts (and accepts) the
    clients with something to check only."""
    base = team[0]
    assert call(f"{base}/api/campaigns", cookie=team[2])[1]["clients"] == []  # not connected
    fake_meta.accounts.append(EMPTY_ACCOUNT)
    base, nato, piero = connected(team, fake_meta)
    clinic = call(f"{base}/api/clients", {"name": "Clínica Bem Estar"}, nato)[1]
    studio = call(f"{base}/api/clients", {"name": "Estúdio Pilates Leve"}, nato)[1]
    nobody = call(f"{base}/api/clients", {"name": "Sem conta"}, nato)[1]
    call(f"{base}/api/meta", cookie=nato)
    call(f"{base}/api/meta/accounts/111", {"client": clinic["id"]}, nato, method="PATCH")
    call(f"{base}/api/meta/accounts/555", {"client": studio["id"]}, nato, method="PATCH")
    assert sync_now(base, nato)["sync_error"] == ""
    status, doc, _ = call(f"{base}/api/campaigns", cookie=piero)
    assert status == 200
    assert [c["name"] for c in doc["clients"]] == ["Clínica Bem Estar", "Estúdio Pilates Leve"]
    assert nobody["id"] not in [c["id"] for c in doc["clients"]]
    first, second = doc["clients"]
    assert len(first["campaigns"]) == 2
    assert first["accounts"] == [
        {
            "id": "111",
            "name": "Clínica Bem Estar",
            "currency": "BRL",
            "business_name": "Agência Exemplo",
            "balance": first["accounts"][0]["balance"],
        }
    ]
    assert first["accounts"][0]["balance"]["remaining_cents"] == 376544
    assert second["campaigns"] == [] and second["seen_today"] is None
    (acc,) = second["accounts"]
    assert acc["id"] == "555" and acc["name"] == "Estúdio Pilates Leve"
    assert acc["business_name"] == "Agência Exemplo" and acc["currency"] == "BRL"
    assert acc["balance"]["available"] and acc["balance"]["remaining_cents"] == 27450
    assert doc["seen"] == {"done": 0, "total": 1}  # the studio has nothing to check
    mine = call(f"{base}/api/campaigns?client={studio['id']}", cookie=piero)[1]
    assert [c["id"] for c in mine["clients"]] == [studio["id"]]
    assert mine["clients"][0]["campaigns"] == [] and mine["seen"] == {"done": 0, "total": 0}
    status, out, _ = call(f"{base}/api/clients/{studio['id']}/reviews", {}, piero)
    assert status == 400 and "campanha ativa" in out["error"]
    # Meta failing (the failure is remembered for a while): the list answers, balances null
    fake_meta.token_invalid = True
    call(f"{base}/api/meta?refresh=1", cookie=nato)
    status, doc, _ = call(f"{base}/api/campaigns", cookie=piero)
    assert status == 200
    assert [c["name"] for c in doc["clients"]] == ["Clínica Bem Estar", "Estúdio Pilates Leve"]
    assert [a["balance"] for c in doc["clients"] for a in c["accounts"]] == [None, None]
    assert doc["clients"][1]["accounts"][0]["business_name"] == "Agência Exemplo"
    assert len(doc["clients"][0]["campaigns"]) == 2


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
    # the rows: dated today (the account's day), by Piero, the note next to this month's numbers
    today = today_in_sao_paulo()
    reviews = call(f"{base}/api/export", cookie=nato)[1]["review"]
    assert len(reviews) == 2 and {r["on"] for r in reviews} == {today.isoformat()}
    assert all(r["note"] == "subi a verba" for r in reviews)
    by_campaign = {r["campaign"]: json.loads(r["snapshot"]) for r in reviews}
    # the snapshot is this month's numbers (the list's default is the last 30 days)
    first = today.replace(day=1).isoformat()
    month = call(f"{base}/api/campaigns?since={first}&until={today.isoformat()}", cookie=piero)[1]
    rows = {k["meta_id"]: k for c in month["clients"] for k in c["campaigns"]}
    limpeza = rows["23850001"]
    snap = by_campaign[limpeza["id"]]
    assert snap["since"] == today.replace(day=1).isoformat() and snap["until"] == today.isoformat()
    assert snap["spend_cents"] == limpeza["spend_cents"]
    assert snap["link_clicks"] == limpeza["link_clicks"]
    assert snap["reach"] == limpeza["reach"] and snap["impressions"] == limpeza["impressions"]
    assert snap["result_indicator"] == CONVERSATIONS and snap["results"] is not None
    assert snap["cost_per_result_cents"] == cents_per(snap["spend_cents"], snap["results"])
    assert snap["cpl_cents"] == cents_per(snap["spend_cents"], snap["link_clicks"])
    # a second tap the same day is another row, not an error; the status stays "seen"
    assert call(f"{base}/api/clients/{clinic['id']}/reviews", {}, piero)[0] == 200
    assert call(f"{base}/api/clients/999/reviews", {}, piero)[0] == 404
    assert call(f"{base}/api/clients/{clinic['id']}/reviews", {})[0] == 401
    # a client with no active campaign has nothing to mark
    extra = call(f"{base}/api/clients", {"name": "Sem campanha"}, nato)[1]
    status, out, _ = call(f"{base}/api/clients/{extra['id']}/reviews", {}, piero)
    assert status == 400 and "campanha ativa" in out["error"]


def test_today_is_the_ad_accounts_day(team, fake_meta, monkeypatch):
    """A frozen clock at 2026-11-01 01:30 CET (00:30 UTC): still 31 Oct in São Paulo, where
    the accounts are. The default range, `today_included` and the review's date follow
    the account, not the server."""
    base, nato, piero, _ = synced(team, fake_meta)
    monkeypatch.setattr(meta_mod, "_now", lambda: datetime(2026, 11, 1, 0, 30, tzinfo=UTC))
    doc = call(f"{base}/api/campaigns", cookie=piero)[1]
    assert doc["since"] == "2026-10-01" and doc["until"] == "2026-10-30"  # 30 days to yesterday
    assert doc["today_included"] is False
    doc = call(f"{base}/api/campaigns?since=2026-10-31&until=2026-10-31", cookie=piero)[1]
    assert doc["today_included"] is True  # 31 Oct is today there...
    doc = call(f"{base}/api/campaigns?since=2026-10-30&until=2026-10-30", cookie=piero)[1]
    assert doc["today_included"] is False  # ...and 30 Oct is yesterday
    cid = doc["clients"][0]["campaigns"][0]["id"]
    doc = call(f"{base}/api/campaigns/{cid}", cookie=piero)[1]
    assert doc["since"] == "2026-10-01" and doc["until"] == "2026-10-30"
    clinic = doc["campaign"]["client"]
    out = call(f"{base}/api/clients/{clinic}/reviews", {"note": "noite"}, piero)[1]
    assert out["seen_today"]["by"] == "Piero"
    reviews = call(f"{base}/api/export", cookie=nato)[1]["review"]
    assert {r["on"] for r in reviews} == {"2026-10-31"}
    snap = json.loads(reviews[0]["snapshot"])
    assert snap["since"] == "2026-10-01" and snap["until"] == "2026-10-31"
    # the list's "seen today" is that day's too
    doc = call(f"{base}/api/campaigns", cookie=piero)[1]
    assert doc["seen"] == {"done": 1, "total": 2}
    # with no account linked, the team's default zone (São Paulo as well) decides
    call(f"{base}/api/meta/accounts/111", {"client": None}, nato, method="PATCH")
    call(f"{base}/api/meta/accounts/222", {"client": None}, nato, method="PATCH")
    monkeypatch.delenv("PAUTA_TZ", raising=False)
    doc = call(f"{base}/api/campaigns", cookie=piero)[1]
    assert doc["since"] == "2026-10-01" and doc["until"] == "2026-10-30"


def test_manual_sync_is_for_admins_once_in_15_minutes(team, fake_meta, monkeypatch):
    base, nato, piero = connected(team, fake_meta)
    assert call(f"{base}/api/meta/sync", {}, piero)[0] == 403
    assert call(f"{base}/metrics")[1]["meta"]["last_sync"] is None
    m = sync_now(base, nato)  # nothing linked yet: nothing to read, still a pass
    assert m["sync_error"] == ""
    status, out, _ = call(f"{base}/api/meta/sync", {}, nato)
    assert status == 429 and out["error"] == server_mod.SYNC_TOO_SOON
    assert 0 < out["retry_in_s"] <= 900
    monkeypatch.setattr(server_mod, "MANUAL_SYNC_SECONDS", 0)
    assert call(f"{base}/api/meta/sync", {}, nato)[0] == 202
    wait_sync(base)
    status, out, _ = call(f"{base}/api/meta/connections/{BUSINESS}", cookie=nato, method="DELETE")
    assert status == 200 and not out["connected"]
    status, out, _ = call(f"{base}/api/meta/sync", {}, nato)
    assert status == 409 and out["error"] == NOT_CONNECTED


def test_manual_sync_answers_at_once_and_refuses_a_second_while_it_runs(
    team, fake_meta, monkeypatch
):
    """Atualizar agora doesn't hold a server slot for the whole pass: 202 right away with
    the previous `last_sync` (the pass is still at its first Graph read when the answer
    is in), `syncing` on while the thread works, 409 "já está sincronizando" to a second
    tap (or the scheduler) meanwhile, and `last_sync` moved once it ended. The 15-minute
    limit counts from the pass that started, not the 409."""
    base, nato, piero, m = synced(team, fake_meta)
    monkeypatch.setattr(server_mod, "MANUAL_SYNC_SECONDS", 0)
    before = m["last_sync"]
    # the stamp has whole seconds: give this pass one that cannot be the previous one's
    stamp = "2026-10-20T12:00:00Z"
    monkeypatch.setattr(sync, "_stamp", lambda: stamp)
    fake_meta.hold()  # every Graph answer waits: the pass is open until release()
    status, out, _ = call(f"{base}/api/meta/sync", {}, nato)
    assert status == 202 and out == {"started": True, "last_sync": before}
    assert call(f"{base}/metrics")[1]["meta"]["syncing"] is True
    doc = call(f"{base}/api/campaigns", cookie=piero)[1]
    assert doc["syncing"] is True and doc["last_sync"] == before  # the UI polls this
    status, out, _ = call(f"{base}/api/meta/sync", {}, nato)
    assert status == 409 and out["error"] == sync.BUSY and "já está sincronizando" in sync.BUSY
    assert fake_meta.held.wait(30) and sync.running()
    fake_meta.release()
    after = wait_sync(base)
    assert after["last_sync"] == stamp != before and after["sync_error"] == ""
    doc = call(f"{base}/api/campaigns", cookie=piero)[1]
    assert doc["syncing"] is False and doc["last_sync"] == after["last_sync"]
    # the busy answer didn't eat the next manual sync
    assert call(f"{base}/api/meta/sync", {}, nato)[0] == 202
    wait_sync(base)


def test_metrics_and_export_carry_the_sync(team, fake_meta):
    base, nato, piero, _ = synced(team, fake_meta)
    m = call(f"{base}/metrics")[1]["meta"]
    assert m["last_sync"].endswith("Z") and m["sync_error"] == ""
    doc = call(f"{base}/api/export", cookie=nato)[1]
    assert len(doc["campaign"]) == 3 and doc["review"] == []
    assert len(doc["insight"]) > 0 and isinstance(doc["insight"][0]["actions"], dict)
    # a sync with trouble shows on /metrics and on the list (the UI's toast says it)
    fake_meta.throttle = True
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(server_mod, "MANUAL_SYNC_SECONDS", 0)
        m = sync_now(base, nato)
    assert m["sync_error"] == THROTTLED
    assert call(f"{base}/api/campaigns", cookie=nato)[1]["sync_error"] == THROTTLED


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
