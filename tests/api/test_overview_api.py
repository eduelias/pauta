"""Visão geral over HTTP (docs/campaign-overview-spec.md): one row per client with the
period's sums, the change against the period before, 14 days of trend, the balance and the
flags; open to members, the reason numbers aren't arriving spelled out to admins only."""

from datetime import date, timedelta

import pytest
from test_campaigns_api import last_30_days, synced, today_in_sao_paulo

from fakemeta import BUSINESS, expected
from pauta import overview
from softpasskey import call

CLINIC, BAKERY = "Clínica Bem Estar", "Padaria Trigo de Ouro"
KEYS = {"no_data", "stopped", "balance", "volume", "cost", "unseen"}


@pytest.fixture()
def meta(meta_on):
    return meta_on


def get(base, cookie, query=""):
    status, doc, _ = call(f"{base}/api/campaigns/overview{query}", cookie=cookie)
    assert status == 200, doc
    return doc


def by_name(doc):
    return {c["name"]: c for c in doc["clients"]}


def test_a_member_sees_every_client_on_one_row(team, fake_meta):
    base, nato, piero, m = synced(team, fake_meta)
    today = today_in_sao_paulo()
    since, until = last_30_days(today)
    doc = get(base, piero)
    assert (doc["since"], doc["until"]) == (since.isoformat(), until.isoformat())
    assert doc["previous"] == [
        (since - timedelta(days=30)).isoformat(),
        (since - timedelta(days=1)).isoformat(),
    ]
    assert doc["today_included"] is False and doc["last_sync"] == m["last_sync"]
    assert doc["sync_error"] == ""
    rows = by_name(doc)
    assert set(rows) == {CLINIC, BAKERY}
    assert doc["flagged"] == sum(1 for c in doc["clients"] if c["flags"])
    # the ones that need a look come first
    assert [c["level"] for c in doc["clients"]] == sorted(
        (c["level"] for c in doc["clients"]), reverse=True
    )

    clinic = rows[CLINIC]
    limpeza = expected("23850001", since, until, date(2026, 10, 3))
    botox = expected("23850002", since, until, date(2026, 10, 3))
    assert clinic["period"]["spend_cents"] >= limpeza["spend_cents"]
    assert clinic["period"]["link_clicks"] >= limpeza["link_clicks"]
    assert clinic["period"]["spend_cents"] <= limpeza["spend_cents"] + botox["spend_cents"]
    # conversations and leads don't add up: no client-wide Resultados, the click compares
    assert clinic["period"]["mixed"] and clinic["period"]["results"] is None
    assert clinic["change"]["kind"] == "click"
    assert (clinic["campaigns"], clinic["active"], clinic["currency"]) == (2, 2, "BRL")
    # 14 days ending yesterday, oldest first
    assert len(clinic["days"]) == overview.TREND_DAYS
    assert clinic["days"][-1]["day"] == (today - timedelta(days=1)).isoformat()
    assert clinic["days"][-1]["spend_cents"] > 0
    # R$ 5.000,00 of limit, R$ 1.234,56 spent: what is left, at the last 7 days' pace
    left = clinic["balance"]
    assert left["remaining_cents"] == 500000 - 123456
    assert left["days_left"] is not None and left["days_left"] > overview.LOW_BALANCE_DAYS
    assert clinic["seen_today"] is None and clinic["last_seen"] is None

    bakery = rows[BAKERY]
    assert bakery["balance"] is None  # no limit on the account: Meta gives nothing to divide
    assert bakery["period"]["result_indicator"] == "link_click"
    assert bakery["period"]["results"] == bakery["period"]["link_clicks"] > 0
    for c in doc["clients"]:
        assert {f["key"] for f in c["flags"]} <= KEYS - {"no_data", "unseen", "balance"}
        assert all(f["text"] and f["level"] in (0, 1, 2) for f in c["flags"])


def test_a_custom_period_and_its_previous_one(team, fake_meta):
    base, _, piero, _ = synced(team, fake_meta)
    today = today_in_sao_paulo()
    since, until = today - timedelta(days=3), today
    doc = get(base, piero, f"?since={since.isoformat()}&until={until.isoformat()}")
    assert doc["today_included"] is True
    assert doc["previous"] == [
        (since - timedelta(days=4)).isoformat(),
        (since - timedelta(days=1)).isoformat(),
    ]
    status, out, _ = call(
        f"{base}/api/campaigns/overview?since=2026-10-10&until=2026-10-01", cookie=piero
    )
    assert status == 400 and "início" in out["error"]


def test_visto_hoje_shows_and_then_an_old_one_is_flagged(team, fake_meta, store):
    base, nato, piero, _ = synced(team, fake_meta)
    assert call(f"{base}/api/reviews/today", {}, piero)[0] == 200
    rows = by_name(get(base, piero))
    assert rows[CLINIC]["seen_today"]["by"] == "Piero"
    assert rows[CLINIC]["last_seen"] == today_in_sao_paulo().isoformat()
    assert all("unseen" not in {f["key"] for f in c["flags"]} for c in rows.values())
    # three days on, nobody looked again
    old = (today_in_sao_paulo() - timedelta(days=3)).isoformat()
    with store.db() as db:
        db.execute('UPDATE review SET "on"=?', (old,))
    rows = by_name(get(base, piero))
    assert rows[CLINIC]["seen_today"] is None
    assert {"key": "unseen", "level": overview.NOTE, "text": "sem análise há 3 dias"} in rows[
        CLINIC
    ]["flags"]


def test_why_numbers_stopped_is_the_admins_to_read(team, fake_meta, store):
    base, nato, piero, _ = synced(team, fake_meta)
    store.set_connection_sync(BUSINESS, "2026-10-20T10:00:00Z", "a Meta recusou o acesso")
    for cookie, text in (
        (nato, "sem dados novos da Meta: a Meta recusou o acesso"),
        (piero, "sem dados novos da Meta"),
    ):
        doc = get(base, cookie)
        assert doc["flagged"] == 2
        for c in doc["clients"]:
            assert c["flags"][0] == {"key": "no_data", "level": overview.ACT, "text": text}
            assert "stopped" not in {f["key"] for f in c["flags"]}


def test_nothing_tracked_is_an_empty_list_and_strangers_get_nothing(team):
    base, nato, _, _ = team
    doc = get(base, nato)
    assert doc["clients"] == [] and doc["flagged"] == 0 and doc["last_sync"] is None
    assert call(f"{base}/api/campaigns/overview")[0] == 401
